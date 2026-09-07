"""Central configuration, loaded from environment / .env.

Every secret (SerpApi key, RPC URL, private key) is read from the environment.
Nothing sensitive is ever hardcoded here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
ARTIFACT_PATH = PROJECT_ROOT / "blockchain" / "artifacts" / "FaceEvidenceRegistry.json"

load_dotenv(PROJECT_ROOT / ".env")


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class FaceConfig:
    """InsightFace settings.

    ``match_threshold`` is cosine similarity between two L2-normalised ArcFace
    embeddings. See README for how this value was chosen.
    """

    model_pack: str = field(default_factory=lambda: os.getenv("FACE_MODEL_PACK", "buffalo_l"))
    det_size: int = field(default_factory=lambda: _get_int("FACE_DET_SIZE", 640))
    det_threshold: float = field(default_factory=lambda: _get_float("FACE_DET_THRESHOLD", 0.5))
    match_threshold: float = field(default_factory=lambda: _get_float("FACE_MATCH_THRESHOLD", 0.45))


@dataclass(frozen=True)
class SearchConfig:
    """SerpApi / Google Lens settings."""

    api_key: str | None = field(default_factory=lambda: os.getenv("SERPAPI_API_KEY") or None)
    timeout: int = field(default_factory=lambda: _get_int("SERPAPI_TIMEOUT", 60))
    country: str = field(default_factory=lambda: os.getenv("SERPAPI_COUNTRY", "us"))
    language: str = field(default_factory=lambda: os.getenv("SERPAPI_LANGUAGE", "en"))
    max_candidates: int = field(default_factory=lambda: _get_int("MAX_CANDIDATES", 25))
    # Which platform to favour among candidates that already passed the face
    # check. X (Twitter) is this pipeline's designated social-media target;
    # "Web" selects a news/blog/institutional article instead.
    prefer_platform: str = field(
        default_factory=lambda: os.getenv("PREFER_PLATFORM", "X (Twitter)").strip()
    )
    max_face_checks: int = field(default_factory=lambda: _get_int("MAX_FACE_CHECKS", 12))
    download_timeout: int = field(default_factory=lambda: _get_int("DOWNLOAD_TIMEOUT", 20))
    max_download_bytes: int = field(default_factory=lambda: _get_int("MAX_DOWNLOAD_BYTES", 12_000_000))


@dataclass(frozen=True)
class ChainConfig:
    """Ethereum settings. ``network`` selects sepolia or the local dev chain."""

    network: str = field(default_factory=lambda: os.getenv("BLOCKCHAIN_NETWORK", "local").strip().lower())
    sepolia_rpc_url: str = field(
        default_factory=lambda: os.getenv("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com")
    )
    local_rpc_url: str = field(default_factory=lambda: os.getenv("LOCAL_RPC_URL", "http://127.0.0.1:8545"))
    private_key: str | None = field(default_factory=lambda: os.getenv("WALLET_PRIVATE_KEY") or None)
    contract_address: str | None = field(default_factory=lambda: os.getenv("CONTRACT_ADDRESS") or None)
    tx_timeout: int = field(default_factory=lambda: _get_int("TX_TIMEOUT", 300))

    @property
    def rpc_url(self) -> str:
        return self.sepolia_rpc_url if self.network == "sepolia" else self.local_rpc_url

    @property
    def explorer_base(self) -> str | None:
        return "https://sepolia.etherscan.io" if self.network == "sepolia" else None


@dataclass(frozen=True)
class Config:
    face: FaceConfig = field(default_factory=FaceConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    chain: ChainConfig = field(default_factory=ChainConfig)


def load_config() -> Config:
    return Config()
