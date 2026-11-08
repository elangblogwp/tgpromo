import json
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from .login import LoginError
from .telegram import LOG

COOKIE = "__Host-userbot-login"
STATIC = Path(__file__).parent / "static"


def make_app(login):
    origin = login.settings.public_base_url
    host = urlsplit(origin).netloc

    @web.middleware
    async def secure(request, handler):
        try:
            if request.host != host:
                raise LoginError("Invalid host", 400)
            if request.method == "POST":
                if request.headers.get("Origin") != origin:
                    raise LoginError("Invalid request origin", 403)
                if request.content_type != "application/json":
                    raise LoginError("JSON request required", 415)
            response = await handler(request)
        except LoginError as exc:
            response = web.json_response({"error": str(exc)}, status=exc.status)
        except web.HTTPException as exc:
            response = web.json_response({"error": exc.reason}, status=exc.status)
        except (json.JSONDecodeError, UnicodeError):
            response = web.json_response({"error": "Invalid JSON"}, status=400)
        except Exception as exc:
            LOG.warning("Panel request failed: %s", type(exc).__name__)
            response = web.json_response({"error": "Request failed. Please try again."}, status=500)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Strict-Transport-Security": "max-age=31536000",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'",
            }
        )
        return response

    async def body(request):
        value = await request.json()
        if not isinstance(value, dict) or any(not isinstance(item, str) for item in value.values()):
            raise LoginError("Expected a JSON object containing strings")
        return value

    async def exchange(request):
        data = await body(request)
        cookie, csrf, suffix = await login.exchange(data.get("token", ""))
        response = web.json_response({"csrf": csrf, "suffix": suffix, "step": "send"})
        response.set_cookie(
            COOKIE,
            cookie,
            secure=True,
            httponly=True,
            samesite="Strict",
            path="/",
            max_age=login.settings.login_ttl,
        )
        return response

    async def action(request):
        data = await body(request)
        result = await login.action(
            request.cookies.get(COOKIE, ""),
            request.headers.get("X-CSRF-Token", ""),
            data.get("action", ""),
            data.get("value", ""),
        )
        response = web.json_response(result)
        if result["step"] in {"done", "cancelled"}:
            response.del_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Strict")
        return response

    async def index(request):
        return web.Response(text=(STATIC / "index.html").read_text(), content_type="text/html")

    async def script(request):
        return web.Response(
            text=(STATIC / "app.js").read_text(), content_type="application/javascript"
        )

    async def style(request):
        return web.Response(text=(STATIC / "style.css").read_text(), content_type="text/css")

    app = web.Application(middlewares=[secure], client_max_size=8192)
    app.add_routes(
        [
            web.get("/", index),
            web.get("/app.js", script),
            web.get("/style.css", style),
            web.post("/api/exchange", exchange),
            web.post("/api/action", action),
        ]
    )
    return app
