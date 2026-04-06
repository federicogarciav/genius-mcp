from fastmcp import FastMCP

mcp = FastMCP(
    name="Genius MCP Server",
    instructions=(
        "This server allows an LLM to explore music meaning by searching for songs, "
        "artists, and albums on Genius, fetching their details, and reading "
        "crowd-sourced and artist-verified annotations."
    ),
)

from mcp_components import mcp_tools  # noqa: E402, F401 — registers tools on mcp
import mcp_components.mcp_prompts  # noqa: E402, F401 — registers prompts on mcp
