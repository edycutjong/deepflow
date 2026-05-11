"""
Health check endpoint for Docker HEALTHCHECK.
Simple HTTP server on port 8080 that returns 200 if the scheduler is running.
"""
from aiohttp import web
from loguru import logger


_healthy = False


def set_healthy(healthy: bool) -> None:
    """Set health status from main scheduler."""
    global _healthy
    _healthy = healthy


async def _health_handler(request: web.Request) -> web.Response:
    """Return 200 if healthy, 503 otherwise."""
    if _healthy:
        return web.json_response({"status": "ok"}, status=200)
    return web.json_response({"status": "unhealthy"}, status=503)


async def start_health_server(port: int = 8080) -> web.AppRunner:
    """Start a lightweight health check HTTP server."""
    app = web.Application()
    app.router.add_get("/health", _health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check server started on port {port}")
    return runner
