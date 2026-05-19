import asyncio
import http.server
import logging
import os
import re
import sys
import threading

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import config
from downloader import download_tiktok

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

TIKTOK_RE = re.compile(
    r"https?://(?:www\.|vm\.|vt\.)?tiktok\.com/\S+", re.IGNORECASE
)


def extract_links(text: str) -> list[str]:
    return TIKTOK_RE.findall(text)


def strip_links(text: str) -> str:
    return TIKTOK_RE.sub("", text).strip()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return
    if user.is_bot:
        return

    text = message.text or message.caption or ""
    links = extract_links(text)
    if not links:
        return

    url = links[0]
    username = user.username and f"@{user.username}" or user.full_name
    clean_text = strip_links(text)
    caption = f"🎵 {username}: {clean_text}" if clean_text else f"🎵 {username}"

    try:
        await message.delete()
    except Exception as exc:
        logger.warning("Could not delete original message: %s", exc)

    video_path: str | None = None
    try:
        video_path = await download_tiktok(url, config.TEMP_DIR, config.MAX_FILE_SIZE_MB)
    except Exception as exc:
        logger.error("Unexpected error during download: %s", exc)

    if video_path is None:
        fallback = f"{username} shared a TikTok: {url}"
        if clean_text:
            fallback = f"{username}: {clean_text}\n{url}"
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=fallback,
            )
        except Exception as exc:
            logger.error("Failed to send fallback message: %s", exc)
        return

    try:
        with open(video_path, "rb") as video_file:
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_file,
                caption=caption,
                supports_streaming=True,
            )
    except Exception as exc:
        logger.error("Failed to send video: %s", exc)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{username} shared a TikTok: {url}",
            )
        except Exception as inner_exc:
            logger.error("Failed to send fallback after video error: %s", inner_exc)
    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception as exc:
                logger.warning("Could not remove temp file %s: %s", video_path, exc)


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args) -> None:
        pass  # silence access logs


def _start_health_server(port: int = 3000) -> None:
    server = http.server.HTTPServer(("", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Health server listening on port %d", port)


def main() -> None:
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .build()
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT | filters.CAPTION,
            handle_message,
        )
    )

    _start_health_server()
    logger.info("Bot starting (polling)…")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
