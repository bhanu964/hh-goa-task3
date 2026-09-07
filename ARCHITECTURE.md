# Architecture

Technical design of the HH Goa 2026 Task 3 pipeline: what each module owns, how
data flows, which decisions were made and why, and — importantly — what the
system does *not* prove.

For setup see [COMPLETE_SETUP_GUIDE.md](COMPLETE_SETUP_GUIDE.md). For a
requirement-by-requirement map see
[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md).

---

## 1. Design principles

Four rules drove every decision.

**1. A failure is never dressed up as a success.** Each stage either produces
real evidence or reports honestly that it could not. There is no fallback path
that fabricates a result, and no `except: pass` that turns an error into a
green tick. The pipeline exits `2` when it finds nothing rather than lowering
its standards.

**2. Search rank is not evidence.** That a search engine returned a page says
nothing about whose face is in it. A candidate is accepted only after its image
is downloaded, a face is detected in it, and the cosine similarity of two
embeddings clears a documented threshold.

**3. Biometrics stay off-chain.** The blockchain is the trust and audit layer,
not a biometric database. Face embeddings never enter the evidence record,
never enter the hash, and never reach the chain. Only a 32-byte commitment does.

**4. The smallest dependency set that does the job.** 12 direct runtime
dependencies. No browser automation, no scraping, no IPFS, no database, no
frontend, no agent framework.

---

## 2. Data flow

```
                          input image (any common format)
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
        ▼                             ▼                             ▼
   utils.imaging              integrity.hashing            search.serpapi_client
   ───────────────            ────────────────             ─────────────────────
   sniff magic bytes          sha256 of the file           POST /image → image_id
   decode + EXIF              (query provenance)           GET  /search?
   downscale for detect                                      engine=google_lens
        │                                                    no_cache=true
        ▼                                                          │
   face.detector                                                   ▼
   ─────────────                                        exact_matches +
   RetinaFace det_10g                                   visual_matches +
        │                                               organic_results
        ▼                                                          │
   face.encoder                                                    ▼
   ────────────                                       search.result_parser
   ArcFace w600k_r50                                  ───────────────────
        │                                             boundary-aware platform
        ▼                                             tagging · exclude engine
   embedding A (512-d, L2-normalised)                 internals · de-dup by
        │                                             canonical URL AND image
        │                                             URL · rank by tier
        │                                                          │
        │                                                          ▼
        │                                        search.candidate_selector
        │                                        ─────────────────────────
        │                                        download (full image, then
        │                                        thumbnail) · validate it
        │                                        decodes · detect face
        │                                                          │
        │                                                          ▼
        │                                              embedding B (512-d)
        │                                                          │
        └────────────────► face.matcher ◄─────────────────────────┘
                           ────────────
                           cosine(A, B) ≥ threshold
                                      │
                        ┌─────────────┴─────────────┐
                        ▼                           ▼
                  no candidate passed          best candidate
                  → exit 2, honest             (tier, then similarity)
                                                    │
                                                    ▼
                                         integrity.hashing
                                         ─────────────────
                                         canonical JSON (sorted keys,
                                         no whitespace, UTF-8, fixed
                                         float precision)
                                                    │
                                                    ▼
                                            SHA-256 → 32 bytes
                                                    │
                                                    ▼
                                         blockchain.writer
                                         ─────────────────
                                         anchor(bytes32) as a signed
                                         transaction, waited on until
                                         receipt.status == 1
                                                    │
                                                    ▼
                                         blockchain.verifier
                                         ───────────────────
                                         getRecord(id) from the contract
                                         recompute SHA-256 locally
                                         compare
                                                    │
                                      ┌─────────────┴─────────────┐
                                      ▼                           ▼
                                 VERIFIED ✓                  NOT VERIFIED ✗
```

---

## 3. Module responsibilities

| Module | Lines | Owns | Deliberately does not |
| :--- | ---: | :--- | :--- |
| `main.py` | 382 | Orchestration, CLI, terminal output, exit codes | Any domain logic |
| `config.py` | 80 | Environment-driven settings, one place for defaults | Hold any secret literal |
| `utils/imaging.py` | 157 | Format sniffing, decoding, EXIF, path hygiene, downscaling | Know anything about faces |
| `utils/console.py` | 54 | Terminal formatting for the recording | Decide anything |
| `face/detector.py` | 109 | RetinaFace detection, model lifecycle | Compare faces |
| `face/encoder.py` | 53 | Image → 512-d ArcFace embedding | Decide a match |
| `face/matcher.py` | 51 | Cosine similarity, threshold decision | Know about search or chains |
| `search/serpapi_client.py` | 190 | Upload, live Lens query, API error translation | Interpret results |
| `search/result_parser.py` | 353 | Platform tagging, tiering, de-dup, ranking | Decide identity |
| `search/candidate_selector.py` | 216 | Download, face-check, select best evidence | Talk to the search API |
| `integrity/hashing.py` | 130 | Canonical record, SHA-256 | Know about the chain |
| `blockchain/chain.py` | 127 | Network selection, connection, account | Build records |
| `blockchain/writer.py` | 198 | Deploy, anchor, real signed transactions | Verify |
| `blockchain/verifier.py` | 92 | Read back, recompute, compare | Write |

