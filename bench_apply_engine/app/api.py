from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .adzuna_adapter import (
    adzuna_credentials_status,
    match_resources_to_job_description,
    search_jobs_via_adzuna,
)
from .activity_log import ActivityLogger
from .models import ActivityEvent, BenchResource, JobPosting
from .pipeline import process_resources_and_jobs


class BenchResourceIn(BaseModel):
    resource_id: str
    full_name: str
    target_roles: list[str]
    position_types: list[str]
    preferred_locations: list[str]
    work_authorization: str
    expected_rate: str | None = None
    verified_skills: list[str] = Field(default_factory=list)
    base_resume_text: str = ""


class JobPostingIn(BaseModel):
    job_id: str
    title: str
    portal: str
    location: str
    job_type: str
    job_description: str
    salary_or_rate: str | None = None
    immigration_status: str | None = None
    url: str | None = None


class MatchJobsRequest(BaseModel):
    resources: list[BenchResourceIn]
    jobs: list[JobPostingIn]
    threshold: float = 70.0


class PreparePacketsRequest(BaseModel):
    resources: list[BenchResourceIn]
    jobs: list[JobPostingIn]
    threshold: float = 70.0
    output_dir: str = "component_outputs"


class ActivityLogRequest(BaseModel):
    output_dir: str = "component_outputs"
    limit: int = 100


class ExtensionHandoffRequest(BaseModel):
    apply_packet: dict[str, Any]
    require_user_confirmation: bool = True


class AdapterContractRequest(BaseModel):
    portal: str


class ExtensionTaskQueueRequest(BaseModel):
    grouped_packets: dict[str, Any]
    resource_id: str | None = None
    max_tasks_per_resource: int = 10
    cooldown_seconds: int = 120
    require_user_confirmation: bool = True


class AdzunaSearchRequest(BaseModel):
    query: str
    location: str | None = None
    results_per_page: int = 20
    max_days_old: int = 2
    country: str | None = None
    page: int = 1


class CandidateMatchFromJDRequest(BaseModel):
    resources: list[BenchResourceIn]
    title: str
    job_description: str
    location: str = ""
    job_type: str = ""
    threshold: float = 70.0


class AdzunaSearchAndMatchRequest(BaseModel):
    resources: list[BenchResourceIn]
    query: str
    location: str | None = None
    results_per_page: int = 20
    max_days_old: int = 2
    country: str | None = None
    page: int = 1
    threshold: float = 70.0
    near_match_min_score: float = 0.0
    compact_response: bool = False


