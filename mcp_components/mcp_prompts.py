import asyncio
import logging

from mcp.types import TextContent
from fastmcp.prompts.base import Message, PromptResult

from app import mcp, genius_client, GENIUS_ACCESS_TOKEN  # noqa: F401

logger = logging.getLogger("genius_mcp")

_TRUST_ORDER = {"artist_verified": 0, "accepted": 1, "unreviewed": 2}


def _compute_trust_level(annotation: dict) -> str:
    if annotation.get("verified"):
        return "artist_verified"
    elif annotation.get("state") == "accepted":
        return "accepted"
    else:
        return "unreviewed"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _search_song(song_title: str, artist_name: str) -> dict | None:
    """Return the first song hit for the query, or None if not found."""
    q = f"{song_title} {artist_name}".strip()
    response = await genius_client.get("/search", params={"q": q, "type": "song"})
    if response.status_code != 200:
        return None
    hits = response.json().get("response", {}).get("hits", [])
    if not hits:
        return None
    song = hits[0].get("result", {})
    return {
        "song_id": song.get("id"),
        "full_title": song.get("full_title"),
        "artist_name": song.get("primary_artist", {}).get("name"),
        "url": song.get("url"),
    }


async def _search_artist(artist_name: str) -> dict | None:
    """Return the first artist hit for the query, or None if not found."""
    response = await genius_client.get(
        "/search", params={"q": artist_name, "type": "artist"}
    )
    if response.status_code != 200:
        return None
    hits = response.json().get("response", {}).get("hits", [])
    if not hits:
        return None
    song = hits[0].get("result", {})
    artist = song.get("primary_artist", {})
    return {
        "artist_id": artist.get("id"),
        "name": artist.get("name"),
        "url": artist.get("url"),
    }


async def _get_song_details(song_id: int) -> dict:
    response = await genius_client.get(
        f"/songs/{song_id}", params={"text_format": "plain"}
    )
    if response.status_code != 200:
        return {}
    song = response.json().get("response", {}).get("song", {})
    description_raw = song.get("description", {})
    description = (
        description_raw.get("plain", "") if isinstance(description_raw, dict) else ""
    )
    album = song.get("album") or {}
    return {
        "title": song.get("title", ""),
        "full_title": song.get("full_title", ""),
        "artist_name": song.get("primary_artist", {}).get("name", ""),
        "album_name": album.get("name"),
        "release_date": song.get("release_date"),
        "lyrics_state": song.get("lyrics_state", ""),
        "url": song.get("url", ""),
        "description": description,
        "annotation_count": song.get("annotation_count", 0),
        "unreviewed_annotations": song.get("stats", {}).get("unreviewed_annotations", 0),
    }


async def _get_artist_details(artist_id: int) -> dict:
    response = await genius_client.get(
        f"/artists/{artist_id}", params={"text_format": "plain"}
    )
    if response.status_code != 200:
        return {}
    artist = response.json().get("response", {}).get("artist", {})
    description_raw = artist.get("description", {})
    description = (
        description_raw.get("plain", "") if isinstance(description_raw, dict) else ""
    )
    return {
        "name": artist.get("name", ""),
        "url": artist.get("url", ""),
        "is_verified": artist.get("is_verified", False),
        "followers_count": artist.get("followers_count"),
        "description": description,
    }


async def _get_artist_top_songs(artist_id: int, per_page: int = 3) -> list[dict]:
    response = await genius_client.get(
        f"/artists/{artist_id}/songs",
        params={"sort": "popularity", "per_page": per_page},
    )
    if response.status_code != 200:
        return []
    songs = response.json().get("response", {}).get("songs", [])
    return [{"song_id": s.get("id"), "title": s.get("title", "")} for s in songs]


async def _get_referents(song_id: int) -> list[dict]:
    """Return raw list of referent dicts for a song."""
    response = await genius_client.get(
        "/referents",
        params={"song_id": song_id, "text_format": "plain", "per_page": 50},
    )
    if response.status_code != 200:
        return []
    return response.json().get("response", {}).get("referents", [])


async def _get_annotation_detail(annotation_id: int) -> str | None:
    """Return the plain-text body of an annotation, or None if the fetch fails."""
    response = await genius_client.get(
        f"/annotations/{annotation_id}", params={"text_format": "plain"}
    )
    if response.status_code != 200:
        return None
    annotation = response.json().get("response", {}).get("annotation", {})
    body_raw = annotation.get("body", {})
    return body_raw.get("plain", "") if isinstance(body_raw, dict) else ""


