"""FORGE backend entrypoint — FastAPI app with the realtime WebSocket bridge.

Routes:
  * ``GET  /healthz``                 — liveness.
  * ``GET  /api/config``              — non-secret runtime config for the frontend.
  * ``GET  /api/schematics/{file}``   — serve the bundled labeled SVG schematics.
  * ``WS   /ws``                      — the realtime field-console bridge.
  * ``GET  /cloud/health``            — Alibaba Cloud OSS + DashScope proof (Stage G).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.data.catalog import catalog
from app.data.catalog import SCHEMATICS_DIR
from app.ws.gateway import RealtimeBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("forge")

settings = get_settings()
app = FastAPI(title="FORGE", version="0.1.0", description="Field Operations Real-time Guidance Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Alibaba Cloud proof router (OSS + cloud health). Optional so the app boots even
# before cloud creds are wired.
try:  # pragma: no cover - exercised at deploy time
    from app.cloud.alibaba import router as cloud_router

    app.include_router(cloud_router)
except Exception as exc:  # noqa: BLE001
    logger.info("cloud router not mounted: %s", exc)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "forge",
        "realtime_configured": settings.realtime_configured,
        "model": settings.realtime_model,
        "region": settings.region,
    }


@app.get("/api/config")
def api_config() -> dict[str, object]:
    """Non-secret config the frontend needs (audio rates, asset, vision dims)."""
    return {
        "asset_id": catalog.default_asset_id,
        "input_sample_rate": settings.input_sample_rate,
        "output_sample_rate": settings.output_sample_rate,
        "vision": {"width": 320, "height": 240, "fps": 1, "screen": {"width": 768, "height": 768}},
        "session_max_seconds": settings.session_resume_after_seconds,
    }


@app.get("/api/schematics/{file}", response_model=None)
def schematic(file: str) -> FileResponse | JSONResponse:
    # Serve only bundled SVGs; reject anything that isn't a plain .svg basename.
    if "/" in file or "\\" in file or not file.endswith(".svg"):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = SCHEMATICS_DIR / file
    if not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="image/svg+xml")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    bridge = RealtimeBridge(websocket)
    await bridge.run()


# Serve the built field console (single-container deploy). API/WS routes above take
# precedence; this SPA mount (html=True) catches everything else. Set FORGE_FRONTEND_DIST
# or place the build at ../frontend/dist.
_dist = Path(os.environ.get("FORGE_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
    logger.info("serving frontend from %s", _dist)
else:
    logger.info("frontend dist not found at %s (dev mode serves it via Vite)", _dist)

