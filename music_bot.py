"""
Telegram Music Bot — Multi-Platform Search
- Searches SoundCloud, Audiomack, YouTube Music, and Boomplay in parallel
- Ranks results by relevance (exact match, recency, official releases)
- Downloads audio via yt-dlp where permitted, sends listening links otherwise
- Sends the audio file to the user then deletes it from /tmp

Design rules:
  • Every callback edits cq.message in-place (never sends new messages).
  • One unavailable platform never crashes the bot.
  • No API keys or cookies are hardcoded — all from env vars.
"""

import asyncio
import functools
import html
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ── Optional platform imports (each is skipped gracefully if missing) ────────

try:
    import httpx  # for Audiomack / Boomplay API calls
except ImportError:
    httpx = None

try:
    from ytmusicapi import YTMusic as _YTMusic
    _ytm = _YTMusic()
except Exception:
    _ytm = None

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.vendor.ptb_urllib3").setLevel(logging.WARNING)


# ── yt-dlp logger adapter ─────────────────────────────────────────────────────

class _YtdlLogger:
    def debug(self, msg: str) -> None:
        if "[download]" in msg:
            return
        logger.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        logger.info("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        logger.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        logger.error("yt-dlp: %s", msg)


_YTDL_LOGGER = _YtdlLogger()

# ── Constants ─────────────────────────────────────────────────────────────────

PAGE_SIZE   = 5        # results shown per page
MAX_FILE_MB = 48       # Telegram bot file upload limit is 50 MB
ASK_SONG    = 0        # ConversationHandler state
CACHE_TTL   = 300      # search cache lives 5 minutes

SOURCES = ["SoundCloud", "Audiomack", "YouTube Music", "Boomplay"]

_COOKIEFILE = ""

# ── Error messages shown to users (include code for log matching) ─────────────

_ERR: dict[str, str] = {
    "DOWNLOAD_FAILED": (
        "❌ Download failed. The track may be unavailable or region-locked.\n"
        "<code>[DOWNLOAD_FAILED]</code>"
    ),
    "YOUTUBE_BLOCKED": (
        "❌ YouTube is blocking downloads from this server.\n"
        "Try a <b>SoundCloud</b> result instead — those download reliably.\n"
        "Or set the <code>YOUTUBE_COOKIES</code> env var in Railway.\n"
        "<code>[YOUTUBE_BLOCKED]</code>"
    ),
    "FILE_TOO_LARGE": (
        f"❌ That track exceeds Telegram's {MAX_FILE_MB} MB upload limit.\n"
        f"<code>[FILE_TOO_LARGE]</code>"
    ),
    "SEND_FAILED": (
        "❌ The file downloaded but Telegram refused the upload.\n"
        "<code>[SEND_FAILED]</code>"
    ),
    "SEARCH_EMPTY": (
        "No results found on any source. Try different words.\n"
        "<code>[SEARCH_EMPTY]</code>"
    ),
    "INTERNAL_ERROR": (
        "❌ An unexpected error occurred. Please try again.\n"
        "<code>[INTERNAL_ERROR]</code>"
    ),
}


# ── Utility helpers ───────────────────────────────────────────────────────────

def fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def _is_music_url(text: str) -> bool:
    """True when *text* is a URL from any supported music platform."""
    try:
        p = urlparse(text.strip())
        if p.scheme not in ("http", "https"):
            return False
        host = p.netloc.lower()
        return any(d in host for d in (
            "soundcloud.com", "audiomack.com", "music.youtube.com",
            "youtube.com", "youtu.be", "boomplay.com",
        ))
    except Exception:
        return False


def _setup_cookies() -> str:
    raw = os.environ.get("YOUTUBE_COOKIES")
    if not raw:
        return ""
    try:
        path = "/tmp/cookies.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)
        logger.info("COOKIES_WRITTEN path=%s bytes=%d", path, len(raw))
        return path
    except Exception:
        logger.exception("COOKIES_WRITE_FAILED")
        return ""


# ── Ranking ──────────────────────────────────────────────────────────────────

_REMIX_WORDS = (
    "remix", "cover", "edit", "bootleg", "instrumental",
    "acoustic", "karaoke", "slowed", "reverb", "nightcore",
)


def _rank_score(track: dict, query: str) -> float:
    """Score a track's relevance to *query*.  Higher = better."""
    q = query.lower().strip()
    title = (track.get("title") or "").lower()
    artist = (track.get("artist") or "").lower()
    score = 0.0

    # Exact title match
    if title == q:
        score += 100
    elif title.startswith(q):
        score += 60
    elif q in title:
        score += 35

    # Exact artist match
    if artist and artist == q:
        score += 60
    elif q in artist:
        score += 30

    # "Song - Artist" format: bonus when both parts match
    if " - " in q:
        parts = q.split(" - ", 1)
        song_part, artist_part = parts[0].strip(), parts[1].strip()
        if song_part in title:
            score += 30
        if artist_part in artist:
            score += 40

    # Word-level matching (handles "Artist Song" queries without hyphens)
    q_words = {w for w in q.split() if len(w) > 2}
    if q_words:
        for w in q_words:
            if w in title:
                score += 15
            if w in artist:
                score += 15

    # Penalise remixes/covers when the user didn't ask for one
    if any(w in title for w in _REMIX_WORDS) and not any(w in q for w in _REMIX_WORDS):
        score -= 35

    # Popularity bonus (views)
    views_str = str(track.get("views") or "")
    if views_str:
        try:
            num = float(re.sub(r"[^\d.]", "", views_str))
            if "B" in views_str:
                num *= 1000
            score += min(num, 20)
        except (ValueError, TypeError):
            pass

    # Recency bonus
    release = str(track.get("release_date") or "")
    if release:
        try:
            year = int(release[:4])
            if year >= 2024:
                score += 15
            elif year >= 2022:
                score += 10
            elif year >= 2020:
                score += 5
        except (ValueError, TypeError):
            pass

    # Penalise very long tracks (likely DJ mixes)
    dur = track.get("duration") or 0
    if dur and dur > 600:
        score -= 15

    # Boost downloadable tracks so users try those first.
    # SoundCloud works reliably; YouTube Music often blocks datacenter IPs.
    if track.get("can_download") and track.get("download_url"):
        score += 15

    return score


# ── Platform: SoundCloud ─────────────────────────────────────────────────────

def search_soundcloud(query: str, limit: int = 5) -> list[dict]:
    """Search SoundCloud via yt-dlp scsearch.  Returns normalised track dicts."""
    search_url = f"scsearch{limit}:{query}"
    logger.info("SEARCH_START source=SoundCloud query=%r", query)
    opts: dict[str, Any] = {
        "quiet": True, "no_warnings": True,
        "extract_flat": True, "noplaylist": False,
        "logger": _YTDL_LOGGER,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_url, download=False) or {}
        tracks = []
        for e in (info.get("entries") or []):
            if not e or not e.get("id"):
                continue
            thumbs = e.get("thumbnails") or []
            tracks.append({
                "title": e.get("title", ""),
                "artist": e.get("uploader", ""),
                "album": "", 
                "duration": e.get("duration"),
                "thumbnail": e.get("thumbnail") or (thumbs[-1]["url"] if thumbs else ""),
                "url": e.get("webpage_url") or e.get("url", ""),
                "source": "SoundCloud",
                "can_download": True,
                "release_date": "",
                "download_url": e.get("webpage_url") or e.get("url", ""),
                "views": "",
            })
        logger.info("SEARCH_DONE source=SoundCloud results=%d query=%r", len(tracks), query)
        return tracks
    except Exception:
        logger.exception("SEARCH_FAILED source=SoundCloud query=%r", query)
        return []


# ── Platform: Audiomack ──────────────────────────────────────────────────────

def search_audiomack(query: str, limit: int = 5) -> list[dict]:
    """Search Audiomack.  Tries the API, then falls back to scraping the search page."""
    if httpx is None:
        logger.warning("SEARCH_SKIP source=Audiomack reason=httpx_not_installed")
        return []
    logger.info("SEARCH_START source=Audiomack query=%r", query)
    tracks: list[dict] = []
    try:
        # ── Attempt 1: public API (may redirect / require auth) ──────────────
        try:
            resp = httpx.get(
                "https://api.audiomack.com/v2/search",
                params={"q": query, "limit": limit},
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=12,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    data = resp.json()
                    raw = data.get("results") or data.get("data") or []
                    for r in raw:
                        if not isinstance(r, dict):
                            continue
                        url = r.get("url") or r.get("permalink") or ""
                        if not url and r.get("slug"):
                            up = r.get("uploader") or {}
                            up_slug = up.get("slug", "") if isinstance(up, dict) else r.get("uploader_slug", "")
                            url = f"https://audiomack.com/{up_slug}/song/{r.get('slug', '')}"
                        if not url:
                            continue
                        tracks.append({
                            "title": r.get("title", ""),
                            "artist": (r.get("artist") or
                                       (r.get("uploader", {}).get("name", "") if isinstance(r.get("uploader"), dict) else "")),
                            "album": "",
                            "duration": r.get("duration"),
                            "thumbnail": r.get("image") or r.get("artwork") or "",
                            "url": url,
                            "source": "Audiomack",
                            "can_download": True,
                            "release_date": (r.get("upload_date") or "")[:10],
                            "download_url": url,
                            "views": str(r.get("plays", "")) if r.get("plays") else "",
                        })
            if tracks:
                logger.info("SEARCH_DONE source=Audiomack results=%d query=%r (via API)", len(tracks), query)
                return tracks[:limit]
        except Exception:
            pass  # fall through to scraping

        # ── Attempt 2: scrape the search page ────────────────────────────────
        resp = httpx.get(
            "https://audiomack.com/search",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=12,
            follow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text

        # Track links look like: /artist-slug/song/song-slug
        link_pattern = re.compile(r'href="(/[^"]+/song/[^"]+)"')
        seen: set[str] = set()
        for m in link_pattern.finditer(html):
            path = m.group(1)
            if path in seen:
                continue
            seen.add(path)
            parts = path.strip("/").split("/song/")
            if len(parts) != 2:
                continue
            artist_slug, song_slug = parts[0], parts[1]
            url = f"https://audiomack.com{path}"
            tracks.append({
                "title": song_slug.replace("-", " ").title(),
                "artist": artist_slug.replace("-", " ").title(),
                "album": "",
                "duration": None,
                "thumbnail": "",
                "url": url,
                "source": "Audiomack",
                "can_download": True,
                "release_date": "",
                "download_url": url,
                "views": "",
            })
            if len(tracks) >= limit:
                break

        logger.info("SEARCH_DONE source=Audiomack results=%d query=%r (via scrape)", len(tracks), query)
        return tracks[:limit]

    except Exception:
        logger.exception("SEARCH_FAILED source=Audiomack query=%r", query)
        return []


# ── Platform: YouTube Music ───────────────────────────────────────────────────

def search_ytmusic(query: str, limit: int = 5) -> list[dict]:
    """Search YouTube Music via ytmusicapi.  Returns normalised track dicts."""
    if _ytm is None:
        logger.warning("SEARCH_SKIP source=YouTubeMusic reason=ytmusicapi_not_installed")
        return []
    logger.info("SEARCH_START source=YouTubeMusic query=%r", query)
    try:
        results = _ytm.search(query, filter="songs", limit=limit)
        tracks = []
        for r in results:
            vid = r.get("videoId")
            if not vid:
                continue
            artists = r.get("artists") or []
            artist_names = ", ".join(a.get("name", "") for a in artists if a.get("name"))
            album_info = r.get("album") or {}
            thumbs = r.get("thumbnails") or []
            watch_url = f"https://music.youtube.com/watch?v={vid}"
            tracks.append({
                "title": r.get("title", ""),
                "artist": artist_names,
                "album": album_info.get("name", ""),
                "duration": r.get("duration_seconds"),
                "thumbnail": thumbs[-1].get("url", "") if thumbs else "",
                "url": watch_url,
                "source": "YouTube Music",
                "can_download": bool(_COOKIEFILE),  # only with cookies
                "release_date": str(r.get("year") or ""),
                "download_url": watch_url,
                "views": r.get("views", ""),
            })
        logger.info("SEARCH_DONE source=YouTubeMusic results=%d query=%r", len(tracks), query)
        return tracks
    except Exception:
        logger.exception("SEARCH_FAILED source=YouTubeMusic query=%r", query)
        return []


# ── Platform: Boomplay ──────────────────────────────────────────────────────

def search_boomplay(query: str, limit: int = 5) -> list[dict]:
    """Search Boomplay.  Returns listening links only (no download)."""
    if httpx is None:
        logger.warning("SEARCH_SKIP source=Boomplay reason=httpx_not_installed")
        return []
    logger.info("SEARCH_START source=Boomplay query=%r", query)
    tracks: list[dict] = []
    try:
        # ── Attempt 1: try known API endpoints ───────────────────────────────
        api_urls = [
            "https://www.boomplay.com/api/v3.0/search/song",
            "https://www.boomplay.com/api/v3.0/search/music",
            "https://m.boomplay.com/api/v3.0/search/song",
        ]
        for api_url in api_urls:
            try:
                resp = httpx.get(
                    api_url,
                    params={"keyword": query, "page": 1, "size": limit},
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Accept": "application/json",
                    },
                    timeout=12,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                raw = (
                    (data.get("data") or {}).get("list")
                    if isinstance(data.get("data"), dict) else data.get("data")
                ) or []
                for r in raw:
                    if not isinstance(r, dict):
                        continue
                    tid = r.get("id") or r.get("songId") or ""
                    if not tid:
                        continue
                    tracks.append({
                        "title": r.get("name") or r.get("title", ""),
                        "artist": r.get("singerName") or r.get("artist", ""),
                        "album": r.get("albumName", ""),
                        "duration": r.get("duration", 0),
                        "thumbnail": r.get("cover") or r.get("pic") or r.get("image", ""),
                        "url": f"https://www.boomplay.com/music/{tid}",
                        "source": "Boomplay",
                        "can_download": False,
                        "release_date": str(r.get("releaseDate") or "")[:10],
                        "download_url": "",
                        "views": str(r.get("playCount", "")) if r.get("playCount") else "",
                    })
                if tracks:
                    logger.info("SEARCH_DONE source=Boomplay results=%d query=%r (via API)", len(tracks), query)
                    return tracks[:limit]
            except Exception:
                continue

        # ── Attempt 2: scrape the search page ────────────────────────────────
        resp = httpx.get(
            f"https://www.boomplay.com/search/{query}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=12,
            follow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text

        # Look for music links: /music/NUMBER
        link_pattern = re.compile(r'href="(/music/(\d+)[^"]*)"')
        # Also try to grab titles from nearby elements
        title_pattern = re.compile(r'<(?:a|span|div)[^>]*>([^<]{2,80})</(?:a|span|div)>')
        seen: set[str] = set()
        for m in link_pattern.finditer(html):
            path, tid = m.group(1), m.group(2)
            if tid in seen:
                continue
            seen.add(tid)
            tracks.append({
                "title": "",   # title extraction from HTML is unreliable; leave blank
                "artist": "",
                "album": "",
                "duration": 0,
                "thumbnail": "",
                "url": f"https://www.boomplay.com{path}",
                "source": "Boomplay",
                "can_download": False,
                "release_date": "",
                "download_url": "",
                "views": "",
            })
            if len(tracks) >= limit:
                break

        # If we only got URLs without titles, try to extract titles from the page
        if tracks and not tracks[0].get("title"):
            # Try to find title/artist pairs near the music links
            for t in tracks:
                tid = t["url"].split("/music/")[-1].split("?")[0].split("/")[0]
                # Look for the title near this ID in the HTML
                title_match = re.search(
                    rf'{re.escape(tid)}[^>]*>.*?<[^>]*title[^>]*>([^<]+)<',
                    html, re.DOTALL,
                )
                if title_match:
                    t["title"] = title_match.group(1).strip()

        # Filter out tracks with no title
        tracks = [t for t in tracks if t.get("title")]

        logger.info("SEARCH_DONE source=Boomplay results=%d query=%r (via scrape)", len(tracks), query)
        return tracks[:limit]

    except Exception:
        logger.exception("SEARCH_FAILED source=Boomplay query=%r", query)
        return []


# ── Multi-source search orchestrator ──────────────────────────────────────────

async def multi_search(
    query: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> list[dict]:
    """
    Search all available platforms in parallel, merge, rank, deduplicate,
    and cache the results.
    """
    cache_key = query.lower().strip()
    cache: dict = context.bot_data.setdefault("_search_cache", {})
    if cache_key in cache:
        ts, results = cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            logger.info("SEARCH_CACHE_HIT query=%r", query)
            return results

    logger.info("MULTI_SEARCH_START query=%r", query)

    search_fns = [
        ("SoundCloud",   search_soundcloud),
        ("Audiomack",    search_audiomack),
        ("YouTube Music", search_ytmusic),
        ("Boomplay",     search_boomplay),
    ]

    coros = [_run_blocking(fn, query, 5) for _, fn in search_fns]
    results = await asyncio.gather(*coros, return_exceptions=True)

    all_tracks: list[dict] = []
    for (name, _), result in zip(search_fns, results):
        if isinstance(result, Exception):
            logger.warning("SEARCH_SOURCE_FAILED source=%s error=%s", name, result)
            continue
        if result:
            logger.info("SEARCH_SOURCE_OK source=%s results=%d", name, len(result))
            all_tracks.extend(result)
        else:
            logger.info("SEARCH_SOURCE_EMPTY source=%s", name)

    # Rank by relevance
    ranked = sorted(all_tracks, key=lambda t: _rank_score(t, query), reverse=True)

    # Deduplicate by (title, artist) — keep highest-ranked
    seen: set = set()
    deduped: list[dict] = []
    for t in ranked:
        key = (
            (t.get("title") or "").lower().strip()[:60],
            (t.get("artist") or "").lower().strip()[:40],
        )
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    logger.info("MULTI_SEARCH_DONE query=%r total=%d ranked=%d", query, len(all_tracks), len(deduped))

    # Cache
    cache[cache_key] = (time.time(), deduped)

    return deduped


# ── yt-dlp audio download ─────────────────────────────────────────────────────

def download_audio(url: str, tmpdir: str) -> tuple[str, dict]:
    """
    Download *url* into *tmpdir*, remux to MP3 if FFmpeg is available.
    Returns (file_path, info_dict).
    Raises RuntimeError("DOWNLOAD_FAILED" | "FILE_TOO_LARGE").
    """
    logger.info("DOWNLOAD_START url=%r tmpdir=%r", url, tmpdir)

    has_ffmpeg = _ffmpeg_available()
    logger.info("DOWNLOAD ffmpeg=%s", has_ffmpeg)

    outtmpl = os.path.join(tmpdir, "%(id)s.%(ext)s")
    opts: dict[str, Any] = {
        "format":           "bestaudio/best",
        "outtmpl":          outtmpl,
        "quiet":            False,
        "no_warnings":      False,
        "noplaylist":       True,
        "max_filesize":     MAX_FILE_MB * 1024 * 1024,
        "retries":          3,
        "fragment_retries": 3,
        "logger":           _YTDL_LOGGER,
    }

    if has_ffmpeg:
        opts["postprocessors"] = [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        }]
    else:
        logger.warning("DOWNLOAD ffmpeg_missing — native format will be sent")

    if _COOKIEFILE and os.path.exists(_COOKIEFILE):
        opts["cookiefile"] = _COOKIEFILE
        logger.info("DOWNLOAD using_cookies path=%r", _COOKIEFILE)

    info: dict = {}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
    except yt_dlp.utils.DownloadError as exc:
        err_msg = str(exc).lower()
        # Detect YouTube bot-detection specifically so we can give a
        # helpful "try SoundCloud instead" message to the user.
        if any(kw in err_msg for kw in (
            "sign in to confirm", "not a bot", "429",
            "confirm you", "cookies",
        )):
            logger.warning("YOUTUBE_BLOCKED url=%r", url)
            raise RuntimeError("YOUTUBE_BLOCKED")
        logger.exception("DOWNLOAD_FAILED [DownloadError] url=%r", url)
        raise RuntimeError("DOWNLOAD_FAILED")
    except Exception:
        logger.exception("DOWNLOAD_FAILED [unexpected] url=%r", url)
        raise RuntimeError("DOWNLOAD_FAILED")

    # Locate the produced file
    track_id = str(info.get("id") or "")
    path = ""

    if has_ffmpeg and track_id:
        mp3 = os.path.join(tmpdir, f"{track_id}.mp3")
        if os.path.exists(mp3):
            path = mp3

    if not path and info:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "logger": _YTDL_LOGGER}) as ydl:
                raw = ydl.prepare_filename(info)
            for candidate in [raw, os.path.splitext(raw)[0] + ".mp3"]:
                if os.path.exists(candidate):
                    path = candidate
                    break
        except Exception:
            pass

    if not path or not os.path.exists(path):
        all_files = [
            f for f in os.listdir(tmpdir)
            if not f.endswith(".part") and not f.endswith(".ytdl")
        ]
        if not all_files:
            logger.error("DOWNLOAD_FAILED no_output_file tmpdir=%r", tmpdir)
            raise RuntimeError("DOWNLOAD_FAILED")
        all_files.sort(key=lambda f: os.path.getsize(os.path.join(tmpdir, f)), reverse=True)
        path = os.path.join(tmpdir, all_files[0])

    size_mb = os.path.getsize(path) / (1024 * 1024)
    logger.info("DOWNLOAD_COMPLETE path=%r size_mb=%.2f", path, size_mb)

    if size_mb > MAX_FILE_MB:
        logger.error("FILE_TOO_LARGE size_mb=%.2f url=%r", size_mb, url)
        raise RuntimeError("FILE_TOO_LARGE")

    return path, info


# ── UI builders ───────────────────────────────────────────────────────────────

def build_results_page(
    tracks: list[dict],
    page: int,
    query: str,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build one page of search results as a single editable text message."""
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_tracks = tracks[start:end]
    total_pages = max(1, (len(tracks) + PAGE_SIZE - 1) // PAGE_SIZE)

    lines = [
        f'<b>🎵 Search results for "{html.escape(query)}"</b>',
        f"<i>{len(tracks)} track(s) from multiple sources · page {page}/{total_pages}</i>\n",
    ]
    buttons: list[list[InlineKeyboardButton]] = []

    for i, track in enumerate(page_tracks, start=start):
        title   = html.escape(track.get("title", "Unknown"))
        artist  = html.escape(track.get("artist", "Unknown"))
        source  = track.get("source", "?")
        dur     = fmt_duration(track.get("duration"))

        line = f"{i + 1}. <b>{title}</b> — {artist} [{source}]"
        if dur:
            line += f"  ·  {dur}"
        lines.append(line)

        label = f"{i + 1}. {track.get('title','')[:24]} — {track.get('artist','')[:14]}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"info:{i}")])

    # Navigation row
    nav: list[InlineKeyboardButton] = []
    if page < total_pages:
        nav.append(InlineKeyboardButton("🔎 More Results", callback_data=f"more:{page + 1}"))
    nav.append(InlineKeyboardButton("🔄 Another Source", callback_data="nextsrc"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])

    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_track_detail(track: dict, index: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build the detail card for a single track with source info and buttons."""
    title    = html.escape(track.get("title", "Unknown"))
    artist   = html.escape(track.get("artist", "Unknown"))
    source   = track.get("source", "Unknown")
    release  = str(track.get("release_date") or "")
    dur      = fmt_duration(track.get("duration"))
    url      = track.get("url", "")
    can_dl   = track.get("can_download", False)

    lines = [
        f"🎵 <b>{title}</b>",
        f"👤 Artist: {artist}",
    ]
    if release:
        year = release[:4] if release else ""
        if year and year != "None":
            lines.append(f"📅 Release: {html.escape(year)}")
    if dur:
        lines.append(f"⏱ Duration: {dur}")
    lines.append(f"🎧 Source: {source}")

    buttons: list[list[InlineKeyboardButton]] = []

    # Download row — always show when a download URL exists.
    # If the source blocks the download, the user gets a clear error message
    # ([DOWNLOAD_FAILED]) rather than a missing button.
    if track.get("download_url"):
        buttons.append([InlineKeyboardButton("⬇️ Download", callback_data=f"dl:{index}")])

    # Listen (URL button) + Back row
    action_row: list[InlineKeyboardButton] = []
    if url:
        action_row.append(InlineKeyboardButton("▶️ Listen", url=url))
    action_row.append(InlineKeyboardButton("🔙 Back", callback_data="back"))
    buttons.append(action_row)

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])

    return "\n".join(lines), InlineKeyboardMarkup(buttons)


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg:
        return
    available = []
    if True:                       available.append("SoundCloud")
    if httpx is not None:           available.append("Audiomack")
    if _ytm is not None:            available.append("YouTube Music")
    if httpx is not None:           available.append("Boomplay")
    await msg.reply_text(
        "🎵 <b>Music Bot — Multi-Platform Search</b>\n\n"
        f"Sources: {', '.join(available)}\n\n"
        "• Type any song name or <code>Song - Artist</code>\n"
        "• Paste a music URL (SoundCloud, Audiomack, YouTube) to download directly\n"
        "• /search — step-by-step search prompt\n"
        "• /help — show this message again",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END
    if context.args:
        await _do_search(msg, " ".join(context.args).strip(), context)
        return ConversationHandler.END
    await msg.reply_text("What song are you looking for? (or /cancel)")
    return ASK_SONG


async def receive_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if not msg or not msg.text:
        return ASK_SONG
    await _do_search(msg, msg.text.strip(), context)
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text("Cancelled. Send a song name whenever you're ready.")
    return ConversationHandler.END


async def handle_plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        return
    await _do_search(msg, msg.text.strip(), context)


# ── Search flow ───────────────────────────────────────────────────────────────

async def _do_search(
    msg: Any,
    query: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not query:
        await msg.reply_text("Please send a song name.")
        return

    logger.info("QUERY_RECEIVED chat_id=%s query=%r", msg.chat_id, query)

    # Direct music URL — skip search, download directly
    if _is_music_url(query):
        logger.info("DIRECT_URL url=%r", query)
        status = await msg.reply_text("⬇️ Downloading — please wait…")
        await _download_and_send(
            url=query,
            chat_id=msg.chat_id,
            status_msg=status,
            context=context,
        )
        return

    status = await msg.reply_text("🔍 Searching SoundCloud, Audiomack, YouTube Music, Boomplay…")
    tracks = await multi_search(query, context)

    if not tracks:
        logger.warning("SEARCH_EMPTY query=%r", query)
        await _safe_edit(
            status,
            f"No results for <b>{html.escape(query)}</b>. "
            f"Try different words.\n<code>[SEARCH_EMPTY]</code>",
        )
        return

    # Cache all results + reset pagination state
    context.chat_data["all_tracks"] = tracks
    context.chat_data["last_query"] = query
    context.chat_data["current_page"] = 1
    context.chat_data["source_offset"] = 0

    text, keyboard = build_results_page(tracks, 1, query)
    await _safe_edit(status, text, keyboard)


# ── Callback handler ──────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cq = update.callback_query
    if not cq or not cq.message:
        return

    try:
        await cq.answer()
    except Exception:
        pass

    data    = (cq.data or "").strip()
    chat_id = cq.message.chat_id
    logger.info("CALLBACK data=%r chat_id=%s", data, chat_id)

    # ── cancel ────────────────────────────────────────────────────────────────
    if data == "cancel":
        logger.info("CANCEL chat_id=%s", chat_id)
        await _safe_edit(cq.message, "Cancelled. Send a song name whenever you're ready.")
        return

    # ── back to results ───────────────────────────────────────────────────────
    if data == "back":
        tracks = context.chat_data.get("all_tracks")
        query  = context.chat_data.get("last_query", "")
        page   = context.chat_data.get("current_page", 1)
        if not tracks:
            await _safe_edit(cq.message, "Session expired — please search again.")
            return
        text, keyboard = build_results_page(tracks, page, query)
        await _safe_edit(cq.message, text, keyboard)
        return

    # ── more results (pagination) ─────────────────────────────────────────────
    if data.startswith("more:"):
        page_str = data[5:]
        try:
            page = int(page_str)
        except ValueError:
            page = 1
        tracks = context.chat_data.get("all_tracks")
        query  = context.chat_data.get("last_query", "")
        if not tracks:
            await _safe_edit(cq.message, "Session expired — please search again.")
            return
        context.chat_data["current_page"] = page
        text, keyboard = build_results_page(tracks, page, query)
        await _safe_edit(cq.message, text, keyboard)
        return

    # ── another source ────────────────────────────────────────────────────────
    if data == "nextsrc":
        tracks = context.chat_data.get("all_tracks")
        query  = context.chat_data.get("last_query", "")
        if not tracks:
            await _safe_edit(cq.message, "Session expired — please search again.")
            return

        # Cycle to the next source and show only that source's results
        offset = context.chat_data.get("source_offset", 0)
        offset = (offset + 1) % len(SOURCES)
        context.chat_data["source_offset"] = offset
        target = SOURCES[offset]
        filtered = [t for t in tracks if t.get("source") == target]

        if not filtered:
            await _safe_edit(
                cq.message,
                f"No results from <b>{target}</b> for this search. "
                f"Try /search or send a new song name.",
            )
            return

        context.chat_data["current_page"] = 1
        text, keyboard = build_results_page(filtered, 1, f"{query} ({target})")
        await _safe_edit(cq.message, text, keyboard)
        return

    # ── track detail ──────────────────────────────────────────────────────────
    if data.startswith("info:"):
        try:
            index = int(data[5:])
        except ValueError:
            await _safe_edit(cq.message, "❌ Invalid track.")
            return
        tracks = context.chat_data.get("all_tracks") or []
        if index < 0 or index >= len(tracks):
            await _safe_edit(cq.message, "❌ Track not found — please search again.")
            return
        track = tracks[index]
        logger.info("TRACK_DETAIL index=%d title=%r source=%s", index, track.get("title"), track.get("source"))
        text, keyboard = build_track_detail(track, index)
        await _safe_edit(cq.message, text, keyboard)
        return

    # ── download ──────────────────────────────────────────────────────────────
    if data.startswith("dl:"):
        try:
            index = int(data[3:])
        except ValueError:
            await _safe_edit(cq.message, "❌ Invalid track.")
            return
        tracks = context.chat_data.get("all_tracks") or []
        if index < 0 or index >= len(tracks):
            await _safe_edit(cq.message, "❌ Track not found — please search again.")
            return
        track = tracks[index]
        dl_url = track.get("download_url") or track.get("url") or ""

        if not dl_url:
            await _safe_edit(
                cq.message,
                "❌ This source does not permit direct downloads. "
                "Use the Listen button to open it in your browser.",
            )
            return

        logger.info("DOWNLOAD_REQUEST index=%d url=%r source=%s chat_id=%s",
                     index, dl_url, track.get("source"), chat_id)

        await _safe_edit(cq.message, "⬇️ Downloading audio — this usually takes 10–30 seconds…")

        await _download_and_send(
            url=dl_url,
            chat_id=chat_id,
            status_msg=cq.message,
            context=context,
            track_meta=track,
        )
        return

    logger.warning("CALLBACK_UNHANDLED data=%r chat_id=%s", data, chat_id)


# ── Download-and-send helper ──────────────────────────────────────────────────

async def _download_and_send(
    url:        str,
    chat_id:    int,
    status_msg: Any,
    context:    ContextTypes.DEFAULT_TYPE,
    track_meta: dict | None = None,
) -> None:
    """Download *url*, send the audio to *chat_id*, delete the temp dir."""
    tmpdir = tempfile.mkdtemp(prefix="scbot_", dir="/tmp")
    logger.info("TMPDIR_CREATED %r", tmpdir)

    try:
        path, dl_info = await _run_blocking(download_audio, url, tmpdir)

        title    = dl_info.get("title")    or (track_meta or {}).get("title")    or ""
        artist   = dl_info.get("uploader") or (track_meta or {}).get("artist")   or \
                   dl_info.get("artist")   or (track_meta or {}).get("artist")  or ""
        dur_secs = dl_info.get("duration") or (track_meta or {}).get("duration")
        page_url = dl_info.get("webpage_url") or url
        source   = (track_meta or {}).get("source", "")
        size_mb  = os.path.getsize(path) / (1024 * 1024)

        logger.info(
            "UPLOAD_START chat_id=%s title=%r artist=%r source=%s size_mb=%.2f",
            chat_id, title, artist, source, size_mb,
        )

        # Build caption in the requested format
        parts: list[str] = []
        if title:
            parts.append(f"🎵 <b>{html.escape(title)}</b>")
        if artist:
            parts.append(f"👤 Artist: {html.escape(artist)}")
        release = (track_meta or {}).get("release_date", "")
        if release and str(release)[:4] not in ("", "None"):
            parts.append(f"📅 Release: {html.escape(str(release)[:4])}")
        dur_str = fmt_duration(int(dur_secs) if dur_secs else None)
        if dur_str:
            parts.append(f"⏱ Duration: {dur_str}")
        if source:
            parts.append(f"🎧 Source: {html.escape(source)}")
        if page_url:
            parts.append(f'\n🔗 <a href="{html.escape(page_url)}">Open on {html.escape(source or "source")}</a>')
        caption = "\n".join(parts)

        try:
            await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
            with open(path, "rb") as f:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    title=title   or None,
                    performer=artist or None,
                    duration=int(dur_secs) if dur_secs else None,
                )
            logger.info("UPLOAD_COMPLETE chat_id=%s title=%r size_mb=%.2f",
                         chat_id, title, size_mb)
        except Exception:
            logger.exception(
                "SEND_FAILED chat_id=%s title=%r size_mb=%.2f",
                chat_id, title, size_mb,
            )
            await _safe_edit(status_msg, _ERR["SEND_FAILED"])
            return

        await _safe_edit(
            status_msg,
            "✅ Sent! Type another song name or paste a music URL for more.",
        )

    except RuntimeError as exc:
        code = str(exc)
        logger.exception("RUNTIME_ERROR code=%r url=%r", code, url)
        await _safe_edit(status_msg, _ERR.get(code, _ERR["INTERNAL_ERROR"]))

    except Exception:
        logger.exception("UNEXPECTED_ERROR url=%r", url)
        await _safe_edit(status_msg, _ERR["INTERNAL_ERROR"])

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        logger.info("TMPDIR_DELETED %r", tmpdir)


# ── Safe in-place message edit ────────────────────────────────────────────────

async def _safe_edit(
    message: Any,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        err = str(exc).lower()
        if "message is not modified" in err:
            pass
        elif "there is no text in the message" in err:
            try:
                await message.edit_caption(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            except Exception:
                logger.exception("EDIT_CAPTION_FAILED")
        else:
            logger.warning("EDIT_FAILED [BadRequest]: %s", exc)
    except (RetryAfter, TimedOut) as exc:
        logger.warning("EDIT_FAILED [rate-limit/timeout]: %s", exc)
    except Exception as exc:
        logger.warning("EDIT_FAILED [unexpected]: %s", exc)


# ── Thread-pool helper ────────────────────────────────────────────────────────

async def _run_blocking(fn: Any, *args: Any, **kwargs: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))


# ── Railway health-check server ───────────────────────────────────────────────

def _start_health_server() -> None:
    port = int(os.environ.get("PORT", 8080))

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("HEALTH_SERVER port=%d", port)


# ── Global Telegram error handler ────────────────────────────────────────────

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    update_str = "no_update"
    if isinstance(update, Update):
        try:
            update_str = json.dumps(update.to_dict(), ensure_ascii=False)
        except Exception:
            update_str = repr(update)
    logger.exception(
        "UNHANDLED_ERROR update=%s",
        update_str,
        exc_info=context.error,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    global _COOKIEFILE

    token = (
        os.environ.get("TELEGRAM_BOT_TOKEN")
        or os.environ.get("BOT_TOKEN")
    )
    if not token:
        raise SystemExit(
            "Set TELEGRAM_BOT_TOKEN (or BOT_TOKEN) to your BotFather token."
        )

    print(f"yt-dlp version  : {yt_dlp.version.__version__}", flush=True)
    print(f"FFmpeg available: {_ffmpeg_available()}", flush=True)
    print(f"YouTube Music   : {'available' if _ytm else 'unavailable (ytmusicapi not installed)'}", flush=True)
    print(f"httpx           : {'available' if httpx else 'unavailable'}", flush=True)
    logger.info("STARTUP yt_dlp=%s ffmpeg=%s ytmusic=%s httpx=%s",
                yt_dlp.version.__version__, _ffmpeg_available(),
                bool(_ytm), bool(httpx))

    _COOKIEFILE = _setup_cookies()

    _start_health_server()

    app = Application.builder().token(token).build()

    search_conv = ConversationHandler(
        entry_points=[CommandHandler("search", cmd_search)],
        states={
            ASK_SONG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_query)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(search_conv)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_plain_text))
    app.add_error_handler(handle_error)

    logger.info("STARTUP polling for updates…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
