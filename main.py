#!/usr/bin/env python3
"""HH Goa 2026 — Task 3 pipeline orchestrator.

    python main.py --image input/sample.jpg

Runs the whole chain of custody in one command:

    image -> face embedding -> reverse image search -> candidate pages
          -> face verification -> evidence record -> SHA-256
          -> blockchain anchor -> read back -> re-verify

Every stage is real. The search is a live API call, the face decision is a
cosine-similarity computation, and the blockchain write is a signed
transaction waited on until it is mined. When a stage genuinely fails, the
pipeline says so and stops — it never reports a success it did not achieve.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from config import OUTPUT_DIR, load_config
from utils import console


EXIT_OK = 0
EXIT_NO_MATCH = 2
EXIT_ERROR = 1
TOTAL_STEPS = 7


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Face identification + reverse image search + blockchain verification.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python main.py --image input/sample.jpg\n"
            "  python main.py --image input/sample.jpg --network sepolia\n"
            "  python main.py --image input/sample.jpg --demo-tamper\n"
        ),
    )
    parser.add_argument(
        "--image",
        required=True,
        metavar="PATH",
        help=(
            "path to the input face image — .jpg, .jpeg, .png, .webp, .bmp, "
            ".tif/.tiff or .gif (format is detected from the file's contents, "
            "not its extension). ~ and quoted paths are accepted"
        ),
    )
    parser.add_argument(
        "--network",
        choices=["sepolia", "local", "memory"],
        help="blockchain to anchor on (default: BLOCKCHAIN_NETWORK in .env)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        help="cosine similarity required for a face match (default: 0.45)",
    )
    parser.add_argument(
        "--max-checks",
        type=int,
        help="how many candidate pages to download and face-check (default: 12)",
    )
    parser.add_argument(
        "--prefer-platform",
        metavar="NAME",
        help=(
            "prefer this platform when several candidates pass the face check. "
            "Accepts X / Twitter / 'X (Twitter)', or Web / news / article for "
            "any web page. Default: X (Twitter). Only reorders verified "
            "matches — it cannot make a non-matching page into a match"
        ),
    )
    parser.add_argument(
        "--no-exact-matches",
        action="store_true",
        help="skip the extra exact_matches query (saves one SerpApi credit)",
    )
    parser.add_argument(
        "--demo-tamper",
        action="store_true",
        help="after verifying, alter the record and re-verify to show detection",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config()

    threshold = args.threshold if args.threshold is not None else config.face.match_threshold
    max_checks = args.max_checks if args.max_checks is not None else config.search.max_face_checks
    network = (args.network or config.chain.network).strip().lower()
    prefer_platform = args.prefer_platform or config.search.prefer_platform or None
    fetch_exact = (
        not args.no_exact_matches
        and os.getenv("SERPAPI_FETCH_EXACT", "true").strip().lower() != "false"
    )

    console.banner("HH GOA 2026 — TASK 3", "FACE + REVERSE SEARCH + BLOCKCHAIN")

    # Imports are deferred so that --help stays instant and a missing optional
    # dependency surfaces as a clean message rather than an import traceback.
    from face.detector import FaceDetectionError, FaceDetector
    from face.encoder import FaceEncoder
    from utils.imaging import ImageError
    from utils.imaging import load_image as load_input_image
    from integrity.hashing import build_record, sha256_file
    from search.candidate_selector import CandidateSelector
    from search.result_parser import parse_lens_response
    from search.serpapi_client import SearchError, SerpApiLensClient

    # ---------------------------------------------------------------- 1/7
    console.step(1, TOTAL_STEPS, "Loading image…")
    try:
        loaded = load_input_image(args.image)
    except ImageError as exc:
        console.fail(str(exc))
        return EXIT_ERROR

    image_path = loaded.path
    query_image_sha256 = sha256_file(image_path)
    console.ok(str(image_path))
    console.detail("format", f"{loaded.image_format}  ({loaded.width}x{loaded.height})")
    console.detail("size", f"{loaded.size_bytes / 1024:.0f} KB")
    console.detail("sha256", query_image_sha256)

    # ---------------------------------------------------------------- 2/7
    console.step(2, TOTAL_STEPS, "Detecting face and generating embedding…")
    detector = FaceDetector(
        model_pack=config.face.model_pack,
        det_size=config.face.det_size,
        det_threshold=config.face.det_threshold,
    )
    encoder = FaceEncoder(detector)
    console.working("Loading InsightFace models (first run downloads ~280 MB)…")
    try:
        reference_face, face_count = encoder.encode_loaded(loaded)
    except FaceDetectionError as exc:
        console.fail(str(exc))
        return EXIT_ERROR

    console.ok(f"Face detected (confidence {reference_face.det_score:.3f})")
    if face_count > 1:
        console.warn(
            f"{face_count} faces found — using the largest. "
            "Crop the image to the target face for a cleaner result."
        )
    console.ok(f"Face embedding generated ({reference_face.embedding.shape[0]}-d ArcFace vector)")
    console.detail("bbox", str(list(reference_face.bbox)))

    # ---------------------------------------------------------------- 3/7
    console.step(3, TOTAL_STEPS, "Performing genuine reverse-image search…")
    try:
        client = SerpApiLensClient(
            api_key=config.search.api_key,
            timeout=config.search.timeout,
            country=config.search.country,
            language=config.search.language,
        )
    except SearchError as exc:
        console.fail(str(exc))
        return EXIT_ERROR

    account = client.account_info()
    if account:
        console.detail(
            "SerpApi quota",
            f"{account.get('total_searches_left', '?')} searches left "
            f"({account.get('plan_name', 'unknown plan')})",
        )

    console.working("Uploading image to SerpApi and querying Google Lens…")
    try:
        search_result = client.search_local_image(
            image_path, include_exact_matches=fetch_exact, loaded=loaded
        )
    except SearchError as exc:
        console.fail(str(exc))
        return EXIT_ERROR

    candidates = parse_lens_response(search_result.payload)
    console.ok("Live search completed — results generated at runtime")
    console.detail("engine", "Google Lens via SerpApi")
    console.detail("queries", ", ".join(search_result.search_types))
    console.detail("search id", search_result.search_id or "n/a")
    console.ok(f"{len(candidates)} candidate pages returned")

    if not candidates:
        console.fail("Reverse-image search returned no candidate pages.")
        return EXIT_NO_MATCH

    social = [c for c in candidates if c.is_social]
    console.detail("social-media hits", str(len(social)))

    # ---------------------------------------------------------------- 4/7 + 5/7
    console.step(4, TOTAL_STEPS, "Inspecting candidates for a real match…")
    console.info(f"Checking up to {max_checks} candidates: X, then Web articles, then other social")
    if prefer_platform:
        from search.result_parser import describe_preference, resolve_preference

        console.info(
            f"Preferring {describe_preference(resolve_preference(prefer_platform))} "
            "among candidates that pass the face check"
        )

    selector = CandidateSelector(
        encoder=encoder,
        threshold=threshold,
        download_timeout=config.search.download_timeout,
        max_download_bytes=config.search.max_download_bytes,
        max_checks=max_checks,
        prefer_platform=prefer_platform,
    )

    def on_progress(candidate, verified, status):
        label = f"{candidate.platform:<14} {console.truncate(candidate.link, 46)}"
        if verified is None:
            console.info(f"{label}  — {status}")
        elif verified.is_match:
            console.ok(f"{label}  cos={verified.similarity:+.4f}  MATCH")
        else:
            console.info(f"{label}  cos={verified.similarity:+.4f}  below threshold")

    console.step(5, TOTAL_STEPS, "Verifying faces against the input embedding…")
    report = selector.verify_candidates(
        candidates, reference_face.embedding, on_progress=on_progress
    )

    print()
    console.detail("faces compared", str(len(report.checked)))
    console.detail("images unavailable", str(report.fetch_failures))
    console.detail("no face in image", str(report.no_face))
    console.detail("passed threshold", str(len(report.matches)))

    best = report.best
    if best is None:
        console.fail(
            f"No candidate passed the face-match threshold of {threshold:g}."
        )
        console.info(
            "The search ran and returned real pages, but none of the images "
            "contained a face matching the input. Reporting this honestly "
            "rather than accepting a weak result."
        )
        return EXIT_NO_MATCH

    if report.matches:
        print()
        console.info("All face-verified matches, strongest first per platform:")
        for verified_match in sorted(
            report.matches, key=lambda c: (c.candidate.tier, -c.similarity)
        ):
            console.detail(
                verified_match.candidate.platform,
                f"cos={verified_match.similarity:+.4f}  "
                f"{console.truncate(verified_match.candidate.link, 52)}",
            )
        print()

    console.ok("Candidate confirmed by face comparison")
    from search.candidate_selector import CandidateSelector as _Selector
    from search.result_parser import (
        TIER_NAMES,
        describe_preference,
        resolve_preference,
    )

    _preference = resolve_preference(prefer_platform)
    if _Selector.matches_preference(best.candidate, _preference):
        console.info(
            f"Selected by preference for {describe_preference(_preference)}, then similarity."
        )
    else:
        if _preference:
            console.warn(
                f"No {describe_preference(_preference)} candidate passed the face check — "
                "fell back to platform priority."
            )
        console.info(
            "Selected by platform priority "
            "(X, then Web articles, then other social), then similarity."
        )
    console.detail("tier", TIER_NAMES.get(best.candidate.tier, "unknown"))
    console.detail("platform", best.candidate.platform)
    console.detail("url", best.candidate.link)
    console.detail("title", console.truncate(best.candidate.title))
    console.detail("similarity", f"{best.similarity:.4f} cosine  (threshold {threshold:g})")
    console.detail("match strength", f"{best.match.percent:.1f}%")
    console.detail("image sha256", best.image_sha256)
    # A Web article is a deliberate, first-class outcome, so only say something
    # when the run genuinely found no social post at all — claiming that while
    # X results are sitting in the list above would be simply untrue.
    if not best.candidate.is_social and not any(
        c.candidate.is_social for c in report.matches
    ):
        console.warn(
            "No social-media page passed the face check. Reporting the "
            "verified web result instead."
        )

    # ---------------------------------------------------------------- 6/7
    console.step(6, TOTAL_STEPS, "Creating integrity fingerprint…")
    record = build_record(
        platform=best.candidate.platform,
        source_url=best.candidate.link,
        title=best.candidate.title,
        source_name=best.candidate.source,
        image_url=best.image_url_used,
        image_sha256=best.image_sha256,
        face_similarity=best.similarity,
        match_threshold=threshold,
        query_image_sha256=query_image_sha256,
        search_engine="google_lens",
        search_provider="serpapi",
        search_id=search_result.search_id,
        match_section=best.candidate.section,
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    record_path = OUTPUT_DIR / "evidence_record.json"
    record.save(record_path)

    console.ok("Deterministic record built (canonical JSON, sorted keys, UTF-8)")
    console.detail("saved to", str(record_path))
    console.hash_block("SHA-256:", record.digest)

    # ---------------------------------------------------------------- 7/7
    console.step(7, TOTAL_STEPS, "Anchoring on blockchain and re-verifying…")
    from blockchain.chain import ChainError, connect
    from blockchain.verifier import EvidenceVerifier
    from blockchain.writer import EvidenceWriter

    try:
        connection = connect(
            network=network,
            rpc_url=(
                config.chain.sepolia_rpc_url if network == "sepolia" else config.chain.local_rpc_url
            ),
            private_key=config.chain.private_key,
            explorer_base="https://sepolia.etherscan.io" if network == "sepolia" else None,
        )
    except ChainError as exc:
        console.fail(str(exc))
        return EXIT_ERROR

    console.ok(f"Connected: {connection.label}")
    console.detail("account", connection.account_address)
    try:
        balance = connection.balance_eth()
        console.detail("balance", f"{balance:.6f} ETH")
        if connection.is_public_testnet and balance == 0:
            console.fail(
                "Wallet has no Sepolia ETH — the anchoring transaction cannot "
                "be paid for. Fund it from a faucet and re-run."
            )
            return EXIT_ERROR
    except Exception:  # noqa: BLE001 - informational only
        pass

    writer = EvidenceWriter(connection, tx_timeout=config.chain.tx_timeout)
    console.working("Submitting transaction…")
    try:
        anchor = writer.anchor(record.digest, config.chain.contract_address)
    except ChainError as exc:
        console.fail(str(exc))
        return EXIT_ERROR

    console.ok("Transaction confirmed")
    console.detail("contract", anchor.contract_address)
    console.detail("record id", str(anchor.record_id))
    console.detail("tx hash", anchor.tx_hash)
    console.detail("block", str(anchor.block_number))
    console.detail("gas used", str(anchor.gas_used))
    if anchor.explorer_url:
        console.detail("explorer", anchor.explorer_url)

    console.working("Reading the record back from the chain…")
    verifier = EvidenceVerifier(connection)
    try:
        result = verifier.verify_record(anchor.contract_address, anchor.record_id, record.data)
    except ChainError as exc:
        console.fail(str(exc))
        return EXIT_ERROR

    print()
    console.hash_block("Local fingerprint  (recomputed from the saved record):", result.local_fingerprint)
    print()
    console.hash_block("Blockchain fingerprint (read from the contract):", result.onchain_fingerprint)

    if result.verified:
        console.verdict(True, "FINAL RESULT: VERIFIED ✓")
    else:
        console.verdict(False, "FINAL RESULT: NOT VERIFIED ✗")

    if args.demo_tamper:
        _demo_tamper(verifier, anchor, record)

    return EXIT_OK if result.verified else EXIT_NO_MATCH


def _demo_tamper(verifier, anchor, record) -> None:
    """Show that altering the record breaks verification against the chain."""
    console.banner("TAMPER DEMONSTRATION", "proving the check actually detects changes")
    console.info("Appending text to the discovered title, then re-verifying…")

    tampered = dict(record.data)
    post = dict(tampered.get("discovered_post", {}))
    post["title"] = (post.get("title", "") or "") + " (tampered)"
    tampered["discovered_post"] = post

    result = verifier.verify_record(anchor.contract_address, anchor.record_id, tampered)
    print()
    console.hash_block("Tampered local fingerprint:", result.local_fingerprint)
    print()
    console.hash_block("Blockchain fingerprint (unchanged, immutable):", result.onchain_fingerprint)
    if result.verified:
        console.fail("Tampered record still verified — this should not happen.")
    else:
        console.ok("Mismatch detected: the altered record no longer matches the chain.")
        console.verdict(False, "TAMPERED RECORD: NOT VERIFIED ✗")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
