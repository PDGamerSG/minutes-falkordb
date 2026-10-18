"""Error shape of the HTTP API: ``{"error": {"code": str, "message": str, ...}}``.

Every failure mode maps to the envelope, including Starlette's own 404/405 for unknown routes.
Unexpected errors return a generic message with a ``request_id`` that is also in the server log
(the exception text never reaches the client). Rate limits carry ``retry_after`` (seconds) in the
envelope and a ``Retry-After`` header.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ingest.email_format import EmailFormatError
from ingest.llm_protocol import LLMFormatError
from ingest.recorder_format import RecorderFormatError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .hive_adapter import HiveConflict, HiveNotFound
from .llm import LLMError, LLMRateLimited

log = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class ApiError(Exception):
    """Raise anywhere in a route to produce the contract's error envelope."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def error_response(status: int, code: str, message: str, *, _headers: dict[str, str] | None = None, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    body.update({k: v for k, v in extra.items() if v is not None})
    headers: dict[str, str] = dict(_headers or {})
    if extra.get("retry_after") is not None:
        headers["Retry-After"] = str(int(max(1, round(float(extra["retry_after"])))))
    return JSONResponse(status_code=status, content={"error": body}, headers=headers or None)


def request_id_of(request: Request) -> str:
    rid = getattr(request.state, "request_id", None) or request.headers.get(REQUEST_ID_HEADER)
    if not rid:
        rid = uuid.uuid4().hex[:16]
    request.state.request_id = rid
    return rid


def _validation_message(errors: list[dict[str, Any]]) -> str:
    """``loc: msg`` pairs; never the submitted input or a Python repr."""
    parts = []
    for err in errors[:3]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body") or "body"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    more = len(errors) - 3
    return "; ".join(parts) + (f" (+{more} more)" if more > 0 else "")


def install_error_handlers(app: FastAPI) -> None:
    """Map every failure mode to the envelope; unexpected errors are logged with a request id and returned as 500."""

    @app.middleware("http")
    async def _request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers.setdefault(REQUEST_ID_HEADER, rid)
        return response

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 400: "bad_request", 401: "unauthorized", 403: "forbidden", 405: "method_not_allowed", 413: "payload_too_large", 422: "validation_error"}.get(exc.status_code, "http_error")
        detail = exc.detail if isinstance(exc.detail, str) else "request failed"
        return error_response(exc.status_code, code, detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "validation_error", _validation_message(list(exc.errors())))

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

    @app.exception_handler(LLMRateLimited)
    async def _llm_rate_limit(_: Request, exc: LLMRateLimited) -> JSONResponse:
        return error_response(503, "llm_rate_limited", "the model is rate limited; retry shortly", retry_after=exc.retry_after)

    @app.exception_handler(LLMError)
    async def _llm_error(request: Request, exc: LLMError) -> JSONResponse:
        rid = request_id_of(request)
        log.warning("model unavailable (request %s): %s", rid, exc)
        return error_response(503, "llm_unavailable", "the model is unavailable; please retry", request_id=rid)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        rid = request_id_of(request)
        retry_after = getattr(exc, "retry_after", None)
        if retry_after is not None:
            log.warning("rate limited (request %s): %s", rid, exc)
            return error_response(503, "llm_rate_limited", "the model is rate limited; retry shortly", _headers={REQUEST_ID_HEADER: rid}, retry_after=retry_after, request_id=rid)
        log.exception("unhandled error (request %s): %s", rid, exc)
        # ServerErrorMiddleware sits outside the request-id middleware, so the header is set here.
        return error_response(500, "internal_error", "internal error; see the server log for this request id", _headers={REQUEST_ID_HEADER: rid}, request_id=rid)
