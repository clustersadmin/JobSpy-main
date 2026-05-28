from __future__ import annotations

import re

from .models import BenchResource, JobPosting, MatchResult, ResumeOptimizationResult


def _to_sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", compact) if s.strip()]


def _build_cover_letter(resource: BenchResource, job: JobPosting, match: MatchResult) -> str:
    top_skills = ", ".join(match.matched_skills[:6]) if match.matched_skills else "relevant engineering skills"
    return (
        f"Dear Hiring Team,\n\n"
        f"I am interested in the {job.title} role. My experience aligns with your requirements, "
        f"especially in {top_skills}. I am currently available and open to discussing fit, timelines, "
        f"and next steps.\n\n"
        f"Best regards,\n{resource.full_name}"
    )


def optimize_resume(resource: BenchResource, job: JobPosting, match: MatchResult) -> tuple[ResumeOptimizationResult, str]:
    original = resource.base_resume_text or ""
    changes: list[str] = []

    if not original.strip():
        original = f"{resource.full_name}\nVerified Skills: " + ", ".join(resource.verified_skills)
        changes.append("Constructed resume shell from verified profile because base resume text was empty.")

    optimized = original

    # Only emphasize verified skills that appear in the JD and are missing in current resume text.
    jd_text = f"{job.title}\n{job.job_description}".lower()
    verified_jd_skills = [
        s for s in resource.verified_skills if s and s.lower() in jd_text
    ]
    missing_from_resume = [
        s for s in verified_jd_skills if s.lower() not in optimized.lower()
    ]

    if missing_from_resume:
        optimized += "\n\nCore Skills Alignment: " + ", ".join(missing_from_resume)
        changes.append("Added a Core Skills Alignment section using verified skills already present in candidate profile.")

    # Add targeted summary from existing profile signals.
    summary = (
        f"\n\nTarget Role Fit: {job.title} | Location Preference: "
        f"{', '.join(resource.preferred_locations)} | Work Authorization: {resource.work_authorization}"
    )
    optimized += summary
    changes.append("Appended targeted summary block for recruiter readability.")

    result = ResumeOptimizationResult(
        original_resume_text=original,
        optimized_resume_text=optimized,
        applied_changes=changes,
    )
    cover_letter = _build_cover_letter(resource, job, match)
    return result, cover_letter