# ---------------------------------------------------------------------------
# Prompt 1: analyze-song
# ---------------------------------------------------------------------------

@mcp.prompt(
    name="analyze-song",
    description=(
        "Fetch full details and all annotations for a song, then ask the LLM to "
        "analyze its meaning, themes, and cultural context. Provide a song title and "
        "optionally an artist name for best results."
    ),
)
async def analyze_song(song_title: str, artist_name: str = "") -> PromptResult:
    # Step 1 — Search for the song
    hit = await _search_song(song_title, artist_name)
    if not hit:
        return PromptResult(
            messages=[
                Message(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f'Song not found on Genius: "{song_title}"'
                        + (f' by "{artist_name}"' if artist_name else ""),
                    ),
                )
            ]
        )

    song_id = hit["song_id"]
    url = hit["url"]

    # Step 2 — Get song details
    details = await _get_song_details(song_id)

    title = details.get("title", song_title)
    full_title = details.get("full_title", hit.get("full_title", song_title))
    artist = details.get("artist_name", hit.get("artist_name", ""))
    album_name = details.get("album_name") or "Unknown"
    release_date = details.get("release_date") or "Unknown"
    lyrics_state = details.get("lyrics_state", "")
    description = details.get("description", "").strip()
    annotation_count = details.get("annotation_count", 0)
    unreviewed_annotations = details.get("unreviewed_annotations", 0)

    # Step 3 — Get all annotations with IDs
    referents = await _get_referents(song_id)
    raw_annotations: list[dict] = []
    for referent in referents:
        annotation = referent.get("annotations", [{}])[0]
        annotation_id = annotation.get("id")
        if not annotation_id:
            continue
        raw_annotations.append({
            "annotation_id": annotation_id,
            "fragment": referent.get("fragment", ""),
            "trust_level": _compute_trust_level(annotation),
        })

    # Step 4 — Fetch full annotation detail for every annotation_id
    full_annotations: list[dict] = []
    for item in raw_annotations:
        body = await _get_annotation_detail(item["annotation_id"])
        if body is None:
            continue  # skip failed fetches silently
        full_annotations.append({
            "fragment": item["fragment"],
            "trust_level": item["trust_level"],
            "body": body,
        })

    # Step 5 — Sort by trust level
    full_annotations.sort(key=lambda a: _TRUST_ORDER.get(a["trust_level"], 99))

    # Step 6 — Assemble the prompt message
    annotations_block = ""
    for ann in full_annotations:
        annotations_block += (
            f"\n[TRUST LEVEL: {ann['trust_level']}]\n"
            f'Lyric fragment: "{ann["fragment"]}"\n'
            f"Explanation: {ann['body']}\n"
        )

    if not annotations_block:
        annotations_block = "\nNo annotations available.\n"

    message_text = f"""\
Analyze the meaning of "{full_title}".

=== SONG INFO ===
Title: {title}
Artist: {artist}
Album: {album_name}
Release Date: {release_date}
Lyrics State: {lyrics_state}
Total Annotations: {annotation_count}
Unreviewed Annotations: {unreviewed_annotations}
Genius URL: {url}

=== EDITORIAL DESCRIPTION ===
{description if description else "No editorial description available."}

=== ANNOTATIONS ===
(Sorted by trust level: artist_verified > accepted > unreviewed)
{annotations_block}
===

Based on all the above, please provide a deep analysis of this song.
Cover its core themes, emotional meaning, cultural or historical context, and any \
notable references or symbolism found in the annotations. Where relevant, distinguish \
between what the artist confirmed versus community interpretations."""

    return PromptResult(
        messages=[
            Message(
                role="user",
                content=TextContent(type="text", text=message_text),
            )
        ]
    )


# ---------------------------------------------------------------------------
# Prompt 2: artist-deep-dive
# ---------------------------------------------------------------------------

