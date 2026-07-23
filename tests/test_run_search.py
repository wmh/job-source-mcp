"""Unit tests for the core search logic, focused on the rate-limited-vs-empty
distinction that is the whole point of this server's error handling."""

from __future__ import annotations

from conftest import FakeAdapter, make_job, rate_limit_adapter

from job_source_mcp.server import run_search


async def test_aggregates_jobs_from_all_sources():
    registry = {
        "104": FakeAdapter("104", jobs=[make_job("104", "a")]),
        "yourator": FakeAdapter("yourator", jobs=[make_job("yourator", "b")]),
    }
    result = await run_search(registry, keyword="go", source="all")

    assert result["count"] == 2
    assert {j["source"] for j in result["jobs"]} == {"104", "yourator"}
    assert result["rate_limited"] == []
    assert result["errors"] == []


async def test_source_filter_selects_single_adapter():
    called = FakeAdapter("104", jobs=[make_job("104", "a")])
    skipped = FakeAdapter("yourator", jobs=[make_job("yourator", "b")])
    registry = {"104": called, "yourator": skipped}

    result = await run_search(registry, keyword="go", source="104")

    assert result["count"] == 1
    assert result["jobs"][0]["source"] == "104"
    assert called.calls and not skipped.calls  # only the selected source ran


async def test_empty_result_has_no_rate_limited_entries():
    """0 jobs with empty rate_limited => genuinely no matches."""
    registry = {"104": FakeAdapter("104", jobs=[])}

    result = await run_search(registry, keyword="nothing", source="104")

    assert result["count"] == 0
    assert result["rate_limited"] == []
    assert result["errors"] == []


async def test_rate_limited_source_is_not_mistaken_for_empty():
    """0 jobs but a rate_limited entry => couldn't fetch, NOT no matches."""
    registry = {"linkedin": rate_limit_adapter("linkedin", interval=99.0)}

    result = await run_search(registry, keyword="go", source="linkedin")

    assert result["count"] == 0
    assert result["rate_limited"] == [{"source": "linkedin", "retry_after": 99.0}]
    # Also mirrored in errors with the distinguishing type.
    assert result["errors"][0]["source"] == "linkedin"
    assert result["errors"][0]["type"] == "rate_limited"


async def test_rate_limit_does_not_suppress_other_sources():
    registry = {
        "104": FakeAdapter("104", jobs=[make_job("104", "a")]),
        "linkedin": rate_limit_adapter("linkedin"),
    }

    result = await run_search(registry, keyword="go", source="all")

    assert result["count"] == 1  # 104's job still comes through
    assert result["jobs"][0]["source"] == "104"
    assert [r["source"] for r in result["rate_limited"]] == ["linkedin"]


async def test_generic_error_is_typed_error_not_rate_limited():
    registry = {"104": FakeAdapter("104", raises=ValueError("boom"))}

    result = await run_search(registry, keyword="go", source="104")

    assert result["count"] == 0
    assert result["rate_limited"] == []  # a plain error is NOT a rate limit
    assert result["errors"][0]["type"] == "error"
    assert "boom" in result["errors"][0]["error"]


async def test_limit_is_clamped_and_applied_across_all_sources():
    registry = {
        "104": FakeAdapter("104", jobs=[make_job("104", str(i)) for i in range(10)]),
        "yourator": FakeAdapter(
            "yourator", jobs=[make_job("yourator", str(i)) for i in range(10)]
        ),
    }

    # limit=3 should cap the merged result even though each source has 10.
    result = await run_search(registry, keyword="go", source="all", limit=3)
    assert result["count"] == 3

    # Over-max limit is clamped to 50; under-min to 1.
    big = await run_search(registry, keyword="go", source="104", limit=999)
    assert big["count"] <= 50
    assert registry["104"].calls[-1]["limit"] == 50

    small = await run_search(registry, keyword="go", source="104", limit=0)
    assert registry["104"].calls[-1]["limit"] == 1
    assert small["count"] == 1


async def test_page_is_floored_to_one():
    adapter = FakeAdapter("104", jobs=[make_job("104", "a")])
    await run_search({"104": adapter}, keyword="go", source="104", page=-5)
    assert adapter.calls[-1]["page"] == 1


async def test_blank_location_normalized_to_none():
    adapter = FakeAdapter("104", jobs=[])
    await run_search({"104": adapter}, keyword="go", source="104", location="   ")
    assert adapter.calls[-1]["location"] is None
