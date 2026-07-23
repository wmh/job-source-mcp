from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal

from mcp.server.fastmcp import FastMCP

from job_source_mcp import __version__
from job_source_mcp.adapters.base import JobSourceAdapter
from job_source_mcp.adapters.cakeresume import CakeResumeAdapter
from job_source_mcp.adapters.jobs104 import Jobs104Adapter
from job_source_mcp.adapters.linkedin import LinkedInAdapter
from job_source_mcp.adapters.yourator import YouratorAdapter
from job_source_mcp.exceptions import RateLimitedError

Source = Literal["all", "104", "yourator", "cakeresume", "linkedin"]

# Ordered so `source="all"` always queries sources in this sequence. The keys
# double as the accepted values for the `source` tool parameter.
ADAPTER_FACTORIES: dict[str, Callable[[], JobSourceAdapter]] = {
    "104": Jobs104Adapter,
    "yourator": YouratorAdapter,
    "cakeresume": CakeResumeAdapter,
    "linkedin": LinkedInAdapter,
}


def _default_registry() -> dict[str, JobSourceAdapter]:
    return {name: factory() for name, factory in ADAPTER_FACTORIES.items()}


def _select(
    registry: Mapping[str, JobSourceAdapter], source: str
) -> list[JobSourceAdapter]:
    if source == "all":
        return list(registry.values())
    adapter = registry.get(source)
    return [adapter] if adapter is not None else []


async def run_search(
    registry: Mapping[str, JobSourceAdapter],
    keyword: str,
    source: str = "all",
    page: int = 1,
    limit: int = 20,
    location: str | None = None,
) -> dict:
    """Core search logic, independent of MCP wiring.

    Kept as a plain function (taking an injectable adapter registry) so the
    rate-limited-vs-empty distinction can be unit tested without spinning up a
    server or hitting the network.
    """
    page = max(page, 1)
    limit = min(max(limit, 1), 50)
    normalized_location = (location or "").strip() or None

    adapters = _select(registry, source)

    all_jobs: list[dict] = []
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


def create_server(
    registry: Mapping[str, JobSourceAdapter] | None = None,
) -> FastMCP:
    """Build the MCP server. Pass `registry` to inject adapters (e.g. in tests)."""
    mcp = FastMCP("job-source-mcp")
    # FastMCP doesn't forward a version to the underlying MCP server, so set it
    # here to keep the initialize handshake reporting our single-source version.
    mcp._mcp_server.version = __version__
    adapters: Mapping[str, JobSourceAdapter] = (
        registry if registry is not None else _default_registry()
    )

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
            "note": "No login required. 104, CakeResume, and LinkedIn use curl_cffi Chrome impersonation; Yourator uses Playwright headless browser. LinkedIn is rate-limited with adaptive low-frequency throttling; when throttled it surfaces in search_jobs' 'rate_limited' field rather than returning an empty result, so 0 jobs with an empty 'rate_limited' means a genuinely empty search. Meet.jobs was removed: the service permanently shut down on 2026-06-30.",  # noqa: E501
        }

    @mcp.tool()
    async def search_jobs(
        keyword: str,
        source: Source = "all",
        page: int = 1,
        limit: int = 20,
        location: str = "",
    ) -> dict:
        """Search job listings from 104, Yourator, CakeResume, and/or LinkedIn."""
        return await run_search(
            adapters,
            keyword=keyword,
            source=source,
            page=page,
            limit=limit,
            location=location,
        )

    return mcp


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
