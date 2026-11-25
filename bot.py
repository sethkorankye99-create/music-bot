"""Telegram bot — aiogram 3.x rewrite."""

import asyncio
import hashlib
import html
import json
import logging
import os
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputMediaAudio,
    InputMediaVideo,
    InputTextMessageContent,
    Message,
)

from config import config
from downloaders import (
    AUDIO_FORMATS,
    VIDEO_QUALITIES,
    DownloadCancelled,
    FileTooLarge,
    cleanup,
    download,
    fetch_kinopoisk_info,
    get_available_audio_codecs,
    get_available_video_heights,
    list_episodes,
    search_youtube_results,
)
from downloaders.core import _human_size, classify_download_error
from health import init as health_init
from health import start_health_server
from i18n import get_text
from platforms import Platform, detect_platform, extract_url, resolve_share_url
from services import CacheEntry, QueueTask, media_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mediabot")

config.validate()

bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Filled in at startup
_bot_username: str = "bot"

_YOUTUBE_CODECS: set[str] = {"opus", "mp4a"}
IGNORED_PERFORMERS = {"Неизвестно", "Unknown", "Кинопоиск", "Kinopoisk"}


# ---------------------------------------------------------------------------
# Keyboard helpers
# ---------------------------------------------------------------------------

def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=d) for t, d in row]
            for row in rows
        ]
    )


def _keyboard_language() -> InlineKeyboardMarkup:
    return _kb([[("🇷🇺 Русский", "set_lang:ru"), ("🇺🇸 English", "set_lang:en")]])


def _keyboard_start(lang: str = "ru") -> InlineKeyboardMarkup:
    return _kb([[
        (get_text(lang, "btn_help"), "help"),
        (get_text(lang, "btn_settings"), "settings"),
    ]])


def _keyboard_cancel(lang: str = "ru") -> InlineKeyboardMarkup:
    return _kb([[(get_text(lang, "btn_cancel"), "cancel_download")]])


def _flow_cancel_row(lang: str = "ru") -> list[tuple[str, str]]:
    return [(get_text(lang, "btn_flow_cancel"), "flow:cancel")]


def _keyboard_disclaimer(lang: str = "ru") -> InlineKeyboardMarkup:
    return _kb([[(get_text(lang, "btn_agree"), "disc:ok")], _flow_cancel_row(lang)])


def _keyboard_search_results(results: list[dict], lang: str = "ru") -> InlineKeyboardMarkup:
    rows = []
    for idx, item in enumerate(results):
        label = f"{idx + 1}. {item.get('title') or get_text(lang, 'untitled')}"
        if len(label) > 55:
            label = label[:52] + "..."
        rows.append([(label, f"sr:{idx}")])
    rows.append(_flow_cancel_row(lang))
    return _kb(rows)


def _keyboard_search_format(show_back: bool, lang: str = "ru") -> InlineKeyboardMarkup:
    rows = [
        [(get_text(lang, "btn_dl_audio"), "dl:audio")],
        [(get_text(lang, "btn_dl_video"), "dl:video")],
    ]
    bottom = [(get_text(lang, "btn_back_results"), "sr:back")] if show_back else []
    rows.append(bottom + _flow_cancel_row(lang))
    return _kb(rows)


def _keyboard_fmt(platform: Platform, lang: str = "ru") -> InlineKeyboardMarkup:
    video_ok = platform not in (
        Platform.SPOTIFY, Platform.SHAZAM, Platform.PINTEREST, Platform.SOUNDCLOUD
    )
    row = []
    if video_ok:
        row.append((get_text(lang, "btn_link_video"), "fmt:video"))
    row.append((get_text(lang, "btn_link_audio"), "fmt:audio"))
    return _kb([row, _flow_cancel_row(lang)])


def _keyboard_video_quality(
    available_heights: list[int] | None = None, lang: str = "ru"
) -> InlineKeyboardMarkup:
    rows = []
    for key, info in VIDEO_QUALITIES.items():
        if available_heights and int(key) > max(available_heights):
            continue
        rows.append([(info["label"], f"vq:{key}")])
    rows.append([(get_text(lang, "btn_back"), "back:fmt")] + _flow_cancel_row(lang))
    return _kb(rows)


def _keyboard_audio_format(
    codecs: set[str] | None = None, show_back: bool = True, lang: str = "ru"
) -> InlineKeyboardMarkup:
    lossless = codecs is None or bool(codecs & {"flac", "alac"})
    rows = []
    for key, info in AUDIO_FORMATS.items():
        if key == "flac" and not lossless:
            continue
        rows.append([(info["label"], f"af:{key}")])
    bottom = [(get_text(lang, "btn_back"), "back:fmt")] if show_back else []
    rows.append(bottom + _flow_cancel_row(lang))
    return _kb(rows)


