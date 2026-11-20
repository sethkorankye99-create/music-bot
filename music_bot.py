"""
Telegram Music Bot
- Searches YouTube Music (unofficial ytmusicapi)
- Downloads audio via yt-dlp and sends the file to the user
"""

import html
import logging
import os
import shutil
import tempfile
from typing import Any

import yt_dlp
from ytmusicapi import YTMusic
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ── Constants ────────────────────────────────────────────────────────────────

MAX_RESULTS = 8
MAX_FILE_MB = 48          # Telegram bot upload limit is 50 MB; stay under it
ASK_SONG = 0              # ConversationHandler state

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Shared YTMusic client (no auth needed for searching)
_ytm = YTMusic()


# ── YTMusic search ───────────────────────────────────────────────────────────

def ytm_search(query: str, limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """Return up to *limit* song results from YouTube Music."""
    try:
        results = _ytm.search(query, filter="songs", limit=limit)
        return [r for r in results if r.get("videoId")]
    except Exception:
        logger.exception("YTMusic search failed for %r", query)
        return []


def fmt_artists(artists: list[dict]) -> str:
    return ", ".join(a.get("name", "") for a in artists if a.get("name"))


def fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


# ── yt-dlp download ──────────────────────────────────────────────────────────

def download_audio(video_id: str, tmpdir: str) -> tuple[str, dict]:
    """
    Download the best available audio for *video_id* into *tmpdir*.
    Returns (file_path, yt_dlp_info_dict).
    Raises RuntimeError when the download fails or the file is too large.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    outtmpl = os.path.join(tmpdir, "%(id)s.%(ext)s")

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_FILE_MB * 1024 * 1024,
        # Remux to MP3 so Telegram's player recognises it properly
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    info: dict = {}

    # First try with FFmpeg post-processing; fall back to raw audio if FFmpeg
    # is not installed on this machine.
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
            # After FFmpeg conversion the extension is .mp3
            path = os.path.join(tmpdir, f"{video_id}.mp3")
            if not os.path.exists(path):
                path = ydl.prepare_filename(info)
    except yt_dlp.utils.PostprocessingError:
        # FFmpeg not available — download raw audio
        ydl_opts_raw: dict[str, Any] = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "max_filesize": MAX_FILE_MB * 1024 * 1024,
        }
        with yt_dlp.YoutubeDL(ydl_opts_raw) as ydl:
            info = ydl.extract_info(url, download=True) or {}
            path = ydl.prepare_filename(info)
    except yt_dlp.utils.MaxDownloadsReached:
        raise RuntimeError("Track exceeds the 48 MB size limit.")
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    if not os.path.exists(path):
        files = [f for f in os.listdir(tmpdir) if not f.endswith(".part")]
        if not files:
            raise RuntimeError("Download produced no file.")
        path = os.path.join(tmpdir, files[0])

    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        raise RuntimeError(f"Track is {size_mb:.0f} MB, which is too large to send.")

    return path, info


# ── Helper: build search result message and keyboard ─────────────────────────

def build_results_ui(tracks: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    lines: list[str] = ["<b>🎵 Search results — tap one to download it</b>\n"]
    buttons: list[list[InlineKeyboardButton]] = []

    for i, track in enumerate(tracks, start=1):
        title = html.escape(track.get("title") or "Unknown")
        artist = html.escape(fmt_artists(track.get("artists") or []) or "Unknown")
        album_info = track.get("album") or {}
        album = html.escape(str(album_info.get("name") or ""))
        dur = fmt_duration(track.get("duration_seconds"))
        views = track.get("views") or ""

        line = f"{i}. <b>{title}</b> — {artist}"
        if album:
            line += f"\n   <i>{album}</i>"
        if dur:
            line += f"  ·  {dur}"
        if views:
            line += f"  ·  {views} views"
        lines.append(line)

        label = f"{i}. {track.get('title', '')[:30]} — {fmt_artists(track.get('artists') or [])[:20]}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"dl:{track['videoId']}")
        ])

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg:
        return
    await msg.reply_text(
        "🎵 <b>YouTube Music Bot</b>\n\n"
        "I search YouTube Music and send you the audio file directly.\n\n"
        "• Send a song name or <code>Song - Artist</code>\n"
        "• Or use /search to be prompted step by step\n"
        "• /help — show this message again",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Entry point for the /search conversation."""
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END

    # If the user typed /search <query> in one go, run it immediately
    if context.args:
        query = " ".join(context.args).strip()
        await _do_search(msg, query)
        return ConversationHandler.END

    await msg.reply_text("What song are you looking for? (send any text or /cancel)")
    return ASK_SONG


async def receive_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive the free-text query in the conversation."""
    msg = update.effective_message
    if not msg or not msg.text:
        return ASK_SONG
    await _do_search(msg, msg.text.strip())
    return ConversationHandler.END


async def cmd_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text("Cancelled.")
    return ConversationHandler.END


async def handle_plain_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle any plain message as a direct search query."""
    msg = update.effective_message
    if not msg or not msg.text:
        return
    await _do_search(msg, msg.text.strip())


async def _do_search(msg: Any, query: str) -> None:
    """Run a YTMusic search and send the results keyboard."""
    if not query:
        await msg.reply_text("Please send a song name.")
        return

    status = await msg.reply_text("🔍 Searching YouTube Music…")

    tracks = ytm_search(query)
    if not tracks:
        await status.edit_text(
            f"No results found for <b>{html.escape(query)}</b>. Try different words.",
            parse_mode=ParseMode.HTML,
        )
        return

    text, keyboard = build_results_ui(tracks)
    await status.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def handle_download_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle a tap on a search result — download and send the audio."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    if not data.startswith("dl:"):
        return

    video_id = data[3:]
    if video_id == "cancel":
        await query.edit_message_text("Cancelled.")
        return

    # Identify the track metadata from the original message text to build
    # a nice caption.  We only have the videoId at this point so we re-fetch.
    await query.edit_message_text("⬇️ Downloading audio, please wait…")

    tmpdir = tempfile.mkdtemp(prefix="ytbot_")
    try:
        path, dl_info = await _run_blocking(download_audio, video_id, tmpdir)

        # Build caption from yt-dlp metadata (no extra network call needed)
        title = dl_info.get("title") or ""
        artist = dl_info.get("artist") or dl_info.get("uploader") or ""
        album = dl_info.get("album") or ""
        duration_secs = dl_info.get("duration")

        caption_parts: list[str] = []
        if title:
            caption_parts.append(f"🎵 <b>{html.escape(title)}</b>")
        if artist:
            caption_parts.append(f"👤 {html.escape(artist)}")
        if album:
            caption_parts.append(f"💿 {html.escape(album)}")
        dur = fmt_duration(int(duration_secs) if duration_secs else None)
        if dur:
            caption_parts.append(f"⏱ {dur}")
        caption_parts.append(
            f"\n<a href='https://music.youtube.com/watch?v={video_id}'>Open in YouTube Music</a>"
        )

        caption = "\n".join(caption_parts)

        chat = query.message.chat if query.message else None
        if chat:
            await context.bot.send_chat_action(chat.id, ChatAction.UPLOAD_VOICE)

        with open(path, "rb") as audio_file:
            await context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=audio_file,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )

        await query.edit_message_text("✅ Sent! Use /search or just type a song name to find more.")

    except RuntimeError as exc:
        await query.edit_message_text(f"❌ {exc}")
    except Exception:
        logger.exception("Download/send failed for videoId=%s", video_id)
        await query.edit_message_text(
            "❌ Something went wrong while downloading. Please try again."
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Blocking helper ───────────────────────────────────────────────────────────

import asyncio
import functools


async def _run_blocking(fn, *args, **kwargs):
    """Run a blocking function in the default thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))


# ── Error handler ─────────────────────────────────────────────────────────────

async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error", exc_info=context.error)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "Set TELEGRAM_BOT_TOKEN to your BotFather token before starting."
        )

    app = Application.builder().token(token).build()

    # Conversation: /search → (optional) query text
    search_conv = ConversationHandler(
        entry_points=[CommandHandler("search", cmd_search)],
        states={
            ASK_SONG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_query)
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(search_conv)
    app.add_handler(CallbackQueryHandler(handle_download_callback, pattern=r"^dl:"))
    # Any plain text outside the conversation triggers a direct search
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_plain_text))
    app.add_error_handler(handle_error)

    logger.info("Bot starting — polling for updates…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
