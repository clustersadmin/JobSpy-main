from __future__ import annotations

import re
from collections import Counter

from .models import BenchResource, JobPosting, MatchResult


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.#/-]*", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


def _normalized_phrase_match(phrase: str, text: str) -> bool:
    p = re.sub(r"\s+", " ", phrase.strip().lower())
    t = re.sub(r"\s+", " ", (text or "").lower())
    return bool(p and p in t)


def compute_match(resource: BenchResource, job: JobPosting) -> MatchResult:
    text = "\n".join([job.title, job.job_description, job.location, job.job_type]).lower()

    role_hits = [r for r in resource.target_roles if _normalized_phrase_match(r, text)]
    skill_hits = [s for s in resource.verified_skills if _normalized_phrase_match(s, text)]

    job_tokens = Counter(_tokens(text))
    resume_tokens = Counter(_tokens(resource.base_resume_text))

    # Overlap from resume content against job description vocabulary.
    overlap = set(job_tokens).intersection(set(resume_tokens))
    overlap_score = min(10.0, float(len(overlap)) * 0.6)

    total_roles = max(1, len(resource.target_roles))
    total_skills = max(1, len(resource.verified_skills))
    role_score = (len(role_hits) / total_roles) * 35.0
    skill_score = (len(skill_hits) / total_skills) * 55.0

    score = round(min(100.0, overlap_score + role_score + skill_score), 2)

    # Missing keywords are high-frequency job tokens not present in resume.
    missing = [
        token
        for token, count in job_tokens.most_common(40)
        if len(token) > 3 and token not in resume_tokens and count >= 2
    ][:15]

    reasoning = (
        f"roles={len(role_hits)}, matched_skills={len(skill_hits)}, token_overlap={len(overlap)}"
    )

    return MatchResult(
        resource_id=resource.resource_id,
        job_id=job.job_id,
        score=score,
        matched_skills=skill_hits,
        missing_keywords=missing,
        reasoning=reasoning,
    )


def rank_jobs(resource: BenchResource, jobs: list[JobPosting], threshold: float = 70.0) -> list[MatchResult]:
    matches = [compute_match(resource, job) for job in jobs]
    qualified = [m for m in matches if m.score >= threshold]
    return sorted(qualified, key=lambda m: m.score, reverse=True)