def _keyboard_kp_seasons(seasons: list[int], lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    for s in seasons:
        row.append((get_text(lang, "kp_season_btn", season=s), f"kp_s:{s}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return _kb(rows)


def _keyboard_kp_episodes(
    season: int, episodes: list[int], lang: str = "ru"
) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    for e in episodes:
        row.append((get_text(lang, "kp_episode_btn", episode=e), f"kp_e:{e}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return _kb(rows)


def _keyboard_kp_translations(translations: list[dict]) -> InlineKeyboardMarkup:
    return _kb([[(t["name"], f"kp_tr:{t['id']}")] for t in translations])


def _history_keyboard(entries: list, lang: str = "ru") -> InlineKeyboardMarkup:
    rows = []
    for entry in entries:
        label = entry.title or get_text(lang, "untitled")
        if entry.performer and entry.performer not in IGNORED_PERFORMERS:
            label = f"{entry.performer} - {label}"
        mt = getattr(entry, "media_type", None)
        kind_map = {
            "audio": get_text(lang, "media_audio"),
            "video": get_text(lang, "media_video"),
            "photo": get_text(lang, "media_photo"),
            "document": get_text(lang, "media_file"),
        }
        kind = kind_map.get(mt, mt or get_text(lang, "media_file"))
        fmt = getattr(entry, "media_format", None) or get_text(lang, "unknown_format")
        label = f"[{kind} | {fmt}] {label}"
        if len(label) > 55:
            label = label[:52] + "..."
        rows.append([(label, f"save:{entry.media_key}")])
    return _kb(rows)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _esc(text) -> str:
    return html.escape(str(text))


def _title_with_link(title: str, url: str | None, lang: str = "ru") -> str:
    safe = _esc(title) if title else get_text(lang, "untitled")
    if not url:
        return safe
    return f'<a href="{_esc(url)}">{safe}</a>'


def _caption(result, url: str | None = None, lang: str = "ru") -> str:
    title_part = _title_with_link(result.title, url, lang=lang)
    performer = result.uploader
    if performer and performer not in IGNORED_PERFORMERS:
        lines = [f"<b>{_esc(performer)}</b> - {title_part}"]
    else:
        lines = [title_part]
    if getattr(result, "converted", False):
        lines.append(get_text(lang, "format_converted"))
    lines.append(f"@{_esc(_bot_username)}")
    return "\n".join(lines)


def _cache_caption(entry: CacheEntry, lang: str = "ru") -> str:
    title_part = _title_with_link(entry.title or "", entry.source_url, lang=lang)
    if entry.performer and entry.performer not in IGNORED_PERFORMERS:
        return f"<b>{_esc(entry.performer)}</b> - {title_part}\n@{_esc(_bot_username)}"
    return f"{title_part}\n@{_esc(_bot_username)}"


def _fmt_duration(seconds: int | None) -> str | None:
    if not seconds:
        return None
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"


def _search_result_line(item: dict, lang: str = "ru") -> str:
    line = _title_with_link(item.get("title") or "", item.get("url"), lang=lang)
    meta = []
    if item.get("channel"):
        meta.append(f"👤 {_esc(item['channel'])}")
    duration = _fmt_duration(item.get("duration"))
    if duration:
        meta.append(f"⏱ {duration}")
    if meta:
        line += "\n    " + " · ".join(meta)
    return line


def _search_results_text(query: str, results: list[dict], lang: str = "ru") -> str:
    lines = [get_text(lang, "search_results_header", query=_esc(query)), ""]
    for idx, item in enumerate(results, start=1):
        lines.append(f"{idx}. {_search_result_line(item, lang)}")
    lines += ["", get_text(lang, "search_results_footer")]
    return "\n".join(lines)


def _search_selected_text(item: dict, lang: str = "ru") -> str:
    return f"{_search_result_line(item, lang)}\n\n{get_text(lang, 'search_choose_format')}"


def _platform_to_json(p: Platform) -> str:
    return p.name


def _platform_from_json(name: str) -> Platform:
    return Platform[name]


def _parse_search_query(text: str):
    text = text.strip()
    if "\n" in text:
        parts = [p.strip() for p in text.splitlines() if p.strip()]
        return (parts[0] if parts else None), (parts[1] if len(parts) > 1 else None), text
    if " - " in text:
        left, _, right = text.partition(" - ")
        return right.strip(), left.strip(), text
    return None, None, None


def get_stable_id(query: str, fmt: str) -> str:
    h = hashlib.blake2b(query.encode(), digest_size=4).hexdigest()
    return f"{fmt}_{h}"


# ---------------------------------------------------------------------------
# Media / upload helpers
# ---------------------------------------------------------------------------

async def _safe_edit(msg: Message, text: str, reply_markup=None, **kwargs):
    try:
        await msg.edit_text(text, reply_markup=reply_markup, **kwargs)
    except Exception as e:  # noqa: BLE001
        log.debug("safe_edit: %s", e)
        try:
            await msg.edit_text(text, reply_markup=reply_markup, parse_mode=None, **kwargs)
        except Exception as e2:  # noqa: BLE001
            log.debug("safe_edit plain: %s", e2)


async def _safe_delete(msg: Message):
    try:
        await msg.delete()
    except Exception as e:  # noqa: BLE001
        log.debug("safe_delete: %s", e)


async def _probe_video_metadata(filepath: Path) -> tuple[int, int, int]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration",
        "-show_entries", "format=duration",
        "-of", "json", str(filepath),
    ]
    w = h = d = 0
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        if proc.returncode == 0 and stdout:
            data = json.loads(stdout.decode())
            streams = data.get("streams", [])
            if streams:
                vs = streams[0]
                w = int(vs.get("width") or 0)
                h = int(vs.get("height") or 0)
                try:
                    d = int(float(vs.get("duration", 0)))
                except (ValueError, TypeError):
                    pass
            if not d and "format" in data:
                try:
                    d = int(float(data["format"].get("duration", 0)))
                except (ValueError, TypeError):
                    pass
    except Exception as e:  # noqa: BLE001
        log.warning("ffprobe failed for %s: %s", filepath, e)
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
    return w, h, d


async def _ensure_video_info(filepath: Path, result) -> tuple[int, int, int, Path | None]:
    width = getattr(result, "width", 0) or 0
    height = getattr(result, "height", 0) or 0
    duration = getattr(result, "duration", 0) or 0
    thumb = getattr(result, "thumbnail", None)
    thumb_path: Path | None = thumb if (thumb and thumb.exists()) else None

    if not (width and height and duration):
        pw, ph, pd = await _probe_video_metadata(filepath)
        if not width and pw:
            width = pw
            if hasattr(result, "width"):
                result.width = width
        if not height and ph:
            height = ph
            if hasattr(result, "height"):
                result.height = height
        if not duration and pd:
            duration = pd
            if hasattr(result, "duration"):
                result.duration = duration

    if not thumb_path:
        gen = filepath.with_suffix(".thumb.jpg")
        if gen.exists() and gen.stat().st_size > 0:
            thumb_path = gen
        else:
            seek = min(5.0, max(1.0, duration * 0.1)) if duration else 3.0
            cmd = [
                "ffmpeg", "-y", "-ss", str(seek),
                "-i", str(filepath), "-vframes", "1", "-q:v", "2", str(gen),
            ]
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=15.0)
                if proc.returncode == 0 and gen.exists() and gen.stat().st_size > 0:
                    thumb_path = gen
                    if hasattr(result, "thumbnail"):
                        result.thumbnail = gen
            except Exception as e:  # noqa: BLE001
                log.warning("Thumbnail generation failed for %s: %s", filepath, e)
                if proc and proc.returncode is None:
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass

    return width, height, duration, thumb_path


async def _send_cached_media(chat_id: int, entry: CacheEntry, lang: str = "ru"):
    cap = _cache_caption(entry, lang=lang)
    try:
        if entry.media_type == "audio":
            return await bot.send_audio(chat_id, audio=entry.file_id, caption=cap)
        if entry.media_type == "video":
            return await bot.send_video(chat_id, video=entry.file_id, caption=cap)
        if entry.media_type == "photo":
            return await bot.send_photo(chat_id, photo=entry.file_id, caption=cap)
        return await bot.send_document(chat_id, document=entry.file_id, caption=cap)
    except Exception as e:  # noqa: BLE001
        log.warning("cached send fallback (%s): %s", entry.media_type, e)
        return await bot.send_document(chat_id, document=entry.file_id, caption=cap)


async def send_result(
    chat_id: int, result, status_msg, url: str | None = None, lang: str = "ru"
):
    """Upload a downloaded file to Telegram. status_msg must have .edit_text / .delete."""
    cap = _caption(result, url, lang=lang)
    fp: Path = result.filepath
    thumb = result.thumbnail
    thumb_fi = FSInputFile(str(thumb)) if (thumb and thumb.exists() and thumb.stat().st_size > 0) else None

    await status_msg.edit_text(get_text(lang, "sending_file"))

    sent = None
    media_type = "document"
    suffix = fp.suffix.lower()

    try:
        if result.is_audio or suffix in (".mp3", ".m4a", ".flac", ".ogg", ".wav"):
            kw: dict = dict(chat_id=chat_id, audio=FSInputFile(str(fp)), caption=cap)
            if result.uploader:
                kw["performer"] = result.uploader
            if result.title:
                kw["title"] = result.title
            if thumb_fi:
                kw["thumbnail"] = thumb_fi
            try:
                sent = await bot.send_audio(**kw)
            except Exception as err:  # noqa: BLE001
                log.warning("send_audio retry without thumbnail: %s", err)
                kw.pop("thumbnail", None)
                sent = await bot.send_audio(**kw)
            media_type = "audio"

        elif suffix in (".mp4", ".mkv", ".webm", ".mov", ".avi"):
            vw, vh, vd, vt = await _ensure_video_info(fp, result)
            kw = dict(
                chat_id=chat_id, video=FSInputFile(str(fp)),
                caption=cap, supports_streaming=True,
            )
            if vt:
                kw["thumbnail"] = FSInputFile(str(vt))
            if vw:
                kw["width"] = vw
            if vh:
                kw["height"] = vh
            if vd:
                kw["duration"] = vd
            try:
                sent = await bot.send_video(**kw)
            except Exception as err:  # noqa: BLE001
                log.warning("send_video retry without thumbnail: %s", err)
                kw.pop("thumbnail", None)
                sent = await bot.send_video(**kw)
            media_type = "video"

        elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
            sent = await bot.send_photo(chat_id, photo=FSInputFile(str(fp)), caption=cap)
            media_type = "photo"

        else:
            kw = dict(chat_id=chat_id, document=FSInputFile(str(fp)), caption=cap)
            if thumb_fi:
                kw["thumbnail"] = thumb_fi
            try:
                sent = await bot.send_document(**kw)
            except Exception as err:  # noqa: BLE001
                log.warning("send_document retry without thumbnail: %s", err)
                kw.pop("thumbnail", None)
                sent = await bot.send_document(**kw)
            media_type = "document"

    except Exception as e:  # noqa: BLE001
        log.warning("media send failed, falling back to raw document: %s", e)
        sent = await bot.send_document(chat_id, document=FSInputFile(str(fp)), caption=cap)
        media_type = "document"

    await status_msg.delete()
    return sent, media_type


async def _try_send_cached(
    chat_id: int, user_id: int, media_key: str,
    status_msg=None, lang: str = "ru"
) -> bool:
    cached = await media_service.storage.get_cache(media_key)
    if cached is None:
        return False
    if status_msg is not None:
        await status_msg.edit_text(get_text(lang, "found_in_cache"))
    await _send_cached_media(chat_id, cached, lang=lang)
    await media_service.storage.add_history(user_id, media_key)
    if status_msg is not None:
        await status_msg.delete()
    return True


# ---------------------------------------------------------------------------
# Thin proxy so _process_queued_download can edit/delete status messages
# via the Bot object (no Message object is kept across the queue boundary)
# ---------------------------------------------------------------------------

class _BotMsgProxy:
    """Minimal Message-like proxy backed by bot.edit_message_text / delete_message."""

    def __init__(self, chat_id: int, message_id: int):
        self.chat = type("_C", (), {"id": chat_id})()
        self.message_id = message_id

    async def edit_text(self, text: str, reply_markup=None):
        try:
            await bot.edit_message_text(
                chat_id=self.chat.id,
                message_id=self.message_id,
                text=text,
                reply_markup=reply_markup,
            )
        except Exception as e:  # noqa: BLE001
            log.debug("proxy edit_text: %s", e)
            try:
                await bot.edit_message_text(
                    chat_id=self.chat.id,
                    message_id=self.message_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=None,
                )
            except Exception as e2:  # noqa: BLE001
                log.debug("proxy edit_text plain: %s", e2)

    async def delete(self):
        try:
            await bot.delete_message(self.chat.id, self.message_id)
        except Exception as e:  # noqa: BLE001
            log.debug("proxy delete: %s", e)


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------

async def _update_waiting_queue_positions():
    try:
        tasks = await media_service.queue.get_all_queued_tasks()
        total = len(tasks)
        for idx, task in enumerate(tasks, start=1):
            try:
                ul = (await media_service.storage.get_user_language(task.user_id)) or "ru"
                await bot.edit_message_text(
                    chat_id=task.status_chat_id,
                    message_id=task.status_message_id,
                    text=get_text(ul, "queue_position", pos=idx, total=total),
                    reply_markup=_keyboard_cancel(ul),
                )
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        log.warning("update_queue_positions: %s", e)


async def _enqueue_download(
    *,
    chat_id: int,
    user_id: int,
    url: str | None,
    platform: Platform,
    want_audio: bool,
    status_msg,
    audio_format: str = "mp3_192",
    video_quality: str = "1080",
    search_query: str | None = None,
    music_title: str | None = None,
    music_artist: str | None = None,
    season: int | None = None,
    episode: int | None = None,
    translation_id: int | None = None,
):
    ul = (await media_service.storage.get_user_language(user_id)) or "ru"

    # --- Daily download limit check ---
    allowed = await media_service.queue.check_and_increment_daily_limit(
        user_id, config.DAILY_DOWNLOAD_LIMIT
    )
    if not allowed:
        await status_msg.edit_text(
            get_text(ul, "daily_limit_reached", limit=config.DAILY_DOWNLOAD_LIMIT)
        )
        return

    media_key = await media_service.compute_media_key(
        url=url, platform=platform, want_audio=want_audio,
        audio_format=audio_format, video_quality=video_quality,
        search_query=search_query, music_title=music_title,
        music_artist=music_artist, season=season,
        episode=episode, translation_id=translation_id,
    )

    if await _try_send_cached(chat_id, user_id, media_key, status_msg=status_msg):
        return

    task = QueueTask(
        task_id=f"{user_id}:{status_msg.message_id}:{media_key[:8]}",
        user_id=user_id,
        chat_id=chat_id,
        status_chat_id=status_msg.chat.id,
        status_message_id=status_msg.message_id,
        url=url,
        platform=platform.value,
        want_audio=want_audio,
        audio_format=audio_format,
        video_quality=video_quality,
        search_query=search_query,
        music_title=music_title,
        music_artist=music_artist,
        media_key=media_key,
        season=season,
        episode=episode,
        translation_id=translation_id,
    )
    await media_service.queue.enqueue(task)
    pos, total = await media_service.queue.get_task_position(task.task_id)
    text = (
        get_text(ul, "queue_position", pos=pos, total=total)
        if pos > 1
        else get_text(ul, "task_processing_started")
    )
    await status_msg.edit_text(text, reply_markup=_keyboard_cancel(ul))


async def _process_queued_download(task: QueueTask):
    await media_service.queue.set_active(task.user_id, task.status_message_id)
    ul = (await media_service.storage.get_user_language(task.user_id)) or "ru"
    proxy = _BotMsgProxy(task.status_chat_id, task.status_message_id)

    await proxy.edit_text(
        get_text(ul, "task_processing_started"),
        reply_markup=_keyboard_cancel(ul),
    )
    asyncio.create_task(_update_waiting_queue_positions())

    if task.media_key and await _try_send_cached(
        task.chat_id, task.user_id, task.media_key, lang=ul
    ):
        await proxy.delete()
        await media_service.queue.clear_active(task.user_id, task.task_id)
        asyncio.create_task(_update_waiting_queue_positions())
        return

    last_progress = [""]

    async def on_progress(text: str):
        if text != last_progress[0]:
            last_progress[0] = text
            await proxy.edit_text(_esc(text), reply_markup=_keyboard_cancel(ul))

    def should_cancel() -> bool:
        return media_service.queue.is_cancel_requested_sync(task.user_id)

    result = None
    try:
        async with asyncio.timeout(config.TASK_TIMEOUT_SECONDS):
            result = await download(
                url=task.url,
                platform=Platform(task.platform),
                want_audio=task.want_audio,
                on_progress=on_progress,
                audio_format=task.audio_format,
                video_quality=task.video_quality,
                artist_track_name=task.search_query,
                music_title=task.music_title,
                music_artist=task.music_artist,
                should_cancel=should_cancel,
                season=task.season,
                episode=task.episode,
                translation_id=task.translation_id,
                lang=ul,
            )

            sent, media_type = await send_result(
                task.chat_id, result, proxy, url=task.url, lang=ul
            )

            if sent and task.media_key:
                file_id = None
                if media_type == "audio" and sent.audio:
                    file_id = sent.audio.file_id
                elif media_type == "video" and sent.video:
                    file_id = sent.video.file_id
                elif media_type == "photo" and sent.photo:
                    file_id = sent.photo[-1].file_id
                elif sent.document:
                    file_id = sent.document.file_id
                if file_id:
                    await media_service.storage.save_cache(
                        media_key=task.media_key,
                        file_id=file_id,
                        media_type=media_type,
                        media_format=task.audio_format if task.want_audio else task.video_quality,
                        title=result.title or task.music_title,
                        performer=result.uploader or task.music_artist,
                        source_url=task.url,
                    )
                    await media_service.storage.add_history(task.user_id, task.media_key)

    except TimeoutError:
        log.warning("Task %s timed out after %ss", task.task_id, config.TASK_TIMEOUT_SECONDS)
        await proxy.edit_text(get_text(ul, "download_timeout"))
    except DownloadCancelled:
        await media_service.queue.clear_cancel(task.user_id)
        await proxy.edit_text(get_text(ul, "cancel_done"))
    except FileTooLarge:
        await proxy.edit_text(get_text(ul, "file_too_large", limit=config.MAX_FILE_SIZE_MB))
    except Exception as e:
        log.exception("download failed for task %s", task.task_id)
        await proxy.edit_text(get_text(ul, classify_download_error(e) or "download_error"))
    finally:
        await media_service.queue.clear_active(task.user_id, task.task_id)
        if result and result.filepath and result.filepath.exists():
            cleanup(result.filepath)
        asyncio.create_task(_update_waiting_queue_positions())


# ---------------------------------------------------------------------------
# Language guard
# ---------------------------------------------------------------------------

async def _ensure_user_lang(event) -> str | None:
    user_id = event.from_user.id
    lang = await media_service.storage.get_user_language(user_id)
    if lang is None:
        markup = _keyboard_language()
        text = get_text(None, "select_language_prompt")
        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(text, reply_markup=markup)
        else:
            await event.answer(text, reply_markup=markup)
        return None
    return lang


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@router.message(Command("start"))
async def cmd_start(msg: Message):
    lang = await media_service.storage.get_user_language(msg.from_user.id)
    if lang is None:
        await msg.answer(
            get_text(None, "select_language_prompt"),
            reply_markup=_keyboard_language(),
        )
        return
    await msg.answer(get_text(lang, "start_text"), reply_markup=_keyboard_start(lang))


@router.message(Command("settings"))
async def cmd_settings(msg: Message):
    lang = (await media_service.storage.get_user_language(msg.from_user.id)) or "ru"
    await msg.answer(get_text(lang, "settings_text"), reply_markup=_keyboard_language())


@router.message(Command("help"))
async def cmd_help(msg: Message):
    lang = await _ensure_user_lang(msg)
    if not lang:
        return
    await msg.answer(get_text(lang, "help_text"))


@router.message(Command("queue"))
async def cmd_queue(msg: Message):
    lang = await _ensure_user_lang(msg)
    if not lang:
        return
    tasks = await media_service.queue.list_user_tasks(msg.from_user.id)
    if not tasks:
        await msg.answer(get_text(lang, "queue_empty"))
        return
    lines = [get_text(lang, "queue_header")]
    for idx, task in enumerate(tasks, start=1):
        kind = get_text(lang, "btn_audio" if task.get("want_audio") else "btn_video")
        status = get_text(lang, f"status_{task['status']}")
        label = task.get("music_title") or task.get("search_query") or task.get("url") or "?"
        label = _esc(label)
        lines.append(f"{idx}. [{status}] {kind} - {label}")
    await msg.answer("\n".join(lines))


@router.message(Command("cancel"))
async def cmd_cancel(msg: Message):
    lang = await _ensure_user_lang(msg)
    if not lang:
        return
    cancelled = await media_service.queue.request_cancel(msg.from_user.id)
    await msg.answer(get_text(lang, "cancel_requested" if cancelled else "cancel_no_active"))


@router.message(Command("saves"))
async def cmd_saves(msg: Message):
    lang = await _ensure_user_lang(msg)
    if not lang:
        return
    history = await media_service.storage.recent_history(msg.from_user.id, limit=10)
    if not history:
        await msg.answer(get_text(lang, "saves_empty"))
        return
    await msg.answer(
        get_text(lang, "saves_header", limit=10),
        reply_markup=_history_keyboard(history, lang),
    )


@router.message(Command("search"))
async def cmd_search(msg: Message):
    lang = await _ensure_user_lang(msg)
    if not lang:
        return
    args = (msg.text or "").partition(" ")[2].strip()
    if not args:
        await msg.answer(get_text(lang, "search_usage"))
        return
    title, artist, query = _parse_search_query(args)
    if query is None:
        await msg.answer(get_text(lang, "search_usage"))
        return
    await _ask_disclaimer(
        msg, lang, kind="cmd_search",
        search_query=query, music_title=title, music_artist=artist,
    )


# ---------------------------------------------------------------------------
# Text handler: URLs go to the link flow, plain text becomes a YouTube search
# ---------------------------------------------------------------------------

_SEARCH_MAX_LEN = 200
_SEARCH_VIDEO_QUALITY = "720"
_SEARCH_AUDIO_FORMAT = "mp3_192"
_SEARCH_RESULTS_LIMIT = 5


@router.message(F.text)
async def handle_text(msg: Message):
    text = (msg.text or "").strip()
    if not text or text.startswith("/"):
        return
    lang = await _ensure_user_lang(msg)
    if not lang:
        return
    url = extract_url(text)
    if url:
        url = await resolve_share_url(url)
        if detect_platform(url) == Platform.UNKNOWN:
            await msg.answer(get_text(lang, "unsupported_platform"))
            return
        await _ask_disclaimer(msg, lang, kind="link", url=url)
    elif msg.chat.type == "private":
        await _ask_disclaimer(msg, lang, kind="search", query=text[:_SEARCH_MAX_LEN])


async def _ask_disclaimer(msg: Message, lang: str, *, kind: str, **data):
    reply = await msg.answer(
        get_text(lang, "disclaimer_text"),
        reply_markup=_keyboard_disclaimer(lang),
    )
    await media_service.pending.set(f"{reply.chat.id}:{reply.message_id}", {
        "stage": "disclaimer",
        "kind": kind,
        "user_id": msg.from_user.id,
        **data,
    })


async def _run_search(status_msg: Message, key: str, user_id: int, query: str, lang: str):
    await _safe_edit(status_msg, get_text(lang, "text_searching", query=_esc(query)))
    try:
        results = await search_youtube_results(query, limit=_SEARCH_RESULTS_LIMIT)
    except Exception as e:  # noqa: BLE001
        log.warning("YouTube search failed: %s", e)
        results = []
    if not results:
        await media_service.pending.pop(key)
        await _safe_edit(status_msg, get_text(lang, "text_search_empty", query=_esc(query)))
        return
    state = {
        "stage": "results",
        "kind": "search",
        "user_id": user_id,
        "query": query,
        "results": results,
        "selected": None,
    }
    if len(results) == 1:
        state["stage"] = "format"
        state["selected"] = 0
        await media_service.pending.set(key, state)
        await _safe_edit(
            status_msg, _search_selected_text(results[0], lang),
            reply_markup=_keyboard_search_format(show_back=False, lang=lang),
        )
        return
    await media_service.pending.set(key, state)
    await _safe_edit(
        status_msg, _search_results_text(query, results, lang),
        reply_markup=_keyboard_search_results(results, lang),
    )


async def _continue_link(status_msg: Message, url: str, user_id: int, lang: str):
    """Start the format-selection flow for a link on an existing bot message."""
    platform = detect_platform(url)
    key = f"{status_msg.chat.id}:{status_msg.message_id}"
    if platform == Platform.UNKNOWN:
        await media_service.pending.pop(key)
        await _safe_edit(status_msg, get_text(lang, "unsupported_platform"))
        return

    if platform == Platform.PINTEREST:
        await media_service.pending.pop(key)
        await _safe_edit(status_msg, get_text(lang, "pinterest_added"))
        await _enqueue_download(
            chat_id=status_msg.chat.id, user_id=user_id,
            url=url, platform=platform, want_audio=False, status_msg=status_msg,
        )
        return

    if platform == Platform.KINOPOISK:
        await _safe_edit(status_msg, get_text(lang, "kinopoisk_fetching"))
        try:
            info = await fetch_kinopoisk_info(url)
        except Exception as e:  # noqa: BLE001
            log.warning("Kinopoisk fetch error: %s", e)
            await media_service.pending.pop(key)
            await status_msg.edit_text(get_text(lang, "kinopoisk_error"))
            return
        state = {
            "url": url,
            "platform": _platform_to_json(platform),
            "user_id": user_id,
            "content_type": info["content_type"],
            "file_list": info["file_list"],
            "translations": info["translations"],
            "seasons": info["seasons"],
            "season": None,
            "episode": None,
            "translation_id": None,
        }
        await media_service.pending.set(key, state)
        meta = info.get("meta", {})
        title_name = (
            meta.get("nameRu") or meta.get("nameOriginal")
            or (get_text(lang, "serial_label") if info["content_type"] == "serial"
                else get_text(lang, "movie_label"))
        )
        title_name = _esc(title_name)
        year_str = f" ({_esc(meta['year'])})" if meta.get("year") else ""
        if info["content_type"] == "serial":
            await status_msg.edit_text(
                get_text(lang, "kp_season_select", title=title_name, year=year_str),
                reply_markup=_keyboard_kp_seasons(info["seasons"], lang=lang),
            )
        else:
            await status_msg.edit_text(
                get_text(lang, "kp_movie_tr"),
                reply_markup=_keyboard_kp_translations(info["translations"]),
            )
        return

    if platform in (Platform.SPOTIFY, Platform.SHAZAM, Platform.YANDEX,
                    Platform.SOUNDCLOUD, Platform.VK_MUSIC):
        await media_service.pending.set(key, {
            "url": url,
            "platform": _platform_to_json(platform),
            "want_audio": True,
            "available_codecs": list(_YOUTUBE_CODECS),
            "user_id": user_id,
        })
        await _safe_edit(
            status_msg, get_text(lang, "select_audio_format"),
            reply_markup=_keyboard_audio_format(_YOUTUBE_CODECS, show_back=False, lang=lang),
        )
        return

    await media_service.pending.set(key, {
        "url": url,
        "platform": _platform_to_json(platform),
        "want_audio": None,
        "user_id": user_id,
    })
    await _safe_edit(
        status_msg, get_text(lang, "select_format"),
        reply_markup=_keyboard_fmt(platform, lang=lang),
    )


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------

# Pending-message keys with a callback currently being processed (blocks double clicks)
_inflight: set[str] = set()


async def _owned_pending(
    cq: CallbackQuery, lang: str, *,
    pop: bool = False, hold: bool = False, stage: str | None = None,
) -> tuple[str, dict | None]:
    """Load the pending state behind a callback and check it belongs to the clicking user.

    Answers the callback itself on failure and returns (key, None).
    With hold=True the key is marked in-flight; the caller must discard it from _inflight.
    """
    key = f"{cq.message.chat.id}:{cq.message.message_id}"
    state = await media_service.pending.get(key)
    if not state:
        await cq.answer(get_text(lang, "query_expired"), show_alert=True)
        await _safe_edit(cq.message, get_text(lang, "request_expired_msg"))
        return key, None
    if state.get("user_id") != cq.from_user.id:
        await cq.answer(get_text(lang, "not_your_request"), show_alert=True)
        return key, None
    if key in _inflight or (stage is not None and state.get("stage") != stage):
        await cq.answer(get_text(lang, "already_processing"))
        return key, None
    if pop:
        state = await media_service.pending.pop(key)
        if not state:
            await cq.answer(get_text(lang, "already_processing"))
            return key, None
    if hold:
        _inflight.add(key)
    return key, state


@router.callback_query(F.data == "disc:ok")
async def cb_disclaimer_accept(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    key, state = await _owned_pending(cq, lang, hold=True, stage="disclaimer")
    if not state:
        return
    try:
        await cq.answer()
        kind = state.get("kind")
        if kind == "search":
            await _run_search(cq.message, key, state["user_id"], state["query"], lang)
        elif kind == "link":
            await _continue_link(cq.message, state["url"], state["user_id"], lang)
        elif kind == "cmd_search":
            await media_service.pending.set(key, {
                "url": None,
                "platform": _platform_to_json(Platform.UNKNOWN),
                "want_audio": True,
                "available_codecs": list(_YOUTUBE_CODECS),
                "search_query": state.get("search_query"),
                "music_title": state.get("music_title"),
                "music_artist": state.get("music_artist"),
                "user_id": state["user_id"],
            })
            await _safe_edit(
                cq.message, get_text(lang, "select_audio_format"),
                reply_markup=_keyboard_audio_format(_YOUTUBE_CODECS, show_back=False, lang=lang),
            )
        else:
            await media_service.pending.pop(key)
            await _safe_edit(cq.message, get_text(lang, "request_expired_msg"))
    finally:
        _inflight.discard(key)


@router.callback_query(F.data == "flow:cancel")
async def cb_flow_cancel(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    _, state = await _owned_pending(cq, lang, pop=True)
    if not state:
        return
    await cq.answer()
    await _safe_edit(cq.message, get_text(lang, "flow_cancelled"))


@router.callback_query(F.data.regexp(r"^sr:(\d+|back)$"))
async def cb_search_result(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    choice = cq.data.split(":", 1)[1]
    expected_stage = "format" if choice == "back" else "results"
    key, state = await _owned_pending(cq, lang, hold=True, stage=expected_stage)
    if not state:
        return
    try:
        results = state.get("results") or []
        if choice == "back":
            state["stage"] = "results"
            state["selected"] = None
            await media_service.pending.set(key, state)
            await cq.answer()
            await _safe_edit(
                cq.message, _search_results_text(state.get("query", ""), results, lang),
                reply_markup=_keyboard_search_results(results, lang),
            )
            return
        idx = int(choice)
        if idx >= len(results):
            await cq.answer(get_text(lang, "query_expired"), show_alert=True)
            return
        state["stage"] = "format"
        state["selected"] = idx
        await media_service.pending.set(key, state)
        await cq.answer()
        await _safe_edit(
            cq.message, _search_selected_text(results[idx], lang),
            reply_markup=_keyboard_search_format(show_back=len(results) > 1, lang=lang),
        )
    finally:
        _inflight.discard(key)


@router.callback_query(F.data.in_({"dl:audio", "dl:video"}))
async def cb_search_download(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    _, state = await _owned_pending(cq, lang, pop=True, stage="format")
    if not state:
        return
    try:
        item = state["results"][state["selected"]]
    except (KeyError, IndexError, TypeError):
        await cq.answer(get_text(lang, "query_expired"), show_alert=True)
        await _safe_edit(cq.message, get_text(lang, "request_expired_msg"))
        return
    await cq.answer()
    want_audio = cq.data == "dl:audio"
    if want_audio:
        label = AUDIO_FORMATS[_SEARCH_AUDIO_FORMAT]["label"]
        await _safe_edit(cq.message, get_text(lang, "adding_audio_queue", label=_esc(label)))
    else:
        label = VIDEO_QUALITIES[_SEARCH_VIDEO_QUALITY]["label"]
        await _safe_edit(cq.message, get_text(lang, "adding_video_queue", quality=_esc(label)))
    await _enqueue_download(
        chat_id=cq.message.chat.id, user_id=state["user_id"],
        url=item["url"], platform=Platform.YOUTUBE, want_audio=want_audio,
        audio_format=_SEARCH_AUDIO_FORMAT, video_quality=_SEARCH_VIDEO_QUALITY,
        status_msg=cq.message,
    )

@router.callback_query(F.data == "settings")
async def cb_settings(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    await cq.answer()
    await cq.message.edit_text(get_text(lang, "settings_text"), reply_markup=_keyboard_language())


@router.callback_query(F.data == "help")
async def cb_help(cq: CallbackQuery):
    lang = await _ensure_user_lang(cq)
    if not lang:
        return
    await cq.message.answer(get_text(lang, "help_text"))


@router.callback_query(F.data.startswith("set_lang:"))
async def cb_set_lang(cq: CallbackQuery):
    lang_code = cq.data.split(":")[1]
    await media_service.storage.set_user_language(cq.from_user.id, lang_code)
    await cq.answer(get_text(lang_code, "language_saved"), show_alert=True)
    await cq.message.edit_text(
        get_text(lang_code, "start_text"),
        reply_markup=_keyboard_start(lang_code),
    )


@router.callback_query(F.data == "cancel_download")
async def cb_cancel_download(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    cancelled = await media_service.queue.request_cancel(cq.from_user.id)
    if cancelled:
        await cq.answer(get_text(lang, "cancel_requested"), show_alert=True)
        await _safe_edit(cq.message, get_text(lang, "cancel_downloading"))
    else:
        await cq.answer(get_text(lang, "cancel_no_active"), show_alert=True)


@router.callback_query(F.data.in_({"fmt:video", "fmt:audio"}))
async def cb_fmt(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    key, state = await _owned_pending(cq, lang, hold=True)
    if not state:
        return
    try:
        await _select_fmt(cq, key, state, lang)
    finally:
        _inflight.discard(key)


async def _select_fmt(cq: CallbackQuery, key: str, state: dict, lang: str):
    await cq.answer()
    platform = _platform_from_json(state["platform"])

    if cq.data == "fmt:video":
        state["want_audio"] = False
        await cq.message.edit_text(get_text(lang, "getting_qualities"))
        heights = (
            [1080, 720, 480, 360]
            if platform == Platform.KINOPOISK
            else await get_available_video_heights(state["url"])
        )
        state["available_heights"] = heights
        await media_service.pending.set(key, state)
        await cq.message.edit_text(
            get_text(lang, "select_quality"),
            reply_markup=_keyboard_video_quality(heights or None, lang=lang),
        )
    else:
        state["want_audio"] = True
        await cq.message.edit_text(get_text(lang, "getting_formats"))
        codecs = (
            {"mp3_192"}
            if platform == Platform.KINOPOISK
            else await get_available_audio_codecs(state["url"])
        )
        state["available_codecs"] = list(codecs)
        await media_service.pending.set(key, state)
        await cq.message.edit_text(
            get_text(lang, "select_audio_format"),
            reply_markup=_keyboard_audio_format(codecs or None, lang=lang),
        )


@router.callback_query(F.data.regexp(r"^vq:\d+$"))
async def cb_video_quality(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    _, state = await _owned_pending(cq, lang, pop=True)
    if not state:
        return
    quality = cq.data.split(":")[1]
    await cq.answer()
    await cq.message.edit_text(
        get_text(lang, "adding_video_queue", quality=_esc(VIDEO_QUALITIES[quality]["label"]))
    )
    await _enqueue_download(
        chat_id=cq.message.chat.id, user_id=state["user_id"],
        url=state.get("url"), platform=_platform_from_json(state["platform"]),
        want_audio=False, status_msg=cq.message, video_quality=quality,
        search_query=state.get("search_query"), music_title=state.get("music_title"),
        music_artist=state.get("music_artist"), season=state.get("season"),
        episode=state.get("episode"), translation_id=state.get("translation_id"),
    )


@router.callback_query(F.data.regexp(r"^af:.+$"))
async def cb_audio_format(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    _, state = await _owned_pending(cq, lang, pop=True)
    if not state:
        return
    afmt = cq.data.split(":", 1)[1]
    label = AUDIO_FORMATS.get(afmt, {}).get("label", afmt)
    await cq.answer()
    await cq.message.edit_text(get_text(lang, "adding_audio_queue", label=_esc(label)))
    await _enqueue_download(
        chat_id=cq.message.chat.id, user_id=state["user_id"],
        url=state.get("url"), platform=_platform_from_json(state["platform"]),
        want_audio=True, status_msg=cq.message, audio_format=afmt,
        search_query=state.get("search_query"), music_title=state.get("music_title"),
        music_artist=state.get("music_artist"), season=state.get("season"),
        episode=state.get("episode"), translation_id=state.get("translation_id"),
    )


@router.callback_query(F.data.regexp(r"^kp_s:\d+$"))
async def cb_kp_season(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    key, state = await _owned_pending(cq, lang)
    if not state:
        return
    season = int(cq.data.split(":")[1])
    state["season"] = season
    await media_service.pending.set(key, state)
    await cq.answer()
    episodes = list_episodes(state["file_list"], season)
    await cq.message.edit_text(
        get_text(lang, "kp_serial_season", season=season),
        reply_markup=_keyboard_kp_episodes(season, episodes, lang=lang),
    )


@router.callback_query(F.data.regexp(r"^kp_e:\d+$"))
async def cb_kp_episode(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    key, state = await _owned_pending(cq, lang)
    if not state:
        return
    episode = int(cq.data.split(":")[1])
    state["episode"] = episode
    await media_service.pending.set(key, state)
    await cq.answer()
    await cq.message.edit_text(
        get_text(lang, "kp_serial_episode", season=state["season"], episode=episode),
        reply_markup=_keyboard_kp_translations(state.get("translations", [])),
    )


@router.callback_query(F.data.regexp(r"^kp_tr:\d+$"))
async def cb_kp_translation(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    key, state = await _owned_pending(cq, lang)
    if not state:
        return
    translation_id = int(cq.data.split(":")[1])
    state["translation_id"] = translation_id
    await media_service.pending.set(key, state)
    await cq.answer()
    await cq.message.edit_text(
        get_text(lang, "select_format"),
        reply_markup=_keyboard_fmt(Platform.KINOPOISK, lang=lang),
    )


@router.callback_query(F.data == "back:fmt")
async def cb_back(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    key, state = await _owned_pending(cq, lang)
    if not state:
        return
    platform = _platform_from_json(state["platform"])
    if platform in (Platform.SPOTIFY, Platform.SHAZAM, Platform.YANDEX,
                    Platform.SOUNDCLOUD, Platform.VK_MUSIC):
        await cq.answer(get_text(lang, "cannot_go_back"), show_alert=True)
        return
    await cq.answer()
    state["want_audio"] = None
    await media_service.pending.set(key, state)
    await cq.message.edit_text(
        get_text(lang, "select_format"),
        reply_markup=_keyboard_fmt(platform, lang=lang),
    )


@router.callback_query(F.data.startswith("save:"))
async def cb_saved_media(cq: CallbackQuery):
    lang = (await media_service.storage.get_user_language(cq.from_user.id)) or "ru"
    media_key = cq.data.split(":", 1)[1]
    entry = await media_service.storage.get_cache(media_key)
    if entry is None:
        await cq.answer(get_text(lang, "file_unavailable"), show_alert=True)
        return
    await cq.answer(get_text(lang, "sending_saved"))
    await _send_cached_media(cq.message.chat.id, entry, lang=lang)
    await media_service.storage.add_history(cq.from_user.id, media_key)


# ---------------------------------------------------------------------------
# Inline query
# ---------------------------------------------------------------------------

@router.inline_query()
async def on_inline_query(iq: InlineQuery):
    ul = (await media_service.storage.get_user_language(iq.from_user.id)) or "ru"
    query = iq.query.strip()
    if not query:
        await iq.answer([], cache_time=0)
        return

    url = extract_url(query)
    title, artist, search_q = None, None, None

    if url:
        platform = detect_platform(url)
    else:
        title, artist, search_q = _parse_search_query(query)
        if search_q is None:
            await iq.answer([], cache_time=0)
            return
        platform = Platform.UNKNOWN

    results = []
    for key, info in AUDIO_FORMATS.items():
        if key == "flac":
            continue
        desc = get_text(ul, "download_as_fmt", label=info["label"])
        if title and artist:
            desc = f"{artist} - {title} {info['label']}"
        results.append(InlineQueryResultArticle(
            id=get_stable_id(query, f"af_{key}"),
            title=info["label"],
            description=desc,
            input_message_content=InputTextMessageContent(
                message_text=get_text(ul, "download_inline_status",
                                      query=_esc(query), fmt=_esc(info["label"]))
            ),
        ))

    if not search_q and platform not in (
        Platform.SPOTIFY, Platform.SHAZAM, Platform.YANDEX,
        Platform.SOUNDCLOUD, Platform.VK_MUSIC,
    ):
        for q, info in VIDEO_QUALITIES.items():
            results.append(InlineQueryResultArticle(
                id=get_stable_id(query, f"vf_{q}"),
                title=info["label"],
                description=get_text(ul, "download_video_fmt", label=info["label"]),
                input_message_content=InputTextMessageContent(
                    message_text=get_text(ul, "download_inline_status",
                                          query=_esc(query), fmt=_esc(f'Video {info["label"]}'))
                ),
            ))

    await iq.answer(results, cache_time=0, is_personal=True)


@router.chosen_inline_result()
async def on_chosen_inline_result(chosen: ChosenInlineResult):
    asyncio.create_task(_process_chosen_inline(chosen))


async def _process_chosen_inline(chosen: ChosenInlineResult):
    if not chosen.inline_message_id:
        return
    rid = chosen.result_id
    if not (rid.startswith("af_") or rid.startswith("vf_")):
        return
    try:
        prefix, fmt, _ = rid.split("_", 2)
    except ValueError:
        return

    is_video = prefix == "vf"
    want_audio = not is_video
    afmt = fmt if want_audio else "mp3_192"
    vfmt = fmt if is_video else "1080"
    ul = (await media_service.storage.get_user_language(chosen.from_user.id)) or "ru"

    await bot.edit_message_text(
        inline_message_id=chosen.inline_message_id,
        text=get_text(ul, "starting_download"),
    )

    original_query = chosen.query.strip()
    url = extract_url(original_query)
    title, artist, search_q = None, None, None
    platform = Platform.UNKNOWN

    if url:
        platform = detect_platform(url)
        if is_video and platform in (Platform.SPOTIFY, Platform.SHAZAM,
                                     Platform.YANDEX, Platform.SOUNDCLOUD, Platform.VK_MUSIC):
            return
    else:
        title, artist, search_q = _parse_search_query(original_query)

    media_key = await media_service.compute_media_key(
        url=url, platform=platform, want_audio=want_audio,
        audio_format=afmt, video_quality=vfmt,
        search_query=search_q, music_title=title, music_artist=artist,
    )

    cached = await media_service.storage.get_cache(media_key)
    if cached and (
        (want_audio and cached.media_type == "audio")
        or (is_video and cached.media_type == "video")
    ):
        try:
            if cached.media_type == "audio":
                media_obj = InputMediaAudio(
                    media=cached.file_id,
                    caption=_cache_caption(cached, lang=ul),
                )
            else:
                media_obj = InputMediaVideo(
                    media=cached.file_id,
                    caption=_cache_caption(cached, lang=ul),
                )
            await bot.edit_message_media(
                inline_message_id=chosen.inline_message_id,
                media=media_obj,
            )
            await media_service.storage.add_history(chosen.from_user.id, media_key)
            return
        except Exception as e:  # noqa: BLE001
            log.warning("Inline cache send failed, downloading: %s", e)

    try:
        result = await download(
            url=url, platform=platform, want_audio=want_audio,
            audio_format=afmt, video_quality=vfmt,
            artist_track_name=search_q, music_title=title, music_artist=artist,
            lang=ul,
        )
        thumb_path = str(result.thumbnail) if (result.thumbnail and result.thumbnail.exists()) else None
        if want_audio:
            media_obj = InputMediaAudio(
                media=FSInputFile(str(result.filepath)),
                caption=_caption(result, url, lang=ul),
                performer=result.uploader,
                title=result.title,
                thumbnail=FSInputFile(thumb_path) if thumb_path else None,
            )
        else:
            media_obj = InputMediaVideo(
                media=FSInputFile(str(result.filepath)),
                caption=_caption(result, url, lang=ul),
                thumbnail=FSInputFile(thumb_path) if thumb_path else None,
            )
        await bot.edit_message_media(
            inline_message_id=chosen.inline_message_id,
            media=media_obj,
        )
        cleanup(result)
    except Exception as e:  # noqa: BLE001
        log.error("Inline download error: %s", e)
        await bot.edit_message_text(
            inline_message_id=chosen.inline_message_id,
            text=get_text(ul, classify_download_error(e) or "download_error"),
        )


# ---------------------------------------------------------------------------
# Connectivity watchdog
# ---------------------------------------------------------------------------

WATCHDOG_INTERVAL = 60
WATCHDOG_TIMEOUT = 15
WATCHDOG_MAX_FAIL = 2


async def _connectivity_watchdog():
    consecutive = 0
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL)
        try:
            await asyncio.wait_for(bot.get_me(), timeout=WATCHDOG_TIMEOUT)
            if consecutive:
                log.info("Watchdog recovered after %d failure(s)", consecutive)
            consecutive = 0
        except Exception as e:  # noqa: BLE001
            consecutive += 1
            log.error("Watchdog probe failed (%d/%d): %s", consecutive, WATCHDOG_MAX_FAIL, e)
            if consecutive >= WATCHDOG_MAX_FAIL:
                log.error("Client unresponsive — force-restarting.")
                os._exit(1)


# ---------------------------------------------------------------------------
# Startup / main
# ---------------------------------------------------------------------------

async def main():
    global _bot_username
    log.info("Starting mediabot (aiogram)")

    await media_service.init()
    media_service.start_workers(_process_queued_download)

    me = await bot.get_me()
    _bot_username = me.username or "bot"
    log.info("Bot username: @%s", _bot_username)

    health_init(bot, media_service)
    health_runner = await start_health_server(host="0.0.0.0", port=8080)

    watchdog_task = asyncio.create_task(_connectivity_watchdog())
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        watchdog_task.cancel()
        await health_runner.cleanup()
        await bot.session.close()
        await media_service.close()


if __name__ == "__main__":
    asyncio.run(main())
