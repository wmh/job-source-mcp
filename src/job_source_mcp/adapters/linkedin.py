from __future__ import annotations

import asyncio
import re

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from job_source_mcp.adapters.base import JobSourceAdapter
from job_source_mcp.exceptions import RateLimitedError
from job_source_mcp.models import JobListing
from job_source_mcp.throttle import AdaptiveRateLimiter

# Unauthenticated "guest" job-search endpoint. Returns ~10 HTML job cards per
# request, no login or session cookie required.
_API_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_DEFAULT_LOCATION = "Taiwan"
_PER_REQUEST = 10  # cards returned per page by this endpoint
_URN_RE = re.compile(r":(\d+)$")

# LinkedIn is the most rate-limit sensitive source. Keep the call rate LOW and
# let it drop further (process-wide) whenever a 429 is seen. Shared across all
# LinkedInAdapter instances so repeated searches in one process stay spaced out.
_LIMITER = AdaptiveRateLimiter(min_interval=8.0, max_interval=120.0, jitter=4.0)


class LinkedInAdapter(JobSourceAdapter):
    name = "linkedin"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    async def search(
        self,
        keyword: str,
        page: int = 1,
        limit: int = 20,
        location: str | None = None,
    ) -> list[JobListing]:
        params = {
            "keywords": keyword,
            "location": location or _DEFAULT_LOCATION,
            "start": str((page - 1) * _PER_REQUEST),
        }
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.linkedin.com/jobs",
        }

        html = await self._fetch(params, headers)
        return self._parse(html, limit, location)

    async def _fetch(self, params: dict, headers: dict) -> str:
        """Fetch with low-frequency throttling and 429 back-off.

        On 429 we do NOT hammer the endpoint: we escalate the global interval
        (so every subsequent call is slower) and back off before a single
        retry. If still throttled, raise RateLimitedError so the caller can
        report "throttled" rather than silently collapsing into an empty
        result. The raised interval protects future calls.
        """
        for attempt in range(2):
            await _LIMITER.acquire()
            async with AsyncSession(impersonate="chrome110") as s:
                resp = await s.get(
                    _API_URL, params=params, headers=headers, timeout=self._timeout
                )
            if resp.status_code == 429:
                _LIMITER.penalize()
                if attempt == 0:
                    # Wait out the cool-down before the one allowed retry.
                    await asyncio.sleep(_LIMITER.interval)
                    continue
                raise RateLimitedError(self.name, _LIMITER.interval)
            resp.raise_for_status()
            _LIMITER.relax()
            return resp.text
        raise RateLimitedError(self.name, _LIMITER.interval)

    def _parse(self, html: str, limit: int, location: str | None) -> list[JobListing]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[JobListing] = []
        for card in soup.select("div.base-card[data-entity-urn]")[:limit]:
            urn = card.get("data-entity-urn", "")
            m = _URN_RE.search(urn)
            job_id = m.group(1) if m else ""

            title_el = card.select_one("h3.base-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle")
            loc_el = card.select_one("span.job-search-card__location")
            link_el = card.select_one("a.base-card__full-link")
            date_el = card.select_one("time.job-search-card__listdate")
            salary_el = card.select_one("span.job-search-card__salary-info")

            url = link_el.get("href", "") if link_el else ""
            url = url.split("?", 1)[0]  # drop tracking query string

            results.append(
                JobListing(
                    source=self.name,
                    id=job_id,
                    title=title_el.get_text(strip=True) if title_el else "",
                    company=company_el.get_text(strip=True) if company_el else "",
                    location=(loc_el.get_text(strip=True) if loc_el else "")
                    or (location or ""),
                    salary=salary_el.get_text(strip=True) if salary_el else "",
                    url=url,
                    posted_at=date_el.get("datetime", "") if date_el else "",
                    tags=[],
                    description="",
                )
            )
        return results
