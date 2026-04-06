import logging
from typing import Optional

from app import mcp
import mcp_components.genius_api as genius_api
from mcp_components.genius_api import GeniusAPIError, compute_trust_level

logger = logging.getLogger("genius_mcp")


def _extract_annotation(referent: dict) -> dict:
    annotation = referent.get("annotations", [{}])[0]
    authors = [
        {"username": a.get("user", {}).get("login", ""), "iq": a.get("pinned_role")}
        for a in annotation.get("authors", [])
    ]
    body_raw = annotation.get("body", {})
    body = body_raw.get("plain", "") if isinstance(body_raw, dict) else ""

    return {
        "annotation_id": annotation.get("id"),
        "fragment": referent.get("fragment", ""),
        "body": body,
        "trust_level": compute_trust_level(annotation),
        "state": annotation.get("state"),
        "verified": annotation.get("verified", False),
        "community": annotation.get("community", False),
        "votes_total": annotation.get("votes_total", 0),
        "authors": authors,
    }


@mcp.tool()
async def search_song(query: str, per_page: int = 5) -> list[dict]:
    """Search Genius for songs matching a query.

    Use this when the user provides a song title, or a song title and artist name.
    Returns a list of song matches with their IDs, which are required to fetch song
    details or annotations.

    Args:
        query: The search query, ideally "Song Title Artist Name"
        per_page: Number of results to return (max 10, default 5)
    """
    logger.info("search_song | query=%r per_page=%d", query, per_page)
    try:
        hits = await genius_api.search(query, per_page=per_page)
    except GeniusAPIError as e:
        return [{"error": f"Genius API returned status {e.status_code}"}]

    results = []
    for hit in hits:
        song = hit.get("result", {})
        results.append({
            "song_id": song.get("id"),
            "title": song.get("title"),
            "full_title": song.get("full_title"),
            "artist_name": song.get("primary_artist", {}).get("name"),
            "url": song.get("url"),
            "annotation_count": song.get("annotation_count"),
            "unreviewed_annotations": song.get("stats", {}).get("unreviewed_annotations"),
            "lyrics_state": song.get("lyrics_state"),
        })
    logger.info("search_song | returned %d results", len(results))
    return results


@mcp.tool()
async def search_artist(query: str, per_page: int = 5) -> list[dict]:
    """Search Genius for an artist by name.

    Use this when the user wants to explore an artist's profile, bio, or discography.
    Returns artist IDs required for fetching artist details or song lists.
    Note: followers_count is not available in search results — call get_artist_details
    with the returned artist_id to get the full profile including followers.

    Args:
        query: The artist name
        per_page: Number of results to return (max 10, default 5)
    """
    logger.info("search_artist | query=%r per_page=%d", query, per_page)
    # The Genius public API /search endpoint only returns songs. We extract unique
    # artists from the primary_artist field of the song results.
    try:
        hits = await genius_api.search(query, per_page=min(per_page * 3, 50))
    except GeniusAPIError as e:
        return [{"error": f"Genius API returned status {e.status_code}"}]

    seen_ids: set = set()
    results = []
    for hit in hits:
        artist = hit.get("result", {}).get("primary_artist", {})
        artist_id = artist.get("id")
        if artist_id and artist_id not in seen_ids:
            seen_ids.add(artist_id)
            results.append({
                "artist_id": artist_id,
                "name": artist.get("name"),
                "url": artist.get("url"),
                "is_verified": artist.get("is_verified", False),
                "followers_count": None,  # not available in search results
            })
        if len(results) >= per_page:
            break
    logger.info("search_artist | returned %d unique artists", len(results))
    return results


