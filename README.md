# PiShop Cloud — Parcial 1 (primer corte, 15 %)

Fundamentos de Arquitectura (1419) · Politécnico Internacional I.E.S. · Docente: Edgar Humberto Angel Millán

Sistema de comercio electrónico que los 12 estudiantes construyen entre todos aplicando las semanas 1 a 4 del curso (arquitectura y calidad, DDD y servicios, escalabilidad y comunicación, configuración y descubrimiento).

**Entrega: martes 10 de noviembre de 2026, 13:00 (hora de Bogotá).**

## Empiece aquí

1. Lea [`docs/ENUNCIADO.md`](docs/ENUNCIADO.md): reglas, flujo de GitHub, cronograma y rúbrica.
2. Consulte su paquete (lo asigna la [ruleta](ruleta/index.html)) en [`docs/ROLES.md`](docs/ROLES.md).
3. Respete los contratos de [`docs/CONTRATOS.md`](docs/CONTRATOS.md) y los de [`contracts/endpoints.json`](contracts/endpoints.json).
4. Copie `plantilla-servicio/` a `services/<su-servicio>/` y trabaje en una rama `pXX-nombre`.
5. Valide: `python herramientas/validar_entrega.py <su-servicio>`.
6. Abra un Pull Request hacia `main`.
7. Declare el uso de IA generativa (si la utilizó) en el README de su paquete: qué parte y qué verificó.

## Levantar el sistema completo

```
docker compose up -d
```

## Estructura

```
contracts/endpoints.json   contrato verificable por máquina
docs/                      enunciado, contratos, roles y (P11) arquitectura
plantilla-servicio/        servicio FastAPI base: settings, tres sondas, Dockerfile, prueba
services/                  un directorio por servicio (lo crea cada estudiante)
herramientas/              validar_entrega.py (y las que cree P11/P12)
ruleta/index.html          ruleta para repartir los 12 paquetes
docker-compose.yml         sistema completo (lo mantiene P12)
```

## Entorno

Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL 17, Redis 8, Consul 1.21 y Docker Compose v2.
