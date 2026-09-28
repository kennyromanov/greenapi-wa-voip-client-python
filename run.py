"""Application example entry point; call handling will be added after the SDK."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Green-API WhatsApp voice call example")
    parser.add_argument("--api-url", help="Instance API URL")
    parser.add_argument("--id-instance", help="Green-API instance ID")
    parser.add_argument("--api-token-instance", help="Green-API instance token")
    parser.add_argument("--dial", help="Phone number, chat ID, or LID to call")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    raise SystemExit("The call example is not implemented yet")


if __name__ == "__main__":
    raise SystemExit(main())
