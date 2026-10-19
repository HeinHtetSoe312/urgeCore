"""RFC 9457 (formerly RFC 7807) problem-details error responses."""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import correlation_id_var

logger = logging.getLogger("app.errors")
PROBLEM_JSON = "application/problem+json"


class ProblemDetail(Exception):  # noqa: N818 - reads better as a domain term
    """Raise this anywhere to return an application/problem+json response."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        headers: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.type_ = type_
        self.headers = headers
        self.extensions = extensions


def _problem_response(
    request: Request,
    status: int,
    title: str,
    detail: str | None = None,
    type_: str = "about:blank",
    headers: dict[str, str] | None = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status,
        "instance": request.url.path,
        "correlation_id": correlation_id_var.get(),
    }
    if detail:
        body["detail"] = detail
    if extensions:
        body.update(extensions)
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON, headers=headers)


async def _handle_problem(request: Request, exc: ProblemDetail) -> JSONResponse:
    return _problem_response(
        request, exc.status, exc.title, exc.detail, exc.type_, exc.headers, exc.extensions
    )


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    try:
        title = HTTPStatus(exc.status_code).phrase
    except ValueError:
        title = "Error"
    headers = dict(exc.headers) if exc.headers else None
    return _problem_response(request, exc.status_code, title, str(exc.detail), headers=headers)


async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Deliberately drop "input" and "ctx": they can echo passwords or other secrets.
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return _problem_response(
        request,
        422,
        "Validation Error",
        "Request validation failed.",
        extensions={"errors": errors},
    )


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error")  # full detail goes to logs, never to the client
    return _problem_response(request, 500, "Internal Server Error", "An unexpected error occurred.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemDetail, _handle_problem)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unexpected)
