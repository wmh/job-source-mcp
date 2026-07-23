"""Parsing tests for the 104 and CakeResume adapters. The network call is
replaced with a fake session so we test only the response->JobListing mapping."""

from __future__ import annotations

import json

import pytest
from conftest import FakeResponse, FakeSession, session_factory

from job_source_mcp.adapters import cakeresume as ck
from job_source_mcp.adapters import jobs104 as j104
from job_source_mcp.adapters.cakeresume import CakeResumeAdapter, _format_salary
from job_source_mcp.adapters.jobs104 import Jobs104Adapter


@pytest.fixture(autouse=True)
def _no_human_delay(monkeypatch):
    """These adapters sleep random.uniform(1.5, 3.5)s to mimic a human; make it
    instant so the suite stays fast."""
    monkeypatch.setattr(j104.random, "uniform", lambda _a, _b: 0)
    monkeypatch.setattr(ck.random, "uniform", lambda _a, _b: 0)


# --- 104 -----------------------------------------------------------------

_JOBS_104 = {
    "data": [
        {
            "jobNo": 12345,  # numeric in the API; adapter must stringify
            "jobName": "Golang Backend Engineer",
            "custName": "Acme Corp",
            "jobAddrNoDesc": "台北市信義區",
            "salaryLow": 80000,
            "salaryHigh": 120000,
            "link": {"job": "//www.104.com.tw/job/abc"},
            "appearDate": "20260601",
            "tags": ["Go", {"name": "Kafka"}, None],  # mixed str/dict/None
            "description": "build things",
        },
        {
            "jobNo": 67890,
            "jobName": "Intern",
            "custName": "Beta",
            "jobAddrNoDesc": "台北市",
            "salaryLow": 0,  # incomplete salary -> empty string
            "salaryHigh": 0,
            "link": {},
            "appearDate": "20260602",
            "tags": [],
        },
    ]
}


async def test_104_maps_fields_and_stringifies_id(monkeypatch):
    session = FakeSession(FakeResponse(json_data=_JOBS_104))
    monkeypatch.setattr(j104, "AsyncSession", session_factory(session))

    jobs = await Jobs104Adapter().search("golang")
    first = jobs[0]
    assert first.id == "12345"
    assert first.title == "Golang Backend Engineer"
    assert first.company == "Acme Corp"
    assert first.salary == "80,000–120,000"
    assert first.url == "//www.104.com.tw/job/abc"
    # str tags kept, dict tags flattened via .name, falsy dropped.
    assert first.tags == ["Go", "Kafka"]


async def test_104_incomplete_salary_becomes_empty(monkeypatch):
    session = FakeSession(FakeResponse(json_data=_JOBS_104))
    monkeypatch.setattr(j104, "AsyncSession", session_factory(session))

    jobs = await Jobs104Adapter().search("x")
    assert jobs[1].salary == ""


async def test_104_handles_dict_shaped_data_with_list_key(monkeypatch):
    payload = {"data": {"list": _JOBS_104["data"]}}
    session = FakeSession(FakeResponse(json_data=payload))
    monkeypatch.setattr(j104, "AsyncSession", session_factory(session))

    jobs = await Jobs104Adapter().search("x")
    assert len(jobs) == 2


async def test_104_limit_caps_results(monkeypatch):
    session = FakeSession(FakeResponse(json_data=_JOBS_104))
    monkeypatch.setattr(j104, "AsyncSession", session_factory(session))

    jobs = await Jobs104Adapter().search("x", limit=1)
    assert len(jobs) == 1


# --- CakeResume ----------------------------------------------------------


def _next_data_html(entities: dict) -> str:
    payload = {
        "props": {
            "pageProps": {"initialState": {"jobSearch": {"entityByPathId": entities}}}
        }
    }
    blob = json.dumps(payload)
    return (
        "<html><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{blob}</script>'
        "</body></html>"
    )


_CK_ENTITIES = {
    "company-x/jobs/backend-eng": {
        "title": "Backend Engineer",
        "page": {"name": "Company X"},
        "locations": ["Taipei"],
        "contentUpdatedAt": "2026-06-01T12:34:56Z",
        "tags": ["Go", "Redis", 5],  # non-str dropped
        "salary": {"min": "800000", "max": "1200000", "type": "per_year"},
        "description": "desc",
    }
}


async def test_cakeresume_parses_next_data_blob(monkeypatch):
    html = _next_data_html(_CK_ENTITIES)
    session = FakeSession(FakeResponse(text=html))
    monkeypatch.setattr(ck, "AsyncSession", session_factory(session))

    jobs = await CakeResumeAdapter().search("backend")
    job = jobs[0]
    assert job.id == "company-x/jobs/backend-eng"
    assert job.url == "https://www.cakeresume.com/jobs/company-x/jobs/backend-eng"
    assert job.title == "Backend Engineer"
    assert job.company == "Company X"
    assert job.location == "Taipei"
    assert job.posted_at == "2026-06-01"  # truncated to YYYY-MM-DD
    assert job.tags == ["Go", "Redis"]
    assert job.salary == "800,000–1,200,000/年"


async def test_cakeresume_missing_next_data_returns_empty(monkeypatch):
    session = FakeSession(FakeResponse(text="<html>no next data</html>"))
    monkeypatch.setattr(ck, "AsyncSession", session_factory(session))
    assert await CakeResumeAdapter().search("x") == []


async def test_cakeresume_malformed_json_returns_empty(monkeypatch):
    bad = '<script id="__NEXT_DATA__" type="application/json">{not json}</script>'
    session = FakeSession(FakeResponse(text=bad))
    monkeypatch.setattr(ck, "AsyncSession", session_factory(session))
    assert await CakeResumeAdapter().search("x") == []


# --- _format_salary (pure) ----------------------------------------------


@pytest.mark.parametrize(
    "salary,expected",
    [
        (None, ""),
        ({}, ""),
        ({"min": 0, "max": 0}, ""),
        (
            {"min": "800000", "max": "1200000", "type": "per_year"},
            "800,000–1,200,000/年",
        ),
        ({"min": "40000", "max": "60000", "type": "per_month"}, "40,000–60,000/月"),
        ({"min": "40000", "max": "60000"}, "40,000–60,000"),  # no type -> no suffix
        ({"min": "a", "max": "b", "type": "per_month"}, "a–b/月"),  # non-numeric
    ],
)
def test_format_salary(salary, expected):
    assert _format_salary(salary) == expected
