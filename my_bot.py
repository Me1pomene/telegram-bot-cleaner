import os
import asyncio
import threading
import logging
import httpx
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

# === Настройки ===
load_dotenv()
TOKEN = os.getenv("TOKEN")
ALLOWED_CHAT_IDS = [int(x.strip()) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.strip()]
NOTIFY_CHAT_ID = int(os.getenv("NOTIFY_CHAT_ID", "0"))

BANNED_WORDS_FILE = "banned_words.txt"
JOIN_LOG = "join_log.txt"
DELETE_LOG = "deleted_messages.txt"
CHAT_LOG = "bot_chats.log"

banned_words = []

def is_allowed_chat(chat_id: int) -> bool:
    return not ALLOWED_CHAT_IDS or chat_id in ALLOWED_CHAT_IDS

def load_banned_words():
    global banned_words
    if not os.path.exists(BANNED_WORDS_FILE):
        banned_words = []
    else:
        with open(BANNED_WORDS_FILE, "r", encoding="utf-8") as f:
            banned_words = [w.strip().lower() for w in f if w.strip()]

def save_banned_words(words):
    with open(BANNED_WORDS_FILE, "w", encoding="utf-8") as f:
        for w in words:
            f.write(w + "\n")
    load_banned_words()

load_banned_words()

async def is_user_admin(update: Update, user_id: int) -> bool:
    member = await update.effective_chat.get_member(user_id)
    return member.status in ("administrator", "creator")

async def delayed_delete(bot, chat_id, message_id, delay=60):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

# === Команды ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type != "private" and not is_allowed_chat(chat.id):
        return
    await update.message.reply_text(
        "👋 Привет! Я бот, который помогает наводить порядок в чате.\n"
        "Удаляю системные сообщения, фильтрую запрещённые слова и логирую события.\n\n"
        "Для списка функций — напиши /help\n"
        "По доработкам обращайся к @v_golikov"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    await update.message.reply_text(f"✅ Бот работает. Время: {now}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 Функции бота:\n"
        "• Приветствие новых участников\n"
        "• Удаление системных сообщений (вступление, выход, темы, закрепы и т.п.)\n"
        "• Фильтрация сообщений по запрещённым словам\n"
        "• Логирование вступлений и удалений\n\n"
        "📌 Все команды работают только в группах, где бот является администратором:\n"
        "/addword <слово> — добавить запрещённое слово\n"
        "/delword <слово> — удалить запрещённое слово\n"
        "/listwords — показать список запрещённых слов"
    )

async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update.effective_chat.id):
        return
    if not await is_user_admin(update, update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("❗ Использование: /addword <слово>")
        return
    word = context.args[0].lower()
    if word in banned_words:
        await update.message.reply_text(f"⚠️ '{word}' уже есть.")
    else:
        banned_words.append(word)
        save_banned_words(banned_words)
        await update.message.reply_text(f"✅ Слово '{word}' добавлено.")

async def del_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update.effective_chat.id):
        return
    if not await is_user_admin(update, update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("❗ Использование: /delword <слово>")
        return
    word = context.args[0].lower()
    if word not in banned_words:
        await update.message.reply_text(f"⚠️ '{word}' нет в списке.")
    else:
        banned_words.remove(word)
        save_banned_words(banned_words)
        await update.message.reply_text(f"✅ Слово '{word}' удалено.")

async def list_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update.effective_chat.id):
        return
    if not banned_words:
        await update.message.reply_text("Список пуст.")
    else:
        await update.message.reply_text("🚫 Запрещённые слова:\n" + "\n".join(banned_words))

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not is_allowed_chat(chat.id):
        return
    for user in update.message.new_chat_members:
        try:
            await update.message.delete()
        except:
            pass
        msg = await context.bot.send_message(
            chat_id=chat.id,
            text=f"👋 Добро пожаловать, {user.mention_html()}!",
            parse_mode="HTML",
        )
        with open(JOIN_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} — {user.full_name} (@{user.username}) ID:{user.id} вступил(а) в {chat.title}\n")
        asyncio.create_task(delayed_delete(context.bot, chat.id, msg.message_id, delay=300))

async def delete_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not is_allowed_chat(update.effective_chat.id):
        return
    try:
        if (
            msg.new_chat_members
            or msg.left_chat_member
            or msg.new_chat_photo
            or msg.delete_chat_photo
            or msg.pinned_message
            or msg.group_chat_created
            or msg.supergroup_chat_created
            or msg.message_auto_delete_timer_changed
            or getattr(msg, "forum_topic_created", None)
            or getattr(msg, "forum_topic_closed", None)
            or getattr(msg, "forum_topic_reopened", None)
            or getattr(msg, "general_forum_topic_hidden", None)
            or getattr(msg, "general_forum_topic_unhidden", None)
        ):
            await msg.delete()
    except:
        pass

async def filter_bad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or not is_allowed_chat(update.effective_chat.id):
        return
    if any(word in msg.text.lower() for word in banned_words):
        try:
            await msg.delete()
        except:
            pass
        with open(DELETE_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"{datetime.now()} — Удалено сообщение от @{msg.from_user.username or 'без ника'}: {msg.text}\n"
            )

async def log_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return
    log_line = f"{datetime.now()} — {chat.type.upper()} — {chat.title or 'Личка'} (ID: {chat.id})\n"
    with open(CHAT_LOG, "a", encoding="utf-8") as f:
        f.write(log_line)

def run_healthcheck():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"I'm alive!")
    server = HTTPServer(("0.0.0.0", 10000), Handler)
    server.serve_forever()

threading.Thread(target=run_healthcheck, daemon=True).start()

# Настраиваем httpx с увеличенным таймаутом
request = HTTPXRequest(
    connect_timeout=10.0,
    read_timeout=30.0,
    write_timeout=30.0,
    pool_timeout=30.0,
)

app = ApplicationBuilder().token(TOKEN).request(request).build()

# Команды
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("status", status_command))
app.add_handler(CommandHandler("addword", add_word))
app.add_handler(CommandHandler("delword", del_word))
app.add_handler(CommandHandler("listwords", list_words))

# События
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
app.add_handler(MessageHandler(filters.StatusUpdate.ALL, delete_system))
app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, filter_bad))
app.add_handler(MessageHandler(filters.ALL, log_chat), group=-1)

print("🚀 Бот запущен!")
app.run_polling(ready=notify_on_startup)

