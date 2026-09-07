"""FastAPI front-end: upload a face, watch the pipeline run live.

Progress is streamed with Server-Sent Events so the browser shows each stage as
it completes, the same way the CLI does — rather than staring at a spinner for
30 seconds and being handed a finished blob.

Concurrency is deliberately capped at one run: the face models are the dominant
memory cost and two simultaneous runs would risk an out-of-memory kill on a
small instance.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config  # noqa: E402
from webapp import runner  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
SAMPLE = ROOT / "input" / "sample.jpg"

MAX_UPLOAD_BYTES = 8 * 1024 * 1024

app = FastAPI(title="HH Goa 2026 — Task 3", docs_url=None, redoc_url=None)

# One run at a time. See module docstring.
_run_lock = asyncio.Lock()


@app.get("/healthz")
async def healthz():
    config = load_config()
    return {
        "status": "ok",
        "search_configured": bool(config.search.api_key),
        "network": config.chain.network,
        "models_loaded": runner._detector is not None,
    }


@app.get("/api/config")
async def api_config():
    config = load_config()
    return {
        "network": config.chain.network,
        "threshold": config.face.match_threshold,
        "prefer_platform": config.search.prefer_platform,
        "max_checks": config.search.max_face_checks,
        "search_configured": bool(config.search.api_key),
        "sample_available": SAMPLE.exists(),
    }


@app.get("/api/sample")
async def api_sample():
    if not SAMPLE.exists():
        raise HTTPException(404, "sample image not found")
    return FileResponse(SAMPLE, media_type="image/jpeg")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _stream(image_path: Path, cleanup: Path | None, options: dict):
    """Drive the blocking pipeline in a worker thread, emitting SSE as it goes."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()

    def produce():
        try:
            for event in runner.run(image_path, **options):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:  # noqa: BLE001 - surfaced to the browser
            loop.call_soon_threadsafe(
                queue.put_nowait, {"event": "fail", "text": f"Pipeline error: {exc}"}
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    started = time.monotonic()
    task = loop.run_in_executor(None, produce)
    try:
        while True:
            event = await queue.get()
            if event is SENTINEL:
                break
            yield _sse(event)
        yield _sse({"event": "elapsed", "seconds": round(time.monotonic() - started, 1)})
    finally:
        await task
        if cleanup is not None:
            cleanup.unlink(missing_ok=True)


@app.post("/api/run")
async def api_run(
    image: UploadFile | None = File(default=None),
    use_sample: str = Form(default="false"),
    prefer_platform: str = Form(default=""),
    threshold: str = Form(default=""),
    max_checks: str = Form(default=""),
):
    if _run_lock.locked():
        raise HTTPException(
            429, "A run is already in progress. This demo processes one image at a time."
        )

    cleanup: Path | None = None
    if use_sample.lower() == "true" or image is None:
        if not SAMPLE.exists():
            raise HTTPException(400, "No image supplied and no sample available")
        path = SAMPLE
    else:
        data = await image.read()
        if not data:
            raise HTTPException(400, "Uploaded file is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Image exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB")
        suffix = Path(image.filename or "upload.jpg").suffix or ".jpg"
        handle = tempfile.NamedTemporaryFile(prefix="hhgoa_web_", suffix=suffix, delete=False)
        handle.write(data)
        handle.close()
        path = cleanup = Path(handle.name)

    options: dict = {}
    if prefer_platform.strip():
        options["prefer_platform"] = prefer_platform.strip()
    if threshold.strip():
        try:
            options["threshold"] = float(threshold)
        except ValueError:
            raise HTTPException(400, "threshold must be a number") from None
    if max_checks.strip():
        try:
            options["max_checks"] = max(1, min(25, int(max_checks)))
        except ValueError:
            raise HTTPException(400, "max_checks must be an integer") from None

    async def guarded():
        async with _run_lock:
            async for chunk in _stream(path, cleanup, options):
                yield chunk

    return StreamingResponse(
        guarded(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
