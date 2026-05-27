from __future__ import annotations

import argparse
import json
import re
from typing import Any

from jobspy.e2e import JobSpyRunConfig, run_and_export


SUPPORTED_SITES = {
    "indeed",
    "linkedin",
    "zip_recruiter",
    "glassdoor",
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
    "bayt",
    "naukri",
    "bdjobs",
}

SITE_ALIASES = {
    "indeed": "indeed",
    "indeed.com": "indeed",
    "linkedin": "linkedin",
    "linkedin.com": "linkedin",
    "zip_recruiter": "zip_recruiter",
    "zip_recruitor": "zip_recruiter",
    "ziprecruiter": "zip_recruiter",
    "ziprecruiter.com": "zip_recruiter",
    "glassdoor": "glassdoor",
    "glassdoor.com": "glassdoor",
    "google": "google",
    "google.com": "google",
    "google.com/search": "google",
    "google.com/search?q=jobs": "google",
    "dice": "dice",
    "dice.com": "dice",
    "dice.com/jobs": "dice",
    "usajobs": "usajobs",
    "usajobs.gov": "usajobs",
    "builtin": "builtin",
    "builtin.com": "builtin",
    "builtin.com/jobs": "builtin",
    "monster": "monster",
    "monster.com": "monster",
    "monster.com/jobs": "monster",
    "simplyhired": "simplyhired",
    "simplyhired.com": "simplyhired",
    "careerbuilder": "careerbuilder",
    "careerbuilder.com": "careerbuilder",
    "careerbuilder.com/jobs": "careerbuilder",
    "hired": "hired",
    "hired.com": "hired",
    "wellfound": "wellfound",
    "wellfound.com": "wellfound",
    "hiringcafe": "hiringcafe",
    "hiringcafe.com": "hiringcafe",
    "cybercoders": "cybercoders",
    "cybercoders.com": "cybercoders",
    "computerjobs": "computerjobs",
    "computerjobs.com": "computerjobs",
    "techfetch": "techfetch",
    "techfetch.com": "techfetch",
    "bayt": "bayt",
    "bayt.com": "bayt",
    "naukri": "naukri",
    "naukri.com": "naukri",
    "bdjobs": "bdjobs",
    "bdjobs.com": "bdjobs",
}


def _tokenize_values(value: str | None) -> list[str]:
    if not value:
        return []
    return [token.strip() for token in re.split(r"[\n,]+", value) if token.strip()]


def _normalize_site_token(token: str) -> str:
    normalized = token.strip().lower()
    normalized = normalized.replace("https://", "").replace("http://", "")
    normalized = normalized.split("/")[0] if "/" in normalized and "search?q=jobs" not in token.lower() else normalized
    normalized = normalized.replace("www.", "")
    normalized = normalized.replace(" ", "")
    return normalized


def _parse_sites(value: str | None) -> tuple[list[str], list[str], list[str]]:
    if not value:
        defaults = [
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
        ]
        return defaults, [], defaults

    requested_tokens = _tokenize_values(value)
    active_sites: list[str] = []
    unsupported_sites: list[str] = []

    for token in requested_tokens:
        normalized = _normalize_site_token(token)
        canonical = SITE_ALIASES.get(normalized)

        if canonical and canonical in SUPPORTED_SITES:
            if canonical not in active_sites:
                active_sites.append(canonical)
            continue

        if normalized in SUPPORTED_SITES:
            if normalized not in active_sites:
                active_sites.append(normalized)
            continue

        if token not in unsupported_sites:
            unsupported_sites.append(token)

    if not active_sites:
        active_sites = [
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
        ]

    return active_sites, unsupported_sites, requested_tokens


def _parse_csv(value: str | None) -> list[str]:
    return _tokenize_values(value)


def _parse_job_types(value: str | None) -> list[str]:
    if not value:
        return []

    parsed = [job_type.strip().lower() for job_type in value.split(",") if job_type.strip()]
    if not parsed:
        return []

    if "all" in parsed or "any" in parsed:
        return []

    return parsed


