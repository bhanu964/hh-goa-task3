#!/usr/bin/env python3
"""Generate a throwaway Ethereum keypair for the Sepolia demo.

    python scripts/new_wallet.py

Prints an address and private key for you to paste into .env yourself — the
key is never written to a file automatically, and .env is gitignored.

Use this for testnet play money only. Never put a key holding real funds in a
project .env.
"""

from __future__ import annotations

import secrets

from eth_account import Account


def main() -> int:
    account = Account.from_key("0x" + secrets.token_hex(32))

    print("\nNew throwaway Ethereum account (testnet use only)")
    print("=" * 60)
    print(f"Address:     {account.address}")
    print(f"Private key: 0x{account.key.hex().removeprefix('0x')}")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Add to .env:")
    print(f"       WALLET_PRIVATE_KEY=0x{account.key.hex().removeprefix('0x')}")
    print("       BLOCKCHAIN_NETWORK=sepolia")
    print(f"  2. Fund {account.address} from a Sepolia faucet, e.g.")
    print("       https://www.alchemy.com/faucets/ethereum-sepolia")
    print("       https://sepolia-faucet.pk910.de")
    print("  3. A first run deploys the contract; put the printed address in")
    print("     CONTRACT_ADDRESS to reuse it on later runs.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
