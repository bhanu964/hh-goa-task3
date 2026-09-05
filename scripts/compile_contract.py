#!/usr/bin/env python3
"""Compile FaceEvidenceRegistry.sol into a committed ABI + bytecode artifact.

Run this only when the contract source changes:

    python scripts/compile_contract.py

The resulting artifact is committed, so running the pipeline needs no Solidity
toolchain at all — just web3.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import solcx

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "contracts" / "FaceEvidenceRegistry.sol"
ARTIFACT = ROOT / "blockchain" / "artifacts" / "FaceEvidenceRegistry.json"
SOLC_VERSION = "0.8.24"
CONTRACT_NAME = "FaceEvidenceRegistry"


def main() -> int:
    if not SOURCE.exists():
        print(f"Contract source not found: {SOURCE}", file=sys.stderr)
        return 1

    installed = {str(v) for v in solcx.get_installed_solc_versions()}
    if SOLC_VERSION not in installed:
        print(f"Installing solc {SOLC_VERSION} …")
        solcx.install_solc(SOLC_VERSION)

    print(f"Compiling {SOURCE.relative_to(ROOT)} with solc {SOLC_VERSION} …")
    compiled = solcx.compile_files(
        [str(SOURCE)],
        output_values=["abi", "bin"],
        solc_version=SOLC_VERSION,
        optimize=True,
        optimize_runs=200,
    )

    key = next(k for k in compiled if k.endswith(f":{CONTRACT_NAME}"))
    contract = compiled[key]

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(
        json.dumps(
            {
                "contractName": CONTRACT_NAME,
                "solcVersion": SOLC_VERSION,
                "optimizer": {"enabled": True, "runs": 200},
                "abi": contract["abi"],
                "bytecode": "0x" + contract["bin"].removeprefix("0x"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {ARTIFACT.relative_to(ROOT)}")
    print(f"  ABI entries:   {len(contract['abi'])}")
    print(f"  Bytecode size: {len(contract['bin']) // 2} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
