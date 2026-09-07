# Deployment

The pipeline ships with an optional web front-end: upload a face, watch each
stage stream live, see the on-chain verification. It is not required by the
task — the CLI is the deliverable — but it makes the project demonstrable from
a URL.

---

## The one thing to know first: memory

This pipeline loads InsightFace RetinaFace + ArcFace models. They are large,
and they decide where this can be hosted.

**Measured, not estimated.** The container was run under hard memory limits:

| Container limit | Result |
| :--- | :--- |
| **512 MB** | ❌ **OOM-killed** — `OOMKilled=true`, exit 137, died during model load after 6 events |
| **1 GB** | ✅ Full pipeline completed, `verified: true`, 45 events streamed |
| **2 GB** | ✅ Comfortable headroom |

Reproduce it yourself:

```bash
docker build -t hhgoa-task3 .
docker run --rm --memory=512m --memory-swap=512m -p 8000:8000 \
  -e SERPAPI_API_KEY=... -e BLOCKCHAIN_NETWORK=memory hhgoa-task3
# then POST /api/run and watch it die
docker inspect <id> --format '{{.State.OOMKilled}}'   # true
```

Local peak-RSS measurements agree — roughly 880 MB for `buffalo_l`. Every
mitigation was tried and none helped enough:

| Attempt | Peak | Verdict |
| :--- | ---: | :--- |
| `buffalo_l`, arena on (default) | 881 MB | over |
| `buffalo_l`, CPU arena disabled | 906 MB | no help |
| `buffalo_l`, det size 320 | 840 MB | no help |
| ONNX graph optimisation basic / disabled | 932–985 MB | no help |
| `buffalo_s` (small pack) | 579–672 MB | **still over 512 MB** |

`buffalo_s` is also not a drop-in substitute: it produces a *different
embedding space*, so its scores are not comparable with `buffalo_l`
(`cos(buffalo_l, buffalo_s) = -0.0065` on the same face). Swapping it would
change every threshold in the project.

**Conclusion: a 512 MB instance cannot run this.** Pick a host with ≥ 1 GB.

---

## Option A — Render (needs a paid instance)

