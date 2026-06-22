from __future__ import annotations

import asyncio
import json
import random
import re
from urllib.parse import quote_plus

from curl_cffi.requests import AsyncSession

from job_source_mcp.adapters.base import JobSourceAdapter
from job_source_mcp.models import JobListing

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
    re.DOTALL,
)
_BASE_URL = "https://www.cakeresume.com"


def _format_salary(salary: dict | None) -> str:
    if not salary:
        return ""
    lo = salary.get("min") or ""
    hi = salary.get("max") or ""
    sal_type = salary.get("type", "")
    suffix = "/月" if sal_type == "per_month" else "/年" if sal_type == "per_year" else ""
    try:
        lo_i, hi_i = int(lo or 0), int(hi or 0)
    except ValueError:
        return f"{lo}–{hi}{suffix}" if lo and hi else ""
    if lo_i == 0 and hi_i == 0:
        return ""
    return f"{lo_i:,}–{hi_i:,}{suffix}"


class CakeResumeAdapter(JobSourceAdapter):
    name = "cakeresume"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    async def search(
        self,
        keyword: str,
        page: int = 1,
        limit: int = 20,
        location: str | None = None,
    ) -> list[JobListing]:
        await asyncio.sleep(random.uniform(1.5, 3.5))

        params = {
            "q": keyword,
            "refinementList[lang][]": "zh-TW",
            "page": str(page),
        }
        # Build query string manually to keep repeated param names
        qs = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
        url = f"{_BASE_URL}/jobs?{qs}"

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Referer": f"{_BASE_URL}/jobs",
        }

        async with AsyncSession(impersonate="chrome110") as s:
            resp = await s.get(url, headers=headers, timeout=self._timeout)
        resp.raise_for_status()

        m = _NEXT_DATA_RE.search(resp.text)
        if not m:
            return []

        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []

        entities: dict = (
            data.get("props", {})
            .get("pageProps", {})
            .get("initialState", {})
            .get("jobSearch", {})
            .get("entityByPathId", {})
        )
        if not entities:
            return []

        results: list[JobListing] = []
        for path, item in list(entities.items())[:limit]:
            company_obj = item.get("page") or {}
            company = company_obj.get("name", "")
            locs = item.get("locations") or []
            loc = locs[0] if locs else (location or "")
            posted = (item.get("contentUpdatedAt") or "")[:10]  # YYYY-MM-DD
            tags = [t for t in (item.get("tags") or []) if isinstance(t, str)]

            results.append(
                JobListing(
                    source=self.name,
                    id=path,
                    title=item.get("title", ""),
                    company=company,
                    location=loc,
                    salary=_format_salary(item.get("salary")),
                    url=f"{_BASE_URL}/jobs/{path}",
                    posted_at=posted,
                    tags=tags,
                    description=item.get("description", ""),
                )
            )
        return results
