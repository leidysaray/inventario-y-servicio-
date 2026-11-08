"""PiShop Cloud — Microservicio y Aplicación de Inventario (P02 - Core).

Código Python completo, ejecutable y autónomo para Visual Studio Code.
Cumple con los contratos de la Semana 1 a 4 del curso Fundamentos de Arquitectura:
- Endpoints del contrato (/v1/stock/{sku}, /v1/reservas, compensación /liberar).
- Datos simulados e inventados cargados automáticamente.
- Garantía de Idempotencia mediante la cabecera 'Idempotency-Key'.
- Prevención de condiciones de carrera mediante bloqueos atómicos por SKU.
- Sondas de salud diferenciadas (/health/live, /health/ready, /health/startup).
- Panel interactivo web integrado directamente en http://localhost:8002/
"""

import asyncio
import json
import socket
import sys
import threading
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

_raiz = Path(__file__).resolve().parent
_svc_dir = _raiz / "services" / "inventario-service"
if str(_svc_dir) not in sys.path:
    sys.path.insert(0, str(_svc_dir))

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, Text, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
import uvicorn

# ==============================================================================
# 1. MODELOS DE BASE DE DATOS (SQLAlchemy 2.0 Asíncrono - Semana 1)
# ==============================================================================
Base = declarative_base()


class Stock(Base):
    """Modelo de existencias por producto (Base de datos propia y exclusiva)."""
    __tablename__ = "stock"

    sku = Column(String(64), primary_key=True, index=True)
    cantidad = Column(Integer, nullable=False, default=0)
    reservado = Column(Integer, nullable=False, default=0)
    actualizado_en = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Reserva(Base):
    """Modelo de reservas generadas durante el flujo de compra (Saga tentative)."""
    __tablename__ = "reservas"

    reserva_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sku = Column(String(64), nullable=False, index=True)
    cantidad = Column(Integer, nullable=False)
    pedido_id = Column(String(64), nullable=False, index=True)
    estado = Column(String(20), nullable=False, default="ACTIVA")
    idempotency_key = Column(String(128), nullable=True, index=True)
    creado_en = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RegistroIdempotencia(Base):
    """Almacén de respuestas previas para garantizar idempotencia en POST /v1/reservas."""
    __tablename__ = "idempotencia"

    clave = Column(String(128), primary_key=True, index=True)
    ruta = Column(String(128), nullable=False)
    codigo_estado = Column(Integer, nullable=False)
    cuerpo_respuesta = Column(Text, nullable=False)
    creado_en = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ==============================================================================
# 2. ESQUEMAS PYDANTIC (Validación de Contratos - Semana 2)
# ==============================================================================
class StockUpdate(BaseModel):
    cantidad: int = Field(..., ge=0, description="Cantidad total en inventario (>= 0)")


class StockResponse(BaseModel):
    sku: str
    cantidad: int
    reservado: int


class ReservaCreate(BaseModel):
    sku: str = Field(..., min_length=1, description="SKU del producto a reservar")
    cantidad: int = Field(..., gt=0, description="Cantidad a reservar (> 0)")
    pedido_id: str = Field(..., min_length=1, description="ID del pedido asociado")


class ReservaResponse(BaseModel):
    reserva_id: str
    sku: str
    cantidad: int
    pedido_id: str
    estado: str


class ReservaLiberarResponse(BaseModel):
    reserva_id: str
    sku: str
    cantidad: int
    pedido_id: str
    estado: str
    mensaje: str


