"""MCP stdio smoke tests: spawn the real server over stdio, check the tool
list, and check that instructive errors actually reach the client."""

import os
import sys

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

EXPECTED_TOOLS = {
    "wiki_update",
    "wiki_status",
    "wiki_search",
    "wiki_sections",
    "wiki_page",
    "wiki_links",
}


def _params(env_dir):
    env = dict(os.environ)
    env["OSDEV_WIKI_DIR"] = str(env_dir)
    return StdioServerParameters(command=sys.executable, args=["-m", "osdev_wiki_mcp"], env=env)


@pytest.mark.anyio
async def test_stdio_handshake_lists_expected_tools(tmp_path):
    async with stdio_client(_params(tmp_path)) as (read, write), ClientSession(read, write) as session:
        init_result = await session.initialize()
        assert init_result.server_info.name == "osdev-wiki"
        names = {t.name for t in (await session.list_tools()).tools}
        assert names == EXPECTED_TOOLS, (
            f"missing: {EXPECTED_TOOLS - names}, unexpected: {names - EXPECTED_TOOLS}"
        )


@pytest.mark.anyio
async def test_no_index_error_reaches_the_agent(tmp_path):
    """MCPServer hides non-ToolError exceptions behind 'Error executing tool X';
    the 'call wiki_update first' instruction must survive the trip."""
    async with stdio_client(_params(tmp_path)) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("wiki_search", {"query": "paging"})
        assert result.is_error
        assert "call wiki_update first" in result.content[0].text


@pytest.mark.anyio
async def test_search_over_stdio(wiki_dir):
    async with stdio_client(_params(wiki_dir)) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("wiki_search", {"query": "IDT", "limit": 2})
        assert not result.is_error
        assert result.content[0].text.startswith("1. Interrupt Descriptor Table *")


@pytest.fixture
def anyio_backend():
    return "asyncio"
