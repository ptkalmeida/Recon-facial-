"""
Security Middleware Module

Provides security headers and request validation.
"""

import logging
import secrets
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_cors_origins, settings

logger = logging.getLogger(__name__)

# Paths under /api that already have their own dedicated rate limiter (login,
# recognition) or must always stay reachable for monitoring (health).
_GENERAL_RATE_LIMIT_EXCLUDED_PATHS = (
    "/api/auth/login",
    "/api/recognition/detect",
    "/api/health",
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to all responses.
    
    Headers added:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Strict-Transport-Security (HSTS)
    - Content-Security-Policy
    - Referrer-Policy
    - Permissions-Policy
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generated up front so HTML-rendering routes (main.py) can read
        # request.state.csp_nonce and tag their <script> block with the same value.
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # HSTS - only in production
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # Content Security Policy. Scripts run only via this request's nonce -
        # no 'unsafe-inline'/'unsafe-eval'. style-src keeps 'unsafe-inline' for now
        # (inline style attributes are used throughout the templates; XSS risk via
        # style is much lower than via script).
        #
        # Os dois CDNs abaixo são carregados por app/templates/*.html (fonte Inter e
        # ícones Font Awesome). Sem eles no allowlist, o navegador bloqueia as
        # folhas de estilo e as páginas ficam sem ícone nenhum - regressão que o
        # teste de navegador (tests/browser/test_xss_escaping.py) pegou. Nenhum
        # deles entra em script-src: só estilo e fonte.
        csp = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob:; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        response.headers["Content-Security-Policy"] = csp
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions Policy (Feature Policy)
        permissions = (
            "camera=(self), "
            "microphone=(), "
            "geolocation=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "speaker=()"
        )
        response.headers["Permissions-Policy"] = permissions
        
        # Remove server header info (don't reveal framework)
        if "server" in response.headers:
            del response.headers["server"]
        
        return response


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """
    Validate incoming requests for security issues.
    
    Checks:
    - Request size limits
    - Suspicious patterns
    - Content-Type validation
    """
    
    def __init__(self, app, max_body_size: int = 10 * 1024 * 1024):  # 10MB default
        super().__init__(app)
        self.max_body_size = max_body_size
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check content length
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > self.max_body_size:
                    logger.warning(f"Request too large: {length} bytes from {request.client.host}")
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request entity too large"}
                    )
            except ValueError:
                pass
        
        # Log suspicious requests
        user_agent = request.headers.get("user-agent", "")
        if not user_agent or len(user_agent) < 5:
            logger.debug(f"Suspicious request: missing/short user-agent from {request.client.host}")
        
        return await call_next(request)


class GeneralRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Enforce api_rate_limiter (settings.rate_limit_max_requests / _window_seconds)
    on /api/* routes that don't already have a dedicated limiter.

    /api/auth/login and /api/recognition/detect are excluded (protected by their
    own stricter limiters in app/api/routes.py); /api/health is excluded so
    monitoring can always reach it.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path.startswith("/api/") and path not in _GENERAL_RATE_LIMIT_EXCLUDED_PATHS:
            from app.security.rate_limiter import (
                api_rate_limiter,
                create_rate_limit_key,
                get_client_ip,
            )

            client_ip = get_client_ip(request)
            rate_key = create_rate_limit_key("api", client_ip)
            allowed, metadata = api_rate_limiter.is_allowed(rate_key)

            if not allowed:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Muitas requisições. Tente novamente em {metadata['retry_after']} segundos."}
                )

        return await call_next(request)


# Security configuration helpers
def get_secure_cors_options() -> dict:
    """Get secure CORS configuration."""
    return {
        "allow_origins": get_cors_origins(),
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": [
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With"
        ],
        "expose_headers": [
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset"
        ],
        "max_age": 600,  # 10 minutes cache for preflight
    }