The dependency graph is acyclic and one-directional: `main` → everything;
`search` → `face` (to verify candidates); `blockchain` → `integrity` (to
recompute). `face` knows nothing about search, `integrity` knows nothing about
the chain.

---

## 4. Key design decisions

### 4.1 Programmatic API over browser automation

Google Lens now requires a JavaScript-capable client and actively detects bots.
A Playwright/Selenium approach hits CAPTCHAs and needs manual intervention —
fatal for an unedited screen recording, and it makes the pipeline
non-reproducible for an evaluator.

SerpApi handles that upstream and returns parsed JSON over plain HTTPS. Cost:
an API key and a quota. Benefit: the search step is deterministic in its
mechanics, runs headless, and cannot be blocked mid-demo.

`no_cache=true` is sent on every query, so results are fetched fresh rather
than served from SerpApi's cache.

### 4.2 Two-query strategy

`type=all` carries `visual_matches`; a second `type=exact_matches` query finds
pages hosting the *same* image, which is the strongest evidence available.
Merging both maximises the chance of finding a real social post, at the cost of
one extra API credit per run. Controlled by `SERPAPI_FETCH_EXACT` /
`--no-exact-matches`.

### 4.3 Boundary-aware domain matching

Platform tagging matches on domain boundaries — a host qualifies only when it
*is* the domain or a subdomain of it.

This was originally naive substring containment, which silently mislabelled any
host merely *containing* a platform domain. `"x.com"` is a substring of
`netflix.com`, `vox.com`, `dropbox.com`, `xbox.com` and `peakpx.com` — all of
which were reported as X posts and promoted to the top tier. A live run selected
a wallpaper page labelled "X (Twitter)". Country-TLD platforms
(`pinterest.co.uk`, `mastodon.social`) match on a whole domain label, so
`pinterest-clone.com` does not qualify.

### 4.4 Candidate tiering

| Tier | Contents | Why |
| :--- | :--- | :--- |
| 0 | X (Twitter) | The designated social target. Serves full-resolution images to any client; a status URL is a specific, citable post |
| 1 | Web — news, interviews, blogs, institutional pages | First-class evidence: full-resolution images and real editorial context |
| 2 | Other social — Facebook, LinkedIn, TikTok, Threads, Bluesky, Mastodon | Genuine posts, but crawler-gated images |
| 3 | Instagram, Reddit, YouTube, Pinterest, merchandise/stock/wallpaper hosts | See below |

Tiering exists to neutralise a **resolution artefact**. Facebook, Instagram and
Threads serve their full image only to their own crawlers and hand everyone
else an HTML page, so the pipeline face-checks a ~250 px Google thumbnail for
those platforms. Sites that serve full-resolution images therefore score
systematically higher on the *same person*. Ordering purely by similarity would
let download quality — not evidence — pick the winner.

Merchandise, stock-photo and wallpaper hosts are low-signal for a different
reason: the image may genuinely be the person, but a product listing is not
evidence of that person's presence on the web.

### 4.5 Two-axis de-duplication

Candidates are collapsed by canonical URL (tracking, locale and share
parameters stripped, so `…/status/123` and `…/status/123?lang=en` are one
result) **and** by image URL.

Google Lens routinely returns one thumbnail for many pages on the same site. On
a live run, five different Times of India articles shared a single thumbnail —
face-checking that identical image five times produced five identical scores
and spent the candidate budget for nothing. Adding image de-duplication took
the number of distinct sites reached, at the same budget, **from four to
eight**.

### 4.6 Image fetch with validation, not trust

The full image URL is tried first, then the thumbnail. The decision that a
download "worked" is **whether the bytes decode as an image**, not the HTTP
status — social platforms answer their own image links with `200 OK` and an
HTML page for non-crawler clients.

### 4.7 Canonical serialisation

```python
json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

Keys sorted at every level, no insignificant whitespace, UTF-8 without escaping
so text hashes by its actual characters, and floats rounded to 6 decimal places
so trailing float noise cannot change the digest. Empty fields are dropped
rather than stored as `null`, so the record never implies it holds data the
search did not return.

### 4.8 Verification recomputes rather than reuses

`blockchain/verifier.py` re-derives the digest from the record data instead of
reusing the value computed during the write. That is the entire point: if the
record is altered afterwards, the recomputed digest changes and stops matching
the immutable on-chain commitment. Reusing the write-time value would make
verification a tautology.

---

## 5. Smart contract

`contracts/FaceEvidenceRegistry.sol` — Solidity 0.8.24, **928 bytes** compiled
with the optimizer at 200 runs.

```solidity
function anchor(bytes32 fingerprint) external returns (uint256 recordId);
function getRecord(uint256 recordId) external view
    returns (bytes32 fingerprint, uint64 timestamp, address submitter);
