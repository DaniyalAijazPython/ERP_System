from fastapi import APIRouter, FastAPI

from app.core.errors import register_error_handlers
from app.modules.auth.routes import router as auth_router
from app.modules.inventory.routes import router as inventory_router


def create_app() -> FastAPI:
    app = FastAPI(title="Lightweight ERP for Small Manufacturers", version="0.1.0")
    register_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(auth_router)
    api.include_router(inventory_router)
    app.include_router(api)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
