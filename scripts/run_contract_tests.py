#!/usr/bin/env python3
"""Run the standard-library unit, concurrency, and hook contract tests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


SUITES = ("unit", "state-concurrency", "contract")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    for suite in SUITES:
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(root / "tests" / suite),
            "-p",
            "test_*.py",
            "-v",
        ]
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(command, cwd=root, check=False, env=environment)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())