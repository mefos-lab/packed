"""Smoke tests for the MCP server module itself.

These exist because of a real outage: `packed/server.py` silently
stopped importing when pip installed mcp 2.0.0 (which removed the
`@server.list_tools()` decorator API the server is built on). The
unpinned `mcp>=1.0.0` dependency allowed it, and nothing caught it —
every other test imports clients and patterns directly and never
touches the server, so the full suite passed while the actual product
could not start.

The point of this file is that the server is now exercised by the test
suite at all. Keep at least an import + tool-registration check here.
"""

import asyncio

import pytest

import packed.server as server_module


@pytest.mark.asyncio
async def test_server_module_imports_and_lists_tools():
    """The decorator API must still be intact and tools must register."""
    tools = await server_module.list_tools()
    assert len(tools) > 0


@pytest.mark.asyncio
async def test_every_tool_has_name_description_and_schema():
    for tool in await server_module.list_tools():
        assert tool.name, "tool missing a name"
        assert tool.description, f"{tool.name} missing a description"
        assert tool.inputSchema, f"{tool.name} missing an inputSchema"


@pytest.mark.asyncio
async def test_tool_names_are_unique():
    names = [t.name for t in await server_module.list_tools()]
    assert len(names) == len(set(names))


@pytest.mark.asyncio
async def test_every_source_and_pattern_family_is_represented():
    """Guards against a whole family of tools failing to register."""
    names = [t.name for t in await server_module.list_tools()]
    for prefix in ("fec_", "lda_", "propublica_", "congress_", "pattern_"):
        assert any(n.startswith(prefix) for n in names), f"no {prefix}* tools registered"


@pytest.mark.asyncio
async def test_unknown_tool_is_handled_not_raised():
    result = await server_module.call_tool("definitely_not_a_real_tool", {})
    assert "Unknown tool" in result[0].text
