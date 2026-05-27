from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from jobspy.model import JobPost, JobResponse, JobType, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger, create_session, extract_emails_from_text

log = create_logger("Wellfound")


def _parse_date(text: str):
    match = re.search(r"\b([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\b", text)
    if not match:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(match.group(1), fmt).date()
        except ValueError:
            continue
    return None


def _infer_types(text: str) -> list[JobType] | None:
    lower = text.lower()
    out: list[JobType] = []
    if "full-time" in lower or "full time" in lower:
        out.append(JobType.FULL_TIME)
    if "part-time" in lower or "part time" in lower:
        out.append(JobType.PART_TIME)
    if "contract" in lower:
        out.append(JobType.CONTRACT)
    if "temporary" in lower or "temp " in lower:
        out.append(JobType.TEMPORARY)
    if "intern" in lower:
        out.append(JobType.INTERNSHIP)
    return out if out else None


class Wellfound(Scraper):
    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None, user_agent: str | None = None):
        super().__init__(Site.WELLFOUND, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)
        self.base_url = "https://wellfound.com"
        self.session = create_session(proxies=self.proxies, ca_cert=ca_cert, is_tls=False, has_retry=True)
        self.seen_urls: set[str] = set()

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        q = quote_plus(scraper_input.search_term or "")
        l = quote_plus(scraper_input.location or "")
        url = f"{self.base_url}/jobs?query={q}&location={l}"
        jobs: list[JobPost] = []

        try:
            response = self.session.get(
                url,
                timeout=scraper_input.request_timeout,
                headers={"User-Agent": self.user_agent or "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
            )
            if response.ok:
                html = response.text
                if "captcha" not in html.lower() and "access denied" not in html.lower():
                    jobs = self._parse_html(html)
                else:
                    log.warning("Wellfound returned anti-bot/challenge page; skipping in legal no-key mode.")
            else:
                log.warning(f"Wellfound response status code {response.status_code}")
        except Exception as exc:
            log.warning(f"Wellfound request failed: {exc}")

        sliced = jobs[scraper_input.offset : scraper_input.offset + scraper_input.results_wanted]
        return JobResponse(jobs=sliced)

    def _parse_html(self, html: str) -> list[JobPost]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[JobPost] = []

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            text = script.get_text(strip=True)
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, dict) or "jobposting" not in str(item.get("@type", "")).lower():
                    continue
                title = str(item.get("title", "")).strip()
                job_url = str(item.get("url", "")).strip()
                if not title or not job_url:
                    continue
                job_url = urljoin(self.base_url, job_url)
                if job_url in self.seen_urls:
                    continue
                desc = str(item.get("description", "") or "")
                text_blob = f"{title} {desc}"
                jobs.append(
                    JobPost(
                        id=f"wellfound-{abs(hash(job_url))}",
                        title=title,
                        company_name=None,
                        job_url=job_url,
                        location=Location(country="USA"),
                        description=desc or text_blob,
                        date_posted=_parse_date(text_blob),
                        is_remote=("remote" in text_blob.lower()),
                        emails=extract_emails_from_text(text_blob),
                        job_type=_infer_types(text_blob),
                    )
                )
                self.seen_urls.add(job_url)

        if jobs:
            return jobs

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if not any(token in href.lower() for token in ["/job", "/jobs", "/role/"]):
                continue
            job_url = urljoin(self.base_url, href)
            if job_url in self.seen_urls:
                continue
            title = anchor.get_text(" ", strip=True)
            if not title:
                continue
            card = anchor.find_parent(["article", "li", "div"])
            text_blob = card.get_text(" ", strip=True) if card else title
            jobs.append(
                JobPost(
                    id=f"wellfound-{abs(hash(job_url))}",
                    title=title,
                    company_name=None,
                    job_url=job_url,
                    location=Location(country="USA"),
                    description=text_blob,
                    date_posted=_parse_date(text_blob),
                    is_remote=("remote" in text_blob.lower()),
                    emails=extract_emails_from_text(text_blob),
                    job_type=_infer_types(text_blob),
                )
            )
            self.seen_urls.add(job_url)

        return jobs
