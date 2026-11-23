# Laboratorio de Arquitectura de Microservicios: Productos y Pedidos

Proyecto didáctico. Dos servicios FastAPI autónomos, bases SQLite separadas y Docker Compose.
Este ZIP contiene **el código terminado**. No se requiere modificarlo ni instalar Python en Windows.

## Inicio rápido (PowerShell en la carpeta que contiene `compose.yaml`)

```powershell
docker compose config
docker compose up --build -d
docker compose ps
```

- Productos: http://localhost:8001
- Pedidos: http://localhost:8002
- JSON de productos: http://localhost:8001/api/productos
- JSON de pedidos: http://localhost:8002/api/pedidos

## Probar interrupción y recuperación

```powershell
docker compose stop productos
docker compose ps
# Compruebe que http://localhost:8002 sigue mostrando los pedidos existentes.
docker compose start productos
docker compose ps
```

## Comprobar persistencia al recrear contenedores

```powershell
docker compose down
docker compose up -d
docker compose ps
```

**IMPORTANTE:** No use `docker compose down -v` ni `docker compose down --volumes`,
pues esos comandos eliminan las bases SQLite guardadas en los volúmenes.

## Cómo está organizado

- `compose.yaml`: definición de los servicios, puertos, red interna y volúmenes.
- `productos/`: microservicio de Productos con su propia SQLite (`/data/productos.db`).
- `pedidos/`: microservicio de Pedidos con su propia SQLite (`/data/pedidos.db`).
- Cada servicio: `Dockerfile`, dependencias, aplicación Python, plantilla HTML y CSS.

El enlace `http://productos:8000` funciona dentro de la red de Docker Compose;
no está pensado para abrirse en el navegador del equipo Windows.

Los nombres de los volúmenes son `laboratorio-microservicios_datos_productos` y
`laboratorio-microservicios_datos_pedidos`. El prefijo puede variar con la configuración local.

## Restricciones del ejemplo

Uso didáctico local: sin autenticación, sin inventario, sin cobros, sin gateway,
sin balanceo y sin garantías de alta disponibilidad. No exponer este proyecto a Internet.
El servicio Pedidos conserva una copia del nombre y precio al crear cada pedido.
Cuando Productos no está disponible, Pedidos **sí** consulta pedidos guardados,
pero **no** puede validar ni crear pedidos nuevos.
