"""Thin integration tests: the tools are registered on the server and the
search_jobs tool is wired to the injected adapter registry."""

from __future__ import annotations

import json

from conftest import FakeAdapter, make_job, rate_limit_adapter

from job_source_mcp.server import create_server


def _json(result) -> dict:
    """FastMCP.call_tool returns serialized content blocks; pull out the JSON."""
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


async def test_tools_are_registered():
    server = create_server(registry={})
    names = {t.name for t in await server.list_tools()}
    assert {"ping", "session_status", "search_jobs"} <= names


async def test_ping_ok():
    server = create_server(registry={})
    assert _json(await server.call_tool("ping", {}))["ok"] is True


async def test_search_jobs_tool_uses_injected_registry():
    registry = {"104": FakeAdapter("104", jobs=[make_job("104", "a")])}
    server = create_server(registry=registry)

    payload = _json(
        await server.call_tool("search_jobs", {"keyword": "go", "source": "104"})
    )
    assert payload["count"] == 1
    assert payload["jobs"][0]["source"] == "104"


async def test_search_jobs_tool_surfaces_rate_limited():
    registry = {"linkedin": rate_limit_adapter("linkedin", interval=12.0)}
    server = create_server(registry=registry)

    payload = _json(
        await server.call_tool("search_jobs", {"keyword": "go", "source": "linkedin"})
    )
    assert payload["count"] == 0
    assert payload["rate_limited"] == [{"source": "linkedin", "retry_after": 12.0}]