function verify(uint256 recordId, bytes32 fingerprint) external view returns (bool);
function exists(uint256 recordId) external view returns (bool);
function recordCount() external view returns (uint256);

event EvidenceAnchored(
    uint256 indexed recordId, bytes32 indexed fingerprint,
    address indexed submitter, uint64 timestamp
);
```

**Stored:** the 32-byte SHA-256, the block timestamp, the submitting address.
**Never stored:** face images, embeddings, or any other biometric data.

Design notes:

* `timestamp == 0` is the "does not exist" sentinel, and `getRecord` reverts on
  an unknown id — so a missing record can never be misread as a zero
  fingerprint.
* `anchor` rejects a zero fingerprint, so an empty hash cannot be anchored.
* `verify()` is a convenience cross-check. The pipeline's real verification is
  the local recompute-and-compare; the on-chain check is reported alongside it.
* No owner, no roles, no upgradeability. Nothing in this pipeline needs them,
  and every extra feature is extra attack surface and gas.

The compiled ABI + bytecode artifact is committed, so running the pipeline
needs **no Solidity toolchain** — only `web3.py`.

---

## 6. Blockchain network modes

| `BLOCKCHAIN_NETWORK` | What it is | Trade-off |
| :--- | :--- | :--- |
| `sepolia` | Public Ethereum testnet | Permanent, publicly verifiable on Etherscan. Needs a funded wallet |
| `local` | Any JSON-RPC node on localhost (Anvil, Hardhat, Ganache) | Real EVM, persists while the node runs. No public explorer |
| `memory` | In-process py-evm chain via eth-tester | Zero setup, always works offline. **Ephemeral** — exists only for the process lifetime |

`memory` is a genuine EVM executing genuine transactions with real receipts and
real state, not a simulation of one. It is nonetheless ephemeral, and the
pipeline always prints which network it used so a viewer of the recording can
tell exactly which chain a transaction landed on.

---

## 7. What the system proves — and what it does not

This matters more than any feature, so it is stated plainly.

**The anchor proves:** that this exact record, byte for byte, existed at the
block time it was anchored, and has not changed since. Any alteration to any
field changes the digest and fails verification.

**The anchor does not prove:**

* that the identification is *correct*. Garbage in, hashed garbage on-chain.
  The chain attests to the record's integrity, never to its truth.
* that the discovered page still exists, or still contains that image.
* that the person in the input image is who anyone claims they are.

**The face match is statistical, not proof of identity.** Cosine similarity
above a threshold is evidence, not certainty. False positives (lookalikes,
family members, low-resolution images) and false negatives (extreme pose,
occlusion, heavy compression, age gap) are both possible. The `buffalo_l`
models carry the demographic biases of their training data, and accuracy is not
uniform across populations.

**This is an identification aid, not an identification system.** It should not
be used to make consequential decisions about a person, and running it against
private individuals without consent may be unlawful in your jurisdiction.

---

## 8. Error handling

Every external boundary is wrapped and translated into an actionable message.
The pipeline distinguishes three outcomes:

| Exit | Meaning | Examples |
| ---: | :--- | :--- |
| `0` | Verified | Full chain completed, digests match |
| `2` | Ran correctly, found nothing | No candidate passed the threshold; search returned no pages; digests differ |
| `1` | Could not run | Image missing/corrupt/HEIC, no face, API key invalid, quota exhausted, RPC unreachable, transaction reverted |

Exit `2` is deliberately distinct from `1`: "I did my job and the answer is no"
is a different result from "I could not do my job", and conflating them would
hide real failures.

---

## 9. Testing strategy

209 tests. The split is deliberate:

**Deterministic logic is unit-tested** — hashing, similarity maths, parsing,
tiering, de-duplication, selection policy. These run in ~1.5 s with no network
and no model weights.

**The blockchain is tested against a real EVM**, not mocks. `test_blockchain.py`
deploys the actual contract to an in-process py-evm chain, sends real
transactions, and reads state back through the ABI. Mocking the chain would
test the mock.

**The search is tested live**, not against a recorded fixture. A fixture would
prove the parser still parses a 2026 payload; it would prove nothing about
whether the search still works. `test_search_live.py` makes a real API call,
and is skipped by default because it spends credits.

Two tests exist specifically to protect the integrity of the claims:

* `test_preference_cannot_promote_a_failing_candidate` — the platform
  preference reorders verified matches and can never manufacture one.
* `test_a_high_ranked_result_that_fails_the_face_check_is_not_selected` —
  search rank alone never makes something a match.
