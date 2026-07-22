"""Command-line interface used by hooks and conformance tests."""

from __future__ import annotations

import argparse
import json
import sys

from .hooks import handle_hook
from .protocol import failure_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mythos-runtime")
    parser.add_argument("--host", required=True, choices=("codex", "claude"))
    parser.add_argument("--event", required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("stdin must contain one JSON object")
        result = handle_hook(host=args.host, event=args.event, payload=payload)
    except Exception as error:
        result = failure_result(
            host=args.host,
            event=args.event,
            reason=f"Hook runtime failure: {error}",
        )
    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())