# Telegram YouTube Music Bot

Searches YouTube Music (via the unofficial `ytmusicapi`) and sends the audio
file directly to the user's Telegram chat using `yt-dlp` for downloading.

## Features

- Search by any text — song name, artist, or both (`Song - Artist`)
- `/search` command for step-by-step prompts
- Results shown as an inline keyboard — tap any result to download it
- Audio sent as a Telegram audio file (saved in the user's chat)
- Cleans up temp files after every send
- Works without FFmpeg (falls back to raw audio); with FFmpeg installed it
  remuxes to MP3 at 192 kbps for best Telegram player compatibility

## Requirements

- Python 3.10 or newer
- FFmpeg on PATH is **recommended** (for MP3 conversion) but optional

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Set the token and start:

   ```powershell
   $env:TELEGRAM_BOT_TOKEN = "paste-your-token-here"
   python music_bot.py
   ```

4. Open the bot in Telegram and send `/start`.

## Usage

| Action | How |
|---|---|
| Search | Type any song name or `Song - Artist` |
| Step-by-step | `/search` then type the name when prompted |
| Download | Tap a result button — the audio arrives as a file |
| Cancel | `/cancel` during a search conversation |

## Notes

- Telegram bots can upload files up to **50 MB**. Tracks longer than ~1 hour
  may be rejected; the bot will tell you if that happens.
- The bot uses long polling — no public URL or webhook is needed.
- Keep `TELEGRAM_BOT_TOKEN` out of source code and version control.

## Deploy

Run `python music_bot.py` on any machine with outbound internet access and set
`TELEGRAM_BOT_TOKEN` as an environment variable or secret in your host's config.
