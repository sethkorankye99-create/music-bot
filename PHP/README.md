# Telegram Music Search Bot

The bot searches the iTunes catalog by song title and singer/artist, then replies
with matching tracks and buttons for available previews and track pages. It uses
Telegram long polling, so it does not need a public web server and Telegram users
can use it from any device.

## Run locally

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and copy its
   token. Keep the token private.
2. Install Python 3.9 or newer and install the dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Set the token and start the bot:

   ```powershell
   $env:TELEGRAM_BOT_TOKEN = "paste-your-token-here"
   python music_bot.py
   ```

4. Open your bot in Telegram and send `/start`.

Users can send `/search` to be prompted for the song and singer, or send both in
one message, for example `Never Gonna Give You Up - Rick Astley`. `/cancel`
stops an interactive search.

## Deploy

Run `python music_bot.py` on a machine or hosting service that stays online and
has outbound internet access. Set `TELEGRAM_BOT_TOKEN` as a secret environment
variable in that host's settings; do not put the token in source code or commit
it to version control. Long polling means no Telegram webhook URL or public
inbound port is required.

The bot links to catalog entries and available short previews; it does not
download or provide full copyrighted tracks.
