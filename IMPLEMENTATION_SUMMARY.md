# Implementation Summary

**HH Goa 2026 — Shortlisting Task 3: Face Identification & Blockchain Verification**

A summary for evaluation: what was built, how each task requirement is met,
which decisions were made and why, and what this system honestly cannot do.

---

## 1. At a glance

| | |
| :--- | :--- |
| **Deliverable** | A single-command Python CLI pipeline |
| **Run it** | `python main.py --image input/sample.jpg` |
| **Stack** | InsightFace (ArcFace) · SerpApi → Google Lens · `hashlib` · web3.py → Ethereum |
| **Runtime dependencies** | 12 direct |
| **Application code** | ~2255 non-blank lines across 19 modules |
| **Tests** | 202 unit + 7 live integration |
| **Smart contract** | `FaceEvidenceRegistry.sol`, Solidity 0.8.24, 928 bytes compiled |
| **Networks supported** | Ethereum Sepolia · local JSON-RPC node · in-process py-evm |
| **Browser automation** | None. No Playwright, no Selenium, no scraping, no CAPTCHA |

---

## 2. Task requirements → implementation

### ✅ 1. Face identification

> *"Detect and encode a face from an input image."*

`face/detector.py` runs InsightFace **RetinaFace** (`det_10g.onnx`);
`face/encoder.py` produces a **512-dimensional ArcFace** embedding
(`w600k_r50.onnx`), L2-normalised, on CPU via ONNX Runtime.

Multiple faces are handled explicitly: the largest is used and the run says so.
Zero faces is a clean, reported failure, never a silent pass.

Input handling accepts `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tif`/`.tiff`
and `.gif` in any capitalisation, **detected from file contents rather than the
extension**, with EXIF orientation applied and `~`/quoted/non-ASCII paths
handled. HEIC/AVIF are detected and reported with the exact conversion command.

### ✅ 2. Genuine reverse-image search

> *"This should be a genuine search step, not a hardcoded/pre-picked result."*

This is the requirement most easily faked, so it is the one built most
defensively.

On **every run**, `search/serpapi_client.py`:

1. `POST`s the local image to SerpApi's Image API → a temporary `image_id`.
2. `GET`s `serpapi.com/search` with `engine=google_lens`, that `image_id`, and
   **`no_cache=true`** — forcing a fresh Google Lens query rather than a cached
   one.
3. Optionally repeats with `type=exact_matches` for pages hosting the same image.

