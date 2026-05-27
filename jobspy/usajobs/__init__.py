from __future__ import annotations

import re
import json
from datetime import datetime
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from jobspy.model import JobPost, JobResponse, JobType, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger, create_session, extract_emails_from_text

log = create_logger("USAJobs")


def _extract_date_from_text(text: str):
    # Common USAJobs date format examples: 05/20/2026, 5/2/2026
    match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", text)
    if not match:
        return None

    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date()
    except ValueError:
        return None


def _infer_job_types(text: str) -> list[JobType] | None:
    text = text.lower()
    mapped: list[JobType] = []

    if "full time" in text or "full-time" in text:
        mapped.append(JobType.FULL_TIME)
    if "part time" in text or "part-time" in text:
        mapped.append(JobType.PART_TIME)
    if "contract" in text:
        mapped.append(JobType.CONTRACT)
    if "temporary" in text or "temp " in text:
        mapped.append(JobType.TEMPORARY)
    if "intern" in text:
        mapped.append(JobType.INTERNSHIP)

    return mapped if mapped else None


def _extract_json_objects(blob: str) -> list[dict]:
    """Best-effort extraction of JSON object literals embedded in script tags."""
    objects: list[dict] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(blob):
        if blob[idx] != "{":
            idx += 1
            continue
        try:
            obj, consumed = decoder.raw_decode(blob[idx:])
            if isinstance(obj, dict):
                objects.append(obj)
            idx += consumed
        except Exception:
            idx += 1
    return objects


class USAJobs(Scraper):
    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None, user_agent: str | None = None):
        super().__init__(Site.USAJOBS, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)
        self.base_url = "https://www.usajobs.gov"
        self.search_url = "https://www.usajobs.gov/Search/Results/"
        self.session = create_session(proxies=self.proxies, ca_cert=ca_cert, is_tls=False, has_retry=True)
        self.seen_urls: set[str] = set()

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        # Legal/no-key mode: scrape only publicly accessible USAJobs search pages.
        target_count = scraper_input.results_wanted + scraper_input.offset
        max_pages = max(1, min(10, (target_count // 25) + 1))

        jobs: list[JobPost] = []

        for page in range(1, max_pages + 1):
            params = {
                "k": scraper_input.search_term or "",
                "l": scraper_input.location or "",
                "p": page,
            }

            url = f"{self.search_url}?{urlencode(params)}"

            try:
                response = self.session.get(url, timeout=scraper_input.request_timeout)
            except Exception as exc:
                log.warning(f"USAJobs request failed on page {page}: {exc}")
                break

            if not response.ok:
                log.warning(f"USAJobs response status code {response.status_code}")
                break

            page_jobs = self._parse_search_page(response.text)
            if not page_jobs:
                # Dynamic content can yield empty HTML for bot-like clients.
                if page == 1:
                    log.warning("USAJobs search page returned no parseable job cards in no-key mode.")
                break

            jobs.extend(page_jobs)
            if len(self.seen_urls) >= target_count:
                break

        sliced = jobs[scraper_input.offset : scraper_input.offset + scraper_input.results_wanted]
        return JobResponse(jobs=sliced)

    def _parse_search_page(self, html: str) -> list[JobPost]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[JobPost] = []

        # Parse all anchor tags and keep only likely job detail links.
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue

            href_lower = href.lower()
            if "/job/" not in href_lower and "/getjob/viewdetails/" not in href_lower:
                continue

            job_url = urljoin(self.base_url, href)
            if job_url in self.seen_urls:
                continue

            title = anchor.get_text(" ", strip=True) or str(anchor.get("aria-label", "")).strip()
            if not title or len(title) < 3:
                continue

            card = anchor.find_parent(["article", "li", "div"])
            card_text = card.get_text(" ", strip=True) if card else title
            card_text = re.sub(r"\s+", " ", card_text).strip()

            remote = "remote" in card_text.lower() or "telework" in card_text.lower()
            date_posted = _extract_date_from_text(card_text)
            job_types = _infer_job_types(card_text)

            # Keep US-only marker directly on parsed jobs; e2e also enforces US-only globally.
            location = Location(country="USA")

            jobs.append(
                JobPost(
                    id=f"usajobs-{abs(hash(job_url))}",
                    title=title,
                    company_name=None,
                    job_url=job_url,
                    location=location,
                    description=card_text,
                    date_posted=date_posted,
                    is_remote=remote,
                    emails=extract_emails_from_text(card_text),
                    job_type=job_types,
                )
            )
            self.seen_urls.add(job_url)

        if jobs:
            return jobs

        # Fallback: attempt to parse embedded JSON/script payloads from dynamic pages.
        scripts = [script.get_text(" ", strip=True) for script in soup.find_all("script") if script.get_text(strip=True)]
        script_blob = "\n".join(scripts)

        # Extract direct pairs when embedded in JS literals.
        direct_pairs = re.findall(
            r'"PositionTitle"\s*:\s*"([^\"]+)".*?"PositionURI"\s*:\s*"([^\"]+)"',
            script_blob,
            flags=re.IGNORECASE,
        )
        for raw_title, raw_url in direct_pairs:
            title = raw_title.encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore").strip()
            job_url = raw_url.encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore").strip()
            job_url = job_url.replace("\\/", "/")
            job_url = urljoin(self.base_url, job_url)
            if not title or not job_url or job_url in self.seen_urls:
                continue

            jobs.append(
                JobPost(
                    id=f"usajobs-{abs(hash(job_url))}",
                    title=title,
                    company_name=None,
                    job_url=job_url,
                    location=Location(country="USA"),
                    description=title,
                    date_posted=None,
                    is_remote=False,
                    emails=None,
                    job_type=None,
                )
            )
            self.seen_urls.add(job_url)

        if jobs:
            return jobs

        # Deep fallback: parse JSON object literals and look for title/url keys.
        for obj in _extract_json_objects(script_blob):
            title = None
            job_url = None
            for key, value in obj.items():
                k = str(key).lower()
                if title is None and k in {"positiontitle", "title", "jobtitle"} and isinstance(value, str):
                    title = value
                if job_url is None and k in {"positionuri", "positionurl", "joburl", "url"} and isinstance(value, str):
                    job_url = value

            if not title or not job_url:
                continue

            resolved = urljoin(self.base_url, job_url)
            if resolved in self.seen_urls:
                continue

            jobs.append(
                JobPost(
                    id=f"usajobs-{abs(hash(resolved))}",
                    title=title,
                    company_name=None,
                    job_url=resolved,
                    location=Location(country="USA"),
                    description=title,
                    date_posted=None,
                    is_remote=False,
                    emails=None,
                    job_type=None,
                )
            )
            self.seen_urls.add(resolved)

        return jobs