# ==============================================================================
# 3. DATOS INVENTADOS / SIMULADOS (Catálogo Semilla de PiShop)
# ==============================================================================
DATOS_INVENTADOS = [
    ("CAFE-500G", 50, "Café Especial Colombiano Molido (500g)"),
    ("CAFE-GRANO-1KG", 35, "Café en Grano Selección Origen (1kg)"),
    ("TAZA-PISHOP", 30, "Taza Cerámica Térmica PiShop (350ml)"),
    ("CAMISETA-S", 25, "Camiseta Oficial PiShop Negra (Talla S)"),
    ("CAMISETA-M", 20, "Camiseta Oficial PiShop Negra (Talla M)"),
    ("CAMISETA-L", 15, "Camiseta Oficial PiShop Negra (Talla L)"),
    ("MOLINO-MANUAL", 12, "Molino Manual Cónico en Acero Inoxidable"),
    ("PRENSA-FRANCESA", 18, "Prensa Francesa de Vidrio Borosilicato 600ml"),
    ("VASO-TERMICO", 40, "Vaso Térmico Doble Pared PiShop 16oz"),
    ("GORRA-PISHOP", 22, "Gorra Bordada PiShop Ajustable"),
    ("STICKERS-PACK", 100, "Pack x10 Stickers Vinilo Dev & Coffee"),
    ("PROD-UNICO", 1, "Kit Barista Edición Especial (Última Unidad - Prueba Concurrencia)"),
    ("PROD-AGOTADO", 0, "Delantal Barista Master (Agotado - Prueba 409 Conflict)"),
]

# ==============================================================================
# 4. CONFIGURACIÓN DE BASE DE DATOS Y BLOQUEOS DE CONCURRENCIA
# ==============================================================================
DB_PATH = Path(__file__).resolve().parent / "inventario.db"
DB_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DB_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

_sku_locks: dict[str, asyncio.Lock] = {}
_lock_general = asyncio.Lock()


async def get_sku_lock(sku: str) -> asyncio.Lock:
    """Garantiza exclusión mutua por SKU para evitar condiciones de carrera (Semana 3)."""
    async with _lock_general:
        if sku not in _sku_locks:
            _sku_locks[sku] = asyncio.Lock()
        return _sku_locks[sku]


async def get_db():
    """Generador de sesiones de base de datos asíncronas."""
    async with AsyncSessionLocal() as session:
        yield session


