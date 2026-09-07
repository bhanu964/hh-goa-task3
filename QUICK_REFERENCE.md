# Quick Reference

One page. For full setup see [COMPLETE_SETUP_GUIDE.md](COMPLETE_SETUP_GUIDE.md).

---

## Install & run

```bash
git clone https://github.com/bhanu964/hh-goa-task3.git && cd hh-goa-task3
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then add SERPAPI_API_KEY
python main.py --image input/sample.jpg
```

First run downloads the InsightFace model pack (~280 MB), once.

---

## Commands

```bash
# Standard run
python main.py --image input/sample.jpg

# Recording demo — full chain plus tamper proof
python main.py --image input/sample.jpg --demo-tamper

# Public testnet (needs a funded wallet) — gives an Etherscan link
python main.py --image input/sample.jpg --network sepolia

# Your own photo
python main.py --image ~/Pictures/me.jpeg

# Prefer a platform among verified matches
python main.py --image input/sample.jpg --prefer-platform "X (Twitter)"
python main.py --image input/sample.jpg --prefer-platform Web

# Stricter matching / wider search
python main.py --image input/sample.jpg --threshold 0.60
python main.py --image input/sample.jpg --max-checks 20

# Save one API credit
python main.py --image input/sample.jpg --no-exact-matches

# Tests
pytest -q                                        # 202 offline
RUN_LIVE_SEARCH=1 pytest tests/test_search_live.py -v   # 7 live

# Helpers
python scripts/new_wallet.py                     # testnet burner wallet
python scripts/compile_contract.py               # only if you edit the .sol
```

---

## CLI flags

| Flag | Default | Meaning |
| :--- | :--- | :--- |
| `--image PATH` | required | Input face image |
| `--network` | `memory` | `sepolia` · `local` · `memory` |
| `--threshold FLOAT` | `0.45` | Cosine similarity required for a match |
| `--max-checks INT` | `12` | Candidate pages to download and face-check |
| `--prefer-platform NAME` | `X (Twitter)` | `X` · `Twitter` · `Web` · `news` · a platform · a domain |
| `--no-exact-matches` | off | Skip the second query (saves 1 credit) |
| `--demo-tamper` | off | After verifying, alter the record and re-verify |

---

## `.env`

```ini
SERPAPI_API_KEY=your_key_here      # required — serpapi.com/manage-api-key
SERPAPI_FETCH_EXACT=true           # +1 credit, stronger evidence
FACE_MATCH_THRESHOLD=0.45
MAX_FACE_CHECKS=12
PREFER_PLATFORM=X (Twitter)

BLOCKCHAIN_NETWORK=memory          # sepolia | local | memory
SEPOLIA_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com
WALLET_PRIVATE_KEY=                # testnet burner only
CONTRACT_ADDRESS=                  # set after first deploy to reuse
```

`.env` is gitignored. Never commit it.

---

## Exit codes

| Code | Meaning |
| ---: | :--- |
| `0` | **Verified** — full chain completed, digests match |
| `2` | Ran correctly, **found nothing** — no candidate passed, or digests differ |
| `1` | **Could not run** — bad input, API failure, chain failure |

---

## Input images

**Accepted:** `.jpg` `.jpeg` `.png` `.webp` `.bmp` `.tif` `.tiff` `.gif`, any
capitalisation. Format is read from file contents, not the extension. `~`,
quotes, spaces and non-ASCII names all work. EXIF orientation applied.

**Not accepted:** HEIC/HEIF, AVIF (iPhone default) —
`sips -s format jpeg in.heic --out out.jpg`

**Best results:** one clearly visible face, and a face that is **publicly
indexed on the web**. A private selfie will usually return no matches — the
pipeline says so rather than inventing one.

---

## Platform tiers

Selection order among candidates that **already passed** the face check:

| Tier | Platforms |
| ---: | :--- |
| 0 | **X (Twitter)** |
| 1 | **Web** — news, interviews, blogs, institutional pages |
| 2 | Facebook, LinkedIn, TikTok, Threads, Bluesky, Mastodon |
| 3 | Instagram, Reddit, YouTube, Pinterest, merchandise/stock/wallpaper hosts |

`--prefer-platform` overrides tier, then similarity decides. None of this can
promote a candidate that failed the face check.

---

## Troubleshooting

| Symptom | Fix |
| :--- | :--- |
| `SERPAPI_API_KEY is not set` | `cp .env.example .env`, add your key |
| `rejected the API key (401)` | Bad key — serpapi.com/manage-api-key |
| `quota exhausted (429)` | Free tier used up, or hourly limit hit |
| `No face detected` | Crop closer to the face |
| `N faces found` | Informational — largest is used |
| `HEIF … not supported` | `sips -s format jpeg in.heic --out out.jpg` |
| `No candidate passed the threshold` | **Working as intended.** Try `--threshold 0.35`, `--max-checks 20`, or a more widely published photo |
| `No JSON-RPC node answering` | Start `anvil`, or use `--network memory` |
| `Wallet has no funds` | Fund from a Sepolia faucet |
| `ModuleNotFoundError` | `source .venv/bin/activate` |
| First run hangs | Downloading the 280 MB model pack, once |

---

## Verify the claims in 2 minutes

```bash
# 1. Search is live — the id differs every run, quota decrements
python main.py --image input/sample.jpg | grep -E "search id|quota"

# 2. No hardcoded results — returns nothing
grep -rn -E "instagram\.com/p/|x\.com/[A-Za-z0-9_]+/status" face search main.py

# 3. The face check really rejects — honest failure, exit 2
python main.py --image input/sample.jpg --threshold 0.999; echo "exit=$?"

# 4. The chain is real — deploys and reads back on a real EVM, no mocks
pytest tests/test_blockchain.py -v

# 5. Tampering is caught
python main.py --image input/sample.jpg --demo-tamper
```

---

## Pipeline at a glance

```
image → RetinaFace → ArcFace 512-d embedding A
      → SerpApi upload → Google Lens (no_cache) → candidates
      → tier · de-dup → download → ArcFace embedding B
      → cosine(A,B) ≥ 0.45 ? → evidence record → SHA-256
      → anchor(bytes32) on Ethereum → read back
      → recompute SHA-256 → compare → VERIFIED ✓ / NOT VERIFIED ✗
```

Face embeddings never reach the blockchain. Only the 32-byte record hash does.

---

## Docs

| File | For |
| :--- | :--- |
| [README.md](README.md) | Overview, architecture, full limitations |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module design, decisions, what it proves and doesn't |
| [COMPLETE_SETUP_GUIDE.md](COMPLETE_SETUP_GUIDE.md) | Step-by-step setup, Sepolia, troubleshooting |
| [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) | Requirement-by-requirement map, for evaluation |
