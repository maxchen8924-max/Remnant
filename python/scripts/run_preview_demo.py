#!/usr/bin/env python3
"""Run the Remnant v0.1 preview demo."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from remnant_bridge.preview_demo import (
    DEFAULT_FIXTURE_DIR,
    format_preview_summary,
    run_preview_demo,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Remnant preview demo")
    parser.add_argument(
        "--db-path",
        default="",
        help="SQLite database path. Defaults to a temporary preview.db.",
    )
    parser.add_argument(
        "--fixture-dir",
        default=str(DEFAULT_FIXTURE_DIR),
        help="Directory containing sample_profile.json and wechat_sample.txt.",
    )
    parser.add_argument(
        "--query",
        default="西湖",
        help="Query text to run against the imported sample data.",
    )
    args = parser.parse_args()

    if args.db_path:
        db_path = Path(args.db_path)
    else:
        db_path = Path(tempfile.mkdtemp(prefix="remnant-preview-")) / "preview.db"

    result = run_preview_demo(
        db_path=db_path,
        fixture_dir=Path(args.fixture_dir),
        query=args.query,
    )
    print(format_preview_summary(result))


if __name__ == "__main__":
    main()
