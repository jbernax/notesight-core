import logging
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from app.config import settings

logger = logging.getLogger(__name__)

# Standard CSP configured for NoteSight: allows OSMD SVG, Verovio WASM, Web Audio blobs, and Vite dev/prod scripts
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "worker-src 'self' blob:; "
    "object-src 'none'; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware:
    """
    Pure ASGI middleware attaching defense-in-depth HTTP security headers to all responses.
    Avoids BaseHTTPMiddleware response body buffering and streaming overhead.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not settings.ENABLE_SECURITY_HEADERS:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        req_headers = Headers(scope=scope)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)

                # Anti-MIME sniffing
                headers.setdefault("X-Content-Type-Options", "nosniff")

                # Anti-clickjacking
                csp = DEFAULT_CSP
                if path.startswith("/score/embed") or path.startswith("/api/scores/embed"):
                    csp = csp.replace("frame-ancestors 'self'", "frame-ancestors *")
                    # Omit X-Frame-Options on embed routes so browsers obey CSP frame-ancestors *
                elif (
                    path.startswith("/api/docs")
                    or path.startswith("/docs")
                    or path.startswith("/api/redoc")
                    or path.startswith("/redoc")
                ):
                    csp = (
                        "default-src 'self'; "
                        "script-src 'self' 'unsafe-eval' 'unsafe-inline' https://cdn.jsdelivr.net; "
                        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                        "img-src 'self' data: blob: https://cdn.jsdelivr.net https://fastapi.tiangolo.com; "
                        "font-src 'self' data: https://cdn.jsdelivr.net; "
                        "connect-src 'self'; "
                        "frame-ancestors 'self';"
                    )
                    headers.setdefault("X-Frame-Options", "SAMEORIGIN")
                else:
                    headers.setdefault("X-Frame-Options", "SAMEORIGIN")

                # Modern standard XSS protection (disable flawed legacy browser filter)
                headers.setdefault("X-XSS-Protection", "0")

                # Referrer privacy
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

                # Restrict dangerous browser hardware APIs
                headers.setdefault(
                    "Permissions-Policy",
                    "camera=(), microphone=(), geolocation=(), payment=()",
                )

                # Content Security Policy
                headers.setdefault("Content-Security-Policy", csp)

                # Strict-Transport-Security if request was over HTTPS or forwarded via SSL proxy
                proto = req_headers.get("x-forwarded-proto", scope.get("scheme", "http"))
                if proto == "https":
                    headers.setdefault(
                        "Strict-Transport-Security",
                        "max-age=31536000; includeSubDomains; preload",
                    )

            await send(message)

        await self.app(scope, receive, send_wrapper)
