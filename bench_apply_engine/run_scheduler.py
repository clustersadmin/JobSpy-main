from __future__ import annotations

import argparse
import json

from app.scheduler import SchedulerConfig, run_scheduler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bench-apply-scheduler",
        description="Recurring standalone scheduler for bench apply engine runs.",
    )
    parser.add_argument("--bench-json", required=True, help="Path to bench_resources.json")
    parser.add_argument("--jobs-csv", required=True, help="Path to JobSpy output CSV")
    parser.add_argument("--output-dir", default="component_outputs", help="Output directory")
    parser.add_argument("--threshold", type=float, default=70.0, help="Minimum match threshold")
    parser.add_argument("--interval-minutes", type=int, default=120, help="Run interval in minutes")
    parser.add_argument("--max-runs", type=int, default=1, help="Number of runs. Use 0 for continuous.")
    parser.add_argument("--webhook-url", default=None, help="Optional webhook URL to receive run summaries")
    parser.add_argument("--webhook-timeout-seconds", type=int, default=15, help="Webhook timeout in seconds")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    result = run_scheduler(
        SchedulerConfig(
            bench_json_path=args.bench_json,
            jobs_csv_path=args.jobs_csv,
            output_dir=args.output_dir,
            threshold=args.threshold,
            interval_minutes=args.interval_minutes,
            max_runs=args.max_runs,
            webhook_url=args.webhook_url,
            webhook_timeout_seconds=args.webhook_timeout_seconds,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
