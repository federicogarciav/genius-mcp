<div align="center">

# Genius MCP Server

<img src="sources/genius.png" alt="Genius MCP Server" width="200"/>

**An MCP server that brings the power of [Genius](https://genius.com) into your AI assistant.**

Query songs, artists, lyrics annotations, album artwork annotations, and editorial knowledge through a clean set of tools and prompts — powered by both the official Genius API and the `lyricsgenius` Python library.

</div>

---

## Table of Contents

- [What It Does](#what-it-does)
- [Tools](#tools)
- [Prompts](#prompts)
- [Getting Started](#getting-started)
  - [1. Get a Genius API Token](#1-get-a-genius-api-token)
  - [2. Configure Environment Variables](#2-configure-environment-variables)
  - [3. Run with Python](#3-run-with-python)
  - [4. Run with Docker](#4-run-with-docker)
- [Transport Modes](#transport-modes)
- [Connecting to an MCP Client](#connecting-to-an-mcp-client)
- [Annotation Trust Levels](#annotation-trust-levels)
- [Project Structure](#project-structure)
- [License](#license)

---

## What It Does

The Genius MCP Server exposes the Genius.com knowledge base to any MCP-compatible AI client (Claude Desktop, Claude Code, Cursor, etc.). It lets the AI:

- **Search** for songs and artists by name
- **Fetch full song metadata** — title, album, release date, lyrics state, and Genius editorial descriptions
- **Fetch artist profiles** — bio, follower count, verification status
- **Browse an artist's discography** — sorted by popularity or release date, or as a full album list with tracklists
- **Read annotations** — community and artist-verified explanations of specific lyric fragments, each tagged with a trust level so the AI knows how much weight to give them
- **Read album artwork annotations** — community explanations of visual elements, symbolism, and artistic choices written directly on album cover art images
- **Run pre-built analysis prompts** that gather all relevant data in one shot and ask the AI for a deep analysis of a song or artist

---

## Tools

Some tools call the **official Genius API** (`api.genius.com`) using your access token. Others use the **`lyricsgenius` Python library**, which accesses Genius's undocumented public API — these endpoints are not part of the official API contract and may change without notice.

| Tool | Description | Backend |
|---|---|---|
| `search_song` | Search Genius for songs matching a query. Returns song IDs, titles, artists, and annotation counts. | Official API |
| `search_artist` | Search Genius for an artist by name. Returns artist IDs and basic profile info. | Official API |
| `get_song_details` | Fetch full metadata and editorial description for a song by its Genius ID. | Official API |
| `get_artist_details` | Fetch full profile and editorial bio for an artist by their Genius ID. | Official API |
| `get_artist_songs` | List songs by an artist, sortable by `popularity` or `release_date`, with pagination. | Official API |
| `get_song_annotations` | Fetch all annotations for a song, optionally filtered by trust level (`artist_verified`, `accepted`, `unreviewed`). | Official API |
| `get_annotation_detail` | Fetch the full text and metadata of a single annotation by its ID. | Official API |
| `get_song_questions_and_answers` | Fetch user-submitted questions and answers for a song, with pagination. Only questions that have an accepted answer are returned. | `lyricsgenius` (public undocumented API) |
| `search_album` | Search Genius for albums matching a query. Returns album IDs, names, artist names, and release dates. | `lyricsgenius` (public undocumented API) |
| `get_artist_albums` | Retrieve the full discography of an artist as a paginated list of albums with album IDs. | `lyricsgenius` (public undocumented API) |
| `get_album_details` | Fetch metadata, full ordered tracklist, and cover art list for an album by its Genius album ID. Each track includes its song ID for chaining into other tools. The first cover art is always the main album cover; annotated artworks include an `annotation_id`. | Official API + `lyricsgenius` |
| `get_cover_art_annotations` | Fetch the full annotation written on a specific album cover art image — body text, trust level, authors, and vote count. Requires `cover_art_id` and `album_id` (both available from `get_album_details`). Only call for cover arts that have an `annotation_id`. | `lyricsgenius` (public undocumented API) |

---

## Prompts

Prompts are pre-built multi-step workflows that gather data from Genius and feed it to the AI in a structured context.

### `analyze-song`

**Args:** `song_title` (required), `artist_name` (optional)

Searches for the song, fetches its full metadata and editorial description, retrieves all annotations (sorted by trust level), and asks the AI for a deep analysis of the song's meaning, themes, and cultural context.

### `artist-deep-dive`

**Args:** `artist_name` (required)

Fetches the artist's full bio, their top 3 most popular songs with metadata and artist-verified annotations (where available), and asks the AI for an overview of the artist's themes, style, and significance.

---

## Getting Started

### 1. Get a Genius API Token

1. Go to [https://genius.com/api-clients](https://genius.com/api-clients) and sign in.
2. Create a new API client.
3. Copy the **Client Access Token** — this is the value you'll use for `GENIUS_ACCESS_TOKEN`.

### 2. Configure Environment Variables

Copy the example env file and fill in your token:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Required — your Genius API access token
GENIUS_ACCESS_TOKEN=your_token_here

# Transport mode:
# true  → run as a Streamable HTTP server on port 8080
# false → run in stdio mode (for Claude Desktop)
STREAMABLE_HTTP=true
```

### 3. Run with Python

**Requirements:** Python 3.11+

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the server:

```bash
python main.py
```

The server will start on `http://127.0.0.1:8080` (Streamable HTTP mode) or in stdio mode depending on your `STREAMABLE_HTTP` setting.

### 4. Run with Docker

**Streamable HTTP mode** (default):

```bash
docker compose up --build
```

The server runs as `genius-mcp-server` on port 8080. The `.env` file is mounted into the container — make sure it exists and contains your token before starting.

**stdio mode** (e.g. for Claude Desktop via Docker):

Set `STREAMABLE_HTTP=false` in your `.env`, then run:

```bash
docker run --rm -i --env-file .env $(docker build -q .)
```

---

## Transport Modes

| Mode | `STREAMABLE_HTTP` | Use Case |
|---|---|---|
| Streamable HTTP | `true` (default) | Claude Code, remote MCP clients, web-based tools |
| stdio | `false` | Claude Desktop, local CLI integrations |

---

## Connecting to an MCP Client

### Claude Code (Streamable HTTP)

```bash
claude mcp add genius --transport http http://127.0.0.1:8080/mcp
```

### Claude Desktop (stdio)

With `STREAMABLE_HTTP=false` in your `.env`, add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "genius": {
      "command": "python",
      "args": ["/absolute/path/to/genius-mcp/main.py"],
      "env": {
        "GENIUS_ACCESS_TOKEN": "your_token_here",
        "STREAMABLE_HTTP": "false"
      }
    }
  }
}
```

---

## Annotation Trust Levels

Every annotation returned by the server includes a `trust_level` field. This lets the AI reason about source reliability:

| Trust Level | Meaning |
|---|---|
| `artist_verified` | Written or confirmed by the artist. Treat as ground truth. |
| `accepted` | Reviewed and approved by Genius editorial staff. High quality. |
| `unreviewed` | Submitted by community users, not yet reviewed. Treat as interpretation. |

The `get_song_annotations` tool accepts a `filter` argument to retrieve only annotations at a specific trust level.

---

## Project Structure

```
genius-mcp/
├── main.py                    # Entry point — configures transport and starts the server
├── app.py                     # FastMCP app instance
├── mcp_components/
│   ├── genius_api.py          # Async HTTP client for the Genius API
│   ├── mcp_tools.py           # MCP tool definitions
│   └── mcp_prompts.py         # MCP prompt definitions
├── tests/
│   ├── test_mcp_server_initialization.py
│   └── test_mcp_server_tools.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## License

[MIT](LICENSE)
