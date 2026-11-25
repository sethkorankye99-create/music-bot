"""Localization management module providing Russian and English translations."""

from typing import Any

EMOJI_RU = "5449408995691341691"
EMOJI_US = "5202021044105257611"

DEFAULT_LANGUAGE = "ru"

STRINGS: dict[str, dict[str, str]] = {
    "ru": {
        "select_language_prompt": "<b>Пожалуйста, выберите язык / Please select your language:</b>",
        "language_saved": "Язык успешно изменён на Русский 🇷🇺",
        "start_text": (
            "Пришли ссылку - скачаю.\n"
            "YouTube / TikTok / Instagram / Pinterest / Rutube / VK / Spotify / Shazam / "
            "Yandex Music / SoundCloud / VK Music / Deezer / Apple Music / Tenor / JioSaavn / "
            "Twitch(Только клипы) / Snapchat / Facebook / X (Twitter) / Reddit / Kinopoisk"
        ),
        "settings_text": "<b>Настройки</b>\nВыберите язык:",
        "btn_help": "Помощь",
        "btn_settings": "Настройки",
        "btn_video": "Видео",
        "btn_audio": "Аудио",
        "btn_back": "Назад",
        "btn_cancel": "Отменить",
        "btn_lang_ru": "🇷🇺 Русский",
        "btn_lang_en": "🇺🇸 English",
        "help_text": (
            "<b>Справка по боту:</b>\n\n"
            "1. Отправь ссылку на поддерживаемый ресурс (YouTube, TikTok, VK, Spotify и др.) "
            "или просто название песни для поиска на YouTube.\n"
            "2. Выбери нужный формат (<b>Видео</b> или <b>Аудио</b>) и качество.\n"
            "3. Бот добавит задачу в очередь и пришлёт готовый файл!\n\n"
            "<b>Доступные команды:</b>\n"
            "• /start - Перезапуск бота\n"
            "• /settings - Настройки языка\n"
            "• /help - Инструкция и справка\n"
            "• /saves - Твои сохранённые медиафайлы\n"
            "• /queue - Список задач в очереди\n"
            "• /cancel - Отмена текущей загрузки"
        ),
        "queue_empty": "В очереди нет активных или ожидающих задач.",
        "queue_header": "Твоя очередь загрузок:",
        "status_queued": "в очереди",
        "status_processing": "скачивается",
        "status_completed": "завершено",
        "status_failed": "ошибка",
        "status_cancelled": "отменено",
        "cancel_requested": "Отмена запрошена. Останавливаю текущую загрузку...",
        "cancel_no_active": "Сейчас для тебя нет активной загрузки.",
        "cancel_downloading": "Скачивание отменяется...",
        "cancel_done": "Загрузка отменена.",
        "queue_position": "В очереди: место #{pos} (всего задач в очереди: {total})\nПожалуйста, подождите...",
        "task_processing_started": "Начинаю обработку...",
        "download_timeout": "Превышено время ожидания скачивания (тайм-аут). Сервер недоступен или файл слишком долго скачивался. Попробуйте еще раз.",
        "saves_empty": "Здесь появятся последние сохранённые файлы.",
        "saves_header": "Твои последние {limit} сохранений:",
        "search_usage": (
            "Использование:\n/search Название\nАвтор\n"
            "или /search Автор - Название"
        ),
        "select_audio_format": "Выбери формат аудио:",
        "select_format": "Выбери формат:",
        "unsupported_platform": "Платформа не поддерживается.",
        "pinterest_added": "Добавляю загрузку Pinterest в очередь...",
        "kinopoisk_fetching": "Получаю информацию с Кинопоиска...",
        "kinopoisk_error": "Ошибка получения данных с Кинопоиска.",
        "kp_serial_season": "<b>Сериал</b> | Сезон {season}\nВыбери серию:",
        "kp_serial_episode": "<b>Сериал</b> | S{season:02d}E{episode:02d}\nВыбери озвучку:",
        "kp_movie_tr": "<b>Фильм</b>\nВыбери озвучку:",
        "kp_season_select": "<b>{title}</b>{year}\nВыбери сезон:",
        "query_expired": "Запрос устарел, пришли ссылку заново.",
        "cannot_go_back": "Нельзя вернуться назад для этой платформы.",
        "file_unavailable": "Этот файл больше недоступен.",
        "sending_saved": "Отправляю сохранённый файл...",
        "file_too_large": "Ошибка: файл слишком большой (лимит {limit} МБ).",
        "download_error": "Произошла ошибка при загрузке. Попробуйте ещё раз позже.",
        "media_err_private": "🔒 Это приватный контент. Скачать можно только общедоступные публикации.",
        "media_err_login": (
            "🔑 Этот контент доступен только после входа в аккаунт, поэтому скачать его нельзя. "
            "Поддерживаются только общедоступные публикации."
        ),
        "media_err_removed": "❌ Контент удалён или больше недоступен.",
        "media_err_geo": "🌍 Этот контент недоступен в регионе сервера.",
        "media_err_no_media": "В этой публикации нет видео или аудио для скачивания (например, только фото).",
        "media_err_no_audio": "🔇 В этом видео нет звуковой дорожки. Выберите «Видео», чтобы скачать его.",
        "media_err_unsupported": (
            "Этот тип ссылки не поддерживается. Пришлите прямую ссылку на видео, reels или публикацию."
        ),
        "starting_download": "Начинаю загрузку файла...",
        "download_inline": "Загрузка",
        "download_inline_status": "Запрос: {query}\nФормат: {fmt}\nСтатус: начинаю работу",
        "download_as_fmt": "Скачать как {label}",
        "download_video_fmt": "Скачать видео {label}",
        "kp_season_btn": "Сезон {season}",
        "kp_episode_btn": "Серия {episode}",
        "untitled": "Без названия",
        "unknown_performer": "Неизвестно",
        "unknown_format": "неизвестный формат",
        "format_converted": "\nЗапрошенный формат недоступен - файл конвертирован из лучшего доступного.",
        "sending_file": "Отправляю...",
        "found_in_cache": "Нашёл в кэше, отправляю...",
        "getting_qualities": "Получаю доступные качества...",
        "select_quality": "Выбери качество видео:",
        "getting_formats": "Получаю доступные форматы...",
        "adding_video_queue": "Добавляю видео {quality} в очередь...",
        "adding_audio_queue": "Добавляю аудио ({label}) в очередь...",
        "media_audio": "Аудио",
        "media_video": "Видео",
        "media_photo": "Фото",
        "media_file": "Файл",
        "serial_label": "Сериал",
        "movie_label": "Фильм",
        "compression_starting": "Запуск сжатия видео ({bitrate} kbps)...",
        "compression_progress": "Сжатие видео: {pct:.1f}% ({size})",
        "compression_working": "Сжимаю видео... {out_time} ({size})",
        "file_exceeds_limit": "Файл ({size}) превышает лимит ({limit} МБ). Запускаю сжатие...",
        "will_be_compressed": " (будет сжато)",
        "dl_kinopoisk_links": "Получаю ссылки на поток Кинопоиск...",
        "dl_downloading_audio": "Скачиваю аудио...",
        "dl_downloading_video": "Скачиваю видео...",
        "dl_spotify_track_info": "Получаю информацию о треке Spotify...",
        "dl_spotify_search_ytm": "Ищу '{artist} - {title}' на YouTube Music...",
        "dl_spotify_track_list": "Получаю список треков Spotify...",
        "dl_deezer_search": "Ищу трек в Deezer...",
        "dl_apple_search": "Ищу трек в Apple Music...",
        "dl_format_converted": "Запрошенный формат недоступен, конвертирую из лучшего доступного...",
        "dl_yt_search_fallback": "Поиск на YouTube не дал результатов, пробую SoundCloud...",
        "text_searching": "🔎 Ищу: {query}...",
        "text_search_empty": "Ничего не найдено по запросу: {query}",
        "disclaimer_text": (
            "⚠️ <b>АВТОРСКИЕ ПРАВА И УВЕДОМЛЕНИЕ О КОНТЕНТЕ</b>\n\n"
            "Этот бот предназначен для скачивания медиа, которыми вы владеете, на скачивание которых "
            "у вас есть разрешение или к которым вы иным образом имеете законный доступ.\n\n"
            "Пожалуйста, не скачивайте, не распространяйте и не используйте защищённый авторским "
            "правом контент без необходимого разрешения.\n\n"
            "Продолжая, вы подтверждаете, что у вас есть права или разрешение, необходимые для "
            "скачивания выбранного контента.\n\n"
            "Разработчик бота не несёт ответственности за то, как используется скачанный контент."
        ),
        "btn_agree": "✅ Согласен, продолжить",
        "btn_flow_cancel": "❌ Отмена",
        "btn_dl_audio": "🎵 Скачать аудио (MP3)",
        "btn_dl_video": "🎬 Скачать видео (MP4)",
        "btn_link_audio": "🎵 Аудио (MP3)",
        "btn_link_video": "🎬 Видео (MP4)",
        "btn_back_results": "⬅️ К результатам",
        "flow_cancelled": "❌ Отменено. Ничего не скачано.",
        "request_expired_msg": "⌛ Запрос устарел. Отправь название песни или ссылку заново.",
        "not_your_request": "Эта кнопка относится к запросу другого пользователя.",
        "already_processing": "⏳ Уже обрабатываю, подожди...",
        "search_results_header": "🔎 Результаты по запросу <b>{query}</b>:",
        "search_results_footer": "Выбери нужный трек:",
        "search_choose_format": "Выбери формат для скачивания:",
        "daily_limit_reached": (
            "⛔ Ты достиг дневного лимита загрузок ({limit} файлов в сутки).\n"
            "Лимит сбросится через 24 часа. Возвращайся завтра! 🙂"
        ),
    },
    "en": {
        "select_language_prompt": "<b>Please select your language / Пожалуйста, выберите язык:</b>",
        "language_saved": "Language successfully set to English 🇺🇸",
        "start_text": (
            "Send a link - I will download it.\n"
            "YouTube / TikTok / Instagram / Pinterest / Rutube / VK / Spotify / Shazam / "
            "Yandex Music / SoundCloud / VK Music / Deezer / Apple Music / Tenor / JioSaavn / "
            "Twitch(Clips only) / Snapchat / Facebook / X (Twitter) / Reddit / Kinopoisk"
        ),
        "settings_text": "<b>Settings</b>\nSelect your language:",
        "btn_help": "Help",
        "btn_settings": "Settings",
        "btn_video": "Video",
        "btn_audio": "Audio",
        "btn_back": "Back",
        "btn_cancel": "Cancel",
        "btn_lang_ru": "🇷🇺 Russian",
        "btn_lang_en": "🇺🇸 English",
        "help_text": (
            "<b>Bot Help:</b>\n\n"
            "1. Send a link from a supported service (YouTube, TikTok, VK, Spotify, etc.) "
            "or just a song name to search YouTube.\n"
            "2. Choose your preferred format (<b>Video</b> or <b>Audio</b>) and quality.\n"
            "3. The bot will add the task to the queue and send the file!\n\n"
            "<b>Available commands:</b>\n"
            "• /start - Restart the bot\n"
            "• /settings - Language settings\n"
            "• /help - Instructions and help\n"
            "• /saves - Your saved media files\n"
            "• /queue - List queued tasks\n"
            "• /cancel - Cancel active download"
        ),
        "queue_empty": "There are no active or pending tasks in your queue.",
        "queue_header": "Your download queue:",
        "status_queued": "queued",
        "status_processing": "downloading",
        "status_completed": "completed",
        "status_failed": "failed",
        "status_cancelled": "cancelled",
        "cancel_requested": "Cancellation requested. Stopping active download...",
        "cancel_no_active": "No active download found for you right now.",
        "cancel_downloading": "Download is being cancelled...",
        "cancel_done": "Download cancelled.",
        "queue_position": "Queued: position #{pos} (total in queue: {total})\nPlease wait...",
        "task_processing_started": "Starting processing...",
        "download_timeout": "Download request timed out. The source server may be unavailable or file download took too long. Please try again.",
        "saves_empty": "Your recent saved files will appear here.",
        "saves_header": "Your last {limit} saves:",
        "search_usage": (
            "Usage:\n/search Title\nArtist\n"
            "or /search Artist - Title"
        ),
        "select_audio_format": "Select audio format:",
        "select_format": "Select format:",
        "unsupported_platform": "Platform is not supported.",
        "pinterest_added": "Adding Pinterest download to queue...",
        "kinopoisk_fetching": "Fetching Kinopoisk information...",
        "kinopoisk_error": "Error fetching data from Kinopoisk.",
        "kp_serial_season": "<b>Series</b> | Season {season}\nSelect episode:",
        "kp_serial_episode": "<b>Series</b> | S{season:02d}E{episode:02d}\nSelect voiceover:",
        "kp_movie_tr": "<b>Movie</b>\nSelect voiceover:",
        "kp_season_select": "<b>{title}</b>{year}\nSelect season:",
        "query_expired": "Request expired, please send link again.",
        "cannot_go_back": "Cannot go back for this platform.",
        "file_unavailable": "This file is no longer available.",
        "sending_saved": "Sending saved file...",
        "file_too_large": "Error: file is too large (limit {limit} MB).",
        "download_error": "An error occurred while downloading. Please try again later.",
        "media_err_private": "🔒 This content is private. Only public posts can be downloaded.",
        "media_err_login": (
            "🔑 This content is only available after signing in to the platform, so it can't be downloaded. "
            "Only public posts are supported."
        ),
        "media_err_removed": "❌ This content was deleted or is no longer available.",
        "media_err_geo": "🌍 This content isn't available in the server's region.",
        "media_err_no_media": "This post has no downloadable video or audio (for example, it only has photos).",
        "media_err_no_audio": "🔇 This video has no audio track. Choose Video to download it instead.",
        "media_err_unsupported": (
            "This kind of link isn't supported. Send a direct link to a video, reel or post."
        ),
        "starting_download": "Starting file download...",
        "download_inline": "Downloading",
        "download_inline_status": "Query: {query}\nFormat: {fmt}\nStatus: starting work",
        "download_as_fmt": "Download as {label}",
        "download_video_fmt": "Download video {label}",
        "kp_season_btn": "Season {season}",
        "kp_episode_btn": "Episode {episode}",
        "untitled": "Untitled",
        "unknown_performer": "Unknown",
        "unknown_format": "unknown format",
        "format_converted": "\nRequested format unavailable - converted from best available.",
        "sending_file": "Sending...",
        "found_in_cache": "Found in cache, sending...",
        "getting_qualities": "Fetching available qualities...",
        "select_quality": "Select video quality:",
        "getting_formats": "Fetching available formats...",
        "adding_video_queue": "Adding video {quality} to queue...",
        "adding_audio_queue": "Adding audio ({label}) to queue...",
        "media_audio": "Audio",
        "media_video": "Video",
        "media_photo": "Photo",
        "media_file": "File",
        "serial_label": "Series",
        "movie_label": "Movie",
        "compression_starting": "Starting video compression ({bitrate} kbps)...",
        "compression_progress": "Video compression: {pct:.1f}% ({size})",
        "compression_working": "Compressing video... {out_time} ({size})",
        "file_exceeds_limit": "File ({size}) exceeds limit ({limit} MB). Starting compression...",
        "will_be_compressed": " (will be compressed)",
        "dl_kinopoisk_links": "Getting Kinopoisk stream links...",
        "dl_downloading_audio": "Downloading audio...",
        "dl_downloading_video": "Downloading video...",
        "dl_spotify_track_info": "Getting Spotify track info...",
        "dl_spotify_search_ytm": "Searching '{artist} - {title}' on YouTube Music...",
        "dl_spotify_track_list": "Getting Spotify track list...",
        "dl_deezer_search": "Searching track in Deezer...",
        "dl_apple_search": "Searching track in Apple Music...",
        "dl_format_converted": "Required format not available, converting from best available...",
        "dl_yt_search_fallback": "YouTube search gave no results, searching on SoundCloud...",
        "text_searching": "🔎 Searching: {query}...",
        "text_search_empty": "Nothing found for: {query}",
        "disclaimer_text": (
            "⚠️ <b>COPYRIGHT &amp; CONTENT NOTICE</b>\n\n"
            "This bot is designed to help users download media they own, have permission to "
            "download, or are otherwise legally entitled to access.\n\n"
            "Please do not download, distribute, or use copyrighted content without the "
            "necessary authorization.\n\n"
            "By continuing, you confirm that you have the rights or permission required to "
            "download the selected content.\n\n"
            "The bot developer is not responsible for how downloaded content is used."
        ),
        "btn_agree": "✅ I Agree & Continue",
        "btn_flow_cancel": "❌ Cancel",
        "btn_dl_audio": "🎵 Download Audio (MP3)",
        "btn_dl_video": "🎬 Download Video (MP4)",
        "btn_link_audio": "🎵 Audio (MP3)",
        "btn_link_video": "🎬 Video (MP4)",
        "btn_back_results": "⬅️ Back to results",
        "flow_cancelled": "❌ Cancelled. Nothing was downloaded.",
        "request_expired_msg": "⌛ This request has expired. Please send the song name or link again.",
        "not_your_request": "This button belongs to another user's request.",
        "already_processing": "⏳ Already processing, please wait...",
        "search_results_header": "🔎 Results for <b>{query}</b>:",
        "search_results_footer": "Select the song you want:",
        "search_choose_format": "Choose the download format:",
        "daily_limit_reached": (
            "⛔ You have reached the daily download limit ({limit} files per day).\n"
            "The limit resets after 24 hours. Come back tomorrow! 🙂"
        ),
    },
}


def get_text(lang: str | None, key: str, **kwargs: Any) -> str:
    """Retrieve translated string for a given language code and key.

    Fallback to Russian if language is not supported or key is missing.
    """
    lang_code = lang if lang in STRINGS else DEFAULT_LANGUAGE
    tmpl = STRINGS[lang_code].get(key) or STRINGS[DEFAULT_LANGUAGE].get(key, key)
    if kwargs:
        return tmpl.format(**kwargs)
    return tmpl