**How an evaluator can confirm it is real** (details in
[COMPLETE_SETUP_GUIDE §9](COMPLETE_SETUP_GUIDE.md#9-verifying-the-claims-yourself)):

* The printed **search id** is issued by SerpApi per query and differs on every
  run — it can be looked up in the SerpApi dashboard.
* The printed **remaining quota decrements** run to run.
* **Results change when the input image changes** — candidates, scores and the
  final SHA-256 all differ.
* **There are no post URLs in the source.** This returns nothing:
  ```bash
  grep -rn -E "instagram\.com/p/|x\.com/[A-Za-z0-9_]+/status" face search main.py
  ```
  `search/result_parser.py` contains only *domain fragments* used to label a
  platform — never a specific post.
* There is **no JSON fixture** anywhere in the pipeline, and the search's own
  test is a live API call rather than a recording, precisely because a
  recording would prove nothing.

### ✅ 3. Find a real matching social/web result

> *"Do not assume the first search result is correct… handle multiple candidates."*

`search/result_parser.py` flattens `exact_matches`, `visual_matches` and
`organic_results` into candidates, tags each with its platform, filters
search-engine internals (redirect hops, cached copies, image CDNs), and
de-duplicates on **two axes** — canonical URL and image URL.

`search/candidate_selector.py` then, for each candidate in priority order:
downloads the image (full image first, thumbnail as fallback), validates the
bytes actually decode as an image, detects a face, generates a second
embedding, and computes cosine similarity.

A candidate is accepted **only** on that similarity. Two tests exist to protect
this specific claim:

* `test_a_high_ranked_result_that_fails_the_face_check_is_not_selected`
* `test_preference_cannot_promote_a_failing_candidate`

Real runs demonstrate rejection working: on the sample image, a genuine `x.com`
post the search returned scores **+0.046** and is rejected, while news articles
and another X post pass at 0.89–0.93.

### ✅ 4. Integrity fingerprint

> *"Create a canonical representation… then calculate a SHA-256 fingerprint."*

`integrity/hashing.py` builds a deterministic record — platform, source URL,
title, image URL, SHA-256 of the downloaded image, plus provenance (search
provider, engine, search id, query image hash) and the verification evidence
(similarity, threshold, metric, model).

Determinism comes from one canonical form: keys sorted at every level, no
insignificant whitespace, UTF-8 without escaping, floats pinned to 6 decimal
places. Empty fields are dropped rather than stored as `null`, so the record
never implies data the search did not return.

12 tests cover this, including that **every individual field change alters the
digest** and that a save/load round trip preserves it.

### ✅ 5. Blockchain

> *"Upload the post (or a hash/fingerprint of it)… any blockchain may be used."*

`contracts/FaceEvidenceRegistry.sol` — 928 bytes compiled. `anchor(bytes32)`
stores the fingerprint, block timestamp and submitter; `getRecord` reads it
back; `getRecord` reverts on an unknown id so a missing record can never be
misread as a zero hash.

`blockchain/writer.py` sends a **real signed transaction** and waits for a
receipt with `status == 1`. A revert, an unmined transaction or an unfunded
wallet are all reported as failures — the pipeline refuses to proceed on a zero
balance rather than attempting a transaction it cannot pay for.

Three networks: `sepolia` (public testnet, Etherscan-verifiable), `local` (any
JSON-RPC node), `memory` (in-process py-evm — a genuine EVM with real
transactions and receipts, but ephemeral, and always labelled as such in the
output).

**Biometric data never goes on-chain.** Only the 32-byte SHA-256 of public post
metadata.

### ✅ 6. Blockchain verification

> *"The verification must be real, not hardcoded."*

`blockchain/verifier.py` reads the fingerprint from the contract and
**recomputes** the digest from the saved record — rather than reusing the value
computed during the write. That distinction is the whole point: reusing it
would make verification a tautology, whereas recomputing means any later
alteration to the record breaks the match.

Both branches are implemented and demonstrated. `--demo-tamper` alters one
field and re-verifies, producing `TAMPERED RECORD: NOT VERIFIED ✗` against the
unchanged on-chain value.

### ✅ 7. Repository and README

Full source on GitHub with a README covering what it does, how to run it, which
blockchain, and — at length — its limitations. Plus this summary,
[ARCHITECTURE.md](ARCHITECTURE.md), [COMPLETE_SETUP_GUIDE.md](COMPLETE_SETUP_GUIDE.md)
and [QUICK_REFERENCE.md](QUICK_REFERENCE.md).

---

## 3. Reference repositories: what was used, what was rejected

The brief was to *inspect and adapt*, not merge. Two rounds of reference
material were reviewed.

| Repository | Verdict |
| :--- | :--- |
| **deepinsight/insightface** | **Used** as a dependency. `face/detector.py` wraps its `FaceAnalysis` API, loading only the `detection` and `recognition` sub-models — skipping landmark and gender/age roughly halves start-up |
| **serpapi/serpapi-python** | **Used** as a dependency. `search/serpapi_client.py` wraps `upload_image()` and `search()`, adding error translation and upload-size preparation |
| **serpapi/google-lens-scraper** | **Used as documentation** for Lens request parameters and the `visual_matches`/`exact_matches` response shape |
| **ethereum/web3.py** | **Used** as a dependency for deployment, signing, receipts and reads |
| **ageitgey/face_recognition** | **Rejected.** dlib needs a source build on Python 3.13, and its 128-d encodings are less accurate than ArcFace |
| **ageitgey/face_recognition_models** | **Rejected** with the above |

From the earlier reference set, the following were inspected and deliberately
**not** adopted: `lingolens` and `google-lens-python` (browser automation and
direct Lens scraping — CAPTCHA-prone, and the plain-`requests` approach no
longer works), `eagleeye` and `social-mapper` (2018-era Selenium and Python 2
idioms; the *architecture* informed this design, the code did not), `ublock`
and `trustfacechain` (multi-service MERN/capstone stacks — the
evidence→hash→chain→verify *pattern* was adopted, the applications were not).

Net result: 12 runtime dependencies instead of the dlib + Playwright + Selenium
+ MongoDB + IPFS + Node + React + Streamlit pile that merging would have
produced.

---

## 4. Engineering decisions worth noting

**Boundary-aware domain matching.** Platform tagging originally used substring
containment — so any host merely *containing* a platform domain was mislabelled.
`"x.com"` is a substring of `netflix.com`, `vox.com`, `dropbox.com` and
`peakpx.com`; a live run selected a wallpaper page labelled "X (Twitter)".
Matching is now boundary-aware, with country-TLD platforms matched on a whole
domain label.

**Candidate tiering neutralises a resolution artefact.** Facebook, Instagram and
Threads serve full images only to their own crawlers, so the pipeline
face-checks a ~250 px thumbnail for those platforms. Sites serving
full-resolution images therefore score systematically higher *on the same
person*. Ordering purely by similarity would let download quality — not
evidence — decide the winner, so results are ordered by tier (X → Web articles
→ other social → low-signal) and then by similarity.

**Two-axis de-duplication.** Google Lens routinely returns one thumbnail for
many pages on a site. On a live run, five different Times of India articles
shared a single thumbnail; face-checking that identical image five times
produced five identical scores and spent the budget for nothing. Adding image
de-duplication took the number of distinct sites reached, at the same budget,
**from four to eight**.

**Downloads are validated, not trusted.** Social platforms answer their own
image links with `200 OK` and an HTML page for non-crawler clients. Success is
decided by whether the bytes decode as an image, not by the HTTP status.

**Exit code 2 is distinct from 1.** "I did my job and the answer is no" is not
the same result as "I could not do my job", and conflating them would hide real
failures.

---

## 5. Testing

209 tests: 202 offline (~1.5 s, no network, no model weights) plus 7 live.

| File | Tests | Covers |
| :--- | ---: | :--- |
| `test_result_parser.py` | 44 | Platform tagging and tiering, domain-boundary matching, URL normalisation, two-axis de-dup, engine-internal exclusion, malformed input |
| `test_candidate_selector.py` | 24 | Selection policy, tier order, preference aliases, and that failing candidates are never selected |
| `test_imaging.py` | 21 | Magic-byte format detection, `.jpg`/`.jpeg` spellings, content-over-extension, path hygiene, HEIC guidance, downscaling |
| `test_face_matching.py` | 13 | Cosine maths, symmetry, scale invariance, range, threshold boundary, error cases |
| `test_hashing.py` | 12 | Canonical JSON, digest stability, float precision, per-field sensitivity, round trip |
| `test_blockchain.py` | 11 | Deploy, anchor, read back, verify, tamper detection, reverts — **against a real in-process EVM, no mocks** |
| `test_face_encoder.py` | 10 | Image-loading → detection wiring |
| `test_search_live.py` | 7 | **Live** SerpApi call — opt-in via `RUN_LIVE_SEARCH=1` |

Two deliberate choices:

* **The blockchain is tested against a real EVM.** Mocking the chain would test
  the mock. These deploy the actual contract and read state back through the ABI.
* **The search is tested live, not against a fixture.** A fixture would prove the
  parser still parses a 2026 payload; it would prove nothing about whether the
  search still works.

---

## 6. Verified end to end

| Check | Result |
| :--- | :--- |
| Fresh `git clone` + `pip install -r requirements.txt` + documented command | ✅ Verified |
| Full pipeline on the shipped sample image | ✅ `VERIFIED ✓` |
| Tamper detection | ✅ `TAMPERED RECORD: NOT VERIFIED ✗` |
| `.jpeg`, `.JPG`, filenames with spaces, non-ASCII names | ✅ Verified |
| PNG mislabelled as `.jpg` | ✅ Detected as PNG, re-encoded for upload |
| Impossible threshold (`--threshold 0.999`) | ✅ Honest failure, exit 2 |
| Missing image / no face / directory / corrupt file / HEIC | ✅ Actionable errors, exit 1 |
| Invalid API key, unreachable RPC | ✅ Actionable errors |
| Live SerpApi integration tests | ✅ 7 passed |
| No secrets in any commit | ✅ Verified across full history |

---

## 7. Honest limitations

Stated plainly, because a submission that overclaims is worse than one that
does less and says so. The full list is in the
[README](README.md#limitations); the ones that most affect evaluation:

**The input face must be publicly indexed.** Reverse image search can only find
images that exist on the public web. A private individual's selfie will usually
return no matches at all — and the pipeline reports that honestly rather than
inventing a result. This is a property of reverse image search, not of this
implementation. The shipped sample is a widely published public-domain
photograph for exactly this reason.

**Face similarity is statistical, not proof of identity.** False positives
(lookalikes, family members, low-resolution images) and false negatives
(extreme pose, occlusion, compression, age gap) are both possible. The
`buffalo_l` models carry the demographic biases of their training data.

**Anchoring proves integrity, not truth.** It proves this exact record existed
at that block time and has not changed. It proves nothing about whether the
identification was correct — garbage in, hashed garbage on-chain.

**Platform coverage is uneven.** Private, login-walled, deleted and
robots-blocked posts cannot be discovered. Instagram and Facebook expose only
crawler thumbnails, which is why they are deprioritised.

**`memory` mode is ephemeral.** It is a genuine EVM, but the chain exists only
for the process lifetime. `sepolia` gives a permanent, publicly inspectable
record.

**Ethical scope.** Reverse-image-searching a face is a surveillance-adjacent
capability. This is built as a hackathon demonstration against a public
figure's public-domain photograph. Running it against private individuals
without consent may be unlawful and is not a supported use.

---

## 8. Repository map

```
hh-goa-task3/
├── main.py                      # orchestrator — the single entry point
├── config.py                    # env-driven settings; no secret literals
│
├── face/          detector.py · encoder.py · matcher.py
├── search/        serpapi_client.py · result_parser.py · candidate_selector.py
├── integrity/     hashing.py
├── blockchain/    chain.py · writer.py · verifier.py · artifacts/
├── contracts/     FaceEvidenceRegistry.sol
├── scripts/       compile_contract.py · new_wallet.py
├── utils/         console.py · imaging.py
├── tests/         202 unit + 7 live integration
│
├── input/sample.jpg             # public-domain, attributed
├── README.md · ARCHITECTURE.md · COMPLETE_SETUP_GUIDE.md
├── IMPLEMENTATION_SUMMARY.md · QUICK_REFERENCE.md
└── requirements.txt · .env.example · LICENSE
```
