from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Business-rule error rendered as {"error": {"code", "message", "field"}}."""

    status_code = 400

    def __init__(self, code: str, message: str, field: str | None = None, status_code: int | None = None):
        self.code = code
        self.message = message
        self.field = field
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message)


class NotFound(AppError):
    status_code = 404


class Unauthorized(AppError):
    status_code = 401


class Forbidden(AppError):
    status_code = 403


class Conflict(AppError):
    status_code = 409


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "field": exc.field}},
        )
