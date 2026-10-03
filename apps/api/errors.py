"""Error shape of the HTTP API: ``{"error": {"code": str, "message": str}}``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ingest.email_format import EmailFormatError
from ingest.llm_protocol import LLMFormatError
from ingest.recorder_format import RecorderFormatError

from .hive_adapter import HiveConflict, HiveNotFound

log = logging.getLogger(__name__)


class ApiError(Exception):
    """Raise anywhere in a route to produce the contract's error envelope."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def install_error_handlers(app: FastAPI) -> None:
    """Map every failure mode to the envelope; unexpected errors are logged and returned as 500."""

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = {404: "not_found", 400: "bad_request", 405: "method_not_allowed", 422: "validation_error"}.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "validation_error", str(exc.errors()[:3]))

    @app.exception_handler(HiveNotFound)
    async def _not_found(_: Request, exc: HiveNotFound) -> JSONResponse:
        return error_response(404, "not_found", str(exc))

    @app.exception_handler(HiveConflict)
    async def _conflict(_: Request, exc: HiveConflict) -> JSONResponse:
        return error_response(409, "conflict", str(exc))

    @app.exception_handler(RecorderFormatError)
    async def _recorder(_: Request, exc: RecorderFormatError) -> JSONResponse:
        return error_response(400, "invalid_recorder_export", str(exc)[:2000])

    @app.exception_handler(EmailFormatError)
    async def _email(_: Request, exc: EmailFormatError) -> JSONResponse:
        return error_response(400, "invalid_email_thread", str(exc)[:2000])

    @app.exception_handler(LLMFormatError)
    async def _llm_format(_: Request, exc: LLMFormatError) -> JSONResponse:
        return error_response(502, "llm_format_error", str(exc)[:2000])

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", exc)
        return error_response(500, "internal_error", f"{type(exc).__name__}: {exc}"[:2000])
