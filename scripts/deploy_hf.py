#!/usr/bin/env python3
"""Create/update the Hugging Face Space for the web demo.

    python scripts/deploy_hf.py [--space user/name] [--private]

Needs a Hugging Face token with write access (`hf auth login`, or HF_TOKEN).
The SerpApi key is uploaded as a Space *secret*, never committed.

Hugging Face reads Space configuration from YAML front matter in README.md.
The project's own README is not polluted with it — this script generates a
Space-specific README that carries the front matter and links back to GitHub.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
GITHUB = "https://github.com/bhanu964/hh-goa-task3"

SPACE_README = """---
title: Face Identification and Blockchain Verification
emoji: 🔎
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Face to reverse image search to on-chain verification
---

# Face Identification → Reverse Image Search → Blockchain Verification

**HH Goa 2026 — Shortlisting Task 3**

Upload a face. It is embedded with ArcFace, searched **live** through Google
Lens, every candidate is verified by cosine similarity of face embeddings, and
a SHA-256 of the discovered record is anchored on-chain and read back.

Each of the seven stages streams into the page as it happens.

* **Source, docs and tests:** {github}
* **Blockchain:** in-process EVM (py-evm) — a genuine EVM with real
  transactions and receipts, but ephemeral. The CLI also supports Ethereum
  Sepolia.
* **Face embeddings never leave the server.** Only a 32-byte SHA-256 of public
  post metadata is anchored.

### Notes for visitors

Reverse image search only finds images that are **publicly indexed**. A private
selfie will usually return no match — the pipeline reports that honestly rather
than inventing one.

Runs are rate-limited because the search runs on a personal API key with a
finite monthly allowance. To run without limits, clone the repo and use your
own key.
""".format(github=GITHUB)

# Everything the Space does not need, or must never receive.
IGNORE = [
    ".env",
    ".git/*",
    ".venv/*",
    "**/__pycache__/*",
    "*.pyc",
    ".pytest_cache/*",
    "output/*",
    ".DS_Store",
    "**/.DS_Store",
    "input/*",
    "render.yaml",
    ".github/*",
]
# input/sample.jpg is needed by the demo's "Use sample" button, so it is
# re-added explicitly after the blanket input/ exclusion.
ALLOW = ["input/sample.jpg", "input/ATTRIBUTION.md"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--space", default=None, help="target repo id, e.g. user/name")
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    api = HfApi()
    try:
        user = api.whoami()["name"]
    except Exception as exc:  # noqa: BLE001
        print(f"Not authenticated with Hugging Face: {exc}", file=sys.stderr)
        print("Run: hf auth login   (or set HF_TOKEN)", file=sys.stderr)
        return 1

    repo_id = args.space or f"{user}/hh-goa-task3"
    print(f"target space: {repo_id}")

    api.create_repo(
        repo_id=repo_id,
        repo_type="space",
        space_sdk="docker",
        private=args.private,
        exist_ok=True,
    )
    print("  space exists")

    readme = ROOT / "SPACE_README.md"
    readme.write_text(SPACE_README, encoding="utf-8")
    try:
        api.upload_file(
            path_or_fileobj=str(readme),
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="space",
            commit_message="Space configuration",
        )
    finally:
        readme.unlink(missing_ok=True)
    print("  README (with Space front matter) uploaded")

    api.upload_folder(
        folder_path=str(ROOT),
        repo_id=repo_id,
        repo_type="space",
        ignore_patterns=IGNORE,
        allow_patterns=None,
        commit_message="Deploy pipeline web demo",
    )
    for extra in ALLOW:
        path = ROOT / extra
        if path.exists():
            api.upload_file(
                path_or_fileobj=str(path),
                path_in_repo=extra,
                repo_id=repo_id,
                repo_type="space",
                commit_message=f"Add {extra}",
            )
    print("  project files uploaded")

    serpapi_key = os.getenv("SERPAPI_API_KEY")
    if not serpapi_key:
        from dotenv import dotenv_values

        serpapi_key = (dotenv_values(ROOT / ".env") or {}).get("SERPAPI_API_KEY")
    if serpapi_key:
        api.add_space_secret(repo_id=repo_id, key="SERPAPI_API_KEY", value=serpapi_key)
        print("  SERPAPI_API_KEY set as a Space secret")
    else:
        print("  ! SERPAPI_API_KEY not found — set it in Space settings or search will fail")

    for key, value in {
        "BLOCKCHAIN_NETWORK": "memory",
        "PREFER_PLATFORM": "X (Twitter)",
        "MAX_FACE_CHECKS": "8",
        "OUTPUT_DIR": "/tmp/hhgoa-output",
        "INSIGHTFACE_HOME": "/opt/insightface",
        "OMP_NUM_THREADS": "1",
    }.items():
        api.add_space_variable(repo_id=repo_id, key=key, value=value)
    print("  environment variables set")

    url = f"https://huggingface.co/spaces/{repo_id}"
    print(f"\nSpace: {url}")
    print(f"Live:  https://{repo_id.replace('/', '-').lower()}.hf.space")
    print("\nThe first build takes several minutes (installing deps + baking the model pack).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
