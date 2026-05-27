from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from jobspy.model import JobPost, JobResponse, JobType, Location, Scraper, ScraperInput, Site
from jobspy.util import create_logger, create_session, extract_emails_from_text

log = create_logger("BuiltIn")


def _extract_date_from_text(text: str):
    # Common formats: Jan 2, 2026
    match = re.search(r"\b([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\b", text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%b %d, %Y").date()
    except ValueError:
        try:
            return datetime.strptime(match.group(1), "%B %d, %Y").date()
        except ValueError:
            return None


def _infer_job_types(text: str) -> list[JobType] | None:
    lower = text.lower()
    mapped: list[JobType] = []
    if "full time" in lower or "full-time" in lower:
        mapped.append(JobType.FULL_TIME)
    if "part time" in lower or "part-time" in lower:
        mapped.append(JobType.PART_TIME)
    if "contract" in lower:
        mapped.append(JobType.CONTRACT)
    if "intern" in lower:
        mapped.append(JobType.INTERNSHIP)
    return mapped if mapped else None


class BuiltIn(Scraper):
    def __init__(self, proxies: list[str] | str | None = None, ca_cert: str | None = None, user_agent: str | None = None):
        super().__init__(Site.BUILTIN, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)
        self.base_url = "https://builtin.com"
        self.search_url = "https://builtin.com/jobs/us"
        self.session = create_session(proxies=self.proxies, ca_cert=ca_cert, is_tls=False, has_retry=True)
        self.seen_urls: set[str] = set()

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        target_count = scraper_input.results_wanted + scraper_input.offset
        max_pages = max(1, min(10, (target_count // 20) + 1))
        jobs: list[JobPost] = []

        for page in range(1, max_pages + 1):
            params = {
                "search": scraper_input.search_term or "",
                "page": page,
            }
            url = f"{self.search_url}?{urlencode(params)}"

            try:
                response = self.session.get(url, timeout=scraper_input.request_timeout)
            except Exception as exc:
                log.warning(f"BuiltIn request failed on page {page}: {exc}")
                break

            if not response.ok:
                log.warning(f"BuiltIn response status code {response.status_code}")
                break

            page_jobs = self._parse_page(response.text, scraper_input)
            if not page_jobs:
                if page == 1:
                    log.warning("BuiltIn search page returned no parseable job cards.")
                break

            jobs.extend(page_jobs)
            if len(self.seen_urls) >= target_count:
                break

        sliced = jobs[scraper_input.offset : scraper_input.offset + scraper_input.results_wanted]
        return JobResponse(jobs=sliced)

    def _parse_page(self, html: str, scraper_input: ScraperInput) -> list[JobPost]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[JobPost] = []

        desired_location = (scraper_input.location or "").strip().lower()

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if "/job/" not in href.lower():
                continue

            job_url = urljoin(self.base_url, href)
            if job_url in self.seen_urls:
                continue

            title = anchor.get_text(" ", strip=True)
            if not title:
                continue

            card = anchor.find_parent(["article", "li", "div"])
            card_text = card.get_text(" ", strip=True) if card else title
            card_text = re.sub(r"\s+", " ", card_text).strip()

            full_description, company_name = self._fetch_job_details(
                job_url=job_url,
                fallback_text=card_text,
                timeout=scraper_input.request_timeout,
            )

            # Best effort location extraction from card text.
            location_text = None
            if card:
                card_location = card.find(attrs={"data-id": re.compile("location", re.I)})
                if card_location:
                    location_text = card_location.get_text(" ", strip=True)
            if not location_text:
                m = re.search(r"([A-Za-z .'-]+,\s*[A-Z]{2})", card_text)
                if m:
                    location_text = m.group(1)

            if desired_location and location_text and desired_location not in location_text.lower():
                # Keep broad search behavior when no location is found.
                pass

            remote = "remote" in card_text.lower() or "hybrid" in card_text.lower()
            date_posted = _extract_date_from_text(card_text)

            jobs.append(
                JobPost(
                    id=f"builtin-{abs(hash(job_url))}",
                    title=title,
                    company_name=company_name,
                    job_url=job_url,
                    location=Location(country="USA", city=None, state=None) if not location_text else Location(country="USA"),
                    description=full_description,
                    date_posted=date_posted,
                    is_remote=remote,
                    emails=extract_emails_from_text(full_description),
                    job_type=_infer_job_types(card_text),
                )
            )
            self.seen_urls.add(job_url)

        return jobs

    def _fetch_job_details(self, job_url: str, fallback_text: str, timeout: int) -> tuple[str, str | None]:
        try:
            response = self.session.get(job_url, timeout=timeout)
            if not response.ok:
                return fallback_text, None
        except Exception:
            return fallback_text, None

        soup = BeautifulSoup(response.text, "html.parser")

        company_name = None
        description = ""

        # Prefer JobPosting JSON-LD when available because it is usually the cleanest payload.
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text("", strip=True)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue

            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("@type", "")).lower() != "jobposting":
                    continue

                desc = entry.get("description")
                hiring_org = entry.get("hiringOrganization")
                if isinstance(hiring_org, dict):
                    company_name = hiring_org.get("name") or company_name

                if isinstance(desc, str) and desc.strip():
                    clean = BeautifulSoup(desc, "html.parser").get_text(" ", strip=True)
                    if clean:
                        description = clean
                        break
            if description:
                break

        if not description:
            selectors = [
                "div[data-id*='job-description']",
                "section[data-id*='job-description']",
                "div.job-description",
                "section.job-description",
                "div[class*='description']",
                "section[class*='description']",
                "article",
                "main",
            ]
            for selector in selectors:
                node = soup.select_one(selector)
                if not node:
                    continue
                text = node.get_text(" ", strip=True)
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) >= 120:
                    description = text
                    break

        if not company_name:
            company_selectors = [
                "a[data-id*='company']",
                "div[data-id*='company']",
                "span[data-id*='company']",
                "a[href*='/company/']",
            ]
            for selector in company_selectors:
                node = soup.select_one(selector)
                if not node:
                    continue
                company_text = node.get_text(" ", strip=True)
                if company_text:
                    company_name = company_text
                    break

        final_description = description if description else fallback_text
        return final_description, company_name
