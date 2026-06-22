from __future__ import annotations

import asyncio
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from job_source_mcp.adapters.base import JobSourceAdapter
from job_source_mcp.exceptions import RateLimitedError
from job_source_mcp.models import JobListing
from job_source_mcp.throttle import AdaptiveRateLimiter

_BASE_URL = "https://meet.jobs"
_JOB_ID_RE = re.compile(r"/jobs/(\d+)")

# Meet.jobs is more tolerant than LinkedIn but we still keep the rate low and
# back off on 429. Shared across instances within the process.
_LIMITER = AdaptiveRateLimiter(min_interval=4.0, max_interval=60.0, jitter=3.0)


class MeetJobsAdapter(JobSourceAdapter):
    name = "meetjobs"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    async def search(
        self,
        keyword: str,
        page: int = 1,
        limit: int = 20,
        location: str | None = None,
    ) -> list[JobListing]:
        # Meet.jobs filters on the `q` param; other names (keyword/search) are
        # silently ignored and return the default featured listings.
        url = f"{_BASE_URL}/zh-TW/jobs?q={quote_plus(keyword)}&page={page}"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Referer": f"{_BASE_URL}/zh-TW/jobs",
        }

        html = await self._fetch(url, headers)
        return self._parse(html, limit, location)

    async def _fetch(self, url: str, headers: dict) -> str:
        # On persistent 429 raise RateLimitedError instead of returning None,
        # so a throttled request is not mistaken for an empty result set.
        for attempt in range(2):
            await _LIMITER.acquire()
            async with AsyncSession(impersonate="chrome110") as s:
                resp = await s.get(url, headers=headers, timeout=self._timeout)
            if resp.status_code == 429:
                _LIMITER.penalize()
                if attempt == 0:
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
        for card in soup.select("div.job-card")[:limit]:
            link = card.select_one('a[href*="/jobs/"]')
            href = link.get("href", "") if link else ""
            m = _JOB_ID_RE.search(href)
            if not m:
                continue
            job_id = m.group(1)

            title_el = card.select_one("h3.job-title")
            company_el = card.select_one("h5.employer-name")
            salary_el = card.select_one("h3.salary, .salary")

            results.append(
                JobListing(
                    source=self.name,
                    id=job_id,
                    title=title_el.get_text(strip=True) if title_el else "",
                    company=company_el.get_text(strip=True) if company_el else "",
                    location=location or "",
                    salary=salary_el.get_text(strip=True) if salary_el else "",
                    url=f"{_BASE_URL}{href}" if href.startswith("/") else href,
                    posted_at="",
                    tags=[],
                    description="",
                )
            )
        return results
