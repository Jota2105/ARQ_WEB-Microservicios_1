"""Microservicio Productos. Solo accede a su propia base SQLite."""
from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

DB_PATH = Path(os.getenv("DB_PATH", "/data/productos.db"))
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def conectar() -> sqlite3.Connection:
    conexion = sqlite3.connect(DB_PATH, timeout=10)
    conexion.row_factory = sqlite3.Row
    return conexion


def iniciar_bd() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with conectar() as conexion:
        conexion.execute(
            """CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                precio_centavos INTEGER NOT NULL CHECK(precio_centavos > 0)
            )"""
        )


def formato_dinero(centavos: int) -> str:
    return f"{Decimal(centavos) / 100:.2f}"


def precio_a_centavos(precio: str | Decimal) -> int:
    try:
        valor = Decimal(str(precio))
        if not valor.is_finite() or valor <= 0 or valor > Decimal("99999.99"):
            raise ValueError("El precio debe estar entre 0.01 y 99999.99")
        if valor.as_tuple().exponent < -2:
            raise ValueError("El precio permite máximo dos decimales")
        return int((valor * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Precio inválido; use por ejemplo 12.50") from exc


def guardar_producto(nombre: str, precio: str | Decimal) -> dict:
    nombre = nombre.strip()
    if not (2 <= len(nombre) <= 80):
        raise HTTPException(status_code=422, detail="Nombre: de 2 a 80 caracteres")
    centavos = precio_a_centavos(precio)
    with conectar() as conexion:
        cursor = conexion.execute(
            "INSERT INTO productos(nombre, precio_centavos) VALUES (?, ?)",
            (nombre, centavos),
        )
        id_producto = cursor.lastrowid
    return {"id": id_producto, "nombre": nombre, "precio": formato_dinero(centavos), "precio_centavos": centavos}


def listar_productos() -> list[dict]:
    with conectar() as conexion:
        filas = conexion.execute("SELECT id, nombre, precio_centavos FROM productos ORDER BY id DESC").fetchall()
    return [dict(id=f["id"], nombre=f["nombre"], precio=formato_dinero(f["precio_centavos"]),
                 precio_centavos=f["precio_centavos"]) for f in filas]


@asynccontextmanager
async def lifespan(_: FastAPI):
    iniciar_bd()
    yield


app = FastAPI(title="Microservicio Productos", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class ProductoEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    precio: Decimal = Field(gt=0, le=Decimal("99999.99"), decimal_places=2)


@app.get("/health")
def health():
    with conectar() as conexion:
        conexion.execute("SELECT 1").fetchone()
    return {"servicio": "productos", "estado": "ok"}


@app.get("/")
def inicio(request: Request, creado: int = 0, error: str = ""):
    mensajes = {"nombre": "El nombre debe tener entre 2 y 80 caracteres.",
                "precio": "Precio inválido. Ejemplo válido: 12.50 (mayor que cero)."}
    return templates.TemplateResponse(request, "index.html", {
        "productos": listar_productos(), "creado": bool(creado), "error": mensajes.get(error, "")
    })


@app.post("/registrar")
def registrar(nombre: str = Form(...), precio: str = Form(...)):
    try:
        guardar_producto(nombre, precio)
    except HTTPException as exc:
        error = "nombre" if "Nombre" in str(exc.detail) else "precio"
        return RedirectResponse(f"/?error={error}", status_code=303)
    return RedirectResponse("/?creado=1", status_code=303)


@app.get("/api/productos")
def api_listar():
    return listar_productos()


@app.get("/api/productos/{producto_id}")
def api_obtener(producto_id: int):
    with conectar() as conexion:
        fila = conexion.execute(
            "SELECT id, nombre, precio_centavos FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
    if fila is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return {"id": fila["id"], "nombre": fila["nombre"],
            "precio": formato_dinero(fila["precio_centavos"]), "precio_centavos": fila["precio_centavos"]}


@app.post("/api/productos", status_code=201)
def api_crear(data: ProductoEntrada):
    return guardar_producto(data.nombre, data.precio)