def _parse_keywords(value: str | None) -> dict[str, float]:
    if not value:
        return {}

    # Format: "python:3,aws:2,react:1"
    parsed: dict[str, float] = {}
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue

        if ":" in token:
            key, raw_weight = token.split(":", 1)
            key = key.strip()
            try:
                parsed[key] = float(raw_weight.strip())
            except ValueError as exc:
                raise ValueError(f"Invalid keyword weight '{token}'. Expected keyword:weight") from exc
        else:
            parsed[token] = 1.0

    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobspy-e2e",
        description="End-to-end JobSpy pipeline runner (scrape -> normalize -> score -> export)",
    )

    parser.add_argument("--search-term", required=True, help="Primary search query")
    parser.add_argument("--roles", default=None, help="Comma-separated role queries (e.g. Sr Director,Senior Director)")
    parser.add_argument("--location", default=None, help="Search location (city, state, country)")
    parser.add_argument("--locations", default=None, help="Comma-separated locations (city/state/country)")
    parser.add_argument("--state", default=None, help="State-level search value (used when locations are not provided)")
    parser.add_argument("--google-search-term", default=None, help="Specialized Google Jobs query")
    parser.add_argument("--sites", default="indeed,linkedin,zip_recruiter,google,dice,usajobs,builtin,monster,simplyhired,careerbuilder,hired,wellfound,hiringcafe,cybercoders,computerjobs,techfetch", help="Comma/newline-separated site list. Supported: indeed, linkedin, zip_recruiter, glassdoor, google, dice, usajobs, builtin, monster, simplyhired, careerbuilder, hired, wellfound, hiringcafe, cybercoders, computerjobs, techfetch, bayt, naukri, bdjobs")
    parser.add_argument("--title-include", default=None, help="Comma-separated terms that must appear in title")
    parser.add_argument("--title-exclude", default=None, help="Comma-separated terms to remove from title")
    parser.add_argument("--job-types", default="all", help="Employment filters. Use 'all' to disable filtering, or pass comma-separated types like fulltime,contract,temporary,part time")
    parser.add_argument("--work-modes", default=None, help="Comma-separated work modes: remote,hybrid,onsite")
    parser.add_argument("--results", type=int, default=50, help="Results per site")
    parser.add_argument("--hours-old", type=int, default=72, help="Limit by recency in hours")
    parser.add_argument("--country-indeed", default="usa", help="Indeed/Glassdoor country (USA enforced by pipeline)")
    parser.add_argument("--remote", action="store_true", help="Enable remote filter")
    parser.add_argument("--linkedin-fetch-description", action="store_true", help="Fetch full LinkedIn description (enabled by default)")
    parser.add_argument("--description-format", default="markdown", choices=["markdown", "html", "plain"], help="Description format")
    parser.add_argument("--output-dir", default="outputs", help="Output directory")
    parser.add_argument("--output-basename", default=None, help="Base file name for outputs")
    parser.add_argument("--formats", default="csv,jsonl", help="Comma-separated output formats: csv,jsonl,json,xlsx")
    parser.add_argument("--keywords", default=None, help="Optional keyword weights, e.g. python:3,aws:2,react:1")
    parser.add_argument("--min-match-score", type=float, default=None, help="Drop rows below this score")
    parser.add_argument("--verbose", type=int, default=1, choices=[0, 1, 2], help="JobSpy verbosity")

    return parser


def run_from_args(args: argparse.Namespace) -> dict[str, Any]:
    active_sites, unsupported_sites, requested_sites = _parse_sites(args.sites)

    config = JobSpyRunConfig(
        search_term=args.search_term,
        roles=_parse_csv(args.roles),
        location=args.location,
        locations=_parse_csv(args.locations),
        state=args.state,
        sites=active_sites,
        requested_sites=requested_sites,
        unsupported_sites=unsupported_sites,
        title_include=_parse_csv(args.title_include),
        title_exclude=_parse_csv(args.title_exclude),
        job_types=_parse_job_types(args.job_types),
        work_modes=[mode.lower() for mode in _parse_csv(args.work_modes)],
        results_wanted=args.results,
        hours_old=args.hours_old,
        country_indeed="usa",
        google_search_term=args.google_search_term,
        is_remote=args.remote,
        linkedin_fetch_description=True,
        description_format=args.description_format,
        output_dir=args.output_dir,
        output_basename=args.output_basename,
        output_formats=[fmt.strip() for fmt in args.formats.split(",") if fmt.strip()],
        keyword_weights=_parse_keywords(args.keywords),
        min_match_score=args.min_match_score,
        enforce_usa_only=True,
        enforce_it_only=True,
        strict_usa_location=True,
        verbose=args.verbose,
    )
    return run_and_export(config)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = run_from_args(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
