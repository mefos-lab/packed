"""Smoke tests for the MCP server module itself.

These exist because of a real outage: `packed/server.py` silently
stopped importing when pip installed mcp 2.0.0 (which removed the
`@server.list_tools()` decorator API the server was built on). The
unpinned `mcp>=1.0.0` dependency allowed it, and nothing caught it —
every other test imports clients and patterns directly and never
touches the server, so the full suite passed while the actual product
could not start.

The server has since been migrated to mcp 2.x via `packed/mcp_compat.py`,
which preserves the hand-authored tool schemas instead of letting 2.0
derive them from function signatures. That shim writes to a private
attribute of the SDK's tool manager, because 2.0 offers no public way to
register a pre-built schema. `test_registered_schemas_match_definitions`
is what makes that seam safe: if a future SDK release breaks it, the
schemas stop matching and this fails loudly, rather than the server
quietly advertising degraded schemas the model then calls wrong.
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
async def test_registered_schemas_match_definitions():
    """Every schema the SDK advertises must equal the one we authored.

    This is the guard on the mcp_compat shim. A derived-schema regression
    is silent — the tool still registers, it just loses enums, field
    descriptions or required/optional distinctions — so compare exactly.
    """
    definitions = await server_module.list_tools()
    await server_module._register()
    advertised = {t.name: t for t in await server_module.server.list_tools()}

    assert len(advertised) == len(definitions)
    for d in definitions:
        a = advertised.get(d.name)
        assert a is not None, f"{d.name} was not registered"
        assert a.input_schema == d.inputSchema, f"{d.name} schema drifted from its definition"
        assert a.description == d.description, f"{d.name} description drifted"


@pytest.mark.asyncio
async def test_enums_survive_registration():
    """Spot-check the detail most easily lost by signature-derived schemas."""
    await server_module._register()
    advertised = {t.name: t for t in await server_module.server.list_tools()}
    assert advertised["fec_search_candidates"].input_schema["properties"]["office"]["enum"] == ["H", "S", "P"]
    assert advertised["fec_search_independent_expenditures"].input_schema[
        "properties"]["support_oppose_indicator"]["enum"] == ["S", "O"]


@pytest.mark.asyncio
async def test_unknown_tool_is_handled_not_raised():
    result = await server_module.call_tool("definitely_not_a_real_tool", {})
    assert "Unknown tool" in result[0].text
