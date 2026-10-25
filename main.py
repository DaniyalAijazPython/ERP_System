from fastapi import FastAPI

from app.core.errors import register_error_handlers
from app.modules.auth.routes import router as auth_router


def create_app() -> FastAPI:
    app = FastAPI(title="Lightweight ERP for Small Manufacturers", version="0.1.0")
    register_error_handlers(app)

    app.include_router(auth_router)
    return app


app = create_app()
