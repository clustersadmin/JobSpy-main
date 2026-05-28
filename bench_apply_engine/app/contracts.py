from __future__ import annotations

from typing import Any

SUBMISSION_PACKET_CONTRACT: dict[str, Any] = {
    "contract_version": "1.0",
    "description": "Production-ready application submission contract for candidate/job apply flow.",
    "required_sections": [
        "application",
        "candidate_profile",
        "job",
        "resume",
        "screening_answers",
        "compliance",
        "submission_control",
    ],
    "application": {
        "required": ["application_id", "resource_id", "job_id", "portal", "created_at"],
        "fields": {
            "application_id": "Unique ID for this application attempt",
            "resource_id": "Candidate/resource identifier",
            "job_id": "Target job identifier",
            "portal": "Portal/source (linkedin, indeed, adzuna, etc.)",
            "created_at": "ISO-8601 UTC timestamp",
        },
    },
    "candidate_profile": {
        "required": [
            "full_name",
            "email",
            "phone",
            "current_location",
            "work_authorization",
            "target_roles",
        ],
        "fields": {
            "full_name": "Candidate legal name",
            "email": "Email for recruiter contact",
            "phone": "Phone for recruiter contact",
            "current_location": "City/State/Country",
            "work_authorization": "Exact visa/work authorization phrasing",
            "target_roles": "List of primary target roles",
            "preferred_locations": "Preferred locations and remote preference",
            "compensation_expectation": "Rate/salary range",
            "availability_notice": "Availability and notice period",
            "linkedin_url": "LinkedIn URL",
            "portfolio_url": "Portfolio/GitHub URL if relevant",
        },
    },
    "job": {
        "required": ["title", "location", "job_type", "job_description", "url"],
        "fields": {
            "title": "Job title",
            "location": "Job location",
            "job_type": "Contract/full-time/etc.",
            "job_description": "Full normalized JD text",
            "url": "Canonical application URL",
            "must_have_skills": "Extracted must-have skill list",
            "nice_to_have_skills": "Extracted optional skill list",
            "domain": "Industry/domain tag",
        },
    },
    "resume": {
        "required": ["optimized_resume_text", "resume_variant", "truthfulness_notice"],
        "fields": {
            "original_resume_text": "Source base resume text",
            "optimized_resume_text": "JD-tailored resume text",
            "resume_variant": "Variant label (backend/fullstack/cloud)",
            "matched_skills": "Skills aligned to JD",
            "missing_keywords": "Relevant but missing JD keywords",
            "reasoning": "Why this is a match",
            "truthfulness_notice": "No-fabrication declaration",
        },
    },
    "screening_answers": {
        "required": ["work_authorization_answer", "relocation_answer", "start_date_answer"],
        "fields": {
            "work_authorization_answer": "Pre-validated answer",
            "relocation_answer": "Relocation preference answer",
            "start_date_answer": "Start date/notice period answer",
            "salary_expectation_answer": "Compensation answer",
            "requires_sponsorship_answer": "Sponsorship answer",
            "additional_answers": "Map of portal-specific question answers",
        },
    },
    "compliance": {
        "required": ["eligible_to_apply", "hard_blockers", "risk_flags"],
        "fields": {
            "eligible_to_apply": "Boolean go/no-go",
            "hard_blockers": "List of blockers (visa mismatch, location mismatch, etc.)",
            "risk_flags": "List of soft risks",
        },
    },
    "submission_control": {
        "required": ["require_human_confirmation", "bulk_apply_disabled"],
        "fields": {
            "require_human_confirmation": "Final human check before submit",
            "bulk_apply_disabled": "Guardrail setting",
            "cooldown_seconds_after_task": "Post-submit cooldown",
        },
    },
}


OUTCOME_FEEDBACK_CONTRACT: dict[str, Any] = {
    "contract_version": "1.0",
    "description": "Outcome feedback contract for interview conversion learning.",
    "required_fields": [
        "application_id",
        "resource_id",
        "job_id",
        "portal",
        "outcome_stage",
        "created_at",
    ],
    "outcome_stages": [
        "applied",
        "viewed",
        "contacted",
        "screen_scheduled",
        "interview_scheduled",
        "rejected",
        "offer",
        "hired",
    ],
    "fields": {
        "application_id": "Application attempt identifier",
        "resource_id": "Candidate/resource identifier",
        "job_id": "Job identifier",
        "portal": "Source portal",
        "outcome_stage": "Pipeline stage update",
        "outcome_status": "positive|neutral|negative|unknown",
        "reason_code": "Optional reason for rejection/drop",
        "notes": "Optional notes",
        "created_at": "ISO-8601 UTC timestamp",
        "metadata": "Optional structured metadata (recruiter, company, timestamps, etc.)",
    },
}