def _group_packets_by_resource(
    packets: list[dict[str, Any]],
    match_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    score_by_key: dict[tuple[str, str], float] = {}
    for row in match_rows:
        key = (str(row.get("resource_id") or ""), str(row.get("job_id") or ""))
        score_by_key[key] = float(row.get("score") or 0.0)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for packet in packets:
        resource_id = str(packet.get("resource_id") or "unknown")
        key = (resource_id, str(packet.get("job_id") or ""))
        item = dict(packet)
        item["match_score"] = score_by_key.get(key, 0.0)
        grouped.setdefault(resource_id, []).append(item)

    for resource_id in grouped:
        grouped[resource_id] = sorted(
            grouped[resource_id],
            key=lambda x: float(x.get("match_score") or 0.0),
            reverse=True,
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resources": grouped,
    }


def _parse_resources_json(resources_json: str) -> list[BenchResource]:
    try:
        raw = json.loads(resources_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid resources_json: {exc}") from exc

    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="resources_json must be a JSON array")

    parsed: list[BenchResource] = []
    for item in raw:
        parsed.append(BenchResource(**BenchResourceIn(**item).model_dump()))
    return parsed


def _build_task_queue(
    grouped_packets: dict[str, Any],
    resource_id: str | None,
    max_tasks_per_resource: int,
    cooldown_seconds: int,
    require_user_confirmation: bool,
) -> dict[str, Any]:
    resources_obj = grouped_packets.get("resources")
    if not isinstance(resources_obj, dict):
        raise HTTPException(status_code=400, detail="grouped_packets.resources must be an object keyed by resource_id")

    selected_ids = [resource_id] if resource_id else list(resources_obj.keys())
    queue: list[dict[str, Any]] = []
    sequence = 0

    for rid in selected_ids:
        packets = resources_obj.get(rid, [])
        if not isinstance(packets, list):
            continue

        capped = packets[: max(0, int(max_tasks_per_resource))]
        for idx, packet in enumerate(capped):
            sequence += 1
            queue.append(
                {
                    "sequence": sequence,
                    "resource_id": rid,
                    "job_id": packet.get("job_id"),
                    "portal": packet.get("portal"),
                    "title": packet.get("title"),
                    "location": packet.get("location"),
                    "match_score": packet.get("match_score", 0.0),
                    "task": {
                        "action": "open_prefill_review_submit",
                        "require_user_confirmation": bool(require_user_confirmation),
                        "cooldown_seconds_after_task": int(max(0, cooldown_seconds)),
                        "payload": {
                            "optimized_resume_text": packet.get("optimized_resume_text"),
                            "cover_letter_text": packet.get("cover_letter_text"),
                            "rate": packet.get("rate"),
                            "client": packet.get("client"),
                        },
                    },
                    "limits": {
                        "candidate_task_index": idx + 1,
                        "candidate_task_cap": int(max(0, max_tasks_per_resource)),
                        "bulk_apply_disabled": True,
                    },
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resource_id": resource_id,
        "max_tasks_per_resource": int(max(0, max_tasks_per_resource)),
        "cooldown_seconds": int(max(0, cooldown_seconds)),
        "require_user_confirmation": bool(require_user_confirmation),
        "total_tasks": len(queue),
        "tasks": queue,
    }


app = FastAPI(
    title="Bench Apply Engine API",
    version="0.1.0",
    description="Standalone API for bench-resource job matching and apply packet preparation.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/adzuna/credentials-status")
def adzuna_status() -> dict[str, Any]:
    status = adzuna_credentials_status()
    status["ready"] = bool(status.get("has_app_id") and status.get("has_app_key"))
    return status


@app.post("/adzuna/search-jobs")
def adzuna_search_jobs(request: AdzunaSearchRequest) -> dict[str, Any]:
    try:
        jobs, meta = search_jobs_via_adzuna(
            query=request.query,
            location=request.location,
            results_per_page=request.results_per_page,
            max_days_old=request.max_days_old,
            country=request.country,
            page=request.page,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Adzuna request failed: {exc}") from exc

    rows = [
        {
            "job_id": j.job_id,
            "title": j.title,
            "portal": j.portal,
            "location": j.location,
            "job_type": j.job_type,
            "salary_or_rate": j.salary_or_rate,
            "url": j.url,
            "job_description": j.job_description,
        }
        for j in jobs
    ]
    return {"meta": meta, "jobs": rows}


@app.post("/candidate-match-from-jd")
def candidate_match_from_jd(request: CandidateMatchFromJDRequest) -> dict[str, Any]:
    resources = [BenchResource(**item.model_dump()) for item in request.resources]
    ranked = match_resources_to_job_description(
        resources=resources,
        title=request.title,
        job_description=request.job_description,
        location=request.location,
        job_type=request.job_type,
        threshold=request.threshold,
    )
    return {
        "threshold": request.threshold,
        "candidates": len(ranked),
        "rows": ranked,
    }


@app.post("/adzuna/search-and-match")
def adzuna_search_and_match(request: AdzunaSearchAndMatchRequest) -> dict[str, Any]:
    resources = [BenchResource(**item.model_dump()) for item in request.resources]

    try:
        jobs, meta = search_jobs_via_adzuna(
            query=request.query,
            location=request.location,
            results_per_page=request.results_per_page,
            max_days_old=request.max_days_old,
            country=request.country,
            page=request.page,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Adzuna request failed: {exc}") from exc

    matched_jobs: list[dict[str, Any]] = []
    near_matches: list[dict[str, Any]] = []
    near_min = max(0.0, float(request.near_match_min_score))

    for job in jobs:
        ranked = match_resources_to_job_description(
            resources=resources,
            title=job.title,
            job_description=job.job_description,
            location=job.location,
            job_type=job.job_type,
            threshold=request.threshold,
        )
        relaxed_ranked = match_resources_to_job_description(
            resources=resources,
            title=job.title,
            job_description=job.job_description,
            location=job.location,
            job_type=job.job_type,
            threshold=0.0,
        )

        if relaxed_ranked and float(relaxed_ranked[0].get("score") or 0.0) >= near_min:
            near_matches.append(
                {
                    "job_id": job.job_id,
                    "title": job.title,
                    "location": job.location,
                    "portal": job.portal,
                    "url": job.url,
                    "best_candidate": relaxed_ranked[0],
                }
            )

        if not ranked:
            continue
        matched_jobs.append(
            {
                "job_id": job.job_id,
                "title": job.title,
                "location": job.location,
                "portal": job.portal,
                "url": job.url,
                "top_candidates": ranked[:5],
                "candidate_count": len(ranked),
            }
        )

    if request.compact_response:
        rows_compact = [
            {
                "job_id": row.get("job_id"),
                "title": row.get("title"),
                "portal": row.get("portal"),
                "location": row.get("location"),
                "url": row.get("url"),
                "candidate_count": row.get("candidate_count"),
                "top_candidate_name": (row.get("top_candidates") or [{}])[0].get("full_name"),
                "top_candidate_score": (row.get("top_candidates") or [{}])[0].get("score"),
            }
            for row in matched_jobs
        ]
        near_compact = [
            {
                "job_id": row.get("job_id"),
                "title": row.get("title"),
                "portal": row.get("portal"),
                "location": row.get("location"),
                "url": row.get("url"),
                "best_candidate_name": (row.get("best_candidate") or {}).get("full_name"),
                "best_candidate_score": (row.get("best_candidate") or {}).get("score"),
            }
            for row in near_matches
        ]
        return {
            "meta": meta,
            "threshold": request.threshold,
            "near_match_min_score": near_min,
            "matched_jobs": len(matched_jobs),
            "near_matches": len(near_matches),
            "rows": rows_compact,
            "near_rows": near_compact,
        }

    return {
        "meta": meta,
        "threshold": request.threshold,
        "near_match_min_score": near_min,
        "matched_jobs": len(matched_jobs),
        "near_matches": near_matches,
        "rows": matched_jobs,
    }


@app.post("/match-jobs")
def match_jobs(request: MatchJobsRequest) -> dict[str, Any]:
    resources = [BenchResource(**item.model_dump()) for item in request.resources]
    jobs = [JobPosting(**item.model_dump()) for item in request.jobs]

    _, _, match_rows = process_resources_and_jobs(resources=resources, jobs=jobs, threshold=request.threshold)
    return {
        "threshold": request.threshold,
        "resources": len(resources),
        "jobs": len(jobs),
        "matches": len(match_rows),
        "rows": match_rows,
    }


@app.post("/prepare-apply-packets")
def prepare_apply_packets(request: PreparePacketsRequest) -> dict[str, Any]:
    resources = [BenchResource(**item.model_dump()) for item in request.resources]
    jobs = [JobPosting(**item.model_dump()) for item in request.jobs]

    packets, events, match_rows = process_resources_and_jobs(resources=resources, jobs=jobs, threshold=request.threshold)

    output_dir = Path(request.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = ActivityLogger(output_dir=output_dir)

    for event in events:
        logger.write(ActivityEvent(**event))

    packets_path = output_dir / "apply_packets.json"
    packets_path.write_text(json.dumps(packets, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "threshold": request.threshold,
        "resources": len(resources),
        "jobs": len(jobs),
        "matches": len(match_rows),
        "packets": len(packets),
        "packets_file": str(packets_path),
        "events_file": str(logger.events_file),
        "rows": match_rows,
    }


@app.post("/prepare-apply-packets-grouped")
def prepare_apply_packets_grouped(request: PreparePacketsRequest) -> dict[str, Any]:
    resources = [BenchResource(**item.model_dump()) for item in request.resources]
    jobs = [JobPosting(**item.model_dump()) for item in request.jobs]

    packets, events, match_rows = process_resources_and_jobs(resources=resources, jobs=jobs, threshold=request.threshold)

    output_dir = Path(request.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = ActivityLogger(output_dir=output_dir)

    for event in events:
        logger.write(ActivityEvent(**event))

    grouped = _group_packets_by_resource(packets=packets, match_rows=match_rows)

    grouped_path = output_dir / "apply_packets_grouped.json"
    grouped_path.write_text(json.dumps(grouped, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "threshold": request.threshold,
        "resources": len(resources),
        "jobs": len(jobs),
        "matches": len(match_rows),
        "packets": len(packets),
        "grouped_file": str(grouped_path),
        "events_file": str(logger.events_file),
        "data": grouped,
    }


@app.post("/activity-log")
def activity_log(request: ActivityLogRequest) -> dict[str, Any]:
    events_path = Path(request.output_dir) / "application_events.jsonl"
    if not events_path.exists():
        raise HTTPException(status_code=404, detail=f"No events file found at {events_path}")

    lines = events_path.read_text(encoding="utf-8").splitlines()
    parsed: list[dict[str, Any]] = []
    for line in lines[-request.limit :]:
        if not line.strip():
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return {
        "events_file": str(events_path),
        "count": len(parsed),
        "events": parsed,
    }


@app.post("/prepare-apply-packets-from-files")
async def prepare_apply_packets_from_files(
    resources_json: str = Form(..., description="JSON array matching BenchResourceIn schema"),
    jobs_csv: UploadFile = File(...),
    threshold: float = Form(70.0),
    output_dir: str = Form("component_outputs"),
) -> dict[str, Any]:
    resources = _parse_resources_json(resources_json)

    suffix = Path(jobs_csv.filename or "jobs.csv").suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        content = await jobs_csv.read()
        tmp.write(content)

    try:
        from .pipeline import load_jobs_from_csv

        jobs = load_jobs_from_csv(tmp_path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    packets, events, match_rows = process_resources_and_jobs(resources=resources, jobs=jobs, threshold=threshold)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    logger = ActivityLogger(output_dir=out)

    for event in events:
        logger.write(ActivityEvent(**event))

    packets_path = out / "apply_packets.json"
    packets_path.write_text(json.dumps(packets, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "threshold": threshold,
        "resources": len(resources),
        "jobs": len(jobs),
        "matches": len(match_rows),
        "packets": len(packets),
        "packets_file": str(packets_path),
        "events_file": str(logger.events_file),
    }


@app.post("/extension-handoff")
def extension_handoff(request: ExtensionHandoffRequest) -> dict[str, Any]:
    packet = request.apply_packet
    required = ["resource_id", "job_id", "portal", "title", "location", "optimized_resume_text", "cover_letter_text"]
    missing = [key for key in required if not packet.get(key)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required apply_packet fields: {', '.join(missing)}")

    actions = [
        {
            "step": 1,
            "action": "open_job",
            "portal": packet.get("portal"),
            "job_id": packet.get("job_id"),
            "url": packet.get("url", ""),
        },
        {
            "step": 2,
            "action": "prefill_fields",
            "fields": [
                "full_name",
                "email",
                "phone",
                "work_authorization",
                "resume_upload",
                "cover_letter",
                "rate",
                "location",
            ],
        },
        {
            "step": 3,
            "action": "human_review",
            "required": bool(request.require_user_confirmation),
        },
        {
            "step": 4,
            "action": "submit_application",
            "mode": "user_confirmed_only",
        },
    ]

    return {
        "resource_id": packet.get("resource_id"),
        "job_id": packet.get("job_id"),
        "portal": packet.get("portal"),
        "contract_version": "1.0",
        "guardrails": {
            "bulk_apply_disabled": True,
            "human_confirmation_required": bool(request.require_user_confirmation),
            "no_fabrication_policy": True,
        },
        "actions": actions,
        "payload": {
            "optimized_resume_text": packet.get("optimized_resume_text"),
            "cover_letter_text": packet.get("cover_letter_text"),
            "rate": packet.get("rate"),
            "location": packet.get("location"),
            "client": packet.get("client"),
        },
    }


@app.get("/extension-adapter/{portal}")
def extension_adapter_contract(portal: str) -> dict[str, Any]:
    portal_norm = portal.strip().lower()
    contracts_dir = Path(__file__).resolve().parent / "extension_adapters"
    contract_path = contracts_dir / f"{portal_norm}.json"
    if not contract_path.exists():
        raise HTTPException(status_code=404, detail=f"No adapter contract found for portal '{portal_norm}'")

    try:
        return json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Adapter contract is invalid JSON: {exc}") from exc


@app.post("/extension-task-queue")
def extension_task_queue(request: ExtensionTaskQueueRequest) -> dict[str, Any]:
    return _build_task_queue(
        grouped_packets=request.grouped_packets,
        resource_id=request.resource_id,
        max_tasks_per_resource=request.max_tasks_per_resource,
        cooldown_seconds=request.cooldown_seconds,
        require_user_confirmation=request.require_user_confirmation,
    )


@app.post("/extension-task-queue-from-files")
async def extension_task_queue_from_files(
    resources_json: str = Form(..., description="JSON array matching BenchResourceIn schema"),
    jobs_csv: UploadFile = File(...),
    threshold: float = Form(70.0),
    output_dir: str = Form("component_outputs"),
    resource_id: str | None = Form(None),
    max_tasks_per_resource: int = Form(10),
    cooldown_seconds: int = Form(120),
    require_user_confirmation: bool = Form(True),
) -> dict[str, Any]:
    resources = _parse_resources_json(resources_json)

    suffix = Path(jobs_csv.filename or "jobs.csv").suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        content = await jobs_csv.read()
        tmp.write(content)

    try:
        from .pipeline import load_jobs_from_csv

        jobs = load_jobs_from_csv(tmp_path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    packets, events, match_rows = process_resources_and_jobs(resources=resources, jobs=jobs, threshold=threshold)
    grouped = _group_packets_by_resource(packets=packets, match_rows=match_rows)

    queue = _build_task_queue(
        grouped_packets=grouped,
        resource_id=resource_id,
        max_tasks_per_resource=max_tasks_per_resource,
        cooldown_seconds=cooldown_seconds,
        require_user_confirmation=require_user_confirmation,
    )

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    logger = ActivityLogger(output_dir=out)

    for event in events:
        logger.write(ActivityEvent(**event))

    grouped_path = out / "apply_packets_grouped.json"
    grouped_path.write_text(json.dumps(grouped, indent=2, ensure_ascii=False), encoding="utf-8")

    queue_path = out / "extension_task_queue.json"
    queue_path.write_text(json.dumps(queue, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "threshold": threshold,
        "resources": len(resources),
        "jobs": len(jobs),
        "matches": len(match_rows),
        "packets": len(packets),
        "grouped_file": str(grouped_path),
        "queue_file": str(queue_path),
        "events_file": str(logger.events_file),
        "queue": queue,
    }
