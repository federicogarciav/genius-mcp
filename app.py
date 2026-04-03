import os
from dotenv import load_dotenv
import httpx
from fastmcp import FastMCP

load_dotenv()

GENIUS_ACCESS_TOKEN = os.getenv("GENIUS_ACCESS_TOKEN")
if not GENIUS_ACCESS_TOKEN:
    raise RuntimeError(
        "GENIUS_ACCESS_TOKEN is not set. Copy .env.example to .env and add your token "
        "from https://genius.com/api-clients"
    )

genius_client = httpx.AsyncClient(
    base_url="https://api.genius.com",
    headers={"Authorization": f"Bearer {GENIUS_ACCESS_TOKEN}"},
)

mcp = FastMCP(
    name="Genius MCP Server",
    instructions=(
        "This server allows an LLM to explore music meaning by searching for songs, "
        "artists, and albums on Genius, fetching their details, and reading "
        "crowd-sourced and artist-verified annotations."
    ),
)

from mcp_components import mcp_tools  # noqa: E402, F401 — registers tools on mcp
