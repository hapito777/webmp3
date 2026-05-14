"""Telegram bot: send a YouTube URL, get an mp3 back."""
import asyncio
import os
import re

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from downloader import DownloadError, download_mp3, logger

TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # default Bot API audio upload cap
URL_RE = re.compile(r"https?://\S+")


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send me a YouTube link and I'll reply with the audio as mp3.\n\n"
        "Files larger than 50 MB cannot be delivered via Telegram."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg is None or not msg.text:
        return

    match = URL_RE.search(msg.text)
    if not match:
        await msg.reply_text("Please send a URL (http/https).")
        return
    url = match.group(0)

    user = msg.from_user
    who = f"{user.id}:{user.username or user.first_name or '?'}" if user else "?"

    status = await msg.reply_text("Downloading…")
    await context.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.TYPING)

    try:
        mp3_path, info = await asyncio.to_thread(
            download_mp3, url, source="telegram", who=who
        )
    except DownloadError as e:
        await status.edit_text(f"Failed: {e}")
        return
    except Exception as e:
        logger.exception("bot unexpected error url=%r who=%s", url, who)
        await status.edit_text(f"Unexpected error: {e}")
        return

    title = info["title"]
    size = info["size"]
    duration = info.get("duration") or 0

    if size > TELEGRAM_FILE_LIMIT:
        logger.warning(
            "oversized job=%s title=%r size=%d limit=%d source=telegram who=%s",
            info["job_id"], title, size, TELEGRAM_FILE_LIMIT, who,
        )
        await status.edit_text(
            f"Downloaded ‘{title}’ but the file is {size / 1024 / 1024:.1f} MB — "
            f"larger than Telegram's 50 MB bot upload limit."
        )
        mp3_path.unlink(missing_ok=True)
        return

    await status.edit_text(f"Uploading ‘{title}’…")
    await context.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.UPLOAD_VOICE)

    try:
        with mp3_path.open("rb") as f:
            await context.bot.send_audio(
                chat_id=msg.chat_id,
                audio=f,
                title=title[:64],
                duration=int(duration) if duration else 0,
                filename=(re.sub(r"[^\w\s\-.()]", "", title)[:120] or "audio") + ".mp3",
            )
        logger.info("delivered job=%s filename=%r bytes=%d source=telegram", info["job_id"], title, size)
        await status.delete()
    finally:
        mp3_path.unlink(missing_ok=True)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN env var is required")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("telegram bot starting")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