@mcp.tool()
async def search_album(query: str, per_page: int = 5) -> list[dict]:
    """Search Genius for an album by name or artist + album name.

    Use this when the user wants to explore an album, its tracklist, or context.
    Returns album IDs required for fetching album details.

    Note: The Genius public API does not support direct album search. This tool
    finds albums by searching for related songs and resolving their album via
    get_song_details. For best results, include both the album name and artist name
    in the query (e.g. "A Night at the Opera Queen").

    Args:
        query: The search query, ideally "Album Name Artist Name"
        per_page: Number of results to return (max 10, default 5)
    """
    logger.info("search_album | query=%r per_page=%d", query, per_page)
    # Search for songs matching the query, then resolve albums via song detail calls.
    try:
        hits = await genius_api.search(query, per_page=min(per_page * 3, 50))
    except GeniusAPIError as e:
        return [{"error": f"Genius API returned status {e.status_code}"}]

    seen_album_ids: set = set()
    results = []

    for hit in hits:
        if len(results) >= per_page:
            break
        song_id = hit.get("result", {}).get("id")
        if not song_id:
            continue

        # Fetch full song details to get album info
        try:
            song = await genius_api.get_song(song_id)
        except GeniusAPIError:
            continue
        album = song.get("album")
        if not album:
            continue
        album_id = album.get("id")
        if not album_id or album_id in seen_album_ids:
            continue
        seen_album_ids.add(album_id)
        results.append({
            "album_id": album_id,
            "name": album.get("name"),
            "full_title": album.get("full_title"),
            "artist_name": album.get("artist", {}).get("name"),
            "url": album.get("url"),
            "release_date": album.get("release_date_for_display"),
        })

    logger.info("search_album | returned %d albums", len(results))
    return results


@mcp.tool()
async def get_song_details(song_id: int) -> dict:
    """Fetch full metadata and editorial information for a specific song by its Genius song ID.

    Includes the song's editorial description written by Genius editors, which often
    explains the song's themes, context, and meaning. Always call this before fetching
    annotations to get the full picture.

    Args:
        song_id: The Genius song ID (obtained from search_song)
    """
    logger.info("get_song_details | song_id=%d", song_id)
    try:
        song = await genius_api.get_song(song_id)
    except GeniusAPIError as e:
        return {"error": f"Genius API returned status {e.status_code}"}

    description_raw = song.get("description", {})
    description = (
        description_raw.get("plain", "")
        if isinstance(description_raw, dict)
        else ""
    )
    album = song.get("album") or {}
    result = {
        "song_id": song.get("id"),
        "title": song.get("title"),
        "full_title": song.get("full_title"),
        "artist_name": song.get("primary_artist", {}).get("name"),
        "album_name": album.get("name"),
        "release_date": song.get("release_date"),
        "lyrics_state": song.get("lyrics_state"),
        "url": song.get("url"),
        "description": description,
        "annotation_count": song.get("annotation_count"),
        "unreviewed_annotations": song.get("stats", {}).get("unreviewed_annotations"),
    }
    logger.info("get_song_details | title=%r artist=%r", result["title"], result["artist_name"])
    return result


@mcp.tool()
async def get_artist_details(artist_id: int) -> dict:
    """Fetch full profile and editorial bio for a specific artist by their Genius artist ID.

    The description field often contains a rich editorial write-up about the artist's
    background, style, and significance.

    Args:
        artist_id: The Genius artist ID (obtained from search_artist)
    """
    logger.info("get_artist_details | artist_id=%d", artist_id)
    try:
        artist = await genius_api.get_artist(artist_id)
    except GeniusAPIError as e:
        return {"error": f"Genius API returned status {e.status_code}"}

    description_raw = artist.get("description", {})
    description = (
        description_raw.get("plain", "")
        if isinstance(description_raw, dict)
        else ""
    )
    result = {
        "artist_id": artist.get("id"),
        "name": artist.get("name"),
        "url": artist.get("url"),
        "is_verified": artist.get("is_verified", False),
        "description": description,
        "followers_count": artist.get("followers_count"),
    }
    logger.info("get_artist_details | name=%r verified=%s", result["name"], result["is_verified"])
    return result


@mcp.tool()
async def get_album_details(album_id: int) -> dict:
    """Fetch full metadata for a specific album by its Genius album ID.

    Includes the tracklist with song IDs, which can then be used to fetch details or
    annotations for individual songs.

    Args:
        album_id: The Genius album ID (obtained from search_album)
    """
    logger.info("get_album_details | album_id=%d", album_id)
    try:
        album = await genius_api.get_album(album_id)
    except GeniusAPIError as e:
        return {"error": f"Genius API returned status {e.status_code}"}

    description_raw = album.get("description", {})
    description = (
        description_raw.get("plain", "")
        if isinstance(description_raw, dict)
        else ""
    )
    tracks_raw = album.get("album_appearances", [])
    tracklist = [
        {
            "song_id": t.get("song", {}).get("id"),
            "title": t.get("song", {}).get("title"),
            "url": t.get("song", {}).get("url"),
        }
        for t in tracks_raw
        if t.get("song")
    ]
    result = {
        "album_id": album.get("id"),
        "name": album.get("name"),
        "full_title": album.get("full_title"),
        "artist_name": album.get("artist", {}).get("name"),
        "url": album.get("url"),
        "release_date": album.get("release_date"),
        "description": description,
        "tracklist": tracklist,
    }
    logger.info("get_album_details | name=%r tracks=%d", result["name"], len(tracklist))
    return result


