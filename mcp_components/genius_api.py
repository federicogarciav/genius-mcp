import asyncio
import logging
import os

import httpx
import lyricsgenius
from dotenv import load_dotenv

load_dotenv()

_token = os.getenv("GENIUS_ACCESS_TOKEN")
if not _token:
    raise RuntimeError(
        "GENIUS_ACCESS_TOKEN is not set. Copy .env.example to .env and add your token "
        "from https://genius.com/api-clients"
    )

genius_client = httpx.AsyncClient(
    base_url="https://api.genius.com",
    headers={"Authorization": f"Bearer {_token}"},
)

_public_api = lyricsgenius.PublicAPI(_token)

logger = logging.getLogger("genius_mcp")


class GeniusAPIError(Exception):
    def __init__(self, status_code: int, endpoint: str) -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(f"Genius API returned status {status_code} for {endpoint}")


def compute_trust_level(item: dict) -> str:
    if item.get("verified"):
        return "artist_verified"
    elif item.get("state") == "accepted":
        return "accepted"
    else:
        return "unreviewed"


async def search(q: str, per_page: int = 5) -> list[dict]:
    """GET /search. Returns the hits list. Raises GeniusAPIError on non-200."""
    response = await genius_client.get("/search", params={"q": q, "per_page": per_page})
    logger.debug("GET /search → %d", response.status_code)
    if response.status_code != 200:
        logger.error("GET /search failed | status=%d", response.status_code)
        raise GeniusAPIError(response.status_code, "/search")
    return response.json().get("response", {}).get("hits", [])


async def get_song(song_id: int) -> dict:
    """GET /songs/{song_id}. Returns the song object. Raises GeniusAPIError on non-200."""
    response = await genius_client.get(f"/songs/{song_id}", params={"text_format": "plain"})
    logger.debug("GET /songs/%d → %d", song_id, response.status_code)
    if response.status_code != 200:
        logger.error("GET /songs/%d failed | status=%d", song_id, response.status_code)
        raise GeniusAPIError(response.status_code, f"/songs/{song_id}")
    return response.json().get("response", {}).get("song", {})


async def get_artist(artist_id: int) -> dict:
    """GET /artists/{artist_id}. Returns the artist object. Raises GeniusAPIError on non-200."""
    response = await genius_client.get(f"/artists/{artist_id}", params={"text_format": "plain"})
    logger.debug("GET /artists/%d → %d", artist_id, response.status_code)
    if response.status_code != 200:
        logger.error("GET /artists/%d failed | status=%d", artist_id, response.status_code)
        raise GeniusAPIError(response.status_code, f"/artists/{artist_id}")
    return response.json().get("response", {}).get("artist", {})


async def get_artist_songs(
    artist_id: int,
    sort: str = "popularity",
    per_page: int = 10,
    page: int = 1,
) -> list[dict]:
    """GET /artists/{artist_id}/songs. Returns the songs list. Raises GeniusAPIError on non-200."""
    response = await genius_client.get(
        f"/artists/{artist_id}/songs",
        params={"sort": sort, "per_page": per_page, "page": page},
    )
    logger.debug("GET /artists/%d/songs → %d", artist_id, response.status_code)
    if response.status_code != 200:
        logger.error("GET /artists/%d/songs failed | status=%d", artist_id, response.status_code)
        raise GeniusAPIError(response.status_code, f"/artists/{artist_id}/songs")
    return response.json().get("response", {}).get("songs", [])


async def get_referents(song_id: int, per_page: int = 50) -> list[dict]:
    """GET /referents. Returns the referents list. Raises GeniusAPIError on non-200."""
    response = await genius_client.get(
        "/referents",
        params={"song_id": song_id, "text_format": "plain", "per_page": per_page},
    )
    logger.debug("GET /referents (song_id=%d) → %d", song_id, response.status_code)
    if response.status_code != 200:
        logger.error("GET /referents failed | song_id=%d status=%d", song_id, response.status_code)
        raise GeniusAPIError(response.status_code, "/referents")
    return response.json().get("response", {}).get("referents", [])


async def get_annotation(annotation_id: int) -> tuple[dict, dict]:
    """GET /annotations/{annotation_id}. Returns (annotation, referent). Raises GeniusAPIError on non-200."""
    response = await genius_client.get(
        f"/annotations/{annotation_id}", params={"text_format": "plain"}
    )
    logger.debug("GET /annotations/%d → %d", annotation_id, response.status_code)
    if response.status_code != 200:
        logger.error("GET /annotations/%d failed | status=%d", annotation_id, response.status_code)
        raise GeniusAPIError(response.status_code, f"/annotations/{annotation_id}")
    data = response.json().get("response", {})
    return data.get("annotation", {}), data.get("referent", {})


async def get_song_questions(
    song_id: int,
    per_page: int = 20,
    page: int = 1,
) -> dict:
    """Calls genius.com/api/questions via lyricsgenius.PublicAPI.
    Returns the response dict. Raises GeniusAPIError on non-200."""
    endpoint = "genius.com/api/questions"
    try:
        result = await asyncio.to_thread(
            _public_api.questions,
            song_id=song_id,
            per_page=per_page,
            page=page,
            text_format="plain",
        )
    except AssertionError as e:
        # lyricsgenius raises AssertionError with message "Unexpected response status code: N..."
        parts = str(e).split("status code: ")
        status_code = int(parts[1].split(".")[0]) if len(parts) > 1 else 0
        logger.error("GET %s failed | song_id=%d status=%d", endpoint, song_id, status_code)
        raise GeniusAPIError(status_code, endpoint) from e
    logger.debug("GET %s (song_id=%d) → 200", endpoint, song_id)
    return result