Render's Free and Starter web services are 512 MB, so they will be OOM-killed.
The smallest plan that works is **Standard (2 GB)**. Check
[render.com/pricing](https://render.com/pricing) for the current cost before
committing — plan specs change.

`render.yaml` in this repo is a ready blueprint.

1. Push this repo to GitHub (already done).
2. Go to [dashboard.render.com](https://dashboard.render.com) →
   **New → Blueprint**.
3. Connect the GitHub account and pick this repository. Render reads
   `render.yaml` and proposes one Docker web service.
4. Set the one secret it asks for:
   - `SERPAPI_API_KEY` — your key. It is marked `sync: false`, so it is never
     stored in git.
5. Confirm the plan is **Standard** or larger, then **Apply**.

First build takes roughly 5–10 minutes: it installs the dependencies and bakes
the ~280 MB model pack into the image so cold starts do not have to download
it.

Your URL will be `https://hh-goa-task3.onrender.com` (or whatever name you
choose). `/healthz` returns readiness JSON.

> **Free-tier note.** If you deploy to a free instance anyway to see what
> happens, the service will start, serve the page, and then get killed the
> moment the first run loads the models. That is the OOM above, not a bug.

---

## Option B — Hugging Face Spaces (requires PRO)

The container is already Spaces-ready: it listens on 7860, runs as uid 1000,
and writes only to `/tmp`. A deploy script is included:

```bash
pip install huggingface_hub
hf auth login                    # or export HF_TOKEN
python scripts/deploy_hf.py      # creates the Space, uploads, sets the secret
```

**However, Docker Spaces are no longer free.** Attempting to create one on a
free account returns:

```
402 Payment Required
Static Spaces are free for everyone, but hosting Gradio and Docker Spaces
on free cpu-basic requires a PRO subscription.
```

Only *static* Spaces are free, and a static Space cannot run Python. With a PRO
subscription the script above deploys in one command.

## Option C — Google Cloud Run (usage-based free allowance)

The most practical genuinely-low-cost option: memory is configurable well above
1 GB, it scales to zero so an idle demo costs nothing, and the monthly free
allowance comfortably covers demo traffic. It does require a Google Cloud
account with billing enabled.

```bash
gcloud run deploy hh-goa-task3 \
  --source . --region us-central1 \
  --memory 2Gi --cpu 2 --timeout 600 \
  --min-instances 0 --allow-unauthenticated \
  --set-env-vars BLOCKCHAIN_NETWORK=memory,OUTPUT_DIR=/tmp/hhgoa-output,INSIGHTFACE_HOME=/opt/insightface \
  --set-secrets SERPAPI_API_KEY=serpapi-key:latest
```

Check current [Cloud Run pricing](https://cloud.google.com/run/pricing) before
relying on the free allowance.

## Option D — Fly.io / Koyeb / Railway

* **Fly.io** — no longer has a free tier; paid machines work fine at 1 GB.
* **Koyeb** — free instance is 512 MB, which is below the measured floor.
* **Railway** — trial credit only, then usage-based.

## The honest summary

Every 512 MB free tier is ruled out by measurement, and the 2020-era generous
free PaaS tiers are gone. A live URL for this project costs either a small
subscription (HF PRO), a paid instance (Render Standard, Fly), or a
usage-metered account (Cloud Run).

**The task does not require a hosted site** — "You do not need to build or host
a project website." The CLI plus the screen recording is the complete
submission; this web UI is a bonus.

---

## Running it locally

```bash
pip install -r requirements-web.txt
uvicorn webapp.app:app --port 8000
# open http://127.0.0.1:8000
```

Or with Docker:

```bash
docker build -t hhgoa-task3 .
docker run --rm -p 8000:8000 \
  -e SERPAPI_API_KEY=your_key \
  -e BLOCKCHAIN_NETWORK=memory \
  hhgoa-task3
```

---

## Environment variables

| Variable | Required | Notes |
| :--- | :--- | :--- |
| `SERPAPI_API_KEY` | **yes** | The search stage fails without it. Set as a secret, never in git |
| `BLOCKCHAIN_NETWORK` | no | `memory` (default) needs no wallet. `sepolia` needs a funded key |
| `WALLET_PRIVATE_KEY` | only for sepolia/local | Testnet burner key |
| `PREFER_PLATFORM` | no | Defaults to `X (Twitter)` |
| `MAX_FACE_CHECKS` | no | Web default is 8 to keep requests brisk; the CLI uses 12 |
| `FACE_MATCH_THRESHOLD` | no | Defaults to `0.45` |
| `INSIGHTFACE_HOME` | no | Where models live. The image sets `/opt/insightface` |
| `OMP_NUM_THREADS` | no | Set to `1`; more threads add memory for no gain on small instances |
| `PORT` | no | Injected by most hosts; the image honours it |

---

## Design notes for the web layer

**One run at a time.** `webapp/app.py` holds an `asyncio.Lock` around the
pipeline. The models are the dominant memory cost, and two concurrent runs
would risk the OOM described above. A second request gets `429` with a clear
message rather than taking the process down.

**Models load once per process,** not per request. `webapp/runner.py` keeps a
process-wide singleton behind a lock and warms it on first use.

**Progress streams over Server-Sent Events.** The pipeline is a generator that
yields one event per step; the app drives it in a worker thread and forwards
events to the browser. The user watches stages complete rather than staring at
a spinner for 20 seconds.

**The CLI remains the reference implementation.** `main.py` was not refactored
to share the orchestration — it is the verified submission deliverable, and the
web runner mirrors its sequence while calling the same underlying modules, so
behaviour cannot diverge.

**Uploads are capped at 8 MB** and written to a temp file that is deleted after
the run. Nothing a visitor uploads is retained.

---

## Cold starts

The image bakes the model pack in at build time, so a cold start does not have
to download 280 MB. It still has to load ~700 MB of weights into memory on the
first request, which takes a few seconds. On hosts that idle a service down
after inactivity, expect the first request after a sleep to be slow.

`/healthz` reports `models_loaded`, so you can see whether the process is warm.
