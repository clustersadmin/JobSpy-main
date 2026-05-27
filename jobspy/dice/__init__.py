from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from jobspy.model import JobPost, JobResponse, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger, create_session, extract_emails_from_text, extract_job_type

log = create_logger("Dice")


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _pick(d: dict, *keys):
    for key in keys:
        if key in d and d[key] not in (None, ""):
            return d[key]
    return None


class Dice(Scraper):
    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None, user_agent: str | None = None):
        super().__init__(Site.DICE, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)
        self.base_url = "https://www.dice.com"
        self.search_url = "https://www.dice.com/jobs"
        self.session = create_session(proxies=self.proxies, ca_cert=ca_cert, is_tls=False, has_retry=True)
        self.seen_urls: set[str] = set()

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        target_count = scraper_input.results_wanted + scraper_input.offset
        jobs: list[JobPost] = []

        max_pages = max(1, min(10, (target_count // 20) + 1))

        for page in range(1, max_pages + 1):
            params = {
                "q": scraper_input.search_term or "",
                "location": scraper_input.location or "",
                "page": page,
                "pageSize": 20,
            }

            try:
                response = self.session.get(self.search_url, params=params, timeout=scraper_input.request_timeout)
            except Exception as exc:
                log.warning(f"Dice request failed on page {page}: {exc}")
                break

            if not response.ok:
                log.warning(f"Dice response status code {response.status_code}")
                break

            page_jobs = self._parse_response(response.text)
            if not page_jobs:
                break

            jobs.extend(page_jobs)

            if len(self.seen_urls) >= target_count:
                break

        return JobResponse(jobs=jobs)

    def _parse_response(self, html: str) -> list[JobPost]:
        jobs: list[JobPost] = []

        # Preferred source: Next.js payload on the Dice search page.
        try:
            soup = BeautifulSoup(html, "html.parser")
            script = soup.find("script", id="__NEXT_DATA__")
            if script and script.string:
                payload = json.loads(script.string)
                jobs.extend(self._extract_jobs_from_payload(payload))
        except Exception as exc:
            log.warning(f"Dice Next.js payload parse failed: {exc}")

        # Fallback: anchor-based extraction when payload shape changes.
        if not jobs:
            jobs.extend(self._extract_jobs_from_html(html))

        return jobs

    def _extract_jobs_from_payload(self, payload: dict) -> list[JobPost]:
        extracted: list[JobPost] = []

        for d in _walk_dicts(payload):
            title = _pick(d, "jobTitle", "title", "positionTitle")
            detail_url = _pick(d, "detailUrl", "jobUrl", "url", "redirectUrl")

            if not title or not detail_url:
                continue

            company = _pick(d, "companyName", "company", "company_name")
            description = _pick(d, "summary", "description", "jobDescription") or ""
            location_raw = _pick(d, "jobLocation", "location", "displayLocation")
            posted_raw = _pick(d, "postedDate", "datePosted", "postDate")
            job_id = _pick(d, "id", "jobId", "positionId")

            post = self._build_job_post(
                job_id=job_id,
                title=str(title),
                detail_url=str(detail_url),
                company=str(company) if company else None,
                description=str(description),
                location_raw=str(location_raw) if location_raw else None,
                posted_raw=str(posted_raw) if posted_raw else None,
            )
            if post:
                extracted.append(post)

        return extracted

    def _extract_jobs_from_html(self, html: str) -> list[JobPost]:
        extracted: list[JobPost] = []
        soup = BeautifulSoup(html, "html.parser")

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href")
            if not href:
                continue
            if "dice.com/job-detail/" not in href and "/job-detail/" not in href:
                continue

            title = anchor.get_text(" ", strip=True)
            if not title:
                continue

            post = self._build_job_post(
                job_id=None,
                title=title,
                detail_url=href,
                company=None,
                description="",
                location_raw=None,
                posted_raw=None,
            )
            if post:
                extracted.append(post)

        return extracted

    def _build_job_post(
        self,
        *,
        job_id: str | None,
        title: str,
        detail_url: str,
        company: str | None,
        description: str,
        location_raw: str | None,
        posted_raw: str | None,
    ) -> JobPost | None:
        job_url = urljoin(self.base_url, detail_url)
        if job_url in self.seen_urls:
            return None
        self.seen_urls.add(job_url)

        city = None
        state = None
        country = None
        if location_raw:
            parts = [p.strip() for p in re.split(r",|\|", location_raw) if p.strip()]
            if parts:
                city = parts[0]
            if len(parts) > 1:
                state = parts[1]
            if len(parts) > 2:
                country = parts[2]

        date_posted = None
        if posted_raw:
            iso_match = re.search(r"\d{4}-\d{2}-\d{2}", posted_raw)
            if iso_match:
                date_posted = datetime.strptime(iso_match.group(0), "%Y-%m-%d").date()

        combined_text = f"{title} {description}".strip()

        return JobPost(
            id=f"dice-{job_id}" if job_id else None,
            title=title,
            company_name=company,
            job_url=job_url,
            location=Location(city=city, state=state, country=country),
            description=description,
            date_posted=date_posted,
            is_remote=("remote" in combined_text.lower() or "work from home" in combined_text.lower()),
            emails=extract_emails_from_text(description),
            job_type=extract_job_type(combined_text),
        )
