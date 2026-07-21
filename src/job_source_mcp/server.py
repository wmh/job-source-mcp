from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from job_source_mcp.adapters.cakeresume import CakeResumeAdapter
from job_source_mcp.adapters.jobs104 import Jobs104Adapter
from job_source_mcp.adapters.linkedin import LinkedInAdapter
from job_source_mcp.adapters.yourator import YouratorAdapter
from job_source_mcp.exceptions import RateLimitedError

mcp = FastMCP("job-source-mcp")


def _adapter_104() -> Jobs104Adapter:
    return Jobs104Adapter()


def _adapter_yourator() -> YouratorAdapter:
    return YouratorAdapter()


def _adapter_cakeresume() -> CakeResumeAdapter:
    return CakeResumeAdapter()


def _adapter_linkedin() -> LinkedInAdapter:
    return LinkedInAdapter()


@mcp.tool()
def ping() -> dict:
    return {"ok": True, "server": "job-source-mcp"}


@mcp.tool()
def session_status() -> dict:
    """Check readiness of each source. None require login."""
    return {
        "104": True,
        "yourator": True,
        "cakeresume": True,
        "linkedin": True,
        "note": "No login required. 104, CakeResume, and LinkedIn use curl_cffi Chrome impersonation; Yourator uses Playwright headless browser. LinkedIn is rate-limited with adaptive low-frequency throttling; when throttled it surfaces in search_jobs' 'rate_limited' field rather than returning an empty result, so 0 jobs with an empty 'rate_limited' means a genuinely empty search. Meet.jobs was removed: the service permanently shut down on 2026-06-30.",
    }


@mcp.tool()
async def search_jobs(
    keyword: str,
    source: Literal["all", "104", "yourator", "cakeresume", "linkedin"] = "all",
    page: int = 1,
    limit: int = 20,
    location: str = "",
) -> dict:
    """Search job listings from 104, Yourator, CakeResume, and/or LinkedIn."""
    page = max(page, 1)
    limit = min(max(limit, 1), 50)
    normalized_location = location.strip() or None

    adapters = []
    if source in ("all", "104"):
        adapters.append(_adapter_104())
    if source in ("all", "yourator"):
        adapters.append(_adapter_yourator())
    if source in ("all", "cakeresume"):
        adapters.append(_adapter_cakeresume())
    if source in ("all", "linkedin"):
        adapters.append(_adapter_linkedin())

    all_jobs = []
    errors: list[dict] = []
    rate_limited: list[dict] = []
    for adapter in adapters:
        try:
            jobs = await adapter.search(
                keyword=keyword,
                page=page,
                limit=limit,
                location=normalized_location,
            )
            all_jobs.extend([x.to_dict() for x in jobs])
        except RateLimitedError as exc:
            # Throttled, not empty: keep this separate so a 0-job result from a
            # rate-limited source is never mistaken for "no matching jobs".
            rate_limited.append({"source": exc.source, "retry_after": exc.interval})
            errors.append(
                {"source": adapter.name, "type": "rate_limited", "error": str(exc)}
            )
        except Exception as exc:
            errors.append({"source": adapter.name, "type": "error", "error": str(exc)})

    if source == "all":
        all_jobs = all_jobs[:limit]

    return {
        "keyword": keyword,
        "source": source,
        "count": len(all_jobs),
        "jobs": all_jobs,
        # Sources throttled this call. When this is non-empty, count==0 means
        # "couldn't fetch", NOT "no jobs found". Empty list => no throttling.
        "rate_limited": rate_limited,
        "errors": errors,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
