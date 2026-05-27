from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from jobspy import scrape_jobs


EMPLOYMENT_SYNONYMS: dict[str, set[str]] = {
    "fulltime": {"fulltime", "full time", "full-time", "fte", "full time employee"},
    "contract": {
        "contract",
        "contractor",
        "temporary",
        "temp",
        "consultant",
        "consulting",
        "sow",
        "statement of work",
    },
}

WORK_MODE_SYNONYMS: dict[str, set[str]] = {
    "remote": {"remote", "work from home", "wfh"},
    "hybrid": {"hybrid"},
    "onsite": {"onsite", "on site", "on-site", "in office", "office-based"},
}

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
}

NON_US_LOCATION_HINTS = {
    "india", "canada", "mexico", "bangladesh", "pakistan", "uk", "united kingdom",
    "ireland", "germany", "france", "spain", "italy", "netherlands", "poland",
    "romania", "portugal", "sweden", "norway", "denmark", "finland", "belgium",
    "switzerland", "austria", "australia", "new zealand", "singapore", "japan",
    "south korea", "taiwan", "philippines", "vietnam", "thailand", "malaysia",
    "indonesia", "brazil", "argentina", "colombia", "chile", "peru", "uruguay",
    "uae", "united arab emirates", "saudi", "qatar", "egypt", "south africa",
}

IT_KEYWORDS = {
    "software", "developer", "engineer", "data", "analytics", "analyst", "python",
    "java", "javascript", "typescript", "react", "angular", "node", "backend",
    "front end", "frontend", "full stack", "fullstack", "cloud", "aws", "azure",
    "gcp", "devops", "sre", "site reliability", "cyber", "security", "infosec",
    "network", "systems", "it ", "information technology", "database", "sql",
    "machine learning", "ai", "artificial intelligence", "qa automation", "platform",
    "technical product", "solution architect", "enterprise architect",
}

PORTAL_TRUST_PRIORITY: dict[str, int] = {
    "usajobs": 1,
    "linkedin": 2,
    "indeed": 3,
    "dice": 4,
    "builtin": 5,
    "glassdoor": 6,
    "monster": 7,
    "simplyhired": 8,
    "careerbuilder": 9,
    "wellfound": 10,
    "hired": 11,
    "zip_recruiter": 12,
    "google": 13,
    "cybercoders": 14,
    "computerjobs": 15,
    "techfetch": 16,
    "hiringcafe": 17,
}


@dataclass
class JobSpyRunConfig:
    search_term: str
    location: str | None = None
    roles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    state: str | None = None
    sites: list[str] = field(default_factory=lambda: [
        "indeed",
        "linkedin",
        "zip_recruiter",
        "google",
        "dice",
        "usajobs",
        "builtin",
        "monster",
        "simplyhired",
        "careerbuilder",
        "hired",
        "wellfound",
        "hiringcafe",
        "cybercoders",
        "computerjobs",
        "techfetch",
    ])
    requested_sites: list[str] = field(default_factory=list)
    unsupported_sites: list[str] = field(default_factory=list)
    title_include: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    job_types: list[str] = field(default_factory=list)
    work_modes: list[str] = field(default_factory=list)
    results_wanted: int = 50
    hours_old: int | None = 72
    country_indeed: str = "usa"
    google_search_term: str | None = None
    is_remote: bool = False
    enforce_annual_salary: bool = True
    linkedin_fetch_description: bool = True
    description_format: str = "markdown"
    output_dir: str = "outputs"
    output_basename: str | None = None
    output_formats: list[str] = field(default_factory=lambda: ["csv", "jsonl"])
    keyword_weights: dict[str, float] = field(default_factory=dict)
    min_match_score: float | None = None
    enforce_usa_only: bool = True
    enforce_it_only: bool = True
    strict_usa_location: bool = True
    enforce_full_description: bool = True
    dedupe_to_trusted_portal: bool = True
    verbose: int = 1


REQUIRED_COLUMNS = [
    "site",
    "title",
    "company",
    "location",
    "job_url",
    "date_posted",
    "description",
]


