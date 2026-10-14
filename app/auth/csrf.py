"""CSRF middleware: double-submit cookie pattern.

For any state-changing request (POST/PUT/PATCH/DELETE) that targets /api/*,
require that:
  - The `csrf` cookie exists, AND
  - The `X-CSRF-Token` header matches it, AND
  - The Origin (when present) matches CORS allowlist.

Exempted: the M-Pesa Daraja callback (Safaricom can't include our CSRF cookie)
— authenticity for that endpoint comes from origin/IP allowlisting (Phase 5).
"""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.config import settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT_PATH_PREFIXES = ("/api/mpesa/callback",)


class CsrfMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
            if not any(
                request.url.path.startswith(p) for p in CSRF_EXEMPT_PATH_PREFIXES
            ):
                deny = self._check(request)
                if deny is not None:
                    return deny
        return await call_next(request)

    def _check(self, request: Request) -> JSONResponse | None:
        cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
        header_token = request.headers.get("X-CSRF-Token") or request.headers.get(
            "x-csrf-token"
        )

        # Pre-session requests (e.g. POST /api/auth/request-otp before any cookie is set)
        # are allowed only when neither cookie nor header is present. Once a session
        # exists, both must be present and equal.
        if cookie_token is None and header_token is None:
            return None

        if not cookie_token or not header_token:
            return JSONResponse(
                {"detail": "CSRF cookie or header missing"}, status_code=403
            )
        if not hmac.compare_digest(cookie_token, header_token):
            return JSONResponse({"detail": "CSRF token mismatch"}, status_code=403)

        # Origin sanity check
        origin = request.headers.get("origin")
        if origin and origin not in settings.cors_origins_list:
            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        return None
