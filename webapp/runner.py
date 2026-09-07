"""Pipeline runner that yields progress events instead of printing them.

``main.py`` is the reference implementation and the submission deliverable;
this mirrors its sequence so the web UI can stream each stage as it happens.
All of the actual work — detection, embedding, search, candidate selection,
hashing, anchoring, verification — is done by the same shared modules, so the
two front-ends cannot disagree about behaviour.

The face models are loaded once per process and reused across requests: they
are the dominant memory cost, and reloading them per request would both be
slow and risk an out-of-memory kill.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterator

from config import OUTPUT_DIR, load_config

TOTAL_STEPS = 7

_detector_lock = threading.Lock()
_detector = None


def get_detector():
    """Process-wide singleton InsightFace detector."""
    global _detector
    with _detector_lock:
        if _detector is None:
            from face.detector import FaceDetector

            config = load_config()
            detector = FaceDetector(
                model_pack=config.face.model_pack,
                det_size=config.face.det_size,
                det_threshold=config.face.det_threshold,
            )
            detector._ensure_loaded()  # pay the load cost now, not mid-request
            _detector = detector
    return _detector


def _ev(event: str, **fields: Any) -> dict[str, Any]:
    return {"event": event, **fields}


def run(
    image_path: str | Path,
    *,
    threshold: float | None = None,
    max_checks: int | None = None,
    prefer_platform: str | None = None,
    network: str | None = None,
    fetch_exact: bool | None = None,
) -> Iterator[dict[str, Any]]:
    """Run the full pipeline, yielding one event per meaningful step.

    Terminal events are ``done`` (with ``verified``) or ``fail``. A failure is
    always reported as a failure — never converted into a success.
    """
    from blockchain.chain import ChainError, connect
    from blockchain.verifier import EvidenceVerifier
    from blockchain.writer import EvidenceWriter
    from face.detector import FaceDetectionError
    from face.encoder import FaceEncoder
    from integrity.hashing import build_record, sha256_file
    from search.candidate_selector import CandidateSelector
    from search.result_parser import (
        TIER_NAMES,
        describe_preference,
        parse_lens_response,
        resolve_preference,
    )
    from search.serpapi_client import SearchError, SerpApiLensClient
    from utils.imaging import ImageError
    from utils.imaging import load_image as load_input_image

    config = load_config()
    threshold = config.face.match_threshold if threshold is None else threshold
    max_checks = config.search.max_face_checks if max_checks is None else max_checks
    network = (network or config.chain.network).strip().lower()
    prefer_platform = prefer_platform or config.search.prefer_platform or None
    fetch_exact = True if fetch_exact is None else fetch_exact

    # ------------------------------------------------------------------ 1/7
    yield _ev("stage", n=1, total=TOTAL_STEPS, title="Loading image")
    try:
        loaded = load_input_image(image_path)
    except ImageError as exc:
        yield _ev("fail", text=str(exc))
        return

    query_image_sha256 = sha256_file(loaded.path)
    yield _ev("ok", text=f"{loaded.path.name}")
    yield _ev("detail", label="format", value=f"{loaded.image_format} · {loaded.width}×{loaded.height}")
    yield _ev("detail", label="size", value=f"{loaded.size_bytes / 1024:.0f} KB")
    yield _ev("detail", label="sha256", value=query_image_sha256, mono=True)

    # ------------------------------------------------------------------ 2/7
    yield _ev("stage", n=2, total=TOTAL_STEPS, title="Detecting face and generating embedding")
    encoder = FaceEncoder(get_detector())
    try:
        reference_face, face_count = encoder.encode_loaded(loaded)
    except FaceDetectionError as exc:
        yield _ev("fail", text=str(exc))
        return

    yield _ev("ok", text=f"Face detected (confidence {reference_face.det_score:.3f})")
    if face_count > 1:
        yield _ev("warn", text=f"{face_count} faces found — using the largest")
    yield _ev("ok", text=f"{reference_face.embedding.shape[0]}-d ArcFace embedding generated")
    yield _ev("detail", label="bounding box", value=str(list(reference_face.bbox)))

    # ------------------------------------------------------------------ 3/7
    yield _ev("stage", n=3, total=TOTAL_STEPS, title="Performing genuine reverse-image search")
    try:
        client = SerpApiLensClient(
            api_key=config.search.api_key,
            timeout=config.search.timeout,
            country=config.search.country,
            language=config.search.language,
        )
    except SearchError as exc:
        yield _ev("fail", text=str(exc))
        return

    account = client.account_info()
    if account:
        yield _ev(
            "detail",
            label="SerpApi quota",
            value=f"{account.get('total_searches_left','?')} searches left "
            f"({account.get('plan_name','?')})",
        )

    yield _ev("working", text="Uploading image and querying Google Lens…")
    try:
        search_result = client.search_local_image(
            loaded.path, include_exact_matches=fetch_exact, loaded=loaded
        )
    except SearchError as exc:
        yield _ev("fail", text=str(exc))
        return

    candidates = parse_lens_response(search_result.payload)
    yield _ev("ok", text="Live search completed — results generated at runtime")
    yield _ev("detail", label="engine", value="Google Lens via SerpApi")
    yield _ev("detail", label="queries", value=", ".join(search_result.search_types))
    yield _ev("detail", label="search id", value=search_result.search_id or "n/a", mono=True)
    yield _ev("ok", text=f"{len(candidates)} candidate pages returned")

    if not candidates:
        yield _ev("fail", text="Reverse-image search returned no candidate pages.")
        return

    yield _ev(
        "detail",
        label="social-media hits",
        value=str(sum(1 for c in candidates if c.is_social)),
    )

    # ------------------------------------------------------------ 4/7 + 5/7
    yield _ev("stage", n=4, total=TOTAL_STEPS, title="Inspecting candidates")
    yield _ev("info", text=f"Checking up to {max_checks}: X, then Web articles, then other social")
    preference = resolve_preference(prefer_platform)
    if preference:
        yield _ev("info", text=f"Preferring {describe_preference(preference)} among verified matches")

    yield _ev("stage", n=5, total=TOTAL_STEPS, title="Verifying faces against the input embedding")

    selector = CandidateSelector(
        encoder=encoder,
        threshold=threshold,
        download_timeout=config.search.download_timeout,
        max_download_bytes=config.search.max_download_bytes,
        max_checks=max_checks,
        prefer_platform=prefer_platform,
    )

    events: list[dict[str, Any]] = []

    def on_progress(candidate, verified, status):
        events.append(
            _ev(
                "candidate",
                platform=candidate.platform,
                url=candidate.link,
                title=candidate.title,
                similarity=None if verified is None else round(verified.similarity, 4),
                match=bool(verified and verified.is_match),
                status=status,
            )
        )

    report = selector.verify_candidates(
        candidates, reference_face.embedding, on_progress=on_progress
    )
    for event in events:
        yield event

    yield _ev("detail", label="faces compared", value=str(len(report.checked)))
    yield _ev("detail", label="images unavailable", value=str(report.fetch_failures))
    yield _ev("detail", label="no face in image", value=str(report.no_face))
    yield _ev("detail", label="passed threshold", value=str(len(report.matches)))

    best = report.best
    if best is None:
        yield _ev(
            "fail",
            text=f"No candidate passed the face-match threshold of {threshold:g}.",
            detail=(
                "The search ran and returned real pages, but none of the images "
                "contained a face matching the input. Reported honestly rather "
                "than accepting a weak result."
            ),
        )
        return

    yield _ev("ok", text="Candidate confirmed by face comparison")
    yield _ev(
        "match",
        platform=best.candidate.platform,
        tier=TIER_NAMES.get(best.candidate.tier, "unknown"),
        url=best.candidate.link,
        title=best.candidate.title,
        similarity=round(best.similarity, 4),
        percent=best.match.percent,
        threshold=threshold,
        image_url=best.image_url_used,
        image_sha256=best.image_sha256,
    )

    # ------------------------------------------------------------------ 6/7
    yield _ev("stage", n=6, total=TOTAL_STEPS, title="Creating integrity fingerprint")
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
    record.save(OUTPUT_DIR / "evidence_record.json")

    yield _ev("ok", text="Deterministic record built (canonical JSON, sorted keys, UTF-8)")
    yield _ev("record", data=record.data, sha256=record.digest)

    # ------------------------------------------------------------------ 7/7
    yield _ev("stage", n=7, total=TOTAL_STEPS, title="Anchoring on blockchain and re-verifying")
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
        yield _ev("fail", text=str(exc))
        return

    yield _ev("ok", text=f"Connected: {connection.label}")
    yield _ev("detail", label="account", value=connection.account_address, mono=True)
    try:
        balance = connection.balance_eth()
        yield _ev("detail", label="balance", value=f"{balance:.6f} ETH")
        if connection.is_public_testnet and balance == 0:
            yield _ev("fail", text="Wallet has no Sepolia ETH — cannot pay for the transaction.")
            return
    except Exception:  # noqa: BLE001 - informational only
        pass

    yield _ev("working", text="Submitting transaction…")
    writer = EvidenceWriter(connection, tx_timeout=config.chain.tx_timeout)
    try:
        anchor = writer.anchor(record.digest, config.chain.contract_address)
    except ChainError as exc:
        yield _ev("fail", text=str(exc))
        return

    yield _ev("ok", text="Transaction confirmed")
    yield _ev("anchor", **anchor.to_dict())

    yield _ev("working", text="Reading the record back from the chain…")
    verifier = EvidenceVerifier(connection)
    try:
        result = verifier.verify_record(anchor.contract_address, anchor.record_id, record.data)
    except ChainError as exc:
        yield _ev("fail", text=str(exc))
        return

    yield _ev(
        "verification",
        local=result.local_fingerprint,
        onchain=result.onchain_fingerprint,
        verified=result.verified,
    )

    # Tamper demonstration: alter the record and re-verify against the chain.
    tampered = dict(record.data)
    post = dict(tampered.get("discovered_post", {}))
    post["title"] = (post.get("title", "") or "") + " (tampered)"
    tampered["discovered_post"] = post
    tamper_result = verifier.verify_record(anchor.contract_address, anchor.record_id, tampered)
    yield _ev(
        "tamper",
        local=tamper_result.local_fingerprint,
        onchain=tamper_result.onchain_fingerprint,
        verified=tamper_result.verified,
    )

    yield _ev("done", verified=result.verified)
