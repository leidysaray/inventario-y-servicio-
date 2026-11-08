"""Lanzador oficial para la Aplicación de Inventario (P02 - Core) PiShop Cloud."""
import sys
import threading
import time
import webbrowser
from pathlib import Path
import uvicorn

raiz = Path(__file__).resolve().parent
svc_dir = raiz / "services" / "inventario-service"
if str(svc_dir) not in sys.path:
    sys.path.insert(0, str(svc_dir))

from app.settings import get_settings


def abrir_navegador(url: str):
    time.sleep(1.5)
    print(f"\n[INFO] Abriendo la aplicación en su navegador: {url}\n")
    webbrowser.open(url)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    settings = get_settings()
    app_url = f"http://localhost:{settings.http_port}"
    
    print("\n" + "=" * 65)
    print(" [PiShop Cloud] Microservicio y Aplicacion de Inventario")
    print(" Politecnico Internacional - Fundamentos de Arquitectura")
    print("=" * 65)
    print(f" [*] Panel Interactivo Web : {app_url}/")
    print(f" [*] Documentacion Swagger : {app_url}/docs")
    print(f" [*] OpenAPI JSON          : {app_url}/openapi.json")
    print(f" [*] Sondas de salud       : /health/live - /health/ready - /health/startup")
    print("=" * 65)
    print(" Presione Ctrl + C en la terminal para detener el servidor.\n")

    # Abrir el navegador automaticamente
    threading.Thread(target=abrir_navegador, args=(app_url,), daemon=True).start()

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.http_port,
        reload=True,
        app_dir=str(svc_dir),
    )