async def inicializar_base_datos():
    """Crea tablas y siembra los datos inventados iniciales si la base está limpia."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for sku, cant, _ in DATOS_INVENTADOS:
                existente = await session.get(Stock, sku)
                if not existente:
                    session.add(Stock(sku=sku, cantidad=cant, reservado=0))


# ==============================================================================
# 5. LIFESPAN Y APLICACIÓN FASTAPI
# ==============================================================================
ESTADO = {"arranco": False, "instancia": f"inventario-{uuid.uuid4().hex[:6]}"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await inicializar_base_datos()
    ESTADO["arranco"] = True
    yield
    ESTADO["arranco"] = False


app = FastAPI(
    title="inventario-service",
    version="1.0.0",
    description="Microservicio de Inventario (P02 - Core) PiShop Cloud",
    lifespan=lifespan,
)

# ==============================================================================
# 6. SONDAS DE SALUD (Semana 4 - Kubernetes / Docker)
# ==============================================================================
@app.get("/health/live", tags=["salud"])
def health_live():
    """Sonda live: barata, local, sin dependencias externas."""
    return {"status": "alive", "instance": ESTADO["instancia"]}


@app.get("/health/startup", tags=["salud"])
def health_startup(resp: Response):
    """Sonda startup: confirma si la inicialización de base de datos terminó."""
    if not ESTADO["arranco"]:
        resp.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"started": ESTADO["arranco"]}


@app.get("/health/ready", tags=["salud"])
def health_ready(resp: Response):
    """Sonda ready: confirma disponibilidad para recibir tráfico."""
    if not ESTADO["arranco"]:
        resp.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": ESTADO["arranco"], "instance": ESTADO["instancia"]}


# ==============================================================================
# 7. ENDPOINTS OFICIALES DEL CONTRATO (P02 - Core)
# ==============================================================================
@app.get("/v1/stock/{sku}", response_model=StockResponse, tags=["stock"])
async def obtener_stock(sku: str, db: AsyncSession = Depends(get_db)):
    """Contrato: Consulta cantidad disponible y reservada de un SKU."""
    item = await db.get(Stock, sku)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detalle": f"SKU {sku} no encontrado", "codigo": "SKU_NO_ENCONTRADO"},
        )
    return StockResponse(sku=item.sku, cantidad=item.cantidad, reservado=item.reservado)


@app.put("/v1/stock/{sku}", response_model=StockResponse, tags=["stock"])
async def actualizar_stock(sku: str, payload: StockUpdate, db: AsyncSession = Depends(get_db)):
    """Contrato: Establece la cantidad en stock para un SKU."""
    lock = await get_sku_lock(sku)
    async with lock:
        item = await db.get(Stock, sku)
        if item:
            item.cantidad = payload.cantidad
        else:
            item = Stock(sku=sku, cantidad=payload.cantidad, reservado=0)
            db.add(item)
        await db.commit()
        await db.refresh(item)
        return StockResponse(sku=item.sku, cantidad=item.cantidad, reservado=item.reservado)


@app.post("/v1/reservas", status_code=status.HTTP_201_CREATED, response_model=ReservaResponse, tags=["reservas"])
async def crear_reserva(
    payload: ReservaCreate,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Contrato: Crea reserva con Idempotency-Key obligatoria.
    - Misma clave -> misma respuesta, sin descontar dos veces.
    - Stock insuficiente -> 409 Conflict.
    """
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"detalle": "La cabecera Idempotency-Key es obligatoria", "codigo": "IDEMPOTENCY_KEY_REQUERIDA"},
        )

    clave = idempotency_key.strip()

    # 1. Comprobar idempotencia previa
    registro = await db.get(RegistroIdempotencia, clave)
    if registro:
        return Response(content=registro.cuerpo_respuesta, status_code=registro.codigo_estado, media_type="application/json")

    # 2. Bloqueo atómico por SKU
    lock = await get_sku_lock(payload.sku)
    async with lock:
        # Re-comprobar dentro del bloqueo
        registro = await db.get(RegistroIdempotencia, clave)
        if registro:
            return Response(content=registro.cuerpo_respuesta, status_code=registro.codigo_estado, media_type="application/json")

        stock = await db.get(Stock, payload.sku)
        if not stock:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"detalle": f"SKU {payload.sku} no existe", "codigo": "SKU_NO_ENCONTRADO"},
            )

        if stock.cantidad < payload.cantidad:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "detalle": f"Stock insuficiente para {payload.sku}. Solicitado: {payload.cantidad}, Disponible: {stock.cantidad}",
                    "codigo": "STOCK_INSUFICIENTE",
                },
            )

        # Descontar stock e incrementar reservado
        stock.cantidad -= payload.cantidad
        stock.reservado += payload.cantidad

        reserva_id = str(uuid.uuid4())
        reserva = Reserva(
            reserva_id=reserva_id,
            sku=payload.sku,
            cantidad=payload.cantidad,
            pedido_id=payload.pedido_id,
            estado="ACTIVA",
            idempotency_key=clave,
        )
        db.add(reserva)

        datos_respuesta = {
            "reserva_id": reserva_id,
            "sku": payload.sku,
            "cantidad": payload.cantidad,
            "pedido_id": payload.pedido_id,
            "estado": "ACTIVA",
        }
        cuerpo_json = json.dumps(datos_respuesta)

        # Guardar registro para garantizar idempotencia futura
        registro_nuevo = RegistroIdempotencia(
            clave=clave,
            ruta="/v1/reservas",
            codigo_estado=status.HTTP_201_CREATED,
            cuerpo_respuesta=cuerpo_json,
        )
        db.add(registro_nuevo)

        await db.commit()
        return Response(content=cuerpo_json, status_code=status.HTTP_201_CREATED, media_type="application/json")


