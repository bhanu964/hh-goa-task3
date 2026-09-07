# Face Identification + Reverse Image Search + Blockchain Verification

**HH Goa 2026 — Shortlisting Task 3**

[![tests](https://github.com/bhanu964/hh-goa-task3/actions/workflows/tests.yml/badge.svg)](https://github.com/bhanu964/hh-goa-task3/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![licence](https://img.shields.io/badge/licence-MIT-green)](LICENSE)
[![tests count](https://img.shields.io/badge/tests-203%20unit%20%2B%207%20live-brightgreen)](tests/)

A command-line pipeline that takes a face image, finds a real matching post on
the public web through a genuine reverse-image search, proves the face in that
post is the same person, and anchors a tamper-evident fingerprint of the
discovery on Ethereum — then reads it back and re-verifies it.

Everything in the chain is real. The search is a live API call made at runtime,
the match decision is a cosine-similarity computation over face embeddings, and
the blockchain write is a signed transaction waited on until it is mined. When
a stage genuinely fails, the pipeline says so and stops. It never reports a
success it did not achieve.

> **Evaluating this?** Start with
> **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** — a
> requirement-by-requirement map — then
> [§9 of the setup guide](COMPLETE_SETUP_GUIDE.md#9-verifying-the-claims-yourself),
> which shows how to independently verify that the search is genuinely live and
> that nothing is hardcoded.

---

## Documentation

| Document | What it covers |
| :--- | :--- |
| **README** (this file) | Overview, architecture, usage, full limitations |
| **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** | One-page cheat sheet: commands, flags, exit codes, fixes |
| **[COMPLETE_SETUP_GUIDE.md](COMPLETE_SETUP_GUIDE.md)** | Step-by-step setup from a clean machine, Sepolia funding, troubleshooting |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Module design, key decisions, and what the system proves — and does not |
| **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** | Requirement-by-requirement map, reference-repo verdicts, verification log |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | Optional web UI: hosting, the measured memory floor, Docker, Render blueprint |

### Optional web UI

A browser front-end is included — upload a face, watch every stage stream live,
see the on-chain verification and the tamper check. It is **not required by the
task**; the CLI is the deliverable.

```bash
pip install -r requirements-web.txt
uvicorn webapp.app:app --port 8000     # http://127.0.0.1:8000
```

It needs **≥ 1 GB RAM** — measured, not estimated: a 512 MB container is
OOM-killed while loading the face models. See
[DEPLOYMENT.md](DEPLOYMENT.md) for the numbers and hosting options.

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Technologies](#technologies)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Sample run](#sample-run)
- [Reverse image search — how the search is genuinely performed](#reverse-image-search--how-the-search-is-genuinely-performed)
- [Face verification](#face-verification)
- [Integrity fingerprint](#integrity-fingerprint)
- [Blockchain](#blockchain)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Limitations](#limitations)
- [Reference repositories and licences](#reference-repositories-and-licences)

---

## What it does

Given `input/sample.jpg`, the pipeline:

1. Detects the face and generates a 512-dimensional ArcFace embedding.
2. Uploads the image to SerpApi and runs a **live Google Lens query**, getting
   back structured JSON of pages across the public web.
3. Parses those results into candidate pages, tags each with its platform,
   de-duplicates them, and ranks X (Twitter) posts and web articles first.
4. Downloads each candidate's image, detects the face in it, generates a second
   embedding, and computes cosine similarity against the input.
5. Accepts a candidate **only** if that similarity clears a documented
   threshold — search rank alone never makes something a match.
6. Builds a deterministic metadata record of the discovery and takes its
   SHA-256.
7. Writes that 32-byte fingerprint to a Solidity contract on Ethereum, reads it
   back, recomputes the hash locally, and compares.

Two things it deliberately does **not** do: it never puts biometric data
on-chain, and it never uses the face embedding as the integrity hash. Those are
separate concepts (see [Face verification](#face-verification) and
[Integrity fingerprint](#integrity-fingerprint)).

---

## Architecture

```
                        input/sample.jpg
                               │
                               ▼
                    ┌──────────────────────┐
                    │  InsightFace         │  RetinaFace det_10g
                    │  detection + ArcFace │  + ArcFace w600k_r50
                    └──────────┬───────────┘
                               │
                    512-d embedding  A                    ── OFF-CHAIN, never stored
                               │
                               ▼
                    ┌──────────────────────┐
                    │  SerpApi /image      │  local file → temporary image_id
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  Google Lens engine  │  live query, no browser, no CAPTCHA
                    └──────────┬───────────┘
                               │
                    JSON: exact_matches + visual_matches
                               │
                               ▼
                    ┌──────────────────────┐
                    │  Result parser       │  platform tiering, URL + image
                    │  + candidate ranking │  de-dup, internals filtered
                    └──────────┬───────────┘
                               │
            candidate pages (X, then Web articles, then other social)
                               │
                               ▼
                      candidate image  ──► InsightFace ──► 512-d embedding B
                               │                                   │
                               ▼                                   │
                    ┌──────────────────────┐                       │
                    │  cosine(A, B) ≥ 0.45 │ ◄─────────────────────┘
                    └──────────┬───────────┘
                               │
                          MATCH ✅   (below threshold → honest failure, exit 2)
                               │
                               ▼
                    ┌──────────────────────┐
                    │  Evidence record     │  platform, URL, title, image URL,
                    │  canonical JSON      │  image SHA-256, similarity, threshold
                    └──────────┬───────────┘
                               │
                               ▼
                          SHA-256 (32 bytes)                       ── the ONLY thing
                               │                                      that goes on-chain
                               ▼
                    ┌──────────────────────┐
                    │  web3.py             │  signed transaction
                    │  FaceEvidenceRegistry│  Sepolia / local / in-process EVM
                    └──────────┬───────────┘
                               │
                        TX confirmed, record id
                               │
                               ▼
                      read back from contract
                               │
                               ▼
                    recompute SHA-256 locally
                               │
                               ▼
                        compare digests
                               │
                    ┌──────────┴───────────┐
                    ▼                      ▼
              VERIFIED ✅            NOT VERIFIED ✗
```

---

## Technologies

| Layer | Technology | Why |
| :--- | :--- | :--- |
| Face detection | InsightFace RetinaFace (`det_10g.onnx`) | Robust to pose and lighting; runs on CPU |
| Face embedding | InsightFace ArcFace (`w600k_r50.onnx`), 512-d | Current state of the art for face similarity |
| Inference runtime | ONNX Runtime 1.29 (CPU) | No GPU or PyTorch needed |
| Reverse image search | SerpApi → Google Lens | Programmatic JSON API; no browser, no CAPTCHA |
| HTTP | `requests` | Candidate image downloads |
| Hashing | Python `hashlib` (stdlib) | Zero extra dependency for SHA-256 |
| Smart contract | Solidity 0.8.24 | `FaceEvidenceRegistry`, 928 bytes compiled |
| Blockchain client | web3.py 8.0 | Deploy, sign, send, read back |
| Local EVM | py-evm via eth-tester | Zero-setup offline chain for tests and demos |

**Explicitly not used:** Playwright, Selenium, any browser automation, any
scraping of Google's HTML, IPFS, MongoDB, Node, React, or any web frontend.
The pipeline is a single Python CLI.

---

## Installation

From a clean environment:

```bash
git clone <your-repo-url>
cd hh-goa-task3

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Then configure your key:

```bash
cp .env.example .env
# edit .env and set SERPAPI_API_KEY
```

**First run downloads the InsightFace `buffalo_l` model pack (~280 MB)** into
`~/.insightface/models/`. That is a one-off; later runs start in a few seconds.

Requires **Python 3.11+** (developed and tested on 3.13, macOS arm64).
Python 3.10 is not supported: the pinned `onnxruntime` has no 3.10 wheels.

---

## Configuration

All secrets come from environment variables, loaded from `.env`. `.env` is
gitignored; `.env.example` documents every variable.

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `SERPAPI_API_KEY` | — | **Required.** Free key: [serpapi.com/users/sign_up](https://serpapi.com/users/sign_up) (250 searches/month) |
| `SERPAPI_FETCH_EXACT` | `true` | Also query `exact_matches`. Strongest evidence; costs one extra credit per run |
| `FACE_MATCH_THRESHOLD` | `0.45` | Cosine similarity required to accept a candidate |
| `MAX_FACE_CHECKS` | `12` | How many candidate pages to download and face-check |
| `PREFER_PLATFORM` | `X (Twitter)` | Prefer this platform among verified matches. Accepts `X`/`Twitter`, `Web`/`news`/`article`, a platform name, or a bare domain. Also `--prefer-platform` |
| `BLOCKCHAIN_NETWORK` | `memory` | `sepolia`, `local`, or `memory` |
| `SEPOLIA_RPC_URL` | public node | Any Sepolia JSON-RPC endpoint |
| `LOCAL_RPC_URL` | `http://127.0.0.1:8545` | Anvil / Hardhat / Ganache |
| `WALLET_PRIVATE_KEY` | — | Testnet burner key. Generate with `python scripts/new_wallet.py` |
| `CONTRACT_ADDRESS` | — | Set after first deploy to reuse the same contract |

> **Never** put a private key holding real funds in `.env`. Use a throwaway
> testnet wallet.

---

## Usage

One command runs the whole pipeline:

```bash
python main.py --image input/sample.jpg
```

### Input images

Accepts **`.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tif`/`.tiff`, `.gif`**, in
any capitalisation. The format is detected from the file's *contents*, not its
extension, so a PNG that someone saved as `photo.jpg` still works — and is
re-encoded correctly before upload rather than being rejected by the search API.

Paths are handled the way people actually paste them:

```bash
python main.py --image ~/Pictures/me.jpeg          # ~ is expanded
python main.py --image "~/My Photos/holiday.JPG"   # spaces, any case
python main.py --image '/tmp/照片.jpeg'             # non-ASCII names
```

EXIF orientation is applied, so a portrait photo from a phone is read upright
rather than sideways. Very large images are downscaled for detection only — the
full-resolution original is what gets hashed and uploaded.

**HEIC/HEIF and AVIF are not supported.** These are the iPhone default, so the
error says exactly how to convert:

```
✗ HEIF images (the iPhone default) are not supported. Convert to JPEG first:
    macOS:  sips -s format jpeg 'IMG_0001.heic' --out 'IMG_0001.jpg'
    other:  pip install pillow-heif, or export the photo as JPEG
```

Options:

```bash
# Anchor on the public Ethereum testnet instead of the in-process chain
python main.py --image input/sample.jpg --network sepolia

# Also demonstrate that tampering with the record breaks verification
python main.py --image input/sample.jpg --demo-tamper

# Prefer a particular platform among the candidates that pass the face check.
# X (Twitter) is the default; these are all equivalent:
python main.py --image input/sample.jpg --prefer-platform "X (Twitter)"
python main.py --image input/sample.jpg --prefer-platform X
python main.py --image input/sample.jpg --prefer-platform Twitter

# Prefer a news article / blog / institutional page instead of a social post
python main.py --image input/sample.jpg --prefer-platform Web

# Stricter face matching
python main.py --image input/sample.jpg --threshold 0.60

# Check more candidates
python main.py --image input/sample.jpg --max-checks 20

# Save one SerpApi credit per run
python main.py --image input/sample.jpg --no-exact-matches
```

**Exit codes:** `0` verified · `2` no match found, or verification failed ·
`1` an error (missing image, no face, search failure, chain failure).

---

## Sample run

Abridged real output of `python main.py --image input/sample.jpg --demo-tamper`
— reproducible from a fresh clone, since `sample.jpg` ships with the repo:

```
[1/7] Loading image…
  ✓ input/sample.jpg
    format             JPEG  (720x900)
    sha256             d901d2182ec325b81d204984a425dce1389352530a747c5b637d304bc100f9da

[2/7] Detecting face and generating embedding…
  ✓ Face detected (confidence 0.902)
  ✓ Face embedding generated (512-d ArcFace vector)

[3/7] Performing genuine reverse-image search…
    SerpApi quota      178 searches left (Free Plan)
  ⟳ Uploading image to SerpApi and querying Google Lens…
  ✓ Live search completed — results generated at runtime
    queries            all, exact_matches
    search id          6a9e7dd6bca7e5278f4c6216
  ✓ 268 candidate pages returned
    social-media hits  118

[4/7] Inspecting candidates for a real match…
  · Checking up to 12 candidates: X, then Web articles, then other social
  · Preferring X (Twitter) among candidates that pass the face check

[5/7] Verifying faces against the input embedding…
  ✓ X (Twitter)    https://x.com/TheePopCore/status/208448950327…  cos=+0.8943  MATCH
  ✓ X (Twitter)    https://x.com/PollTracker2024/status/20832911…  cos=+0.8896  MATCH
  · X (Twitter)    https://x.com/mkratsios47/status/209521315932…  cos=+0.0462  below threshold
  ✓ commons.wikimedia.org  https://commons.wikimedia.org/wiki/File:Pre…  cos=+0.9272  MATCH
  ✓ usatoday.com   https://www.usatoday.com/story/theoval/2013/0…  cos=+0.9227  MATCH
  ✓ worcestermag.com  https://www.worcestermag.com/story/news/pol…  cos=+0.9075  MATCH

    faces compared     12
    images unavailable 0
    no face in image   0
    passed threshold   11

  ✓ Candidate confirmed by face comparison
  · Selected by preference for X (Twitter), then similarity.
    tier               X (Twitter)
    platform           X (Twitter)
    url                https://x.com/TheePopCore/status/2084489503278154324
    similarity         0.8943 cosine  (threshold 0.45)

[6/7] Creating integrity fingerprint…
  ✓ Deterministic record built (canonical JSON, sorted keys, UTF-8)
    SHA-256:
    b0558c9598d3d55b9c599145140fe9597701d49fd7e200cccef7706243a5c964

[7/7] Anchoring on blockchain and re-verifying…
  ✓ Connected: In-process EVM (py-evm / eth-tester, ephemeral)
  ⟳ Submitting transaction…
  ✓ Transaction confirmed
    tx hash            0x5bb363665dfe3d2ce536efcae27ef28b96396e8ff62c139ee2d55c2ed8f018c3
    block              2
    gas used           90746
  ⟳ Reading the record back from the chain…

    Local fingerprint  (recomputed from the saved record):
    b0558c9598d3d55b9c599145140fe9597701d49fd7e200cccef7706243a5c964

    Blockchain fingerprint (read from the contract):
    b0558c9598d3d55b9c599145140fe9597701d49fd7e200cccef7706243a5c964

==============================================================
                   FINAL RESULT: VERIFIED ✓
==============================================================


==============================================================
   TAMPER DEMONSTRATION
   proving the check actually detects changes
==============================================================
  · Appending text to the discovered title, then re-verifying…

    Tampered local fingerprint:
    3b472defa05495439b30f07fdd991191462ce23cffa4b7cf375b5b06c92d629f

    Blockchain fingerprint (unchanged, immutable):
    b0558c9598d3d55b9c599145140fe9597701d49fd7e200cccef7706243a5c964
  ✓ Mismatch detected: the altered record no longer matches the chain.

==============================================================
               TAMPERED RECORD: NOT VERIFIED ✗
==============================================================
```

Two details worth noticing.

**The third X line is a rejection.** A real `x.com` post that the search
returned, whose image contains a face that is *not* the same person, scored
**+0.046** and was discarded — despite sitting on the preferred platform and
despite the search engine having surfaced it. That is the face check doing real
work rather than rubber-stamping search results.

**Your run will not look identical.** The search id, candidate set and final
SHA-256 change every run, because Google Lens is queried live with
`no_cache=true` and its index moves. That variance is the evidence the search is
genuine.

The `--demo-tamper` block then alters one field of the record and re-verifies,
producing a different local digest against the unchanged on-chain one, and
`TAMPERED RECORD: NOT VERIFIED ✗`.

---

## Reverse image search — how the search is genuinely performed

This is the requirement most easily faked, so here is exactly what happens.

On every run, `search/serpapi_client.py`:

1. Prepares the local image for upload, recompressing only if it exceeds
   SerpApi's 500 KB limit.
2. `POST`s it to SerpApi's Image API, receiving a temporary `image_id`
   (valid ~10 minutes).
3. `GET`s `https://serpapi.com/search` with `engine=google_lens`,
   `image_id=<that id>`, and `no_cache=true`, which forces a fresh Google Lens
   query rather than a cached one.
4. Optionally repeats with `type=exact_matches` to find pages hosting the very
   same image.

The response is structured JSON containing `visual_matches`, `exact_matches`
and `organic_results` arrays, each entry carrying a page URL, title, source
name and image URLs.

**How you can confirm it is real, on the recording:**

- The printed `search id` is issued by SerpApi per query and is different on
  every run. It can be looked up in your SerpApi dashboard.
- The printed remaining-quota figure decreases run to run.
- `no_cache=true` is sent, so results are freshly fetched.
- Candidate URLs, similarity scores and the final SHA-256 change when the input
  image changes.

There is **no** hardcoded URL, no stored JSON fixture, no pre-selected post and
no browser anywhere in this path. `search/` contains no literal social-media
URLs at all — only domain fragments used to label a platform.

**Why an API instead of browser automation:** Google Lens now requires a
JavaScript-capable client and actively detects bots, so a Playwright/Selenium
approach hits CAPTCHAs and needs manual intervention — fatal for an unedited
screen recording. SerpApi handles that upstream and returns parsed JSON.

**Candidate handling.** Results are de-duplicated by URL and search-engine
internals (`google.com/goto`, `gstatic.com`, cached copies) are filtered out —
they are redirect plumbing, not discoverable pages. Remaining candidates are
ranked social-media-first, then by exact-match-before-visual-match, then by
Lens position. This only sets the *order of inspection*; nothing here decides a
match.

**A note on image URLs.** Facebook, Instagram and Threads serve their `image`
link only to their own crawlers and hand everyone else an HTML page. The
downloader therefore validates that fetched bytes actually decode as an image
and falls back to the Google-hosted thumbnail when they do not. Thumbnails are
around 250 px, so they are upscaled before detection.

---

## Face verification

Two embeddings are compared, never file bytes:

```
input image     → RetinaFace → aligned crop → ArcFace → embedding A (512-d, L2-normalised)
candidate image → RetinaFace → aligned crop → ArcFace → embedding B (512-d, L2-normalised)

similarity = cosine(A, B) = A · B        (∈ [-1, 1])
match      = similarity ≥ 0.45
```

Both vectors are L2-normalised, so cosine similarity is a plain dot product.

**Threshold.** The default is **0.45**, a standard operating point for ArcFace
`buffalo_l` 512-d embeddings. On the sample run above, genuine matches of the
same person scored 0.64–0.99 while different people scored −0.10 and +0.13 — a
wide, unambiguous margin. Configure it with `FACE_MATCH_THRESHOLD` or
`--threshold`. Whichever value was actually applied is written into the
evidence record, so anyone verifying later can see the criterion the decision
was made under.

**Selection policy.** Among candidates that pass the threshold, the order is:

1. `--prefer-platform`, if given and something from that platform passed.
   Defaults to `X (Twitter)`.
2. **Platform tier** (see below).
3. **Similarity**, within a tier.

| Tier | Contents | Rationale |
| :--- | :--- | :--- |
| 0 — **X (Twitter)** | `x.com`, `twitter.com` | The designated social-media target. Serves full-resolution `pbs.twimg.com` images to any client, and a status URL is a specific, citable post |
| 1 — **Web** | News articles, interviews, blogs, institutional and personal sites | First-class evidence, not a fallback. Full-resolution images and real editorial context about the person |
| 2 — Other social | Facebook, LinkedIn, TikTok, Threads, Bluesky, Mastodon | Genuine social posts, but crawler-gated images and less citable URLs |
| 3 — Low signal | Instagram, Reddit, YouTube, Pinterest, and merchandise/stock-photo hosts (Amazon, eBay, Etsy, Alamy, Getty…) | See below |

Instagram is deliberately in the bottom tier. It serves non-Instagram clients
only a ~250 px crawler thumbnail, and its Lens hits are frequently reels or
aggregator reposts rather than a clear face image — so it scores worse on the
same person while also being weaker evidence. Merchandise and stock-photo
listings sit there for a different reason: the image may genuinely be the
person, but a poster shop hosting a photo is not evidence of that person's
presence on the web.

Ordering by tier rather than by raw score also avoids a resolution artefact —
sites that serve full-resolution images systematically score higher than
thumbnail-gated ones, so without tiering the *download quality* rather than the
evidence would decide what gets reported.

**De-duplication.** Before any of this, candidates are collapsed two ways:
by canonical URL (tracking, locale and share parameters stripped, so
`…/status/123` and `…/status/123?lang=en` are one result) and by image URL.
Google Lens routinely returns one thumbnail for many pages on the same site;
face-checking that identical image again cannot produce new evidence and would
spend the candidate budget for nothing. On a live run this raised the number of
distinct sites reached, at the same budget, from four to eight.

Every one of these steps only *orders candidates that already passed the face
check*. None of them can turn a non-matching page into a match: if nothing
clears the threshold the pipeline reports
`No candidate passed the face-match threshold` and exits 2, whatever platform
was requested. `tests/test_candidate_selector.py` asserts this directly in
`test_preference_cannot_promote_a_failing_candidate`.

The displayed "match strength" percentage is `(cosine + 1) / 2 × 100`, purely
so the printed figure is never negative. Every decision uses the raw cosine
value.

---

## Integrity fingerprint

The record is a deterministic snapshot of the discovery:

```json
{
  "schema_version": "1.0",
  "discovered_at": "2026-09-05T11:42:07+00:00",
  "discovered_post": {
    "platform": "Reddit",
    "source_url": "https://www.reddit.com/r/Presidents/comments/…",
    "title": "Was Obama a Good President? …",
    "source_name": "Reddit",
    "image_url": "https://i.redd.it/avoqp9xnw0cb1.jpg",
    "image_sha256": "22e3afabd72a48e14e451810255827e5dc82d61e96dd364bd38765e9f39fed0e"
  },
  "provenance": {
    "search_provider": "serpapi",
    "search_engine": "google_lens",
    "search_id": "6a9bb04777e3d9f28db1a922",
    "match_section": "visual_matches",
    "query_image_sha256": "d901d2182ec325b81d204984a425dce1389352530a747c5b637d304bc100f9da"
  },
  "face_verification": {
    "face_similarity": 0.987903,
    "match_threshold": 0.45,
    "metric": "cosine_similarity",
    "embedding_model": "insightface/buffalo_l (ArcFace w600k_r50, 512-d)"
  }
}
```

Determinism comes from a single canonical serialisation:

```python
json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

— keys sorted at every level, no insignificant whitespace, UTF-8 without
escaping, and floats rounded to 6 decimal places so trailing float noise cannot
change the digest. The SHA-256 of that string is the fingerprint. Fields with
no value are dropped rather than stored as `null`, so the record never implies
it holds data the search did not return.

The record is written to `output/evidence_record.json` alongside its digest.

**The fingerprint is not the face embedding.** The embedding is a biometric
vector used only to compare faces, and it never enters the record, the hash, or
the blockchain. The fingerprint is a cryptographic hash of discovered *public
post metadata*.

---

## Blockchain

**Contract:** `contracts/FaceEvidenceRegistry.sol`, Solidity 0.8.24, 928 bytes
compiled. Deliberately minimal — it stores a `bytes32` commitment, a timestamp
and a submitter address per record.

```solidity
function anchor(bytes32 fingerprint) external returns (uint256 recordId);
function getRecord(uint256 recordId) external view
    returns (bytes32 fingerprint, uint64 timestamp, address submitter);
function verify(uint256 recordId, bytes32 fingerprint) external view returns (bool);
```

**What is stored on-chain:** the 32-byte SHA-256 of the evidence record, the
block timestamp, and the submitting address.

**What is never stored on-chain:** face images, face embeddings, or any other
biometric data. Biometric processing stays entirely off-chain; the chain is the
trust and audit layer holding a commitment that proves the record existed in
this exact form at this block time.

### Networks

| `BLOCKCHAIN_NETWORK` | What it is | Use |
| :--- | :--- | :--- |
| `sepolia` | Public Ethereum testnet | Transactions are permanent and visible on Etherscan. Needs a wallet with faucet ETH |
| `local` | Any JSON-RPC node on localhost | Anvil, Hardhat or Ganache |
| `memory` | In-process py-evm chain via eth-tester | Zero setup, always works offline. A genuine EVM — real transactions, receipts and state — but it exists only for the lifetime of the process |

`memory` is a real EVM executing real transactions, not a simulation of one.
It is nonetheless ephemeral, and the pipeline always prints which network it
used so a viewer can tell exactly which chain a transaction landed on.

The task permits a local or simulated chain provided re-verification against
the on-chain record is demonstrated, which it is in all three modes.

### Running against Sepolia

```bash
python scripts/new_wallet.py          # prints a throwaway address + key
# add WALLET_PRIVATE_KEY to .env, set BLOCKCHAIN_NETWORK=sepolia
# fund the address at https://www.alchemy.com/faucets/ethereum-sepolia
python main.py --image input/sample.jpg --network sepolia
```

The first run deploys the contract and writes `blockchain/deployment.json`.
Put the printed address in `CONTRACT_ADDRESS` to reuse it and avoid paying to
redeploy. The run prints a
`https://sepolia.etherscan.io/tx/…` link you can open on the recording.

### How verification works

1. `anchor(fingerprint)` is sent as a signed transaction and waited on until a
   receipt with `status == 1` arrives. A reverted or unmined transaction is
   reported as a failure.
2. `getRecord(recordId)` reads the fingerprint back **from the contract**.
3. The digest is **recomputed from the saved record data** — not reused from
   step 1. This is the crux: if the record is altered afterwards, the
   recomputed digest changes and no longer matches the immutable on-chain
   value.
4. The two are compared. Equal → `VERIFIED ✓`. Different → `NOT VERIFIED ✗`.

`--demo-tamper` demonstrates step 4's failure branch by altering the record's
title and re-verifying.

### Recompiling the contract

Only needed if you change the Solidity source; the compiled artifact is
committed so normal runs need no Solidity toolchain.

```bash
pip install -r requirements-dev.txt
python scripts/compile_contract.py
```

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest -q
```

203 unit tests, covering the deterministic components:

| File | Covers |
| :--- | :--- |
| `test_hashing.py` | Canonical JSON, digest stability, float precision, sensitivity to every field, save/load round trip |
| `test_face_matching.py` | Cosine similarity maths, symmetry, scale invariance, range, threshold boundary, error cases |
| `test_imaging.py` | Format detection by magic bytes, `.jpg`/`.jpeg` spellings, content-over-extension, tilde/quote/unicode paths, HEIC guidance, downscaling |
| `test_face_encoder.py` | Image-loading to detection wiring, including that `encode_file` and `encode_loaded` agree |
| `test_result_parser.py` | Platform tagging and tiering, URL normalisation, URL + image de-duplication, exclusion of search-engine internals, malformed input, ranking |
| `test_candidate_selector.py` | Selection policy — tier order, X/Web preference aliases, and that a top-ranked result failing the face check is never selected |
| `test_blockchain.py` | Deploy, anchor, read back, verify, tamper detection, reverts — against a real in-process EVM, no mocks |

### Live search test

The reverse-image search is covered by a **real integration test**, not a
recorded fixture — a fixture would prove nothing about whether the search still
works. It is skipped by default because it spends API credits:

```bash
RUN_LIVE_SEARCH=1 pytest tests/test_search_live.py -v
```

It asserts that the upload returns a usable `image_id`, the search reports
`Success`, a fresh search id is issued, and real HTTP candidate URLs with
downloadable images come back.

**Manual test:** run the pipeline and watch the search id and quota change
between runs:

```bash
python main.py --image input/sample.jpg --network memory
```

---

## Project structure

```
hh-goa-task3/
├── main.py                      # orchestrator — the single entry point
├── config.py                    # env-driven configuration
│
├── face/
│   ├── detector.py              # RetinaFace detection, image loading
│   ├── encoder.py               # image → 512-d ArcFace embedding
│   └── matcher.py               # cosine similarity + threshold decision
│
├── search/
│   ├── serpapi_client.py        # upload + live Google Lens query
│   ├── result_parser.py         # JSON → ranked, platform-tagged candidates
│   └── candidate_selector.py    # download, face-check, select best evidence
│
├── integrity/
│   └── hashing.py               # canonical JSON + SHA-256 record fingerprint
│
├── blockchain/
│   ├── chain.py                 # network selection and connection
│   ├── writer.py                # deploy + anchor (real signed transactions)
│   ├── verifier.py              # read back + recompute + compare
│   └── artifacts/               # committed ABI + bytecode
│
├── contracts/
│   └── FaceEvidenceRegistry.sol
│
├── scripts/
│   ├── compile_contract.py      # regenerate the artifact
│   └── new_wallet.py            # generate a testnet burner wallet
│
├── utils/
│   ├── console.py               # terminal output for the screen recording
│   └── imaging.py               # robust image input: formats, paths, EXIF
├── tests/                       # 203 unit tests + live search integration test
├── input/sample.jpg             # public-domain sample (see ATTRIBUTION.md)
└── output/                      # evidence_record.json written here
```

---

## Limitations

Being honest about what this does and does not prove:

**Reverse image search**
- Requires a SerpApi key. The free tier is 250 searches/month; each run uses
  1–2 credits. Exhausted quota is reported as a `429`, not disguised.
- Results depend on Google Lens, which changes its index and result mix without
  notice. The same image can return different candidates on different days.
- Google Lens finds images that are **publicly indexed**. A private
  individual's selfie will usually return no matches at all. The sample image is
  a widely published public-domain photograph for exactly this reason — this is
  a property of reverse image search, not a shortcut in the pipeline.

**Social media**
- Private, login-walled, deleted and robots-blocked posts cannot be discovered
  or downloaded.
- Facebook, Instagram and Threads serve full images only to their own crawlers,
  so the pipeline face-checks a ~250 px Google thumbnail for those platforms.
  Small images score lower than full-resolution ones, which is why selection is
  ordered by platform tier rather than by raw similarity — otherwise download
  quality, not evidence, would pick the winner. Instagram is deprioritised for
  this reason and is unlikely to be selected even when it matches.
- X (Twitter) serves full-resolution `pbs.twimg.com` images to any client,
  which is why it is the target platform — but Lens returns X *profile*
  pictures as well as post images, and a profile picture may be of a different
  person than the post is about. Those are caught by the face check, not
  assumed away.
- Post titles come from the search engine's snapshot; a post edited after
  indexing may not match its live content.

**Face recognition**
- Cosine similarity is a statistical measure, not proof of identity. False
  positives are possible (lookalikes, family members, low-resolution images) as
  are false negatives (extreme pose, occlusion, heavy compression, age gap).
- A single fixed threshold cannot be right for every image quality. 0.45 is a
  reasonable general operating point, not a guarantee.
- Only the largest face is used when an image contains several; the pipeline
  warns when that happens.
- The `buffalo_l` models are trained on datasets with their own demographic
  biases; accuracy is not uniform across populations.
- This is an identification aid, not evidence of identity. It should not be used
  to make consequential decisions about a person.

**Blockchain**
- `memory` mode is a genuine EVM but ephemeral — the chain disappears when the
  process exits. Use `sepolia` for a record that persists and is publicly
  inspectable.
- Sepolia is a testnet: it offers no economic security guarantee and can be
  reset by its operators. Faucets are rate-limited and sometimes unavailable.
- Anchoring proves a record existed in a given form at a given block time. It
  proves nothing about whether the discovery was *correct* — garbage in, hashed
  garbage on-chain.
- Public RPC endpoints can rate-limit; a dedicated Alchemy/Infura URL is more
  reliable for repeated runs.

**Input images**
- HEIC/HEIF and AVIF are not decoded. The error explains how to convert, but an
  iPhone photo will not work straight off the device unless Live Photo capture
  is set to "Most Compatible" or it is exported as JPEG.
- Animated GIFs and multi-page TIFFs are read as their first frame only.

**Ethical use**
- Reverse-image-searching a face is a surveillance-adjacent capability. This is
  built as a hackathon demonstration on a public figure's public-domain
  photograph. Running it against private individuals without consent may be
  unlawful in your jurisdiction and is not a supported use.

---

## Reference repositories and licences

Components inspected, adapted, or used as dependencies. No repository was
merged wholesale; only the parts genuinely needed were used.

| Repository | Licence | How it is used |
| :--- | :--- | :--- |
| [deepinsight/insightface](https://github.com/deepinsight/insightface) | MIT (code) | Used as a dependency for RetinaFace detection and ArcFace embeddings via its `FaceAnalysis` API. `face/detector.py` wraps it, loading only the `detection` and `recognition` sub-models |
| [serpapi/serpapi-python](https://github.com/serpapi/serpapi-python) | MIT | Used as a dependency. `search/serpapi_client.py` wraps `Client.upload_image()` and `Client.search()` and adds error translation and upload-size preparation |
| [serpapi/google-lens-scraper](https://github.com/serpapi/google-lens-scraper) | Documentation | Reference for Google Lens request parameters and the `visual_matches` / `exact_matches` response shape, which `search/result_parser.py` parses |
| [ethereum/web3.py](https://github.com/ethereum/web3.py) | MIT | Used as a dependency for contract deployment, transaction signing, receipts and reads |
| [ageitgey/face_recognition](https://github.com/ageitgey/face_recognition) | MIT | Inspected as a fallback face engine. **Not used** — dlib requires a source build on Python 3.13 and its 128-d encodings are less accurate than ArcFace |
| [ageitgey/face_recognition_models](https://github.com/ageitgey/face_recognition_models) | CC0-1.0 | Inspected alongside the above. Not used |

### InsightFace model licensing

InsightFace's **code** is MIT licensed. Its **pretrained models**, including the
`buffalo_l` pack this project downloads, are licensed by their authors for
**non-commercial research purposes only**. This project is a hackathon
submission and evaluation exercise, which falls within that scope. Any
commercial deployment would require separate licensing from InsightFace, or
custom-trained weights.

### Sample image

`input/sample.jpg` is a public-domain US federal government work. See
[`input/ATTRIBUTION.md`](input/ATTRIBUTION.md).

---

## Licence

MIT — see [`LICENSE`](LICENSE).
