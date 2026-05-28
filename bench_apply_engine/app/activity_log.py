from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import ActivityEvent


class ActivityLogger:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.output_dir / "application_events.jsonl"

    def write(self, event: ActivityEvent) -> None:
        with self.events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
