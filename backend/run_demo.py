#!/usr/bin/env python3
"""Single-command entry point for the observable runtime demo.

Usage (from the repository root):

    .venv/bin/python3 backend/run_demo.py
    .venv/bin/python3 backend/run_demo.py --verbose

Or from ``backend/``:

    ../.venv/bin/python3 run_demo.py

Runs the deterministic demo event sequence through the existing Kernel
store, operational observability metrics, and detection engine, printing
every stage to the console. See ``backend/app/demo_runtime.py`` for the
pipeline implementation and ``docs/demo.md`` for the full demo script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.demo_runtime import run_console_demo  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the observable runtime demo: event generator -> "
            "Kernel -> storage -> metrics -> detection -> console."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Print the raw input event JSON immediately before the output "
            "it produces, for every event."
        ),
    )
    args = parser.parse_args()
    run_console_demo(verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
