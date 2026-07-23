"""LinkedIn adapter tests. `_parse` is a pure HTML->JobListing function so it
needs no mocking; the 429 back-off path is driven with a fake session."""

from __future__ import annotations

import pytest
from conftest import FakeResponse, FakeSession, session_factory

from job_source_mcp.adapters import linkedin as li
from job_source_mcp.adapters.linkedin import LinkedInAdapter
from job_source_mcp.exceptions import RateLimitedError
from job_source_mcp.throttle import AdaptiveRateLimiter

# Two guest job cards; the second omits salary and date to exercise the
# "missing optional field" branches.
_HTML = """
<ul>
  <li>
    <div class="base-card" data-entity-urn="urn:li:jobPosting:3812345678">
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/golang-dev-at-acme-3812345678?trk=track&amp;refId=x">link</a>
      <h3 class="base-search-card__title">Golang Backend Engineer</h3>
      <h4 class="base-search-card__subtitle">Acme Corp</h4>
      <span class="job-search-card__location">Taipei, Taiwan</span>
      <time class="job-search-card__listdate" datetime="2026-06-01">1 month ago</time>
      <span class="job-search-card__salary-info">NT$80,000 - NT$120,000</span>
    </div>
  </li>
  <li>
    <div class="base-card" data-entity-urn="urn:li:jobPosting:99">
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/be-99">link</a>
      <h3 class="base-search-card__title">Backend Engineer</h3>
      <h4 class="base-search-card__subtitle">Beta Inc</h4>
      <span class="job-search-card__location">Remote</span>
    </div>
  </li>
</ul>
"""


def _parse(html: str, limit: int = 20, location: str | None = None):
    return LinkedInAdapter()._parse(html, limit, location)


def test_parse_extracts_all_fields_from_a_card():
    jobs = _parse(_HTML)
    first = jobs[0]
    assert first.source == "linkedin"
    assert first.id == "3812345678"  # trailing digits of the URN
    assert first.title == "Golang Backend Engineer"
    assert first.company == "Acme Corp"
    assert first.location == "Taipei, Taiwan"
    assert first.salary == "NT$80,000 - NT$120,000"
    assert first.posted_at == "2026-06-01"
    # Guest cards never carry tags/description.
    assert first.tags == []
    assert first.description == ""


def test_parse_strips_tracking_query_string_from_url():
    first = _parse(_HTML)[0]
    assert (
        first.url == "https://www.linkedin.com/jobs/view/golang-dev-at-acme-3812345678"
    )
    assert "?" not in first.url


def test_parse_tolerates_missing_optional_fields():
    second = _parse(_HTML)[1]
    assert second.id == "99"
    assert second.salary == ""  # no salary element present
    assert second.posted_at == ""  # no <time> element present


def test_parse_limit_caps_cards():
    assert len(_parse(_HTML, limit=1)) == 1


def test_parse_empty_html_returns_no_jobs():
    assert _parse("<html><body>nothing here</body></html>") == []


async def test_fetch_raises_rate_limited_after_persistent_429(monkeypatch):
    # Isolate from the shared process-wide limiter and never actually sleep.
    monkeypatch.setattr(li, "_LIMITER", AdaptiveRateLimiter(1.0, 4.0))

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(li.asyncio, "sleep", _no_sleep)

    session = FakeSession(FakeResponse(status_code=429))
    monkeypatch.setattr(li, "AsyncSession", session_factory(session))

    with pytest.raises(RateLimitedError):
        await LinkedInAdapter().search("go")

    # One initial call + exactly one retry — we back off, we don't hammer.
    assert len(session.get_calls) == 2


async def test_search_returns_parsed_jobs_on_success(monkeypatch):
    monkeypatch.setattr(li, "_LIMITER", AdaptiveRateLimiter(1.0, 4.0))
    session = FakeSession(FakeResponse(text=_HTML, status_code=200))
    monkeypatch.setattr(li, "AsyncSession", session_factory(session))

    jobs = await LinkedInAdapter().search("go", limit=5)
    assert [j.company for j in jobs] == ["Acme Corp", "Beta Inc"]
    # start offset for page 1 is 0.
    assert session.get_calls[0]["params"]["start"] == "0"
