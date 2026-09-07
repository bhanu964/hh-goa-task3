#!/usr/bin/env python3
"""Download the InsightFace model pack into the image at build time.

Called from the Dockerfile. Retries because a single transient GitHub failure
should not break an otherwise reproducible build — this happened during
development and cost a full rebuild.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import time

ROOT = os.getenv("INSIGHTFACE_HOME", "/opt/insightface")
PACK = os.getenv("FACE_MODEL_PACK", "buffalo_l")
ATTEMPTS = 5


def fetch() -> None:
    from insightface.app import FaceAnalysis

    FaceAnalysis(
        name=PACK,
        root=ROOT,
        allowed_modules=["detection", "recognition"],
        providers=["CPUExecutionProvider"],
    )


def main() -> int:
    target = os.path.join(ROOT, "models", PACK)
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fetch()
            print(f"model pack '{PACK}' ready at {target}")
            return 0
        except Exception as exc:  # noqa: BLE001 - any failure is worth retrying
            print(f"attempt {attempt}/{ATTEMPTS} failed: {exc}", file=sys.stderr)
            # A partial download would otherwise be treated as complete.
            shutil.rmtree(target, ignore_errors=True)
            with contextlib.suppress(OSError):
                os.remove(os.path.join(ROOT, "models", f"{PACK}.zip"))
            if attempt < ATTEMPTS:
                delay = 2**attempt
                print(f"retrying in {delay}s…", file=sys.stderr)
                time.sleep(delay)

    print(f"could not download model pack '{PACK}' after {ATTEMPTS} attempts", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