@mcp.tool()
async def get_artist_songs(
    artist_id: int,
    sort: str = "popularity",
    per_page: int = 10,
    page: int = 1,
) -> list[dict]:
    """Retrieve a list of songs by a specific artist, sortable by popularity or release date.

    Use this to explore an artist's discography when the user wants to find a specific
    song or browse their catalog.

    Args:
        artist_id: The Genius artist ID
        sort: Sort order — "popularity" or "release_date" (default "popularity")
        per_page: Number of results (max 50, default 10)
        page: Page number for pagination (default 1)
    """
    logger.info("get_artist_songs | artist_id=%d sort=%r per_page=%d page=%d", artist_id, sort, per_page, page)
    try:
        songs = await genius_api.get_artist_songs(artist_id, sort=sort, per_page=per_page, page=page)
    except GeniusAPIError as e:
        return [{"error": f"Genius API returned status {e.status_code}"}]

    results = [
        {
            "song_id": s.get("id"),
            "title": s.get("title"),
            "url": s.get("url"),
            "annotation_count": s.get("annotation_count"),
        }
        for s in songs
    ]
    logger.info("get_artist_songs | returned %d songs", len(results))
    return results


@mcp.tool()
async def get_song_annotations(
    song_id: int, filter: Optional[str] = None
) -> list[dict]:
    """Fetch all annotations for a song.

    Each annotation corresponds to a highlighted lyric fragment and contains a community
    or artist explanation of its meaning. Annotations include a trust level field so the
    LLM can reason about their reliability.

    Trust levels (in descending order of reliability):
    - "artist_verified": written or confirmed by the artist. Treat as ground truth.
    - "accepted": reviewed and approved by Genius editorial staff. High quality.
    - "unreviewed": submitted by community users, not yet reviewed. Treat as interpretation.

    Args:
        song_id: The Genius song ID
        filter: Filter by trust level — one of "artist_verified", "accepted",
                "unreviewed". If not provided, all annotations are returned.
    """
    logger.info("get_song_annotations | song_id=%d filter=%r", song_id, filter)
    try:
        referents = await genius_api.get_referents(song_id)
    except GeniusAPIError as e:
        return [{"error": f"Genius API returned status {e.status_code}"}]

    results = []
    for referent in referents:
        annotation = referent.get("annotations", [{}])[0]

        if filter is not None:
            if filter == "artist_verified" and not annotation.get("verified"):
                continue
            elif filter == "accepted" and not (
                annotation.get("state") == "accepted" and not annotation.get("verified")
            ):
                continue
            elif filter == "unreviewed" and annotation.get("state") != "needs_exegesis":
                continue

        results.append(_extract_annotation(referent))

    logger.info("get_song_annotations | returned %d annotations (filter=%r)", len(results), filter)
    return results


@mcp.tool()
async def get_annotation_detail(annotation_id: int) -> dict:
    """Fetch the full detail of a single annotation by its ID.

    Use this when the LLM wants to read a specific annotation in depth, for example
    after identifying its ID from get_song_annotations.

    Args:
        annotation_id: The Genius annotation ID
    """
    logger.info("get_annotation_detail | annotation_id=%d", annotation_id)
    try:
        annotation, referent = await genius_api.get_annotation(annotation_id)
    except GeniusAPIError as e:
        return {"error": f"Genius API returned status {e.status_code}"}

    body_raw = annotation.get("body", {})
    body = body_raw.get("plain", "") if isinstance(body_raw, dict) else ""
    authors = [
        {"username": a.get("user", {}).get("login", ""), "iq": a.get("pinned_role")}
        for a in annotation.get("authors", [])
    ]
    result = {
        "annotation_id": annotation.get("id"),
        "fragment": referent.get("fragment", ""),
        "body": body,
        "trust_level": compute_trust_level(annotation),
        "state": annotation.get("state"),
        "verified": annotation.get("verified", False),
        "community": annotation.get("community", False),
        "votes_total": annotation.get("votes_total", 0),
        "authors": authors,
    }
    logger.info("get_annotation_detail | trust_level=%r votes=%d", result["trust_level"], result["votes_total"])
    return result
