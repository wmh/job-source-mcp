from __future__ import annotations

from collections.abc import Callable

from job_source_mcp.adapters.base import JobSourceAdapter
from job_source_mcp.exceptions import RateLimitedError
from job_source_mcp.models import JobListing


class FakeAdapter(JobSourceAdapter):
    """Test double: returns canned jobs, or raises a preset exception."""

    def __init__(
        self,
        name: str,
        *,
        jobs: list[JobListing] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.name = name
        self._jobs = jobs or []
        self._raises = raises
        self.calls: list[dict] = []

    async def search(
        self,
        keyword: str,
        page: int = 1,
        limit: int = 20,
        location: str | None = None,
    ) -> list[JobListing]:
        self.calls.append(
            {"keyword": keyword, "page": page, "limit": limit, "location": location}
        )
        if self._raises is not None:
            raise self._raises
        return self._jobs[:limit]


def make_job(source: str, jid: str) -> JobListing:
    return JobListing(
        source=source,
        id=jid,
        title=f"Engineer {jid}",
        company="Acme",
        location="台北市",
        salary="",
        url=f"https://example.com/{source}/{jid}",
        posted_at="20260701",
        tags=["Go"],
    )


def rate_limit_adapter(name: str, interval: float | None = 42.0) -> FakeAdapter:
    return FakeAdapter(name, raises=RateLimitedError(source=name, interval=interval))


class FakeResponse:
    """Stand-in for a curl_cffi response object."""

    def __init__(
        self,
        *,
        json_data: object | None = None,
        text: str = "",
        status_code: int = 200,
    ) -> None:
        self._json = json_data
        self.text = text
        self.status_code = status_code

    def json(self) -> object:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Async-context-manager stand-in for curl_cffi's AsyncSession.

    Records every ``get`` call so tests can assert on the request that was made,
    and returns responses from a preset queue (or a single response repeatedly).
    """

    def __init__(self, responses: list[FakeResponse] | FakeResponse) -> None:
        self._responses = (
            [responses] if isinstance(responses, FakeResponse) else list(responses)
        )
        self.get_calls: list[dict] = []

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str = "", **kwargs: object) -> FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        # Pop next response, or reuse the last one for repeated calls (retries).
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def session_factory(session: FakeSession) -> Callable[..., FakeSession]:
    """Return a callable usable as a drop-in for ``AsyncSession(...)``."""
    return lambda *args, **kwargs: session
