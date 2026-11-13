import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.config import INSTANCE_ID, PORT, STATIC_DIR
from app.database import init_db
from app.routers import health, orders, locations, chaos, demo, riders
from app import websockets

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: initializes database tables on startup."""
    init_db()
    os.makedirs(STATIC_DIR, exist_ok=True)
    yield

def create_app(instance_id: str = None) -> FastAPI:
    current_instance = instance_id or INSTANCE_ID
    current_port = 8000 if current_instance == "A" else 8001
    
    app = FastAPI(
        title=f"Crumb Tail - Instance {current_instance}",
        description="Yuktik 26 - Real-time delivery tracking platform powered by Redis and FastAPI",
        version="1.0.0",
        lifespan=lifespan
    )

    # Attach instance state to the app
    app.state.instance_id = current_instance
    app.state.port = current_port

    # Enable full CORS for local network and multi-instance communication
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount routers
    app.include_router(health.router)
    app.include_router(orders.router)
    app.include_router(locations.router)
    app.include_router(chaos.router)
    app.include_router(demo.router)
    app.include_router(riders.router)
    app.include_router(websockets.router)

    # Ensure static directory exists and mount it
    os.makedirs(STATIC_DIR, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/static/index.html")

    return app

# Default app instance
app = create_app()
