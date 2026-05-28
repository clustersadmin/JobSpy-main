from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.pipeline import run_component


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bench-apply-engine",
        description="Standalone bench resource matching and apply-packet preparation component.",
    )
    parser.add_argument("--bench-json", required=True, help="Path to bench_resources.json")
    parser.add_argument("--jobs-csv", required=True, help="Path to JobSpy output CSV")
    parser.add_argument("--output-dir", default="component_outputs", help="Output directory")
    parser.add_argument("--threshold", type=float, default=70.0, help="Minimum JD-resume match threshold")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    summary = run_component(
        bench_json_path=Path(args.bench_json),
        jobs_csv_path=Path(args.jobs_csv),
        output_dir=Path(args.output_dir),
        threshold=args.threshold,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
