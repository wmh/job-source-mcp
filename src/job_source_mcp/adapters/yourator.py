from __future__ import annotations

import asyncio
import os
import random
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout

from job_source_mcp.adapters.base import JobSourceAdapter
from job_source_mcp.models import JobListing

_JOBS_API_PATH = "/api/v4/jobs"
_PROFILE_DIR = Path(
    os.environ.get("JOB_SOURCE_DIR", Path.home() / ".config" / "job-source-mcp")
) / "profiles" / "yourator"
_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


def _chrome_yourator_cookies() -> list[dict]:
    """Read Yourator cookies from the system Chrome profile."""
    try:
        import browser_cookie3
        cookies = browser_cookie3.chrome(domain_name=".yourator.co")
        return [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain if c.domain.startswith(".") else f".{c.domain}",
                "path": c.path or "/",
                "sameSite": "Lax",
            }
            for c in cookies
            if c.name and c.value
        ]
    except Exception:
        return []


class YouratorAdapter(JobSourceAdapter):
    name = "yourator"

    def __init__(self, timeout: float = 25.0) -> None:
        self._timeout_ms = int(timeout * 1000)

    async def search(
        self,
        keyword: str,
        page: int = 1,
        limit: int = 20,
        location: str | None = None,
    ) -> list[JobListing]:
        # Simulate human browsing pace
        await asyncio.sleep(random.uniform(2.0, 4.0))

        browse_url = (
            f"https://www.yourator.co/jobs"
            f"?sort=most_related&term[]={quote_plus(keyword)}&page={page}"
        )

        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        chrome_cookies = _chrome_yourator_cookies()

        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(_PROFILE_DIR),
                headless=True,
                locale="zh-TW",
                viewport={"width": 1400, "height": 900},
                args=_LAUNCH_ARGS,
            )
            if chrome_cookies:
                await ctx.add_cookies(chrome_cookies)

            pg = ctx.pages[0] if ctx.pages else await ctx.new_page()

            try:
                async with pg.expect_response(
                    lambda r: (
                        _JOBS_API_PATH in r.url
                        and ("term%5B%5D=" in r.url or "term[]=" in r.url)
                        and r.status == 200
                    ),
                    timeout=self._timeout_ms,
                ) as response_info:
                    await pg.goto(browse_url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                response = await response_info.value
                data = await response.json()
            except PlaywrightTimeout:
                return []
            finally:
                await ctx.close()

        jobs_raw = data.get("payload", {}).get("jobs", [])
        results: list[JobListing] = []
        for item in jobs_raw[:limit]:
            rel = item.get("path", "")
            full_url = f"https://www.yourator.co{rel}" if rel.startswith("/") else rel
            company = (item.get("company") or {}).get("brand", "")
            results.append(
                JobListing(
                    source=self.name,
                    id=str(item.get("id", "")),
                    title=item.get("name", ""),
                    company=company,
                    location=item.get("location", "") or (location or ""),
                    salary=item.get("salary", ""),
                    url=full_url,
                    posted_at=item.get("lastActiveAt", ""),
                    tags=[x for x in (item.get("tags") or []) if isinstance(x, str)],
                    description=item.get("description", ""),
                )
            )
        return results
