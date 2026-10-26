"""Correlation ID middleware."""

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import correlation_id_var

HEADER = "X-Correlation-ID"
# Only accept safe values so clients cannot inject junk into our logs.
_VALID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(HEADER, "")
        correlation_id = incoming if _VALID.match(incoming) else uuid.uuid4().hex
        # Each request runs in its own task, so no reset is needed; this also lets
        # the outer 500 handler still see the ID.
        correlation_id_var.set(correlation_id)
        response = await call_next(request)
        response.headers[HEADER] = correlation_id
        return response
