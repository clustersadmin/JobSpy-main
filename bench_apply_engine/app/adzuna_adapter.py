from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from .matching import compute_match
from .models import BenchResource, JobPosting


@dataclass
class AdzunaConfig:
    app_id: str
    app_key: str
    country: str = "us"


def _normalize_country(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "us"

    aliases = {
        "usa": "us",
        "united states": "us",
        "united states of america": "us",
        "uk": "gb",
        "united kingdom": "gb",
    }
    return aliases.get(raw, raw)


def adzuna_config_from_env(country: str | None = None) -> AdzunaConfig | None:
    app_id = (os.getenv("ADZUNA_APP_ID") or "").strip()
    app_key = (os.getenv("ADZUNA_APP_KEY") or "").strip()
    env_country = _normalize_country(os.getenv("ADZUNA_COUNTRY") or "us")

    if not app_id or not app_key:
        return None

    selected_country = _normalize_country(country) if country else env_country
    return AdzunaConfig(app_id=app_id, app_key=app_key, country=(selected_country or "us"))


def adzuna_credentials_status() -> dict[str, Any]:
    return {
        "has_app_id": bool((os.getenv("ADZUNA_APP_ID") or "").strip()),
        "has_app_key": bool((os.getenv("ADZUNA_APP_KEY") or "").strip()),
        "country": _normalize_country(os.getenv("ADZUNA_COUNTRY") or "us"),
    }


def _build_salary_text(raw: dict[str, Any]) -> str:
    smin = raw.get("salary_min")
    smax = raw.get("salary_max")
    if smin is None and smax is None:
        return ""
    try:
        min_v = float(smin) if smin is not None else None
        max_v = float(smax) if smax is not None else None
    except (TypeError, ValueError):
        return ""

    if min_v is not None and max_v is not None:
        return f"USD {min_v:,.0f} - {max_v:,.0f}"
    if min_v is not None:
        return f"USD {min_v:,.0f}"
    return f"USD {max_v:,.0f}"


def search_jobs_via_adzuna(
    query: str,
    location: str | None = None,
    results_per_page: int = 20,
    max_days_old: int = 2,
    country: str | None = None,
    page: int = 1,
) -> tuple[list[JobPosting], dict[str, Any]]:
    config = adzuna_config_from_env(country=country)
    if not config:
        raise RuntimeError("Missing Adzuna credentials. Set ADZUNA_APP_ID and ADZUNA_APP_KEY.")

    params = {
        "app_id": config.app_id,
        "app_key": config.app_key,
        "what": query,
        "where": location or "",
        "results_per_page": max(1, min(int(results_per_page), 50)),
        "max_days_old": max(1, int(max_days_old)),
        "sort_by": "date",
        "content-type": "application/json",
    }

    url = f"https://api.adzuna.com/v1/api/jobs/{config.country}/search/{max(1, int(page))}?{urlencode(params)}"
    with urlopen(url, timeout=30) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    results = raw.get("results", []) if isinstance(raw, dict) else []
    jobs: list[JobPosting] = []
    for idx, item in enumerate(results, start=1):
        loc = item.get("location") if isinstance(item, dict) else {}
        display_location = ""
        if isinstance(loc, dict):
            display_location = str(loc.get("display_name") or "")

        contract_type = str(item.get("contract_type") or "").strip()
        contract_time = str(item.get("contract_time") or "").strip()
        job_type = " ".join([x for x in [contract_type, contract_time] if x]).strip()

        jobs.append(
            JobPosting(
                job_id=str(item.get("id") or f"adzuna-{idx}"),
                title=str(item.get("title") or ""),
                portal="adzuna",
                location=display_location,
                job_type=job_type,
                job_description=str(item.get("description") or ""),
                salary_or_rate=_build_salary_text(item),
                immigration_status="",
                url=str(item.get("redirect_url") or ""),
            )
        )

    meta = {
        "count": raw.get("count") if isinstance(raw, dict) else None,
        "mean": raw.get("mean") if isinstance(raw, dict) else None,
        "query": query,
        "location": location,
        "country": config.country,
        "page": page,
        "results": len(jobs),
    }
    return jobs, meta


def match_resources_to_job_description(
    resources: list[BenchResource],
    title: str,
    job_description: str,
    location: str = "",
    job_type: str = "",
    threshold: float = 70.0,
) -> list[dict[str, Any]]:
    pseudo = JobPosting(
        job_id="jd-input",
        title=title,
        portal="manual",
        location=location,
        job_type=job_type,
        job_description=job_description,
        salary_or_rate="",
        immigration_status="",
        url="",
    )

    rows: list[dict[str, Any]] = []
    for resource in resources:
        match = compute_match(resource, pseudo)
        if match.score < threshold:
            continue
        rows.append(
            {
                "resource_id": resource.resource_id,
                "full_name": resource.full_name,
                "score": match.score,
                "matched_skills": match.matched_skills,
                "missing_keywords": match.missing_keywords,
                "reasoning": match.reasoning,
                "work_authorization": resource.work_authorization,
                "expected_rate": resource.expected_rate,
                "preferred_locations": resource.preferred_locations,
            }
        )

    return sorted(rows, key=lambda r: float(r.get("score") or 0.0), reverse=True)
