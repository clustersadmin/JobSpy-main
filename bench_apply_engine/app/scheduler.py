from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError

from .pipeline import run_component


@dataclass
class SchedulerConfig:
    bench_json_path: str
    jobs_csv_path: str
    output_dir: str = "component_outputs"
    threshold: float = 70.0
    interval_minutes: int = 120
    max_runs: int = 0
    webhook_url: str | None = None
    webhook_timeout_seconds: int = 15


def _post_webhook(url: str, payload: dict[str, object], timeout_seconds: int) -> tuple[bool, str]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib_request.urlopen(req, timeout=max(1, timeout_seconds)) as resp:
            status = getattr(resp, "status", 200)
            return True, f"HTTP {status}"
    except HTTPError as exc:
        return False, f"HTTPError {exc.code}: {exc.reason}"
    except URLError as exc:
        return False, f"URLError: {exc.reason}"
    except Exception as exc:
        return False, f"Error: {exc}"


def run_scheduler(config: SchedulerConfig) -> dict[str, object]:
    out = Path(config.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    history_file = out / "scheduler_runs.jsonl"

    run_count = 0
    while True:
        run_count += 1
        started_at = datetime.now(timezone.utc).isoformat()

        summary = run_component(
            bench_json_path=Path(config.bench_json_path),
            jobs_csv_path=Path(config.jobs_csv_path),
            output_dir=out,
            threshold=config.threshold,
        )

        record = {
            "started_at": started_at,
            "run_number": run_count,
            "config": asdict(config),
            "summary": summary,
        }

        if config.webhook_url:
            success, message = _post_webhook(
                url=config.webhook_url,
                payload=record,
                timeout_seconds=config.webhook_timeout_seconds,
            )
            record["webhook"] = {
                "enabled": True,
                "success": success,
                "message": message,
                "url": config.webhook_url,
            }

        with history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        if config.max_runs and run_count >= config.max_runs:
            break

        time.sleep(max(1, int(config.interval_minutes * 60)))

    return {
        "runs": run_count,
        "history_file": str(history_file),
        "output_dir": str(out),
    }
