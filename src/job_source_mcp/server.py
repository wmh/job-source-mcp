from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from job_source_mcp.adapters.jobs104 import Jobs104Adapter
from job_source_mcp.adapters.yourator import YouratorAdapter

mcp = FastMCP("job-source-mcp")


def _adapter_104() -> Jobs104Adapter:
    return Jobs104Adapter()


def _adapter_yourator() -> YouratorAdapter:
    return YouratorAdapter()


@mcp.tool()
def ping() -> dict:
    return {"ok": True, "server": "job-source-mcp"}


@mcp.tool()
def session_status() -> dict:
    """Check readiness of each source. Neither source requires login."""
    return {
        "104": True,
        "yourator": True,
        "note": "No login required. 104 uses curl_cffi Chrome impersonation; Yourator uses Playwright headless browser.",
    }


@mcp.tool()
async def search_jobs(
    keyword: str,
    source: Literal["all", "104", "yourator"] = "all",
    page: int = 1,
    limit: int = 20,
    location: str = "",
) -> dict:
    """Search job listings from 104 and/or Yourator."""
    page = max(page, 1)
    limit = min(max(limit, 1), 50)
    normalized_location = location.strip() or None

    adapters = []
    if source in ("all", "104"):
        adapters.append(_adapter_104())
    if source in ("all", "yourator"):
        adapters.append(_adapter_yourator())

    all_jobs = []
    errors: list[dict] = []
    for adapter in adapters:
        try:
            jobs = await adapter.search(
                keyword=keyword,
                page=page,
                limit=limit,
                location=normalized_location,
            )
            all_jobs.extend([x.to_dict() for x in jobs])
        except (ValueError, KeyError, RuntimeError, Exception) as exc:
            errors.append({"source": adapter.name, "error": str(exc)})

    if source == "all":
        all_jobs = all_jobs[:limit]

    return {
        "keyword": keyword,
        "source": source,
        "count": len(all_jobs),
        "jobs": all_jobs,
        "errors": errors,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
