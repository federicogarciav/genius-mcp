from typing import Optional
from app import mcp, genius_client


def _compute_trust_level(item: dict) -> str:
    if item.get("verified"):
        return "artist_verified"
    elif item.get("state") == "accepted":
        return "accepted"
    else:
        return "unreviewed"


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
        "trust_level": _compute_trust_level(annotation),
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
    response = await genius_client.get(
        "/search", params={"q": query, "type": "song", "per_page": per_page}
    )
    if response.status_code != 200:
        return [{"error": f"Genius API returned status {response.status_code}"}]

    hits = response.json().get("response", {}).get("sections", [{}])[0].get("hits", [])
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
    response = await genius_client.get(
        "/search", params={"q": query, "type": "artist", "per_page": per_page}
    )
    if response.status_code != 200:
        return [{"error": f"Genius API returned status {response.status_code}"}]

    hits = response.json().get("response", {}).get("sections", [{}])[0].get("hits", [])
    results = []
    for hit in hits:
        artist = hit.get("result", {})
        results.append({
            "artist_id": artist.get("id"),
            "name": artist.get("name"),
            "url": artist.get("url"),
            "is_verified": artist.get("is_verified", False),
            "followers_count": artist.get("followers_count"),
        })
    return results


@mcp.tool()
async def search_album(query: str, per_page: int = 5) -> list[dict]:
    """Search Genius for an album by name or artist + album name.

    Use this when the user wants to explore an album, its tracklist, or context.
    Returns album IDs required for fetching album details.

    Args:
        query: The search query, ideally "Album Name Artist Name"
        per_page: Number of results to return (max 10, default 5)
    """
    response = await genius_client.get(
        "/search", params={"q": query, "type": "album", "per_page": per_page}
    )
    if response.status_code != 200:
        return [{"error": f"Genius API returned status {response.status_code}"}]

    hits = response.json().get("response", {}).get("sections", [{}])[0].get("hits", [])
    results = []
    for hit in hits:
        album = hit.get("result", {})
        results.append({
            "album_id": album.get("id"),
            "name": album.get("name"),
            "full_title": album.get("full_title"),
            "artist_name": album.get("artist", {}).get("name"),
            "url": album.get("url"),
            "release_date": album.get("release_date"),
        })
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
    response = await genius_client.get(
        f"/songs/{song_id}", params={"text_format": "plain"}
    )
    if response.status_code != 200:
        return {"error": f"Genius API returned status {response.status_code}"}

    song = response.json().get("response", {}).get("song", {})
    description_raw = song.get("description", {})
    description = (
        description_raw.get("plain", "")
        if isinstance(description_raw, dict)
        else ""
    )
    album = song.get("album") or {}

    return {
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


@mcp.tool()
async def get_artist_details(artist_id: int) -> dict:
    """Fetch full profile and editorial bio for a specific artist by their Genius artist ID.

    The description field often contains a rich editorial write-up about the artist's
    background, style, and significance.

    Args:
        artist_id: The Genius artist ID (obtained from search_artist)
    """
    response = await genius_client.get(
        f"/artists/{artist_id}", params={"text_format": "plain"}
    )
    if response.status_code != 200:
        return {"error": f"Genius API returned status {response.status_code}"}

    artist = response.json().get("response", {}).get("artist", {})
    description_raw = artist.get("description", {})
    description = (
        description_raw.get("plain", "")
        if isinstance(description_raw, dict)
        else ""
    )

    return {
        "artist_id": artist.get("id"),
        "name": artist.get("name"),
        "url": artist.get("url"),
        "is_verified": artist.get("is_verified", False),
        "description": description,
        "followers_count": artist.get("followers_count"),
    }


@mcp.tool()
async def get_album_details(album_id: int) -> dict:
    """Fetch full metadata for a specific album by its Genius album ID.

    Includes the tracklist with song IDs, which can then be used to fetch details or
    annotations for individual songs.

    Args:
        album_id: The Genius album ID (obtained from search_album)
    """
    response = await genius_client.get(
        f"/albums/{album_id}", params={"text_format": "plain"}
    )
    if response.status_code != 200:
        return {"error": f"Genius API returned status {response.status_code}"}

    data = response.json().get("response", {})
    album = data.get("album", {})
    description_raw = album.get("description", {})
    description = (
        description_raw.get("plain", "")
        if isinstance(description_raw, dict)
        else ""
    )

    tracks_raw = data.get("album", {}).get("album_appearances", [])
    tracklist = [
        {
            "song_id": t.get("song", {}).get("id"),
            "title": t.get("song", {}).get("title"),
            "url": t.get("song", {}).get("url"),
        }
        for t in tracks_raw
        if t.get("song")
    ]

    return {
        "album_id": album.get("id"),
        "name": album.get("name"),
        "full_title": album.get("full_title"),
        "artist_name": album.get("artist", {}).get("name"),
        "url": album.get("url"),
        "release_date": album.get("release_date"),
        "description": description,
        "tracklist": tracklist,
    }


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
    response = await genius_client.get(
        f"/artists/{artist_id}/songs",
        params={"sort": sort, "per_page": per_page, "page": page},
    )
    if response.status_code != 200:
        return [{"error": f"Genius API returned status {response.status_code}"}]

    songs = response.json().get("response", {}).get("songs", [])
    return [
        {
            "song_id": s.get("id"),
            "title": s.get("title"),
            "url": s.get("url"),
            "annotation_count": s.get("annotation_count"),
        }
        for s in songs
    ]


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
    response = await genius_client.get(
        "/referents",
        params={"song_id": song_id, "text_format": "plain", "per_page": 50},
    )
    if response.status_code != 200:
        return [{"error": f"Genius API returned status {response.status_code}"}]

    referents = response.json().get("response", {}).get("referents", [])
    results = []
    for referent in referents:
        annotation = referent.get("annotations", [{}])[0]
        trust_level = _compute_trust_level(annotation)

        if filter is not None:
            if filter == "artist_verified" and not annotation.get("verified"):
                continue
            elif filter == "accepted" and not (
                annotation.get("state") == "accepted" and not annotation.get("verified")
            ):
                continue
            elif filter == "unreviewed" and annotation.get("state") != "needs_exegesis":
                continue

        body_raw = annotation.get("body", {})
        body = body_raw.get("plain", "") if isinstance(body_raw, dict) else ""
        authors = [
            {"username": a.get("user", {}).get("login", ""), "iq": a.get("pinned_role")}
            for a in annotation.get("authors", [])
        ]

        results.append({
            "annotation_id": annotation.get("id"),
            "fragment": referent.get("fragment", ""),
            "body": body,
            "trust_level": trust_level,
            "state": annotation.get("state"),
            "verified": annotation.get("verified", False),
            "community": annotation.get("community", False),
            "votes_total": annotation.get("votes_total", 0),
            "authors": authors,
        })
    return results


@mcp.tool()
async def get_annotation_detail(annotation_id: int) -> dict:
    """Fetch the full detail of a single annotation by its ID.

    Use this when the LLM wants to read a specific annotation in depth, for example
    after identifying its ID from get_song_annotations.

    Args:
        annotation_id: The Genius annotation ID
    """
    response = await genius_client.get(
        f"/annotations/{annotation_id}", params={"text_format": "plain"}
    )
    if response.status_code != 200:
        return {"error": f"Genius API returned status {response.status_code}"}

    annotation = response.json().get("response", {}).get("annotation", {})
    body_raw = annotation.get("body", {})
    body = body_raw.get("plain", "") if isinstance(body_raw, dict) else ""
    authors = [
        {"username": a.get("user", {}).get("login", ""), "iq": a.get("pinned_role")}
        for a in annotation.get("authors", [])
    ]

    return {
        "annotation_id": annotation.get("id"),
        "body": body,
        "trust_level": _compute_trust_level(annotation),
        "state": annotation.get("state"),
        "verified": annotation.get("verified", False),
        "community": annotation.get("community", False),
        "votes_total": annotation.get("votes_total", 0),
        "authors": authors,
        "created_at": annotation.get("created_at"),
    }
