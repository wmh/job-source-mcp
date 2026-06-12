from __future__ import annotations

import asyncio
import random
from urllib.parse import quote

from curl_cffi.requests import AsyncSession

from job_source_mcp.adapters.base import JobSourceAdapter
from job_source_mcp.models import JobListing

_API_URL = "https://www.104.com.tw/jobs/search/api/jobs"


class Jobs104Adapter(JobSourceAdapter):
    name = "104"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    async def search(
        self,
        keyword: str,
        page: int = 1,
        limit: int = 20,
        location: str | None = None,
    ) -> list[JobListing]:
        # Simulate human browsing pace to avoid rate-limiting
        await asyncio.sleep(random.uniform(1.5, 3.5))

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Referer": f"https://www.104.com.tw/jobs/search/?keyword={quote(keyword)}",
        }
        params = {
            "keyword": keyword,
            "order": "15",
            "asc": "0",
            "page": str(page),
            "mode": "s",
        }

        async with AsyncSession(impersonate="chrome110") as s:
            resp = await s.get(_API_URL, params=params, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()

        jobs_raw = data.get("data") or []
        if not isinstance(jobs_raw, list):
            jobs_raw = jobs_raw.get("list", [])

        results: list[JobListing] = []
        for item in jobs_raw[:limit]:
            link = (item.get("link") or {}).get("job", "")
            salary_low = item.get("salaryLow", 0)
            salary_high = item.get("salaryHigh", 0)
            salary = f"{salary_low:,}–{salary_high:,}" if salary_low and salary_high else ""

            results.append(
                JobListing(
                    source=self.name,
                    id=str(item.get("jobNo", "")),
                    title=item.get("jobName", ""),
                    company=item.get("custName", ""),
                    location=item.get("jobAddrNoDesc", ""),
                    salary=salary,
                    url=link,
                    posted_at=item.get("appearDate", ""),
                    tags=[t if isinstance(t, str) else t.get("name", "") for t in (item.get("tags") or []) if t],
                    description=item.get("description", ""),
                )
            )
        return results