@app.post("/v1/reservas/{reserva_id}/liberar", response_model=ReservaLiberarResponse, tags=["reservas"])
async def liberar_reserva(reserva_id: str, db: AsyncSession = Depends(get_db)):
    """Contrato: Compensación Saga. Devuelve el stock al inventario.
    Idempotente: liberar dos veces no suma doble stock.
    """
    reserva = await db.get(Reserva, reserva_id)
    if not reserva:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detalle": f"Reserva {reserva_id} no encontrada", "codigo": "RESERVA_NO_ENCONTRADA"},
        )

    lock = await get_sku_lock(reserva.sku)
    async with lock:
        await db.refresh(reserva)
        if reserva.estado == "LIBERADA":
            return ReservaLiberarResponse(
                reserva_id=reserva.reserva_id,
                sku=reserva.sku,
                cantidad=reserva.cantidad,
                pedido_id=reserva.pedido_id,
                estado="LIBERADA",
                mensaje="La reserva ya habia sido liberada previamente",
            )

        stock = await db.get(Stock, reserva.sku)
        if stock:
            stock.cantidad += reserva.cantidad
            stock.reservado = max(0, stock.reservado - reserva.cantidad)

        reserva.estado = "LIBERADA"
        await db.commit()

        return ReservaLiberarResponse(
            reserva_id=reserva.reserva_id,
            sku=reserva.sku,
            cantidad=reserva.cantidad,
            pedido_id=reserva.pedido_id,
            estado="LIBERADA",
            mensaje="Reserva liberada exitosamente y stock devuelto",
        )


# ==============================================================================
# 8. ENDPOINTS AUXILIARES PARA LA APLICACIÓN WEB INTERACTIVA
# ==============================================================================
@app.get("/v1/stock", response_model=list[StockResponse], tags=["aplicacion"])
async def listar_todo_el_stock(db: AsyncSession = Depends(get_db)):
    """Lista todos los productos del inventario para la aplicación."""
    resultado = await db.execute(select(Stock).order_by(Stock.sku))
    return resultado.scalars().all()


@app.get("/v1/reservas", response_model=list[ReservaResponse], tags=["aplicacion"])
async def listar_reservas_realizadas(db: AsyncSession = Depends(get_db)):
    """Lista el historial de reservas registradas."""
    resultado = await db.execute(select(Reserva).order_by(Reserva.creado_en.desc()).limit(50))
    return resultado.scalars().all()


@app.post("/v1/stock/reset", tags=["aplicacion"])
async def restablecer_datos(db: AsyncSession = Depends(get_db)):
    """Restablece los datos inventados originales para pruebas."""
    await db.execute(delete(Reserva))
    await db.execute(delete(RegistroIdempotencia))
    await db.execute(delete(Stock))

    for sku, cant, _ in DATOS_INVENTADOS:
        db.add(Stock(sku=sku, cantidad=cant, reservado=0))
    await db.commit()
    return {"mensaje": "Inventario restablecido con datos inventados exitosamente", "total": len(DATOS_INVENTADOS)}


# ==============================================================================
# 9. PANEL WEB DE LA APLICACIÓN (HTML/CSS/JS Integrado en GET /)
# ==============================================================================
from app.ui import HTML_DASHBOARD


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def panel_web():
    """Sirve la aplicación web interactiva en la raíz del servicio."""
    return HTMLResponse(content=HTML_DASHBOARD)


# ==============================================================================
# 10. EJECUCIÓN DIRECTA DESDE VISUAL STUDIO CODE (Botón Play ▶️ o F5)
# ==============================================================================
def _abrir_navegador(url: str):
    time.sleep(1.2)
    print(f"\n[INFO] Abriendo aplicacion web en el navegador: {url}\n")
    webbrowser.open(url)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    PUERTO = 8002
    URL_LOCAL = f"http://localhost:{PUERTO}"

    print("\n" + "=" * 65)
    print(" [PiShop Cloud] Microservicio de Inventario (P02 - Core)")
    print(" Politecnico Internacional - Fundamentos de Arquitectura")
    print("=" * 65)
    print(f" [*] Panel Interactivo Web : {URL_LOCAL}/")
    print(f" [*] Documentacion Swagger : {URL_LOCAL}/docs")
    print(f" [*] Sondas de salud       : /health/live - /health/ready - /health/startup")
    print("=" * 65)
    print(" Presione Ctrl + C para detener el servidor.\n")

    threading.Thread(target=_abrir_navegador, args=(URL_LOCAL,), daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=PUERTO)
