import html
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ASK_SONG, ASK_ARTIST = range(2)
MAX_RESULTS = 5

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def parse_search_query(text: str) -> tuple[str, str] | None:
    parts = re.split(r"\s+[—–-]\s+", text.strip(), maxsplit=1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return None
    return parts[0].strip(), parts[1].strip()


async def search_tracks(song: str, artist: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            ITUNES_SEARCH_URL,
            params={
                "term": f"{song} {artist}",
                "entity": "song",
                "limit": MAX_RESULTS,
            },
        )
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("The music search service returned an invalid response.")
    return data["results"]


def safe_https_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return value


async def show_results(
    update: Update,
    song: str,
    artist: str,
) -> None:
    message = update.effective_message
    if message is None:
        return

    try:
        tracks = await search_tracks(song, artist)
    except (httpx.HTTPError, ValueError):
        logger.exception("Music search failed for %r by %r", song, artist)
        await message.reply_text(
            "I couldn't reach the music search service. Please try again in a moment."
        )
        return

    if not tracks:
        await message.reply_text(
            f"No tracks found for “{song}” by “{artist}”. Try different spelling."
        )
        return

    cards = []
    keyboard = []
    for track in tracks[:MAX_RESULTS]:
        title = html.escape(str(track.get("trackName") or "Unknown track")[:200])
        track_artist = html.escape(str(track.get("artistName") or "Unknown artist")[:200])
        album = track.get("collectionName")
        card = f"<b>{title}</b>\n{track_artist}"
        if album:
            card += f"\n<i>{html.escape(str(album)[:200])}</i>"
        cards.append(card)

        buttons = []
        preview_url = safe_https_url(track.get("previewUrl"))
        track_url = safe_https_url(track.get("trackViewUrl"))
        if preview_url:
            buttons.append(InlineKeyboardButton("▶ Preview", url=preview_url))
        if track_url:
            buttons.append(InlineKeyboardButton("Open track", url=track_url))
        if buttons:
            keyboard.append(buttons)

    await message.reply_text(
        "\n\n".join(cards),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        disable_web_page_preview=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message:
        await message.reply_text(
            "Hi! I can find songs and preview links.\n\n"
            "Send /search to enter a song and singer step by step, or send both "
            "like this:\n"
            "Never Gonna Give You Up - Rick Astley"
        )


async def search_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if context.args:
        query = parse_search_query(" ".join(context.args))
        if query:
            await show_results(update, *query)
            return ConversationHandler.END
        message = update.effective_message
        if message:
            await message.reply_text(
                "Include both names, separated by a hyphen:\n"
                "/search Never Gonna Give You Up - Rick Astley"
            )
        return ConversationHandler.END

    message = update.effective_message
    if message:
        await message.reply_text("What song are you looking for?")
    return ASK_SONG


async def receive_song(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    message = update.effective_message
    if message is None or not message.text:
        return ASK_SONG
    context.user_data["song"] = message.text.strip()
    await message.reply_text("Who sings it?")
    return ASK_ARTIST


async def receive_artist(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    message = update.effective_message
    if message is None or not message.text:
        return ASK_ARTIST
    song = context.user_data.pop("song", "")
    artist = message.text.strip()
    if not song or not artist:
        await message.reply_text("Please provide both a song and an artist. Send /search to try again.")
        return ConversationHandler.END
    await show_results(update, song, artist)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("song", None)
    message = update.effective_message
    if message:
        await message.reply_text("Search cancelled.")
    return ConversationHandler.END


async def direct_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return
    query = parse_search_query(message.text)
    if query:
        await show_results(update, *query)
        return
    await message.reply_text(
        "Send both the song and singer, separated by a hyphen, "
        "or use /search for step-by-step prompts."
    )


async def log_unhandled_error(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    logger.error(
        "Unhandled Telegram update error",
        exc_info=context.error,
    )


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "Set the TELEGRAM_BOT_TOKEN environment variable with your BotFather token."
        )

    application = Application.builder().token(token).build()
    search_conversation = ConversationHandler(
        entry_points=[CommandHandler("search", search_command)],
        states={
            ASK_SONG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_song)],
            ASK_ARTIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_artist)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(search_conversation)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, direct_search))
    application.add_error_handler(log_unhandled_error)
    application.run_polling()


if __name__ == "__main__":
    main()