@mcp.prompt(
    name="artist-deep-dive",
    description=(
        "Fetch an artist's full bio and their top 3 most popular songs with "
        "artist-verified annotations where available, then ask the LLM to give an "
        "overview of the artist's themes, style, and significance. Falls back "
        "gracefully to editorial descriptions only if the artist has no verified "
        "annotations on Genius."
    ),
)
async def artist_deep_dive(artist_name: str) -> PromptResult:
    # Step 1 — Search for the artist
    hit = await _search_artist(artist_name)
    if not hit:
        return PromptResult(
            messages=[
                Message(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f'Artist not found on Genius: "{artist_name}"',
                    ),
                )
            ]
        )

    artist_id = hit["artist_id"]

    # Steps 2 & 3 — Fetch artist details and top songs in parallel
    artist_details, top_songs = await asyncio.gather(
        _get_artist_details(artist_id),
        _get_artist_top_songs(artist_id, per_page=3),
    )
    name = artist_details.get("name", hit.get("name", artist_name))
    artist_url = artist_details.get("url", hit.get("url", ""))
    is_verified = artist_details.get("is_verified", False)
    followers_count = artist_details.get("followers_count")
    artist_bio = artist_details.get("description", "").strip()

    # Step 4 — For each song, fetch details and referents in parallel
    async def _fetch_song_data(song_stub: dict) -> dict:
        song_id = song_stub["song_id"]

        # 4a & 4b in parallel
        song_details, referents = await asyncio.gather(
            _get_song_details(song_id),
            _get_referents(song_id),
        )
        song_full_title = song_details.get("full_title", song_stub.get("title", ""))
        song_album = song_details.get("album_name") or "Unknown"
        song_release = song_details.get("release_date") or "Unknown"
        song_desc = song_details.get("description", "").strip()

        verified_raw = [
            {"annotation_id": referent.get("annotations", [{}])[0].get("id"), "fragment": referent.get("fragment", "")}
            for referent in referents
            if referent.get("annotations", [{}])[0].get("verified")
            and referent.get("annotations", [{}])[0].get("id")
        ]

        # 4c — Fetch all verified annotation bodies in parallel
        bodies = await asyncio.gather(
            *[_get_annotation_detail(item["annotation_id"]) for item in verified_raw]
        )
        verified_full = [
            {"fragment": item["fragment"], "body": body}
            for item, body in zip(verified_raw, bodies)
            if body is not None
        ]

        return {
            "full_title": song_full_title,
            "album_name": song_album,
            "release_date": song_release,
            "description": song_desc,
            "verified_annotations": verified_full,
        }

    # All songs fetched in parallel
    songs_data: list[dict] = list(await asyncio.gather(*[_fetch_song_data(s) for s in top_songs]))
    total_verified = sum(len(s["verified_annotations"]) for s in songs_data)

    # Step 5 — Determine whether any verified annotations exist
    has_verified_annotations = total_verified > 0

    # Step 6 — Assemble the prompt message

    # Build the top-3 songs section
    songs_block = ""
    if not has_verified_annotations:
        songs_block += (
            "Note: This artist has no artist-verified annotations on Genius.\n"
            "Song analysis is based on editorial descriptions only.\n"
        )

    for i, song in enumerate(songs_data, start=1):
        songs_block += f"\n--- Song {i}: {song['full_title']} ---\n"
        songs_block += f"Album: {song['album_name']}\n"
        songs_block += f"Release Date: {song['release_date']}\n"
        songs_block += "\nEditorial Description:\n"
        songs_block += (song["description"] if song["description"] else "None.") + "\n"

        if has_verified_annotations:
            songs_block += "\nArtist-Verified Annotations:\n"
            songs_block += (
                "(These are explanations written or confirmed by the artist themselves)\n"
            )
            if song["verified_annotations"]:
                for ann in song["verified_annotations"]:
                    songs_block += f'\nLyric fragment: "{ann["fragment"]}"\n'
                    songs_block += f"Artist explanation: {ann['body']}\n"
            else:
                songs_block += "No artist-verified annotations for this song.\n"

    if not songs_data:
        songs_block += "\nNo songs found for this artist.\n"

    # Build the closing instruction
    if has_verified_annotations:
        closing = (
            "Where artist-verified annotations are available, use the artist's own words "
            "to highlight their stated intentions and creative vision. Note which insights "
            "come directly from the artist versus editorial sources."
        )
    else:
        closing = (
            "Note that this artist has not verified any annotations on Genius, so the "
            "analysis should be based on the editorial descriptions and bio alone."
        )

    message_text = f"""\
Give me a deep dive on the artist "{artist_name}".

=== ARTIST PROFILE ===
Name: {name}
Genius Verified Artist: {is_verified}
Followers: {followers_count}
Genius URL: {artist_url}

=== ARTIST BIO ===
{artist_bio if artist_bio else "No bio available."}

=== TOP 3 MOST POPULAR SONGS ===
{songs_block}
===

Based on all the above, please provide an overview of this artist.
Cover their recurring themes, lyrical style, and artistic significance.

{closing}"""

    return PromptResult(
        messages=[
            Message(
                role="user",
                content=TextContent(type="text", text=message_text),
            )
        ]
    )
