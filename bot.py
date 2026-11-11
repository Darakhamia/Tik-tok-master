import http.server
import logging
import os
import re
import sys
import threading
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from downloader import download_video
from storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines contain the bot token
logger = logging.getLogger(__name__)

PLATFORMS = [
    ("🎵", re.compile(r"https?://(?:[\w-]+\.)?tiktok\.com/\S+", re.IGNORECASE)),
    ("📸", re.compile(r"https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|tv)/[\w-]+\S*", re.IGNORECASE)),
    ("▶️", re.compile(r"https?://(?:www\.|m\.)?youtube\.com/shorts/[\w-]+\S*", re.IGNORECASE)),
]

storage = Storage(os.path.join(config.DATA_DIR, "bot.db"))


def find_link(text: str) -> tuple[str, str] | None:
    """First supported link in the text as (emoji, url)."""
    matches = [(m.start(), emoji, m.group()) for emoji, regex in PLATFORMS for m in regex.finditer(text)]
    if not matches:
        return None
    _, emoji, url = min(matches)
    return emoji, url


def strip_links(text: str) -> str:
    for _, regex in PLATFORMS:
        text = regex.sub("", text)
    return text.strip()


def reaction_keyboard(views: int = 0, likes: int = 0) -> InlineKeyboardMarkup:
    def label(emoji: str, count: int) -> str:
        return f"{emoji} {count}" if count else emoji

    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label("👀", views), callback_data="react:view"),
        InlineKeyboardButton(label("👍", likes), callback_data="react:like"),
    ]])


def posted_thread_id(message: Message) -> int | None:
    """Topic the message was posted in; None means General or a chat without topics."""
    return message.message_thread_id if message.is_topic_message else None


def target_thread_id(message: Message) -> int | None:
    """Topic for the video: the TikTok topic in groups with topics, otherwise where the link was."""
    if message.chat.is_forum:
        topic = config.TIKTOK_TOPIC_ID or storage.get_topic(message.chat_id)
        if topic:
            return topic
    return posted_thread_id(message)


def is_tiktok_topic_name(name: str) -> bool:
    normalized = re.sub(r"[\W_]", "", name.lower())
    return "tiktok" in normalized or "тикток" in normalized


def topic_name(message: Message) -> str | None:
    """Name of the topic a message belongs to, when the update carries it."""
    if message.forum_topic_created:
        return message.forum_topic_created.name
    if message.forum_topic_edited and message.forum_topic_edited.name:
        return message.forum_topic_edited.name
    # A message in a topic that isn't an explicit reply points at the topic's creation message.
    reply = message.reply_to_message
    if reply and reply.forum_topic_created:
        return reply.forum_topic_created.name
    return None


async def learn_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.chat.is_forum or not message.is_topic_message:
        return
    name = topic_name(message)
    if name is None or not is_tiktok_topic_name(name):
        return
    if storage.get_topic(message.chat_id) != message.message_thread_id:
        storage.set_topic(message.chat_id, message.message_thread_id)
        logger.info("Found TikTok topic '%s' (%s) in chat %s", name, message.message_thread_id, message.chat_id)


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
    user = update.effective_user
    if message is None or user is None:
        return

    thread_id = posted_thread_id(message)
    if thread_id is None:
        await message.reply_text("Это не тема. Отправь /topic_id внутри темы, куда кидать видео.")
        return

    member = await context.bot.get_chat_member(message.chat_id, user.id)
    if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        await message.reply_text("Менять тему для видео могут только админы.")
        return

    storage.set_topic(message.chat_id, thread_id)
    await message.reply_text(f"Готово, теперь все видео будут приходить в эту тему (ID {thread_id}).")


async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    kind = query.data.removeprefix("react:")
    chat_id = query.message.chat.id
    message_id = query.message.message_id
    user_id = query.from_user.id

    if kind == "view":
        if storage.has_reaction(chat_id, message_id, user_id, "view"):
            await query.answer("Ты уже отметил, что посмотрел 👀")
            return
        storage.add_reaction(chat_id, message_id, user_id, "view")
        await query.answer("Посмотрел 👀")
    else:
        if storage.has_reaction(chat_id, message_id, user_id, "like"):
            storage.remove_reaction(chat_id, message_id, user_id, "like")
            await query.answer("Лайк убран")
        else:
            storage.add_reaction(chat_id, message_id, user_id, "like")
            storage.add_reaction(chat_id, message_id, user_id, "view")
            await query.answer("Лайк 👍")

    counts = storage.counts(chat_id, message_id)
    try:
        await query.edit_message_reply_markup(
            reaction_keyboard(counts.get("view", 0), counts.get("like", 0))
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            logger.warning("Could not update reaction buttons: %s", exc)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user

    if message is None or user is None:
        return
    if user.is_bot:
        return

    text = message.text or message.caption or ""
    found = find_link(text)
    if found is None:
        return

    emoji, url = found
    username = user.username and f"@{user.username}" or user.full_name
    clean_text = strip_links(text)
    caption = f"{emoji} {username}: {clean_text}" if clean_text else f"{emoji} {username}"
    fallback_text = f"{caption}\n{url}"

    try:
        await message.delete()
    except Exception as exc:
        logger.warning("Could not delete original message: %s", exc)

    video_path: str | None = None
    try:
        video_path = await download_video(
            url, config.TEMP_DIR, config.MAX_FILE_SIZE_MB, config.COOKIES_FILE
        )
    except Exception as exc:
        logger.error("Unexpected error during download: %s", exc)

    if video_path is None:
        try:
            await send_to_topic(
                context.bot.send_message, message, text=fallback_text, reply_markup=reaction_keyboard()
            )
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
            reply_markup=reaction_keyboard(),
        )
    except Exception as exc:
        logger.error("Failed to send video: %s", exc)
        try:
            await send_to_topic(
                context.bot.send_message, message, text=fallback_text, reply_markup=reaction_keyboard()
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

    # Group -1 runs on every message before the handlers below, so topics are learned from any chatter.
    application.add_handler(MessageHandler(filters.ALL, learn_topic), group=-1)
    application.add_handler(CommandHandler("topic_id", handle_topic_id))
    application.add_handler(CallbackQueryHandler(handle_reaction, pattern=r"^react:(view|like)$"))
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            handle_message,
        )
    )

    _start_health_server()
    if os.path.isfile(config.COOKIES_FILE):
        logger.info("Using cookies from %s", config.COOKIES_FILE)
    else:
        logger.info("No cookies file at %s, downloading anonymously", config.COOKIES_FILE)
    logger.info("Bot starting (polling)…")
    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