def _slugify(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    text = value.lower().replace(" ", "-")
    return "".join(ch for ch in text if ch in allowed)[:80] or "jobspy"


def _ensure_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _normalize_role_variants(role: str) -> set[str]:
    role = _normalize_space(role)
    variants = {role}
    variants.add(role.replace("senior", "sr"))
    variants.add(role.replace("sr", "senior"))
    variants.add(role.replace("vice president", "vp"))
    variants.add(role.replace("vp", "vice president"))
    return {v.strip() for v in variants if v.strip()}


def _resolve_roles(config: JobSpyRunConfig) -> list[str]:
    roles = [r.strip() for r in config.roles if r and r.strip()]
    if roles:
        return roles
    if config.search_term and config.search_term.strip():
        return [config.search_term.strip()]
    return []


def _resolve_locations(config: JobSpyRunConfig) -> list[str | None]:
    locations = [l.strip() for l in config.locations if l and l.strip()]
    if locations:
        return locations
    if config.state and config.state.strip():
        return [config.state.strip()]
    if config.location and config.location.strip():
        return [config.location.strip()]
    return [None]


def _run_scrapes(config: JobSpyRunConfig, roles: list[str], locations: list[str | None]) -> pd.DataFrame:
    dataframes: list[pd.DataFrame] = []

    scrape_roles = roles or [config.search_term]
    scrape_locations = locations or [config.location]

    # If only remote roles are requested, let upstream boards pre-filter using is_remote.
    normalized_modes = {m.strip().lower() for m in config.work_modes if m and m.strip()}
    remote_only = normalized_modes == {"remote"}

    for role in scrape_roles:
        for location in scrape_locations:
            jobs = scrape_jobs(
                site_name=config.sites,
                search_term=role,
                google_search_term=config.google_search_term,
                location=location,
                results_wanted=config.results_wanted,
                hours_old=config.hours_old,
                country_indeed=config.country_indeed,
                is_remote=remote_only,
                description_format=config.description_format,
                linkedin_fetch_description=config.linkedin_fetch_description,
                enforce_annual_salary=config.enforce_annual_salary,
                verbose=config.verbose,
            )
            if not jobs.empty:
                jobs = jobs.copy()
                jobs["query_role"] = role
                jobs["query_location"] = location
                dataframes.append(jobs)

    if not dataframes:
        return pd.DataFrame()

    return pd.concat(dataframes, ignore_index=True)


def _normalize_jobs(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return _ensure_columns(df.copy(), REQUIRED_COLUMNS + ["match_score", "scraped_at"])

    normalized = df.copy()
    normalized = _ensure_columns(normalized, REQUIRED_COLUMNS)

    normalized["scraped_at"] = datetime.now(timezone.utc).isoformat()
    normalized["title"] = normalized["title"].fillna("").astype(str).str.strip()
    normalized["company"] = normalized["company"].fillna("").astype(str).str.strip()
    normalized["location"] = normalized["location"].fillna("").astype(str).str.strip()
    normalized["description"] = normalized["description"].fillna("").astype(str)

    # Deduplicate aggressively by canonical job URL, then fallback title/company/location.
    normalized["_dedupe_key"] = normalized["job_url"].fillna("").astype(str).str.strip()
    no_url_mask = normalized["_dedupe_key"].eq("")
    normalized.loc[no_url_mask, "_dedupe_key"] = (
        normalized["title"].str.lower()
        + "|"
        + normalized["company"].str.lower()
        + "|"
        + normalized["location"].str.lower()
    )
    normalized = normalized.drop_duplicates(subset=["_dedupe_key"], keep="first")
    normalized = normalized.drop(columns=["_dedupe_key"])

    return normalized.reset_index(drop=True)


def _is_usa_location(location_text: str) -> bool:
    location = _normalize_space(location_text)
    if not location:
        return False

    if (
        "united states" in location
        or " u.s. " in f" {location} "
        or " usa" in f" {location}"
        or location.endswith(" us")
    ):
        return True

    if any(term in location for term in NON_US_LOCATION_HINTS):
        return False

    state_code_match = re.search(r"(?:,|\s)([A-Z]{2})(?:\b|\s|$)", location_text)
    if state_code_match and state_code_match.group(1) in US_STATE_CODES:
        return True

    return any(state_name in location for state_name in US_STATE_NAMES)


def _is_strict_usa_location(location_text: str) -> bool:
    location = _normalize_space(location_text)
    if not location:
        return False

    # Reject known non-US signals first.
    if any(term in location for term in NON_US_LOCATION_HINTS):
        return False

    # Explicit country markers.
    if (
        "united states" in location
        or " usa" in f" {location}"
        or location.endswith(" us")
        or ", us" in location
    ):
        return True

    # Explicit US state code marker, commonly "City, FL".
    state_code_match = re.search(r"(?:,|\s)([A-Z]{2})(?:\b|\s|$)", location_text)
    if state_code_match and state_code_match.group(1) in US_STATE_CODES:
        return True

    # Explicit US state name marker.
    return any(state_name in location for state_name in US_STATE_NAMES)


def _filter_usa_only(df: pd.DataFrame, strict: bool = True) -> pd.DataFrame:
    if df.empty:
        return df

    locations = df["location"].fillna("").astype(str)
    checker = _is_strict_usa_location if strict else _is_usa_location
    mask = locations.apply(checker)
    return df[mask].reset_index(drop=True)


def _filter_it_jobs(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    combined_text = (
        df["title"].fillna("").astype(str)
        + " "
        + df["description"].fillna("").astype(str)
    ).str.lower()

    mask = combined_text.apply(lambda text: any(keyword in text for keyword in IT_KEYWORDS))
    return df[mask].reset_index(drop=True)


def _score_jobs(df: pd.DataFrame, keyword_weights: dict[str, float]) -> pd.DataFrame:
    scored = df.copy()
    if scored.empty:
        scored["match_score"] = []
        return scored

    if not keyword_weights:
        scored["match_score"] = 100.0
        return scored

    text_blob = (
        scored["title"].fillna("")
        + "\n"
        + scored["description"].fillna("")
        + "\n"
        + scored["company"].fillna("")
    ).str.lower()

    total_weight = sum(max(weight, 0.0) for weight in keyword_weights.values()) or 1.0

    score_series = pd.Series(0.0, index=scored.index)
    for keyword, weight in keyword_weights.items():
        if not keyword or weight <= 0:
            continue
        pattern = keyword.lower()
        score_series += text_blob.str.contains(pattern, regex=False).astype(float) * weight

    scored["match_score"] = ((score_series / total_weight) * 100.0).round(2)
    return scored.sort_values(by=["match_score", "date_posted"], ascending=[False, False], na_position="last")


def _canonical_employment_type(value: str) -> str:
    normalized = _normalize_space(value)
    for canonical, synonyms in EMPLOYMENT_SYNONYMS.items():
        if normalized == canonical or normalized in synonyms:
            return canonical
    return normalized


def _filter_job_types(df: pd.DataFrame, allowed_job_types: list[str]) -> pd.DataFrame:
    if df.empty or not allowed_job_types:
        return df

    allowed = {
        _canonical_employment_type(jt)
        for jt in allowed_job_types
        if jt and jt.strip()
    }
    if not allowed:
        return df

    if "job_type" not in df.columns:
        df = df.copy()
        df["job_type"] = ""

    combined_text = (
        df["job_type"].fillna("").astype(str)
        + " "
        + df["title"].fillna("").astype(str)
        + " "
        + df["description"].fillna("").astype(str)
    ).str.lower()

    def has_employment_match(text: str) -> bool:
        for allowed_type in allowed:
            synonyms = EMPLOYMENT_SYNONYMS.get(allowed_type, {allowed_type})
            if any(term in text for term in synonyms):
                return True
        return False

    mask = combined_text.apply(has_employment_match)
    return df[mask].reset_index(drop=True)


def _infer_work_mode(row: pd.Series) -> set[str]:
    modes: set[str] = set()
    text = " ".join(
        [
            str(row.get("title", "")),
            str(row.get("description", "")),
            str(row.get("location", "")),
        ]
    ).lower()

    if bool(row.get("is_remote", False)):
        modes.add("remote")

    for canonical, synonyms in WORK_MODE_SYNONYMS.items():
        if any(term in text for term in synonyms):
            modes.add(canonical)

    return modes


def _filter_work_modes(df: pd.DataFrame, requested_modes: list[str]) -> pd.DataFrame:
    if df.empty:
        return df

    requested = {mode.strip().lower() for mode in requested_modes if mode and mode.strip()}
    if not requested:
        return df

    allowed = {mode for mode in requested if mode in WORK_MODE_SYNONYMS}
    if not allowed:
        return df

    mask = df.apply(lambda row: bool(_infer_work_mode(row) & allowed), axis=1)
    return df[mask].reset_index(drop=True)


def _filter_title_rules(df: pd.DataFrame, include_terms: list[str], exclude_terms: list[str]) -> pd.DataFrame:
    if df.empty:
        return df

    title_series = df["title"].fillna("").astype(str).str.lower()

    include = [term.strip().lower() for term in include_terms if term and term.strip()]
    exclude = [term.strip().lower() for term in exclude_terms if term and term.strip()]

    include_mask = pd.Series(True, index=df.index)
    if include:
        include_mask = title_series.apply(lambda t: any(term in t for term in include))

    exclude_mask = pd.Series(False, index=df.index)
    if exclude:
        exclude_mask = title_series.apply(lambda t: any(term in t for term in exclude))

    return df[include_mask & ~exclude_mask].reset_index(drop=True)


def _filter_role_relevance(df: pd.DataFrame, roles: list[str]) -> pd.DataFrame:
    if df.empty or not roles:
        return df

    role_variants = [
        _normalize_role_variants(role)
        for role in roles
        if role and role.strip()
    ]
    role_variants = [variants for variants in role_variants if variants]
    if not role_variants:
        return df

    def row_role_score(row: pd.Series) -> float:
        title = _normalize_space(str(row.get("title", "")))
        description = _normalize_space(str(row.get("description", "")))

        best = 0.0
        for variants in role_variants:
            score = 0.0
            for variant in variants:
                if variant in title:
                    score += 0.75
                if variant in description:
                    score += 0.35

                words = [w for w in variant.split() if len(w) > 2]
                if words:
                    title_hits = sum(1 for w in words if w in title)
                    desc_hits = sum(1 for w in words if w in description)
                    score += (title_hits / len(words)) * 0.5
                    score += (desc_hits / len(words)) * 0.25

            if score > best:
                best = score
        return best

    scored = df.copy()
    scored["role_relevance_score"] = scored.apply(row_role_score, axis=1)
    filtered = scored[scored["role_relevance_score"] >= 0.75].copy()

    # Blend role relevance into match score pipeline while preserving existing behavior.
    if not filtered.empty:
        base_score = (
            filtered["match_score"].astype(float)
            if "match_score" in filtered.columns
            else pd.Series(100.0, index=filtered.index)
        )
        filtered["match_score"] = (
            base_score * 0.6
            + (filtered["role_relevance_score"] * 100.0) * 0.4
        ).round(2)

    return filtered.reset_index(drop=True)


def _has_meaningful_description(value: object) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass

    text = str(value).strip()
    if not text:
        return False
    if text.lower() in {"nan", "none", "null"}:
        return False

    # Require non-trivial job detail text to avoid summary-only rows.
    word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9+.#/-]*", text))
    return len(text) >= 160 or word_count >= 28


def _filter_full_description(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    descriptions = df["description"].fillna("").astype(str)
    mask = descriptions.apply(_has_meaningful_description)
    return df[mask].reset_index(drop=True)


def _normalize_dedupe_token(value: object) -> str:
    text = _normalize_space(str(value or ""))
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\b(sr|snr)\b", "senior", text)
    text = re.sub(r"\b(jr|jnr)\b", "junior", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_portal_fingerprint(row: pd.Series) -> str:
    title = _normalize_dedupe_token(row.get("title"))
    company = _normalize_dedupe_token(row.get("company"))
    location = _normalize_dedupe_token(row.get("location"))

    if title and company and location:
        return f"{title}|{company}|{location}"
    if title and company:
        return f"{title}|{company}"
    if title and location:
        return f"{title}|{location}"
    if title:
        return f"title:{title}"

    raw_url = str(row.get("job_url") or "").strip().lower()
    if raw_url:
        return raw_url.split("?", 1)[0]

    return ""


def _dedupe_to_trusted_portal(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    deduped = df.copy()
    deduped["_site_rank"] = (
        deduped["site"].fillna("").astype(str).str.lower().map(PORTAL_TRUST_PRIORITY).fillna(999).astype(int)
    )
    deduped["_desc_len"] = deduped["description"].fillna("").astype(str).str.len()
    deduped["_score"] = pd.to_numeric(deduped.get("match_score", 0), errors="coerce").fillna(0.0)
    deduped["_portal_fp"] = deduped.apply(_build_portal_fingerprint, axis=1)

    deduped = deduped.sort_values(
        by=["_portal_fp", "_site_rank", "_desc_len", "_score"],
        ascending=[True, True, False, False],
        na_position="last",
    )

    known_fp_mask = deduped["_portal_fp"].astype(str).str.strip().ne("")
    with_fp = deduped[known_fp_mask].drop_duplicates(subset=["_portal_fp"], keep="first")
    without_fp = deduped[~known_fp_mask]
    deduped = pd.concat([with_fp, without_fp], ignore_index=True)

    return deduped.drop(columns=["_site_rank", "_desc_len", "_score", "_portal_fp"]).reset_index(drop=True)


def _default_basename(config: JobSpyRunConfig) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"jobspy_{_slugify(config.search_term)}_{stamp}"


def _format_salary_or_hourly_price(row: pd.Series) -> str:
    min_amount = row.get("min_amount")
    max_amount = row.get("max_amount")
    interval = str(row.get("interval") or "").strip().lower()
    currency = str(row.get("currency") or "USD").strip().upper()

    if min_amount in (None, "") and max_amount in (None, ""):
        return ""

    try:
        min_value = float(min_amount) if min_amount not in (None, "") else None
        max_value = float(max_amount) if max_amount not in (None, "") else None
    except (TypeError, ValueError):
        return ""

    suffix = {
        "hourly": "/hr",
        "yearly": "/yr",
        "monthly": "/mo",
        "weekly": "/wk",
        "daily": "/day",
    }.get(interval, "")

    if min_value is not None and max_value is not None:
        return f"{currency} {min_value:,.0f} - {max_value:,.0f}{suffix}".strip()
    if min_value is not None:
        return f"{currency} {min_value:,.0f}{suffix}".strip()
    return f"{currency} {max_value:,.0f}{suffix}".strip()


def _infer_immigration_status(text: str) -> str:
    normalized = _normalize_space(text)
    if not normalized:
        return "Not specified"

    if any(term in normalized for term in [
        "usc", "u.s. citizen", "us citizen", "citizens only", "must be a us citizen", "clearance required",
    ]):
        return "US Citizen Required"

    if any(term in normalized for term in [
        "no sponsorship", "unable to sponsor", "cannot sponsor", "will not sponsor",
    ]):
        return "No Sponsorship"

    if any(term in normalized for term in [
        "h1b", "h-1b", "opt", "cpt", "ead", "green card", "visa sponsorship", "sponsorship available",
    ]):
        return "Sponsorship/Work Visa Mentioned"

    return "Not specified"


def _normalize_export_job_type(value: str) -> str:
    normalized = _normalize_space(value)
    if not normalized:
        return "Unknown"

    if any(term in normalized for term in ["fulltime", "full time", "full-time", "fte"]):
        return "Full-time"
    if any(term in normalized for term in ["parttime", "part time", "part-time"]):
        return "Part-time"
    if any(term in normalized for term in ["contract", "contractor", "consultant", "consulting", "sow"]):
        return "Contract"
    if any(term in normalized for term in ["temporary", "temp"]):
        return "Temporary"
    if "intern" in normalized:
        return "Internship"

    return value.strip() if isinstance(value, str) and value.strip() else "Unknown"


def _infer_export_job_type_from_text(text: str) -> str:
    normalized = _normalize_space(text)
    if not normalized:
        return "Unknown"

    if any(term in normalized for term in ["part-time", "part time", "parttime"]):
        return "Part-time"

    if any(
        term in normalized
        for term in [
            "contract-to-hire",
            "contract to hire",
            "contract",
            "contractor",
            "consultant",
            "consulting",
            "c2c",
            "corp-to-corp",
            "corp to corp",
            "1099",
            "w2 contract",
        ]
    ):
        return "Contract"

    if any(term in normalized for term in ["temporary", "temp ", "temp-to-hire", "temp to hire", "seasonal"]):
        return "Temporary"

    if any(term in normalized for term in ["intern", "internship", "co-op", "co op"]):
        return "Internship"

    if any(term in normalized for term in ["full-time", "full time", "fulltime", "fte", "permanent"]):
        return "Full-time"

    return "Unknown"


def _extract_text_snippets_by_keywords(text: str, keywords: set[str], max_items: int = 3) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []

    chunks = _extract_lines(normalized)
    if not chunks:
        chunks = _sentence_split(normalized)

    hits: list[str] = []
    for chunk in chunks:
        lower = chunk.lower()
        if any(keyword in lower for keyword in keywords):
            compact = re.sub(r"\s+", " ", chunk).strip()
            if len(compact) > 220:
                compact = compact[:217].rstrip() + "..."
            if compact and compact not in hits:
                hits.append(compact)
        if len(hits) >= max_items:
            break

    return hits


def _extract_work_mode_from_text(text: str) -> str:
    normalized = _normalize_space(text)
    if not normalized:
        return "Not specified"

    modes: list[str] = []
    if any(term in normalized for term in ["remote", "work from home", "wfh"]):
        modes.append("Remote")
    if "hybrid" in normalized:
        modes.append("Hybrid")
    if any(term in normalized for term in ["onsite", "on-site", "on site", "in office", "in-office"]):
        modes.append("Onsite")

    return ", ".join(modes) if modes else "Not specified"


def _extract_visa_details(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return "Not specified"

    patterns = [
        r"\bvisa\b",
        r"\bsponsor(?:ship|ed|ing)?\b",
        r"\bh-?1b\b",
        r"\bopt\b",
        r"\bcpt\b",
        r"\bead\b",
        r"\bgreen\s+card\b",
        r"\bwork\s+authori[sz]ation\b",
        r"\bu\.?s\.?\s+citizen\b",
        r"\bcitizens?(?:hip)?\b",
    ]

    chunks = _extract_lines(normalized)
    if not chunks:
        chunks = _sentence_split(normalized)

    hits: list[str] = []
    for chunk in chunks:
        lower = chunk.lower()
        if any(re.search(pattern, lower) for pattern in patterns):
            compact = re.sub(r"\s+", " ", chunk).strip()
            if len(compact) > 220:
                compact = compact[:217].rstrip() + "..."
            if compact and compact not in hits:
                hits.append(compact)
        if len(hits) >= 2:
            break

    return " | ".join(hits) if hits else "Not specified"


def _extract_compensation_details(text: str) -> str:
    normalized = str(text or "")
    if not normalized.strip():
        return "Not specified"

    details: list[str] = []

    # Typical salary/hourly ranges and values.
    range_pattern = re.compile(
        r"(?i)(?:usd\s*)?\$\s?\d[\d,]*(?:\.\d+)?\s*(?:-|to)\s*(?:usd\s*)?\$\s?\d[\d,]*(?:\.\d+)?\s*(?:/\s?(?:hr|hour|year|yr|annum))?"
    )
    single_pattern = re.compile(
        r"(?i)(?:usd\s*)?\$\s?\d[\d,]*(?:\.\d+)?\s*(?:/\s?(?:hr|hour|year|yr|annum))"
    )

    for match in range_pattern.findall(normalized):
        item = re.sub(r"\s+", " ", str(match)).strip()
        if item and item not in details:
            details.append(item)
        if len(details) >= 3:
            break

    if len(details) < 3:
        for match in single_pattern.findall(normalized):
            item = re.sub(r"\s+", " ", str(match)).strip()
            if item and item not in details:
                details.append(item)
            if len(details) >= 3:
                break

    if not details:
        comp_hints = {
            "salary",
            "hourly",
            "per hour",
            "per annum",
            "compensation",
            "pay range",
            "w2",
            "1099",
            "rate",
        }
        details = _extract_text_snippets_by_keywords(normalized, comp_hints, max_items=2)

    return " | ".join(details) if details else "Not specified"


def _extract_location_details(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return "Not specified"

    mode_hints = {
        "remote",
        "hybrid",
        "onsite",
        "on-site",
        "on site",
        "in office",
        "in-office",
        "relocation",
        "travel",
        "work from home",
    }
    hits = _extract_text_snippets_by_keywords(normalized, mode_hints, max_items=2)

    city_state_matches = re.findall(r"\b([A-Z][A-Za-z .'-]+,\s*[A-Z]{2})\b", normalized)
    unique_locations: list[str] = []
    for match in city_state_matches:
        cleaned = re.sub(r"\s+", " ", match).strip()
        if cleaned and cleaned not in unique_locations:
            unique_locations.append(cleaned)
        if len(unique_locations) >= 3:
            break

    if unique_locations:
        hits.append("Locations mentioned: " + ", ".join(unique_locations))

    if not hits:
        return "Not specified"

    deduped_hits: list[str] = []
    for item in hits:
        if item not in deduped_hits:
            deduped_hits.append(item)
    return " | ".join(deduped_hits[:3])


def _build_complete_jd(row: pd.Series) -> str:
    parts: list[str] = []

    def _safe_text(value: object) -> str:
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
        text = str(value).strip()
        if text.lower() in {"nan", "none", "null"}:
            return ""
        return text

    description = _safe_text(row.get("description"))
    if description:
        parts.append(description)

    company_description = _safe_text(row.get("company_description"))
    if company_description and company_description.lower() not in description.lower():
        parts.append(f"Company Description: {company_description}")

    skills = _safe_text(row.get("skills"))
    if skills:
        parts.append(f"Skills: {skills}")

    experience_range = _safe_text(row.get("experience_range"))
    if experience_range:
        parts.append(f"Experience: {experience_range}")

    listing_type = _safe_text(row.get("listing_type"))
    if listing_type:
        parts.append(f"Listing Type: {listing_type}")

    combined = "\n\n".join([p for p in parts if p])
    return combined.strip()


def _sentence_split(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]


def _extract_lines(text: str) -> list[str]:
    if not text:
        return []

    # Convert common bullet styles and separators into line breaks.
    normalized = text.replace("\r\n", "\n")
    normalized = re.sub(r"\s*[\u2022\u25CF\-\*]\s+", "\n- ", normalized)
    normalized = normalized.replace(";", "\n")
    lines = [re.sub(r"\s+", " ", line).strip(" -\t") for line in normalized.split("\n")]
    return [line for line in lines if line]


def _build_structured_jd(row: pd.Series) -> str:
    full_text = _build_complete_jd(row)
    title_text = str(row.get("title") or "").strip()
    if not full_text:
        fallback_summary = title_text or "Role details were not provided by the source."
        return (
            f"Role Summary:\n{fallback_summary}\n\n"
            "Roles and Responsibilities:\n"
            "- Responsibilities not explicitly listed by source\n\n"
            "Required Skills:\n"
            "- Skills not explicitly listed by source"
        )

    sentences = _sentence_split(full_text)
    lines = _extract_lines(full_text)

    summary = " ".join(sentences[:2]).strip()
    if not summary and lines:
        summary = lines[0]
    if not summary:
        summary = title_text or "Role details were not provided by the source."

    responsibility_hints = {
        "responsibil", "dutie", "you will", "candidate will", "will be", "own", "lead", "design", "develop", "implement", "maintain",
    }
    skills_hints = {
        "required", "must have", "qualification", "experience", "proficien", "skill", "knowledge", "java", "python", "aws", "sql", "react",
        "typescript", "node", "spring", "microservices", "cloud", "devops", "security",
    }

    responsibilities: list[str] = []
    required_skills: list[str] = []

    for line in lines:
        lower = line.lower()
        if any(hint in lower for hint in responsibility_hints):
            if line not in responsibilities:
                responsibilities.append(line)
        if any(hint in lower for hint in skills_hints):
            if line not in required_skills:
                required_skills.append(line)

    if not responsibilities:
        responsibilities = [s for s in sentences[2:6] if s][:4]

    raw_skills = str(row.get("skills") or "").strip()
    if raw_skills:
        for skill in [s.strip() for s in raw_skills.split(",") if s.strip()]:
            if skill not in required_skills:
                required_skills.append(skill)

    if not required_skills:
        required_skills = [s for s in sentences[6:10] if s][:4]

    sections: list[str] = []
    if summary:
        sections.append(f"Role Summary:\n{summary}")

    if responsibilities:
        resp_text = "\n".join([f"- {item}" for item in responsibilities[:8]])
        sections.append(f"Roles and Responsibilities:\n{resp_text}")

    if required_skills:
        skills_text = "\n".join([f"- {item}" for item in required_skills[:12]])
        sections.append(f"Required Skills:\n{skills_text}")

    return "\n\n".join(sections).strip()


def _build_user_facing_export(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "Title",
                "Job Location",
                "Job Type",
                "Salary or Hourly Price",
                "Immigration Status",
                "Work Mode (Extracted)",
                "Visa / Sponsorship (Extracted)",
                "Compensation Details (Extracted)",
                "Location Details (Extracted)",
                "Portal",
                "Job Description Version 1",
                "Job Description Version 2",
                "Job Description",
            ]
        )

    prepared = _ensure_columns(
        df.copy(),
        [
            "title",
            "location",
            "job_type",
            "description",
            "site",
            "company_description",
            "skills",
            "experience_range",
            "listing_type",
            "min_amount",
            "max_amount",
            "interval",
            "currency",
        ],
    )

    complete_jd_v1_raw = prepared.apply(_build_complete_jd, axis=1)
    complete_jd_v1 = complete_jd_v1_raw.where(
        complete_jd_v1_raw.astype(str).str.strip().ne(""),
        prepared["title"].fillna("").astype(str).str.strip().where(
            prepared["title"].fillna("").astype(str).str.strip().ne(""),
            "Role details were not provided by the source.",
        ),
    )
    complete_jd_v2 = prepared.apply(_build_structured_jd, axis=1)

    normalized_job_type = prepared["job_type"].fillna("").astype(str).apply(_normalize_export_job_type)
    inferred_job_type = (
        prepared["title"].fillna("").astype(str)
        + " "
        + complete_jd_v2
    ).apply(_infer_export_job_type_from_text)
    final_job_type = normalized_job_type.where(normalized_job_type.ne("Unknown"), inferred_job_type)

    user_df = pd.DataFrame(
        {
            "Title": prepared["title"].fillna("").astype(str).str.strip(),
            "Job Location": prepared["location"].fillna("").astype(str).str.strip(),
            "Job Type": final_job_type,
            "Salary or Hourly Price": prepared.apply(_format_salary_or_hourly_price, axis=1),
            "Immigration Status": complete_jd_v1.apply(_infer_immigration_status),
            "Work Mode (Extracted)": complete_jd_v1.apply(_extract_work_mode_from_text),
            "Visa / Sponsorship (Extracted)": complete_jd_v1.apply(_extract_visa_details),
            "Compensation Details (Extracted)": complete_jd_v1.apply(_extract_compensation_details),
            "Location Details (Extracted)": complete_jd_v1.apply(_extract_location_details),
            "Portal": prepared["site"].fillna("").astype(str).str.strip(),
            "Job Description Version 1": complete_jd_v1,
            "Job Description Version 2": complete_jd_v2,
            "Job Description": complete_jd_v2,
        }
    )

    return user_df


def _export_jobs(df: pd.DataFrame, output_dir: Path, basename: str, formats: list[str]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, str] = {}
    selected = {fmt.strip().lower() for fmt in formats if fmt and fmt.strip()}

    if "csv" in selected:
        csv_path = output_dir / f"{basename}.csv"
        df.to_csv(csv_path, index=False)
        artifacts["csv"] = str(csv_path)

    if "jsonl" in selected:
        jsonl_path = output_dir / f"{basename}.jsonl"
        df.to_json(jsonl_path, orient="records", lines=True, force_ascii=False)
        artifacts["jsonl"] = str(jsonl_path)

    if "json" in selected:
        json_path = output_dir / f"{basename}.json"
        df.to_json(json_path, orient="records", indent=2, force_ascii=False)
        artifacts["json"] = str(json_path)

    if "xlsx" in selected:
        xlsx_path = output_dir / f"{basename}.xlsx"
        df.to_excel(xlsx_path, index=False)
        artifacts["xlsx"] = str(xlsx_path)

    return artifacts


def run_jobspy_pipeline(config: JobSpyRunConfig) -> tuple[pd.DataFrame, dict[str, int | str | float | None]]:
    roles = _resolve_roles(config)
    locations = _resolve_locations(config)

    jobs = _run_scrapes(config, roles, locations)

    normalized = _normalize_jobs(jobs)
    usa_filtered = _filter_usa_only(normalized, strict=config.strict_usa_location) if config.enforce_usa_only else normalized
    it_filtered = _filter_it_jobs(usa_filtered) if config.enforce_it_only else usa_filtered
    role_filtered = _filter_role_relevance(it_filtered, roles)
    title_filtered = _filter_title_rules(role_filtered, config.title_include, config.title_exclude)
    full_description_filtered = _filter_full_description(title_filtered) if config.enforce_full_description else title_filtered
    job_type_filtered = _filter_job_types(full_description_filtered, config.job_types)
    mode_filtered = _filter_work_modes(job_type_filtered, config.work_modes)
    scored = _score_jobs(mode_filtered, config.keyword_weights)

    if "role_relevance_score" in scored.columns:
        scored["match_score"] = (
            scored["match_score"].astype(float) * 0.7
            + (scored["role_relevance_score"].astype(float) * 100.0) * 0.3
        ).round(2)
        scored = scored.sort_values(by=["match_score", "date_posted"], ascending=[False, False], na_position="last")

    if config.min_match_score is not None:
        scored = scored[scored["match_score"] >= config.min_match_score].reset_index(drop=True)

    trusted_portal_deduped = _dedupe_to_trusted_portal(scored) if config.dedupe_to_trusted_portal else scored

    metrics: dict[str, int | str | float | None] = {
        "search_term": config.search_term,
        "location": config.location,
        "roles": ",".join(roles),
        "locations": ",".join([loc for loc in locations if loc]) if any(locations) else None,
        "state": config.state,
        "sites": len(config.sites),
        "requested_sites": ",".join(config.requested_sites) if config.requested_sites else None,
        "active_sites": ",".join(config.sites) if config.sites else None,
        "unsupported_sites": ",".join(config.unsupported_sites) if config.unsupported_sites else None,
        "title_include": ",".join(config.title_include) if config.title_include else None,
        "title_exclude": ",".join(config.title_exclude) if config.title_exclude else None,
        "job_types": ",".join(config.job_types) if config.job_types else "all",
        "work_modes": ",".join(config.work_modes) if config.work_modes else "all",
        "raw_jobs": int(len(jobs)),
        "normalized_jobs": int(len(normalized)),
        "usa_filtered_jobs": int(len(usa_filtered)),
        "it_filtered_jobs": int(len(it_filtered)),
        "role_filtered_jobs": int(len(role_filtered)),
        "title_filtered_jobs": int(len(title_filtered)),
        "full_description_filtered_jobs": int(len(full_description_filtered)),
        "job_type_filtered_jobs": int(len(job_type_filtered)),
        "work_mode_filtered_jobs": int(len(mode_filtered)),
        "trusted_portal_deduped_jobs": int(len(trusted_portal_deduped)),
        "final_jobs": int(len(trusted_portal_deduped)),
        "min_match_score": config.min_match_score,
        "enforce_usa_only": str(config.enforce_usa_only).lower(),
        "enforce_it_only": str(config.enforce_it_only).lower(),
        "strict_usa_location": str(config.strict_usa_location).lower(),
        "enforce_full_description": str(config.enforce_full_description).lower(),
        "dedupe_to_trusted_portal": str(config.dedupe_to_trusted_portal).lower(),
    }
    return trusted_portal_deduped, metrics


def run_and_export(config: JobSpyRunConfig) -> dict[str, object]:
    df, metrics = run_jobspy_pipeline(config)
    output_dir = Path(config.output_dir)
    basename = config.output_basename or _default_basename(config)
    export_df = _build_user_facing_export(df)
    artifacts = _export_jobs(export_df, output_dir, basename, config.output_formats)

    return {
        "metrics": metrics,
        "artifacts": artifacts,
        "rows": len(export_df),
        "basename": basename,
    }
