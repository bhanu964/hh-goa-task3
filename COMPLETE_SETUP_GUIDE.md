# Complete Setup Guide

Everything needed to run the pipeline from a clean machine, including the two
things that need an account (a SerpApi key, and — only for the public testnet —
a funded wallet).

**In a hurry?** Steps 1–4 get you a full working run in about five minutes.
Step 5 (Sepolia) is optional.

---

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Install](#2-install)
3. [Get a SerpApi key](#3-get-a-serpapi-key)
4. [First run](#4-first-run)
5. [Optional: anchor on the Sepolia public testnet](#5-optional-anchor-on-the-sepolia-public-testnet)
6. [Using your own image](#6-using-your-own-image)
7. [All configuration options](#7-all-configuration-options)
8. [Troubleshooting](#8-troubleshooting)
9. [Verifying the claims yourself](#9-verifying-the-claims-yourself)

---

## 1. Prerequisites

| Requirement | Notes |
| :--- | :--- |
| **Python 3.11+** | Developed and tested on 3.13 (macOS arm64). `python3 --version`. 3.10 is not supported — the pinned `onnxruntime` has no 3.10 wheels |
| **~1 GB free disk** | ~400 MB dependencies + ~280 MB model pack |
| **Internet access** | The search step is a live API call |
| **A SerpApi key** | Free tier, 250 searches/month — [step 3](#3-get-a-serpapi-key) |

No GPU is needed — inference runs on CPU via ONNX Runtime. No Node, no Docker,
no database, no Solidity compiler (the compiled contract artifact is committed).

---

## 2. Install

```bash
git clone https://github.com/bhanu964/hh-goa-task3.git
cd hh-goa-task3

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

That installs 12 direct dependencies:

| Purpose | Packages |
| :--- | :--- |
| Face detection + embedding | `insightface`, `onnxruntime`, `opencv-python-headless`, `numpy`, `pillow` |
| Reverse image search | `serpapi`, `requests` |
| Blockchain | `web3`, `eth-account`, `eth-tester`, `py-evm` |
| Configuration | `python-dotenv` |

> **First run downloads the InsightFace `buffalo_l` model pack (~280 MB)** into
> `~/.insightface/models/`. This is a one-off and takes a minute or two; later
> runs start in a few seconds. The download happens automatically — nothing to
> do.

---

## 3. Get a SerpApi key

The reverse-image search is a genuine live API call, so it needs a key. The free
tier is enough for ~125 runs a month.

1. Sign up at **[serpapi.com/users/sign_up](https://serpapi.com/users/sign_up)**
   (free plan, 250 searches/month, no card required).
2. Copy your key from
   **[serpapi.com/manage-api-key](https://serpapi.com/manage-api-key)**.
3. Create your `.env` and paste it in:

```bash
cp .env.example .env
```

Then edit `.env`:

```ini
SERPAPI_API_KEY=paste_your_key_here
```

`.env` is gitignored and is never committed. Do not paste your key into a chat,
an issue, or a commit — if you do, rotate it.

**Credit cost per run:** 2 by default (one `all` query, one `exact_matches`).
Use `--no-exact-matches` to spend 1. The pipeline prints your remaining quota at
the start of every run.

---

## 4. First run

```bash
python main.py --image input/sample.jpg
```

`input/sample.jpg` is a public-domain White House portrait that ships with the
repo, so this works immediately with nothing else to source.

The default `BLOCKCHAIN_NETWORK=memory` runs a genuine EVM in-process, so this
first run needs no wallet, no faucet and no node. You should see the seven
stages complete and end with:

```
==============================================================
                   FINAL RESULT: VERIFIED ✓
==============================================================
```

### Try the tamper demonstration

```bash
python main.py --image input/sample.jpg --demo-tamper
```

After the main verdict, this alters one field of the discovered record and
re-verifies, showing a different local digest against the unchanged on-chain
one and `TAMPERED RECORD: NOT VERIFIED ✗`. This is the honest half of the
demonstration — proof the check actually detects changes.

### Run the tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

209 tests. The 7 live-search tests are skipped unless you opt in:

```bash
RUN_LIVE_SEARCH=1 pytest tests/test_search_live.py -v
```

---

## 5. Optional: anchor on the Sepolia public testnet

The `memory` chain is a real EVM but ephemeral. For a permanently verifiable
transaction with an **Etherscan link**, use Sepolia.

### 5.1 Generate a throwaway wallet

```bash
python scripts/new_wallet.py
```

It prints an address and a private key. Paste the key into `.env`:

```ini
BLOCKCHAIN_NETWORK=sepolia
WALLET_PRIVATE_KEY=0x...
```

> **Testnet play money only.** Never put a key holding real funds in a project
> `.env`. The key is printed for you to copy — it is not written to any file
> automatically.

### 5.2 Fund it from a faucet

Sepolia ETH has no monetary value; faucets give it away, but most want some
proof you are not a bot. Try in this order:

| Faucet | Requirement |
| :--- | :--- |
| [Google Cloud faucet](https://cloud.google.com/application/web3/faucet/ethereum/sepolia) | Google account |
| [Alchemy](https://www.alchemy.com/faucets/ethereum-sepolia) | Free Alchemy account |
| [pk910 PoW faucet](https://sepolia-faucet.pk910.de) | Mines in-browser; no account, just slow |
| [Infura](https://www.infura.io/faucet/sepolia) | Free Infura account |

You need very little — **0.005 ETH is plenty** for a deploy plus several
anchors. Check it arrived:

```bash
python -c "
from web3 import Web3
w3 = Web3(Web3.HTTPProvider('https://ethereum-sepolia-rpc.publicnode.com'))
print(w3.from_wei(w3.eth.get_balance('YOUR_ADDRESS'), 'ether'), 'ETH')"
```

### 5.3 Run against Sepolia

```bash
python main.py --image input/sample.jpg --network sepolia
```

The first run deploys the contract and writes `blockchain/deployment.json`. To
avoid paying to redeploy on later runs, copy the printed contract address into
`.env`:

```ini
CONTRACT_ADDRESS=0x...
```

The run prints a `https://sepolia.etherscan.io/tx/...` link — open it to see the
transaction on the public explorer.

> The pipeline refuses to proceed if the wallet balance is zero, rather than
> attempting a transaction that cannot be paid for.

### 5.4 Using a local node instead

If you have Anvil, Hardhat or Ganache:

```bash
anvil                              # in another terminal
```

```ini
BLOCKCHAIN_NETWORK=local
LOCAL_RPC_URL=http://127.0.0.1:8545
WALLET_PRIVATE_KEY=0x...           # any pre-funded key the node prints
```

---

## 6. Using your own image

```bash
python main.py --image ~/Pictures/me.jpeg
python main.py --image "/path/with spaces/photo.JPG"
```

**Accepted:** `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tif`/`.tiff`, `.gif`,
in any capitalisation. Format is detected from file contents, not the
extension, so a PNG saved as `photo.jpg` still works. `~`, quoted paths, spaces
and non-ASCII filenames are all handled, and EXIF orientation is applied so
portrait phone photos load upright.

**Not accepted:** HEIC/HEIF and AVIF (the iPhone default). Convert first:

```bash
sips -s format jpeg IMG_0001.heic --out IMG_0001.jpg     # macOS, built in
```

Anything you drop in `input/` other than `sample.jpg` is gitignored, so your own
photos never land in a public repo by accident.

### What makes a good input image

* **One clearly visible face.** If several are present the pipeline uses the
  largest and says so; cropping gives a cleaner result.
* **A face that is publicly indexed.** This is the big one: reverse image search
  can only find images that exist on the public web. A private individual's
  selfie will usually return **no matches at all** — and the pipeline will
  honestly report that rather than inventing one. That is a property of reverse
  image search, not a bug.

---

## 7. All configuration options

Every setting is an environment variable, read from `.env`. CLI flags override
`.env` for a single run.

### Search

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `SERPAPI_API_KEY` | — | **Required.** Your SerpApi key |
| `SERPAPI_FETCH_EXACT` | `true` | Also query `exact_matches` (+1 credit, stronger evidence) |
| `SERPAPI_COUNTRY` | `us` | Lens country code |
| `SERPAPI_LANGUAGE` | `en` | Lens language code |
| `SERPAPI_TIMEOUT` | `60` | API timeout, seconds |
| `MAX_FACE_CHECKS` | `12` | Candidate pages to download and face-check |
| `PREFER_PLATFORM` | `X (Twitter)` | Preferred platform among verified matches |

### Face

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `FACE_MATCH_THRESHOLD` | `0.45` | Cosine similarity required to accept a candidate |
| `FACE_DET_THRESHOLD` | `0.5` | Detection confidence floor |
| `FACE_DET_SIZE` | `640` | Detector input size |
| `FACE_MODEL_PACK` | `buffalo_l` | InsightFace model pack |

### Blockchain

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `BLOCKCHAIN_NETWORK` | `memory` | `sepolia`, `local` or `memory` |
| `SEPOLIA_RPC_URL` | publicnode | Any Sepolia JSON-RPC endpoint |
| `LOCAL_RPC_URL` | `http://127.0.0.1:8545` | Local node |
| `WALLET_PRIVATE_KEY` | — | Testnet burner key (required for `sepolia`/`local`) |
| `CONTRACT_ADDRESS` | — | Reuse an existing deployment |
| `TX_TIMEOUT` | `300` | Seconds to wait for a receipt |

### CLI flags

```
--image PATH              input face image (required)
--network {sepolia,local,memory}
--threshold FLOAT         cosine similarity required for a match
--max-checks INT          candidate pages to download and face-check
--prefer-platform NAME    X / Twitter / "X (Twitter)" / Web / news / a domain
--no-exact-matches        skip the second query, saving one credit
--demo-tamper             after verifying, alter the record and re-verify
```

---

## 8. Troubleshooting

| Symptom | Cause and fix |
| :--- | :--- |
| `SERPAPI_API_KEY is not set` | `cp .env.example .env` and add your key |
| `SerpApi rejected the API key (401)` | Wrong or revoked key — check [manage-api-key](https://serpapi.com/manage-api-key) |
| `SerpApi quota exhausted (429)` | Free tier used up for the month, or the hourly rate limit hit. Check the [dashboard](https://serpapi.com/dashboard) |
| `No face detected in the image` | No detectable face, or it is too small/blurry. Crop closer to the face |
| `N faces found — using the largest` | Informational. Crop to the target face for a cleaner result |
| `HEIF images (the iPhone default) are not supported` | Convert: `sips -s format jpeg in.heic --out out.jpg` |
| `... is not a recognised image file` | Not an image, or truncated. The message lists supported formats |
| `No candidate passed the face-match threshold` | **Working as intended.** The search ran, but nothing matched. Usually means the input face is not publicly indexed. Try `--threshold 0.35`, `--max-checks 20`, or a more widely published photo |
| `No JSON-RPC node answering at ...` | Local node not running. Start `anvil`, or use `--network memory` |
| `WALLET_PRIVATE_KEY is not set` | Needed for `sepolia`/`local`. Run `python scripts/new_wallet.py`, or use `--network memory` |
| `Wallet ... has no funds` | Fund the address from a faucet ([5.2](#52-fund-it-from-a-faucet)) |
| `Transaction was not mined within 300s` | Sepolia congestion. Raise `TX_TIMEOUT`, or use a dedicated Alchemy/Infura RPC |
| First run seems to hang | It is downloading the 280 MB model pack. One-off |
| `ModuleNotFoundError` | Virtualenv not activated: `source .venv/bin/activate` |

### Exit codes

| Code | Meaning |
| ---: | :--- |
| `0` | Verified — full chain completed and digests match |
| `2` | Ran correctly, found nothing (no match, or digests differ) |
| `1` | Could not run (bad input, API failure, chain failure) |

`2` is deliberately distinct from `1`: "I did my job and the answer is no" is
not the same as "I could not do my job".

---

## 9. Verifying the claims yourself

The task's hardest requirement is that the search is *genuine*. Here is how to
confirm that from the outside, in under two minutes.

**The search id is new on every run.** SerpApi issues it per query; it appears in
your SerpApi dashboard.

```bash
python main.py --image input/sample.jpg --network memory | grep "search id"
python main.py --image input/sample.jpg --network memory | grep "search id"
```

Two different ids — the second run did not replay the first.

**The quota decrements.** Each run prints `SerpApi quota   N searches left`.
Watch N fall.

**Results change with the input.** Feed a different face and the candidate URLs,
similarity scores and final SHA-256 all change.

**There are no hardcoded URLs.** Search the source:

```bash
grep -rn "instagram.com/p/\|x.com/.*status\|facebook.com/.*posts" \
     --include=*.py face/ search/ blockchain/ integrity/ main.py
```

Nothing is returned. `search/result_parser.py` contains only *domain fragments*
used to label a platform — never a specific post URL.

**The face check really rejects things.** Every run prints candidates that
failed, with their scores. A page the search returned whose face does not match
shows `below threshold` and is not selected.

**Make it fail on purpose.**

```bash
python main.py --image input/sample.jpg --threshold 0.999
```

Real search, real candidates, nothing passes an impossible threshold →
`No candidate passed the face-match threshold`, exit 2. No fabricated success.

**The blockchain read-back is real.**

```bash
pytest tests/test_blockchain.py -v
```

These deploy the actual contract to an in-process EVM, send real transactions,
and read state back through the ABI — no mocks stand in for the chain.
