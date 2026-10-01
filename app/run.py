"""Production entrypoint for the FastAPI application."""

from __future__ import annotations

import os

import uvicorn


def _port() -> int:
    """Return Easypanel's PORT, falling back safely when invalid or absent."""
    try:
        port = int(os.environ.get("PORT", 8000))
    except (TypeError, ValueError):
        return 8000
    return port if 1 <= port <= 65535 else 8000


if __name__ == "__main__":
    port = _port()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
