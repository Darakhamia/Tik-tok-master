import asyncio
import http.server
import logging
import os
import re
import sys
import threading
from pathlib import Path

from telegram import Message, Update
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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


def posted_thread_id(message: Message) -> int | None:
    """Topic the message was posted in; None means General or a chat without topics."""
    return message.message_thread_id if message.is_topic_message else None


def target_thread_id(message: Message) -> int | None:
    """Topic for the video: the TikTok topic in groups with topics, otherwise where the link was."""
    if config.TIKTOK_TOPIC_ID and message.chat.is_forum:
        return config.TIKTOK_TOPIC_ID
    return posted_thread_id(message)


async def send_to_topic(send, message: Message, **kwargs):
    """Post into the target topic; if Telegram rejects that topic, post where the link was sent."""
    target = target_thread_id(message)
    try:
        return await send(chat_id=message.chat_id, message_thread_id=target, **kwargs)
    except BadRequest as exc:
        fallback = posted_thread_id(message)
        error = str(exc).lower()
        if target == fallback or ("thread" not in error and "topic" not in error):
            raise
        logger.warning("Could not post to topic %s (%s), posting where the link was sent", target, exc)
        return await send(chat_id=message.chat_id, message_thread_id=fallback, **kwargs)


async def handle_topic_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    thread_id = posted_thread_id(message)
    if thread_id is None:
        text = "This is not a topic. Send /topic_id inside the TikTok topic."
    else:
        text = f"Topic ID: {thread_id}\nSet TIKTOK_TOPIC_ID={thread_id} to post all TikTok videos here."
    await message.reply_text(text)


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
            await send_to_topic(context.bot.send_message, message, text=fallback)
        except Exception as exc:
            logger.error("Failed to send fallback message: %s", exc)
        return

    try:
        # A Path, not an open file: a retry in another topic has to read the file again.
        await send_to_topic(
            context.bot.send_video,
            message,
            video=Path(video_path),
            caption=caption,
            supports_streaming=True,
        )
    except Exception as exc:
        logger.error("Failed to send video: %s", exc)
        try:
            await send_to_topic(
                context.bot.send_message,
                message,
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

    application.add_handler(CommandHandler("topic_id", handle_topic_id))
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
