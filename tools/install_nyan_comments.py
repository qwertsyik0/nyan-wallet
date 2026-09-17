from __future__ import annotations

import py_compile
import shutil
from datetime import datetime
from pathlib import Path


COMMENTS_CODE = r'''import asyncio
import logging
import os
import random
from pathlib import Path

from dotenv import load_dotenv, set_key
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


logger = logging.getLogger(__name__)
ENV_PATH = Path(__file__).with_name(".env")
load_dotenv(ENV_PATH)

try:
    OWNER_ID = int(os.getenv("OWNER_TELEGRAM_ID") or "6289461565")
except ValueError:
    OWNER_ID = 6289461565


def read_chat_id():
    value = os.getenv("DISCUSSION_CHAT_ID", "").strip()
    try:
        return int(value) if value else None
    except ValueError:
        logger.error("DISCUSSION_CHAT_ID должен быть целым числом")
        return None


discussion_chat_id = read_chat_id()
last_phrase = {"post": None, "reply": None}

POST_COMMENTS = (
    "Нян Кэш уже тут и ставит лапку одобрения 🐾",
    "официально одобрено Нян Кэшем 🐾",
    "если бы за красивые посты давали лапкоины этот уже был бы богат",
    "кажется этот пост заслужил отдельную награду 🐾",
    "Нян Шоп снова радует а я всё вижу",
    "я пришёл первым и уже всё одобрил 🐾",
    "хороший пост. Нян Кэш плохого не посоветует",
    "за такое хочется сразу начислить лапкоинов",
    "лапка поставлена, пост принят 🐾",
    "Нян Кэш сообщает: получилось очень хорошо",
    "мимо такого поста даже я пройти не смог",
    "в кошельке стало уютнее от одного этого поста 🐾",
)

REPLIES = (
    "Нян Кэш такое одобряет 🐾",
    "хорошо сказано",
    "согласен с тобой 🐾",
    "у тебя явно хороший вкус",
    "за такой комментарий хочется начислить лапкоин",
    "вот это правильный настрой",
    "записал в свою лапкоиновую книжку",
    "кажется мы с тобой сработаемся 🐾",
    "звучит справедливо, беру на заметку",
    "в комментариях сегодня особенно уютно",
    "вот тут действительно не поспоришь",
    "одобрено главным по лапкоинам 🐾",
    "приятно видеть такое мнение",
    "ты сейчас буквально озвучил мои мысли",
    "Нян Кэш внимательно прочитал и согласился",
    "хороший комментарий, оставляем 🐾",
)


def choose_phrase(kind, phrases):
    choices = [text for text in phrases if text != last_phrase[kind]] or list(phrases)
    selected = random.choice(choices)
    last_phrase[kind] = selected
    return selected


async def bind_comments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global discussion_chat_id

    if update.effective_user is None or update.effective_user.id != OWNER_ID:
        return

    chat = update.effective_chat
    message = update.effective_message

    if chat is None or message is None or chat.type not in {"group", "supergroup"}:
        if message:
            await message.reply_text(
                "Эту команду нужно отправить в группе комментариев Нян Шопа."
            )
        return

    discussion_chat_id = chat.id
    set_key(str(ENV_PATH), "DISCUSSION_CHAT_ID", str(chat.id))

    await message.reply_text(
        "✅ Комментарии Нян Кэша подключены к этой группе.\n"
        "Теперь я буду встречать новые посты и иногда отвечать людям."
    )
    logger.info("Discussion group bound: %s (%s)", chat.title, chat.id)


async def handle_discussion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if message is None or chat is None or discussion_chat_id is None:
        return
    if chat.id != discussion_chat_id:
        return

    if message.is_automatic_forward:
        await asyncio.sleep(random.uniform(1.5, 3.5))
        try:
            await message.reply_text(
                choose_phrase("post", POST_COMMENTS) + "\n\n@nyancash_bot"
            )
        except Exception:
            logger.exception("Не удалось оставить первый комментарий")
        return

    user = update.effective_user

    if user is None or user.is_bot:
        return
    if message.text and message.text.startswith("/"):
        return
    if message.text is None and message.caption is None and message.effective_attachment is None:
        return

    try:
        await message.reply_text(
            choose_phrase("reply", REPLIES) + "\n\n@nyancash_bot"
        )
    except Exception:
        logger.exception("Не удалось ответить в комментариях")
        return

def register_comments_handlers(app: Application):
    app.add_handler(CommandHandler("bindcomments", bind_comments), group=0)
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND,
            handle_discussion,
        ),
        group=1,
    )
'''


def main() -> None:
    root = Path.cwd()
    bot_path = root / "bot.py"
    comments_path = root / "comments.py"

    if not bot_path.is_file():
        raise SystemExit("Ошибка: bot.py не найден. Запусти установщик из ~/new_bot")

    bot_code = bot_path.read_text(encoding="utf-8")
    import_line = "from telegram.ext import Application, CommandHandler, ContextTypes"
    handler_line = '    app.add_handler(CommandHandler("start", start))'

    if import_line not in bot_code:
        raise SystemExit("Ошибка: не найдена строка импорта в bot.py")
    if handler_line not in bot_code:
        raise SystemExit("Ошибка: не найден обработчик /start в bot.py")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = root / f"bot.py.before_comments_{timestamp}"
    shutil.copy2(bot_path, backup_path)

    if "from comments import register_comments_handlers" not in bot_code:
        bot_code = bot_code.replace(
            import_line,
            import_line + "\nfrom comments import register_comments_handlers",
            1,
        )

    if "    register_comments_handlers(app)" not in bot_code:
        bot_code = bot_code.replace(
            handler_line,
            handler_line + "\n    register_comments_handlers(app)",
            1,
        )

    comments_path.write_text(COMMENTS_CODE, encoding="utf-8")
    bot_path.write_text(bot_code, encoding="utf-8")

    try:
        py_compile.compile(str(bot_path), doraise=True)
        py_compile.compile(str(comments_path), doraise=True)
    except Exception:
        shutil.copy2(backup_path, bot_path)
        raise

    print("✅ Комментарии установлены")
    print(f"✅ Резервная копия: {backup_path.name}")
    print("Теперь перезапусти бота и отправь /bindcomments в группе комментариев")


if __name__ == "__main__":
    main()
