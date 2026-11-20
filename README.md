# Telegram Music Bot — Multi-Platform Search

Searches **SoundCloud**, **Audiomack**, **YouTube Music**, and **Boomplay** in
parallel, ranks results by relevance, and sends the audio file directly to
the user's Telegram chat. Deployed on Railway with long polling — no web server
needed.

## Features

- Multi-platform search (all four sources in parallel)
- Smart ranking — exact matches, word-level matching, recency, remix penalty
- Source-aware results — every track shows which platform it came from
- Download — audio sent as a Telegram file (MP3 when FFmpeg is available)
- Listen — URL button opens the track on its source platform
- More Results — pagination through combined results
- Another Source — filter results to a specific platform
- Graceful degradation — one unavailable platform never crashes the bot
- Search cache — 5-minute cache avoids duplicate searches
- Cookie support — `YOUTUBE_COOKIES` env var for YouTube Music downloads

## Requirements

- Python 3.10+
- FFmpeg (recommended for MP3 conversion; bot works without it)

## Setup

```powershell
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN = "your-token-here"
python music_bot.py
```

## Deploy on Railway

1. Push this repo to GitHub
2. Connect it to Railway
3. Set environment variables:
   - `TELEGRAM_BOT_TOKEN` (or `BOT_TOKEN`) — your BotFather token
   - `YOUTUBE_COOKIES` (optional) — Netscape cookies for YouTube Music downloads
4. Start command: `python music_bot.py` (already in `railway.json`)
