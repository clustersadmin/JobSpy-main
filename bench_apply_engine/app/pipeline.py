from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from .activity_log import ActivityLogger
from .matching import rank_jobs
from .models import ActivityEvent, ApplyPacket, BenchResource, JobPosting, MatchResult
from .resume_optimizer import optimize_resume


def load_bench_resources(path: Path) -> list[BenchResource]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [BenchResource(**item) for item in data]


def load_jobs_from_csv(path: Path) -> list[JobPosting]:
    rows: list[JobPosting] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            rows.append(
                JobPosting(
                    job_id=row.get("job_id") or f"job-{idx}",
                    title=row.get("Title") or row.get("title") or "",
                    portal=row.get("Portal") or row.get("site") or "",
                    location=row.get("Job Location") or row.get("location") or "",
                    job_type=row.get("Job Type") or row.get("job_type") or "",
                    job_description=(
                        row.get("Job Description Version 1")
                        or row.get("Job Description")
                        or row.get("description")
                        or ""
                    ),
                    salary_or_rate=row.get("Salary or Hourly Price") or row.get("salary") or "",
                    immigration_status=row.get("Immigration Status") or "",
                    url=row.get("job_url") or "",
                )
            )
    return rows


def process_resources_and_jobs(
    resources: list[BenchResource],
    jobs: list[JobPosting],
    threshold: float = 70.0,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    packets: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    match_rows: list[dict[str, object]] = []

    for resource in resources:
        matches = rank_jobs(resource=resource, jobs=jobs, threshold=threshold)

        start_event = ActivityEvent(
            event_type="resource_match_started",
            resource_id=resource.resource_id,
            job_id="*",
            portal="*",
            payload={"candidate": resource.full_name, "qualified_jobs": len(matches)},
        )
        events.append(asdict(start_event))

        match_by_job: dict[str, MatchResult] = {m.job_id: m for m in matches}
        for job in jobs:
            match_obj = match_by_job.get(job.job_id)
            if not match_obj:
                continue

            match_rows.append(
                {
                    "resource_id": resource.resource_id,
                    "job_id": job.job_id,
                    "portal": job.portal,
                    "title": job.title,
                    "score": match_obj.score,
                    "matched_skills": match_obj.matched_skills,
                    "missing_keywords": match_obj.missing_keywords,
                    "reasoning": match_obj.reasoning,
                }
            )

            optimization, cover_letter = optimize_resume(resource, job, match_obj)

            packet = ApplyPacket(
                resource_id=resource.resource_id,
                job_id=job.job_id,
                portal=job.portal,
                title=job.title,
                location=job.location,
                client=job.portal,
                rate=job.salary_or_rate,
                original_resume_text=optimization.original_resume_text,
                optimized_resume_text=optimization.optimized_resume_text,
                cover_letter_text=cover_letter,
            )
            packets.append(asdict(packet))

            packet_event = ActivityEvent(
                event_type="apply_packet_prepared",
                resource_id=resource.resource_id,
                job_id=job.job_id,
                portal=job.portal,
                payload={
                    "score": match_obj.score,
                    "matched_skills": match_obj.matched_skills,
                    "reasoning": match_obj.reasoning,
                    "changes": optimization.applied_changes,
                },
            )
            events.append(asdict(packet_event))

    return packets, events, match_rows


def run_component(
    bench_json_path: Path,
    jobs_csv_path: Path,
    output_dir: Path,
    threshold: float = 70.0,
) -> dict[str, object]:
    resources = load_bench_resources(bench_json_path)
    jobs = load_jobs_from_csv(jobs_csv_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    logger = ActivityLogger(output_dir=output_dir)
    packets, events, _ = process_resources_and_jobs(resources=resources, jobs=jobs, threshold=threshold)

    for event in events:
        logger.write(ActivityEvent(**event))

    packets_path = output_dir / "apply_packets.json"
    packets_path.write_text(json.dumps(packets, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "resources": len(resources),
        "jobs": len(jobs),
        "packets": len(packets),
        "packets_file": str(packets_path),
        "events_file": str(logger.events_file),
        "threshold": threshold,
    }
    return summary
