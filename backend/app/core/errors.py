"""Uniform error responses and domain exceptions -> {"error": {"code", "message_uz", "message_en"}}."""
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, code: str, message_uz: str, http_status: int = 400, details: Any = None):
        self.code = code
        self.message_uz = message_uz
        self.http_status = http_status
        self.details = details
        super().__init__(message_uz)


class AINotConfigured(ApiError):
    def __init__(self, feature: str = "bu funksiya"):
        super().__init__(
            code="AI_NOT_CONFIGURED",
            message_uz=(
                "AI xizmati hozircha sozlanmagan, shu sababli "
                f"{feature} ishlamaydi. Iltimos, server administratori AI provayder kalitini sozlasin "
                "(env: AI_PROVIDER, AI_API_KEY, AI_MODEL)."
            ),
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def error_response(code: str, message: str, http_status: int, details: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={"error": {"code": code, "message_uz": message, "details": details}},
    )


def install_error_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return error_response(exc.code, exc.message_uz, exc.http_status, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        simplified = [
            {"field": ".".join(str(p) for p in err.get("loc", [])[1:]), "msg": err.get("msg", "")}
            for err in exc.errors()[:10]
        ]
        return error_response("VALIDATION_ERROR", "Yuborilgan ma'lumotlar noto'g'ri formatda.", 422, simplified)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):  # never leak stack traces
        import logging

        logging.getLogger("lingora").exception("Unhandled error: %s", exc)
        return error_response(
            "INTERNAL_ERROR",
            "Serverda kutilmagan xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.",
            500,
        )
