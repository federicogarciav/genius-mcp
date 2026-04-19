import asyncio
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
async def get_song_details(song_id: int) -> dict:
    """Fetch full metadata and editorial information for a specific song by its Genius song ID.

    Includes the song's editorial description (also known as Song Bio) written by Genius editors, which often
    explains the song's themes, context, and meaning. It gives the full picture of the song before diving deeper with annotations.

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
async def get_song_relationships(song_id: int) -> list[dict]:
    """Fetch the musical relationships for a song — samples, interpolations, covers, remixes, and translations.

    Each relationship type links this song to other songs on Genius. Knowing a song
    samples a specific record is often the key to understanding its lyrical references
    and creative context. Only relationship types with at least one song are returned.

    Relationship types: samples, sampled_in, interpolates, interpolated_by, cover_of,
    covered_by, remix_of, remixed_by, translation_of, live_version_of.

    Args:
        song_id: The Genius song ID (obtained from search_song)
    """
    logger.info("get_song_relationships | song_id=%d", song_id)
    try:
        song = await genius_api.get_song(song_id)
    except GeniusAPIError as e:
        return [{"error": f"Genius API returned status {e.status_code}"}]

    relationships = []
    for rel in song.get("song_relationships", []):
        songs = rel.get("songs", [])
        if not songs:
            continue
        relationships.append({
            "type": rel.get("type"),
            "songs": [
                {
                    "song_id": s.get("id"),
                    "title": s.get("title"),
                    "artist_name": s.get("primary_artist", {}).get("name"),
                    "url": s.get("url"),
                }
                for s in songs
            ],
        })
    logger.info("get_song_relationships | song_id=%d returned %d relationship types", song_id, len(relationships))
    return relationships


@mcp.tool()
async def get_song_credits(song_id: int) -> dict:
    """Fetch the writing, production, and performance credits for a song.

    Returns the writers, producers, featured artists, and any additional custom
    performance credits (e.g. mixing engineer, label, recording studio). Useful for
    understanding the commercial and creative context around a song.

    Args:
        song_id: The Genius song ID (obtained from search_song)
    """
    logger.info("get_song_credits | song_id=%d", song_id)
    try:
        song = await genius_api.get_song(song_id)
    except GeniusAPIError as e:
        return {"error": f"Genius API returned status {e.status_code}"}

    def _extract_artists(artist_list: list) -> list[dict]:
        return [
            {"artist_id": a.get("id"), "name": a.get("name"), "url": a.get("url")}
            for a in artist_list
        ]

    custom_performances = [
        {
            "label": cp.get("label"),
            "artists": _extract_artists(cp.get("artists", [])),
        }
        for cp in song.get("custom_performances", [])
    ]

    result = {
        "song_id": song.get("id"),
        "title": song.get("title"),
        "writers": _extract_artists(song.get("writer_artists", [])),
        "producers": _extract_artists(song.get("producer_artists", [])),
        "featured_artists": _extract_artists(song.get("featured_artists", [])),
        "custom_performances": custom_performances,
    }
    logger.info(
        "get_song_credits | song_id=%d writers=%d producers=%d featured=%d",
        song_id,
        len(result["writers"]),
        len(result["producers"]),
        len(result["featured_artists"]),
    )
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
    or artist explanation of its meaning. Annotations include a trust level field to verify their reliability.

    Trust levels (in descending order of reliability):
    - "artist_verified": written or confirmed by the artist. Treat as ground truth.
    - "accepted": reviewed and approved by Genius editorial staff. High quality.
    - "unreviewed": submitted by community users, not yet reviewed. Treat as interpretation.

    The tool returns all annotations (in fragments). To read a specific annotation in depth, use get_annotation_detail tool with the annotation_id.

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

    Use this to read a specific annotation in depth, for example
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


@mcp.tool()
async def get_song_questions_and_answers(
    song_id: int,
    per_page: int = 20,
    page: int = 1,
) -> list[dict]:
    """Fetch user-submitted questions and answers for a specific song.

    Args:
        song_id: The Genius song ID (obtained from search_song or get_song_details)
        per_page: Number of questions to fetch from the API (max 50, default 20)
        page: Page number for pagination (default 1)
    """
    logger.info("get_song_questions | song_id=%d per_page=%d page=%d", song_id, per_page, page)
    try:
        data = await genius_api.get_song_questions(song_id, per_page=per_page, page=page)
    except GeniusAPIError as e:
        return [{"error": f"Genius API returned status {e.status_code}"}]

    results = []
    for q in data.get("questions", []):
        ans = q.get("answer") or {}
        if not ans.get("id"):
            continue
        body_raw = q.get("body", {})
        question_body = body_raw.get("plain", "") if isinstance(body_raw, dict) else str(body_raw)
        ans_body_raw = ans.get("body", {})
        answer_body = (
            ans_body_raw.get("plain", "")
            if isinstance(ans_body_raw, dict)
            else str(ans_body_raw) if ans_body_raw else ""
        )
        results.append({
            "question": question_body,
            "answer": answer_body,
            "votes_total": ans.get("votes_total", 0),
        })

    if not results:
        return [{"info": "No answered questions found for this song on this page."}]

    logger.info("get_song_questions | returned %d answered questions", len(results))
    return results


@mcp.tool()
async def search_album(query: str, per_page: int = 5) -> list[dict]:
    """Search Genius for albums matching a query.

    Use this when the user provides an album name and wants to find its Genius ID.
    Returns a list of album matches with their album_id values, which are required for get_album_details.

    Args:
        query: The album name to search for
        per_page: Number of results to return (max 10, default 5)
    """
    logger.info("search_album | query=%r per_page=%d", query, per_page)
    try:
        data = await genius_api.search_albums(query, per_page=per_page)
    except GeniusAPIError as e:
        return [{"error": f"Genius API returned status {e.status_code}"}]

    results = []
    for section in data.get("sections", []):
        for hit in section.get("hits", []):
            album = hit.get("result", {})
            results.append({
                "album_id": album.get("id"),
                "name": album.get("name"),
                "artist_name": album.get("artist", {}).get("name"),
                "release_date": album.get("release_date_components", {}) or album.get("release_date"),
                "url": album.get("url"),
            })
    logger.info("search_album | returned %d results", len(results))
    return results


@mcp.tool()
async def get_artist_albums(
    artist_id: int,
    per_page: int = 20,
    page: int = 1,
) -> list[dict]:
    """Retrieve the full discography of an artist as a list of albums with album_id values.

    Use this after search_artist to explore an artist's catalog at the album level.
    The returned album_id values can be passed to get_album_details to fetch the
    tracklist and metadata for any album.

    Args:
        artist_id: The Genius artist ID (obtained from search_artist)
        per_page: Number of albums to return (max 50, default 20)
        page: Page number for pagination (default 1)
    """
    logger.info("get_artist_albums | artist_id=%d per_page=%d page=%d", artist_id, per_page, page)
    try:
        data = await genius_api.get_artist_albums(artist_id, per_page=per_page, page=page)
    except GeniusAPIError as e:
        return [{"error": f"Genius API returned status {e.status_code}"}]

    results = [
        {
            "album_id": a.get("id"),
            "name": a.get("name"),
            "release_date": a.get("release_date_components", {}) or a.get("release_date"),
            "url": a.get("url"),
        }
        for a in data.get("albums", [])
    ]
    logger.info("get_artist_albums | returned %d albums", len(results))
    return results


@mcp.tool()
async def get_album_details(album_id: int) -> dict:
    """Fetch metadata, full tracklist, and cover art info for a specific album by its Genius album ID.

    Returns the album's title, artist, release date, description, and an ordered
    tracklist. Each track includes a song_id to chain directly into
    tools like get_song_annotations or get_song_details.

    Also returns a cover_arts list. The first entry is always the main album cover.
    Each entry includes the cover_art_id and, if annotated, an annotation_id.
    Call get_cover_art_annotations with cover_art_id (and album_id) to read the
    full annotation content for any annotated artwork.

    Args:
        album_id: The Genius album ID (obtained from search_album or get_artist_albums)
    """
    logger.info("get_album_details | album_id=%d", album_id)

    async def _get_cover_arts_safe() -> list[dict]:
        try:
            return await genius_api.get_album_cover_arts(album_id)
        except GeniusAPIError:
            return []

    try:
        album_data, tracks_data, cover_arts_raw = await asyncio.gather(
            genius_api.get_album(album_id),
            genius_api.get_album_tracks(album_id),
            _get_cover_arts_safe(),
        )
    except GeniusAPIError as e:
        return {"error": f"Genius API returned status {e.status_code}"}

    album = album_data
    desc_ann = album.get("description_annotation", {})
    desc_body = desc_ann.get("annotations", [{}])[0].get("body", {})
    description = desc_body.get("plain", "") if isinstance(desc_body, dict) else ""

    tracks = [
        {
            "track_number": t.get("number"),
            "song_id": t.get("song", {}).get("id"),
            "title": t.get("song", {}).get("title"),
            "url": t.get("song", {}).get("url"),
            "annotation_count": t.get("song", {}).get("annotation_count"),
        }
        for t in tracks_data.get("tracks", [])
    ]

    def _cover_art_annotation_id(art: dict) -> Optional[int]:
        annotations = art.get("description_annotation", {}).get("annotations", [])
        return annotations[0].get("id") if annotations else None

    cover_arts = []
    for i, art in enumerate(cover_arts_raw):
        entry: dict = {
            "cover_art_id": art.get("id"),
            "image_url": art.get("image_url"),
        }
        if i == 0:
            entry["note"] = "main album cover"
        annotation_id = _cover_art_annotation_id(art) if art.get("annotated") else None
        if annotation_id is not None:
            entry["annotation_id"] = annotation_id
        cover_arts.append(entry)

    result = {
        "album_id": album.get("id"),
        "name": album.get("name"),
        "artist_name": album.get("artist", {}).get("name"),
        "artist_id": album.get("artist", {}).get("id"),
        "release_date": album.get("release_date_components", {}) or album.get("release_date"),
        "url": album.get("url"),
        "description": description,
        "tracks": tracks,
        "cover_arts": cover_arts,
    }
    logger.info(
        "get_album_details | name=%r tracks=%d cover_arts=%d",
        result["name"], len(tracks), len(cover_arts),
    )
    return result


@mcp.tool()
async def get_cover_art_annotations(cover_art_id: int, album_id: int) -> dict:
    """Fetch the annotation written on a specific album cover art image.

    On Genius, cover art images are annotatable — community members and artists can write
    an annotation about visual elements, symbolism, and artistic choices in the artwork.

    Use get_album_details first to get cover_art_id and album_id values.
    Only call this tool for cover arts where has_annotations is True — the annotation
    content is also available inline in get_album_details under the annotation field.

    Trust levels:
    - "artist_verified": confirmed by the artist
    - "accepted": reviewed by Genius editorial staff
    - "unreviewed": community-submitted, not yet reviewed

    Args:
        cover_art_id: The Genius cover art ID (from the cover_arts list in get_album_details)
        album_id: The Genius album ID (same album_id used in get_album_details)
    """
    logger.info("get_cover_art_annotations | cover_art_id=%d album_id=%d", cover_art_id, album_id)
    try:
        cover_arts = await genius_api.get_album_cover_arts(album_id)
    except GeniusAPIError as e:
        return {"error": f"Genius API returned status {e.status_code}"}

    art = next((a for a in cover_arts if a.get("id") == cover_art_id), None)
    if art is None:
        return {"error": f"Cover art {cover_art_id} not found in album {album_id}"}

    desc_ann = art.get("description_annotation", {})
    annotations = desc_ann.get("annotations", [])
    if not annotations:
        return {"info": "No annotation found for this cover art."}

    ann = annotations[0]
    body_raw = ann.get("body", {})
    body = body_raw.get("plain", "") if isinstance(body_raw, dict) else ""
    authors = [
        {"username": a.get("user", {}).get("login", ""), "iq": a.get("pinned_role")}
        for a in ann.get("authors", [])
    ]
    result = {
        "cover_art_id": cover_art_id,
        "image_url": art.get("image_url"),
        "annotation_id": ann.get("id"),
        "body": body,
        "trust_level": compute_trust_level(ann),
        "state": ann.get("state"),
        "votes_total": ann.get("votes_total", 0),
        "authors": authors,
    }
    logger.info(
        "get_cover_art_annotations | cover_art_id=%d trust_level=%r votes=%d",
        cover_art_id, result["trust_level"], result["votes_total"],
    )
    return result
