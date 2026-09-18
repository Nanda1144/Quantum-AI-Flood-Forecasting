"""Unified success / error envelopes for the quantum service API."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class QuantumError(Exception):
    """Raised by the contract layer; serialised to the shared error envelope.

    Codes are stable so the Node backend's fallback policy can act on them
    (e.g. `HARDWARE_UNAVAILABLE`, `AER_UNAVAILABLE`, `QUBO_UNAVAILABLE`).
    """

    def __init__(self, code: str, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def success(data: object) -> dict:
    return {"success": True, "data": data, "timestamp": now_iso()}


def failure(code: str, message: str) -> dict:
    return {"success": False, "error": {"code": code, "message": message}, "timestamp": now_iso()}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=failure("VALIDATION_ERROR", "Request validation failed"))

    @app.exception_handler(QuantumError)
    async def quantum_error_handler(_request: Request, exc: QuantumError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=failure(exc.code, exc.message))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content=failure("INTERNAL_ERROR", "Unexpected server error"))