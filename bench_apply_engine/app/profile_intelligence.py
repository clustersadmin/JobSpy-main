from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen


def _safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _extract_years(resume_text: str) -> int | None:
    text = resume_text.lower()
    marker = "years"
    idx = text.find(marker)
    if idx <= 0:
        return None

    probe = text[max(0, idx - 6) : idx].replace("+", " ").strip()
    digits = "".join(ch for ch in probe if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _normalize_skill(skill: str) -> str:
    return _safe_text(skill).lower()


def assess_profile_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate") or {}
    linkedin = payload.get("linkedin") or {}
    github = payload.get("github") or {}

    target_roles = _safe_list(candidate.get("target_roles"))
    verified_skills = [s for s in (_normalize_skill(x) for x in _safe_list(candidate.get("verified_skills"))) if s]
    preferred_locations = _safe_list(candidate.get("preferred_locations"))
    resume_text = _safe_text(candidate.get("base_resume_text"))

    linkedin_headline = _safe_text(linkedin.get("headline"))
    linkedin_about = _safe_text(linkedin.get("about"))
    linkedin_skills = [s for s in (_normalize_skill(x) for x in _safe_list(linkedin.get("skills"))) if s]
    linkedin_bullets = [b for b in (_safe_text(x) for x in _safe_list(linkedin.get("experience_bullets"))) if b]

    github_url = _safe_text(github.get("url"))
    github_repos = _safe_list(github.get("repos"))
    pinned = _safe_list(github.get("pinned_repo_names"))
    commits_90d = int(github.get("activity_last_90_days_commits") or 0)

    linkedin_score = 0
    if linkedin_headline:
        linkedin_score += 8
    if linkedin_about:
        linkedin_score += 8
    if linkedin_skills:
        linkedin_score += 7
    if linkedin_bullets:
        linkedin_score += 7
    linkedin_score = min(linkedin_score, 30)

    github_score = 0
    if github_url:
        github_score += 6
    if github_repos:
        github_score += min(12, len(github_repos) * 2)
    if pinned:
        github_score += min(6, len(pinned) * 2)
    if commits_90d > 0:
        github_score += min(6, max(1, commits_90d // 10))
    github_score = min(github_score, 30)

    resume_skill_set = set(verified_skills)
    linkedin_skill_set = set(linkedin_skills)
    overlap = len(resume_skill_set.intersection(linkedin_skill_set))
    consistency_score = 0
    if resume_skill_set:
        consistency_score += min(15, int((overlap / max(1, len(resume_skill_set))) * 15))

    timeline_signal = 5 if _extract_years(resume_text) is not None else 0
    role_signal = 5 if any(_safe_text(role).lower() in linkedin_headline.lower() for role in target_roles) else 0
    consistency_score += timeline_signal + role_signal
    consistency_score = min(consistency_score, 25)

    freshness_score = 0
    if commits_90d >= 30:
        freshness_score += 8
    elif commits_90d >= 10:
        freshness_score += 5
    elif commits_90d > 0:
        freshness_score += 2

    updated_repos = 0
    for repo in github_repos:
        updated = _safe_text((repo or {}).get("updated_at"))
        if updated:
            updated_repos += 1
    if updated_repos >= 3:
        freshness_score += 7
    elif updated_repos >= 1:
        freshness_score += 4

    freshness_score = min(freshness_score, 15)

    total_score = linkedin_score + github_score + consistency_score + freshness_score

    actions: list[str] = []
    if not linkedin_headline:
        actions.append("Add a role-focused LinkedIn headline with core stack keywords.")
    if not linkedin_about:
        actions.append("Write a concise LinkedIn About section with years, strengths, and measurable outcomes.")
    if len(linkedin_bullets) < 3:
        actions.append("Add at least 3 quantified impact bullets in LinkedIn experience.")
    if not github_url:
        actions.append("Add a GitHub profile URL to resume and LinkedIn.")
    if len(github_repos) < 3:
        actions.append("Create at least 3 public repositories aligned to target roles.")
    if len(pinned) < 2:
        actions.append("Pin 2-3 strongest repositories that demonstrate production-ready work.")
    if overlap < max(3, len(resume_skill_set) // 2):
        actions.append("Align LinkedIn skills with verified resume skills for consistency.")
    if commits_90d < 10:
        actions.append("Increase recent GitHub activity (10+ commits in 90 days) to improve freshness signal.")

    readiness_band = "high" if total_score >= 80 else "medium" if total_score >= 60 else "low"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scores": {
            "linkedin": linkedin_score,
            "github": github_score,
            "consistency": consistency_score,
            "freshness": freshness_score,
            "total": total_score,
            "readiness_band": readiness_band,
        },
        "signals": {
            "skills_overlap": overlap,
            "verified_skills_count": len(resume_skill_set),
            "github_repos_count": len(github_repos),
            "github_pinned_count": len(pinned),
            "github_commits_last_90_days": commits_90d,
            "preferred_locations": preferred_locations,
        },
        "priority_actions": actions[:10],
    }


def _generate_rule_based_guidance(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate") or {}
    linkedin = payload.get("linkedin") or {}

    full_name = _safe_text(candidate.get("full_name")) or "Candidate"
    target_roles = [x for x in (_safe_text(v) for v in _safe_list(candidate.get("target_roles"))) if x]
    skills = [x for x in (_safe_text(v) for v in _safe_list(candidate.get("verified_skills"))) if x]
    years = _extract_years(_safe_text(candidate.get("base_resume_text")))

    primary_role = target_roles[0] if target_roles else "Software Engineer"
    stack = ", ".join(skills[:4]) if skills else "backend engineering"

    headline = f"{primary_role} | {stack} | Building scalable, production-ready systems"

    about_lines = [
        f"{full_name} is a {primary_role} focused on delivering reliable software outcomes.",
        f"Core strengths include {stack}.",
    ]
    if years is not None:
        about_lines.insert(1, f"Brings {years}+ years of hands-on engineering experience.")
    about_lines.append("Open to roles where architecture quality, ownership, and measurable impact matter.")

    existing_bullets = [x for x in (_safe_text(v) for v in _safe_list(linkedin.get("experience_bullets"))) if x]
    rewritten_bullets: list[str] = []
    for idx, bullet in enumerate(existing_bullets[:5], start=1):
        rewritten_bullets.append(f"Delivered outcome {idx}: {bullet}")

    if not rewritten_bullets:
        rewritten_bullets = [
            "Designed and delivered services with strong API reliability and maintainability.",
            "Improved production stability by addressing performance bottlenecks and operational issues.",
            "Collaborated across teams to ship features aligned with client priorities and timelines.",
        ]

    github_readme_templates = [
        {
            "section": "Project Overview",
            "template": "Problem statement, users impacted, and why this project exists.",
        },
        {
            "section": "Architecture",
            "template": "High-level design, services/modules, and data flow diagram link.",
        },
        {
            "section": "Tech Stack",
            "template": "Languages, frameworks, infra, and tooling used.",
        },
        {
            "section": "Results",
            "template": "Performance, reliability, or business outcomes with numbers.",
        },
    ]

    return {
        "headline_suggestion": headline,
        "about_suggestion": " ".join(about_lines),
        "experience_bullets_suggestion": rewritten_bullets,
        "github_readme_templates": github_readme_templates,
        "recruiter_pitch": f"{primary_role} with strong experience in {stack}, ready to contribute quickly in production environments.",
    }


def _call_llama_guidance(prompt: str) -> dict[str, Any] | None:
    llama_url = _safe_text(os.getenv("LLAMA_API_URL"))
    if not llama_url:
        return None

    api_key = _safe_text(os.getenv("LLAMA_API_KEY"))
    body = json.dumps({"prompt": prompt, "max_tokens": 600}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = Request(llama_url, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    text = _safe_text(raw.get("text") or raw.get("output") or raw.get("response"))
    if not text:
        return None

    return {
        "llama_raw_response": text,
    }


def generate_profile_guidance(payload: dict[str, Any], use_llama: bool = False) -> dict[str, Any]:
    base = _generate_rule_based_guidance(payload)
    out: dict[str, Any] = {"mode": "rule-based", **base}

    if use_llama:
        prompt = (
            "You are a profile optimization assistant. Use only provided facts. "
            "Do not fabricate skills or achievements. Provide concise recruiter-facing improvements.\n\n"
            f"Input payload:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        llama = _call_llama_guidance(prompt)
        if llama:
            out["mode"] = "llama+rule-based"
            out.update(llama)

    return out
