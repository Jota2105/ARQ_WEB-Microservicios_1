"""Microservicio Pedidos. Solo consulta Productos por HTTP; no abre su SQLite."""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("DB_PATH", "/data/pedidos.db"))
PRODUCTOS_URL = os.getenv("PRODUCTOS_URL", "http://productos:8000").rstrip("/")
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
log = logging.getLogger("uvicorn.error")


def conectar() -> sqlite3.Connection:
    conexion = sqlite3.connect(DB_PATH, timeout=10)
    conexion.row_factory = sqlite3.Row
    return conexion


def iniciar_bd() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with conectar() as conexion:
        conexion.execute(
            """CREATE TABLE IF NOT EXISTS pedidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                producto_id INTEGER NOT NULL,
                producto_nombre TEXT NOT NULL,
                precio_unitario_centavos INTEGER NOT NULL,
                cantidad INTEGER NOT NULL CHECK(cantidad BETWEEN 1 AND 99),
                total_centavos INTEGER NOT NULL,
                creado_utc TEXT NOT NULL
            )"""
        )


def dinero(centavos: int) -> str:
    return f"{Decimal(centavos) / 100:.2f}"


def listar_pedidos() -> list[dict]:
    with conectar() as conexion:
        filas = conexion.execute(
            """SELECT id, producto_id, producto_nombre, precio_unitario_centavos,
                      cantidad, total_centavos, creado_utc FROM pedidos ORDER BY id DESC"""
        ).fetchall()
    return [dict(id=f["id"], producto_id=f["producto_id"], producto_nombre=f["producto_nombre"],
                 precio_unitario=dinero(f["precio_unitario_centavos"]),
                 cantidad=f["cantidad"], total=dinero(f["total_centavos"]),
                 creado_utc=f["creado_utc"]) for f in filas]


async def consultar_productos(ruta: str) -> dict | list:
    url = f"{PRODUCTOS_URL}{ruta}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as cliente:
            respuesta = await cliente.get(url)
        log.info("COMUNICACION HTTP: GET %s -> %s", url, respuesta.status_code)
        if respuesta.status_code == 404:
            raise HTTPException(status_code=404, detail="El producto solicitado no existe")
        if respuesta.status_code >= 400:
            raise HTTPException(status_code=502, detail="Productos respondió con un error")
        return respuesta.json()
    except (httpx.RequestError, ValueError) as exc:
        log.warning("COMUNICACION HTTP: GET %s -> ERROR (%s)", url, exc.__class__.__name__)
        raise HTTPException(status_code=503, detail="Productos no disponible por HTTP") from exc


async def crear_pedido(producto_id: int, cantidad: int) -> dict:
    if producto_id < 1 or not 1 <= cantidad <= 99:
        raise HTTPException(status_code=422, detail="Producto o cantidad inválidos")
    producto = await consultar_productos(f"/api/productos/{producto_id}")
    unitario = int(producto["precio_centavos"])
    total = unitario * cantidad
    creado_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with conectar() as conexion:
        cursor = conexion.execute(
            """INSERT INTO pedidos(producto_id, producto_nombre, precio_unitario_centavos,
               cantidad, total_centavos, creado_utc) VALUES (?, ?, ?, ?, ?, ?)""",
            (producto["id"], producto["nombre"], unitario, cantidad, total, creado_utc),
        )
        id_pedido = cursor.lastrowid
    return {"id": id_pedido, "producto_id": producto["id"],
            "producto_nombre": producto["nombre"], "precio_unitario": dinero(unitario),
            "cantidad": cantidad, "total": dinero(total), "creado_utc": creado_utc}


@asynccontextmanager
async def lifespan(_: FastAPI):
    iniciar_bd()
    yield


app = FastAPI(title="Microservicio Pedidos", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class PedidoEntrada(BaseModel):
    producto_id: int = Field(ge=1)
    cantidad: int = Field(ge=1, le=99)


@app.get("/health")
def health():
    with conectar() as conexion:
        conexion.execute("SELECT 1").fetchone()
    return {"servicio": "pedidos", "estado": "ok"}


@app.get("/")
async def inicio(request: Request, creado: int = 0, error: str = ""):
    try:
        productos = await consultar_productos("/api/productos")
        conectado = True
    except HTTPException:
        productos = []
        conectado = False
    mensajes = {
        "productos_no_disponible": "No se pudo contactar a Productos. Los pedidos existentes siguen disponibles.",
        "producto_no_encontrado": "El producto seleccionado ya no existe.",
        "producto_invalido": "Elija un producto válido y una cantidad entre 1 y 99.",
    }
    return templates.TemplateResponse(request, "index.html", {
        "productos": productos, "pedidos": listar_pedidos(), "conectado": conectado,
        "creado": bool(creado), "error": mensajes.get(error, ""),
    })


@app.post("/registrar")
async def registrar(producto_id: int = Form(...), cantidad: int = Form(...)):
    try:
        await crear_pedido(producto_id, cantidad)
    except HTTPException as exc:
        if exc.status_code in (503, 502):
            code = "productos_no_disponible"
        elif exc.status_code == 404:
            code = "producto_no_encontrado"
        else:
            code = "producto_invalido"
        return RedirectResponse(f"/?error={code}", status_code=303)
    return RedirectResponse("/?creado=1", status_code=303)


@app.get("/api/pedidos")
def api_listar():
    # Crucial: la consulta solo utiliza pedidos.db; no consulta al otro servicio.
    return listar_pedidos()


@app.post("/api/pedidos", status_code=201)
async def api_crear(data: PedidoEntrada):
    return await crear_pedido(data.producto_id, data.cantidad)
