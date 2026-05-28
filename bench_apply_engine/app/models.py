from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class BenchResource:
    resource_id: str
    full_name: str
    target_roles: list[str]
    position_types: list[str]
    preferred_locations: list[str]
    work_authorization: str
    expected_rate: str | None = None
    verified_skills: list[str] = field(default_factory=list)
    base_resume_text: str = ""


@dataclass
class JobPosting:
    job_id: str
    title: str
    portal: str
    location: str
    job_type: str
    job_description: str
    salary_or_rate: str | None = None
    immigration_status: str | None = None
    url: str | None = None


@dataclass
class MatchResult:
    resource_id: str
    job_id: str
    score: float
    matched_skills: list[str]
    missing_keywords: list[str]
    reasoning: str


@dataclass
class ResumeOptimizationResult:
    original_resume_text: str
    optimized_resume_text: str
    applied_changes: list[str]
    truthfulness_notice: str = (
        "No fabricated experience/skills added. Only verified skills and wording refinements are used."
    )


@dataclass
class ApplyPacket:
    resource_id: str
    job_id: str
    portal: str
    title: str
    location: str
    client: str
    rate: str | None
    original_resume_text: str
    optimized_resume_text: str
    cover_letter_text: str


@dataclass
class ActivityEvent:
    event_type: str
    resource_id: str
    job_id: str
    portal: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
