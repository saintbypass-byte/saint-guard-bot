import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

from .db import Database

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
STARTUP_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "startup.png"
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID", "").strip()
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0") or 0)
DB_PATH = os.getenv("DATABASE_PATH", "saint_guard.sqlite3")
SPAM_WINDOW = int(os.getenv("SPAM_WINDOW_SECONDS", "8"))
SPAM_LIMIT = int(os.getenv("SPAM_MESSAGE_LIMIT", "6"))
MUTE_MINUTES = int(os.getenv("SPAM_MUTE_MINUTES", "5"))

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("saint_guard")
db = Database(DB_PATH)
recent_messages = defaultdict(deque)


def is_group(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type in ("group", "supergroup"))


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    if BOT_OWNER_ID and update.effective_user.id == BOT_OWNER_ID:
        return True
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False


async def reply(update: Update, text: str, **kwargs):
    if update.effective_message:
        return await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kwargs
        )


async def log_action(context, chat_id: int, text: str):
    db.add_log(chat_id, text)
    if LOG_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=int(LOG_CHAT_ID),
                text=f"🛡️ <b>SAINT GUARD LOG</b>\n{text}",
                parse_mode=ParseMode.HTML,
            )
        except (ValueError, TelegramError) as exc:
            log.warning("Could not send log message: %s", exc)


async def require_admin(update, context):
    if not is_group(update):
        await reply(update, "⚠️ This command only works inside a group.")
        return False
    if not await is_admin(update, context):
        await reply(update, "⛔ <b>Access denied.</b>\nOnly group administrators can use this command.")
        return False
    return True


def target_from_update(update: Update):
    msg = update.effective_message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user
    return None


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡️ Admin commands", callback_data="menu_admin"),
         InlineKeyboardButton("📚 Help", callback_data="menu_help")],
        [InlineKeyboardButton("📊 Statistics", callback_data="menu_stats"),
         InlineKeyboardButton("📜 Group rules", callback_data="menu_rules")],
        [InlineKeyboardButton("ℹ️ About", callback_data="menu_about")],
    ])


START_TEXT = (
    "🌑 <b>ＳＡＩＮＴ  ＧＵＡＲＤ</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "🛡️ <b>GROUP PROTECTION SYSTEM</b>\n"
    "<i>Protect • Manage • Grow</i>\n\n"
    "Welcome, {name}!\n"
    "Your group's security assistant is ready.\n\n"
    "✦ Smart moderation\n✦ Anti-spam protection\n✦ Welcome & goodbye messages\n"
    "✦ Custom keyword filters\n✦ Group statistics\n✦ Admin activity logs\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "⚡ <b>Status:</b> ONLINE\n"
    "⚙️ <b>Version:</b> 2.1.0\n"
    "Choose a panel below."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = escape(user.first_name if user else "there")
    text = START_TEXT.format(name=name)
    message = update.effective_message
    if message and STARTUP_IMAGE.is_file():
        with STARTUP_IMAGE.open("rb") as image:
            await message.reply_photo(
                photo=image,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )
    else:
        await reply(update, text, reply_markup=main_menu())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🛡️ <b>SAINT GUARD • COMMAND CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>Moderation</b> (reply to a member's message)\n"
        " /ban • /unban • /kick • /mute [minutes] • /unmute\n"
        " /warn • /warnings • /purge [count]\n\n"
        "<b>Group tools</b>\n"
        " /lock • /unlock • /rules • /setrules text\n"
        " /welcome on|off • /goodbye on|off\n"
        " /filter add keyword | response\n"
        " /filter remove keyword • /filters\n\n"
        "<b>Information</b>\n"
        " /start • /help • /stats • /id • /ping\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔐 Moderation commands are admin-only.\n"
        "Most moderation commands require replying to the target member's message."
    )
    await reply(update, text)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat = q.message.chat if q.message else None
    data = q.data
    if data == "menu_admin":
        text = ("🛡️ <b>ADMIN PANEL</b>\n"
                "Reply to a member's message with /ban, /kick, /mute, /unmute or /warn.\n"
                "Use /lock and /unlock to control group messaging.\n"
                "Use /filter add keyword | response to create an automatic reply.")
    elif data == "menu_help":
        text = ("📚 <b>COMMAND GUIDE</b>\n"
                "/ban /unban /kick /mute /unmute /warn /warnings /purge\n"
                "/lock /unlock /welcome /goodbye /setrules /rules\n"
                "/filter /filters /stats /id /ping")
    elif data == "menu_stats":
        if chat and chat.type in ("group", "supergroup"):
            s = db.stats(chat.id)
            text = (f"📊 <b>GROUP STATISTICS</b>\n"
                    f"👥 Members: {s['members']}\n"
                    f"⚠️ Warnings recorded: {s['warnings']}\n"
                    f"🧾 Admin actions logged: {s['logs']}")
        else:
            text = "📊 Add me to a group to view its statistics."
    elif data == "menu_rules":
        if chat and chat.type in ("group", "supergroup"):
            text = "📜 <b>GROUP RULES</b>\n" + escape(db.get_setting(chat.id, "rules", "No rules have been configured yet."))
        else:
            text = "📜 Group rules are available inside a group."
    else:
        text = "🌑 <b>SAINT GUARD v2.1</b>\nA dark-themed Telegram group management assistant."
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu())
    except TelegramError:
        pass


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    target = target_from_update(update) or user
    await reply(update, f"🪪 <b>ID CARD</b>\nUser: <code>{target.id}</code>\nChat: <code>{chat.id}</code>")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.monotonic()
    msg = await reply(update, "🏓 <b>Checking system...</b>")
    elapsed = round((time.monotonic() - start_time) * 1000)
    if msg:
        await msg.edit_text(f"🏓 <b>PONG!</b>\n⚡ Response: <code>{elapsed} ms</code>", parse_mode=ParseMode.HTML)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        await reply(update, "📊 Use /stats inside a group.")
        return
    s = db.stats(update.effective_chat.id)
    try:
        count = await context.bot.get_chat_member_count(update.effective_chat.id)
        db.set_setting(update.effective_chat.id, "member_count", str(count))
    except TelegramError:
        count = s["members"]
    await reply(update, (
        "📊 <b>GROUP INTELLIGENCE</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"👥 Members: <b>{count}</b>\n"
        f"⚠️ Warnings: <b>{s['warnings']}</b>\n"
        f"🧾 Logged actions: <b>{s['logs']}</b>\n"
        "━━━━━━━━━━━━━━━━━━"
    ))


async def moderate(update, context, action):
    if not await require_admin(update, context):
        return
    target = target_from_update(update)
    if not target:
        await reply(update, "↪️ Reply to the member's message to select a target.")
        return
    if target.id == update.effective_user.id or target.is_bot:
        await reply(update, "⚠️ That target cannot be moderated with this command.")
        return
    chat_id = update.effective_chat.id
    try:
        if action == "ban":
            await context.bot.ban_chat_member(chat_id, target.id)
            result = "🔨 BANNED"
        elif action == "kick":
            await context.bot.ban_chat_member(chat_id, target.id)
            await context.bot.unban_chat_member(chat_id, target.id)
            result = "👢 REMOVED"
        elif action == "unban":
            await context.bot.unban_chat_member(chat_id, target.id)
            result = "♻️ UNBANNED"
        elif action == "mute":
            minutes = 10
            if context.args:
                try:
                    minutes = max(1, min(int(context.args[0]), 10080))
                except ValueError:
                    pass
            until = int(time.time()) + minutes * 60
            await context.bot.restrict_chat_member(
                chat_id, target.id, ChatPermissions(can_send_messages=False), until_date=until
            )
            result = f"🔇 MUTED for {minutes} minute(s)"
        elif action == "unmute":
            await context.bot.restrict_chat_member(
                chat_id, target.id,
                ChatPermissions(can_send_messages=True, can_send_audios=True,
                                can_send_documents=True, can_send_photos=True,
                                can_send_videos=True, can_send_video_notes=True,
                                can_send_voice_notes=True, can_send_polls=True,
                                can_send_other_messages=True, can_add_web_page_previews=True)
            )
            result = "🔊 UNMUTED"
        else:
            return
        await reply(update, f"🛡️ <b>{result}</b>\nMember: {escape(target.full_name)}")
        await log_action(context, chat_id, f"{result}: {escape(target.full_name)} (<code>{target.id}</code>)")
    except TelegramError as exc:
        await reply(update, f"⚠️ Telegram could not complete that action: <code>{escape(str(exc)[:250])}</code>")


async def ban(update, context): await moderate(update, context, "ban")
async def kick(update, context): await moderate(update, context, "kick")
async def unban(update, context): await moderate(update, context, "unban")
async def mute(update, context): await moderate(update, context, "mute")
async def unmute(update, context): await moderate(update, context, "unmute")


async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return
    target = target_from_update(update)
    if not target:
        await reply(update, "↪️ Reply to a member's message to warn them.")
        return
    if target.is_bot:
        return
    count = db.add_warning(update.effective_chat.id, target.id, update.effective_user.id)
    await reply(update, f"⚠️ <b>WARNING ISSUED</b>\nMember: {escape(target.full_name)}\nWarnings: <b>{count}/3</b>")
    await log_action(context, update.effective_chat.id, f"Warning {count}/3 issued to {escape(target.full_name)} (<code>{target.id}</code>)")
    if count >= 3:
        try:
            await context.bot.restrict_chat_member(
                update.effective_chat.id, target.id, ChatPermissions(can_send_messages=False),
                until_date=int(time.time()) + 3600
            )
            await reply(update, "🔇 Three warnings reached. Member muted for 1 hour.")
            await log_action(context, update.effective_chat.id, f"Auto-muted {escape(target.full_name)} after 3 warnings.")
        except TelegramError:
            pass


async def warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = target_from_update(update) or update.effective_user
    count = db.warning_count(update.effective_chat.id, target.id)
    await reply(update, f"⚠️ <b>WARNING RECORD</b>\n{escape(target.full_name)}: <b>{count}</b>")


async def purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return
    msg = update.effective_message
    if not msg.reply_to_message:
        await reply(update, "↪️ Reply to the first message to delete, then use /purge [count].")
        return
    try:
        count = max(1, min(int(context.args[0]) if context.args else 20, 100))
    except ValueError:
        count = 20
    start_id = msg.reply_to_message.message_id
    deleted = 0
    for mid in range(start_id, min(start_id + count, msg.message_id)):
        try:
            await context.bot.delete_message(update.effective_chat.id, mid)
            deleted += 1
        except TelegramError:
            continue
    try:
        await context.bot.delete_message(update.effective_chat.id, msg.message_id)
    except TelegramError:
        pass
    await log_action(context, update.effective_chat.id, f"Purged {deleted} messages.")
    notice = await context.bot.send_message(update.effective_chat.id, f"🧹 <b>{deleted}</b> messages cleared.", parse_mode=ParseMode.HTML)
    context.job_queue.run_once(lambda c: c.bot.delete_message(update.effective_chat.id, notice.message_id), 5)


async def set_lock(update, context, locked):
    if not await require_admin(update, context):
        return
    perms = ChatPermissions(can_send_messages=not locked)
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, perms)
        label = "LOCKED 🔒" if locked else "UNLOCKED 🔓"
        await reply(update, f"🛡️ <b>GROUP {label}</b>")
        await log_action(context, update.effective_chat.id, f"Group {label}.")
    except TelegramError as exc:
        await reply(update, f"⚠️ Could not change permissions: <code>{escape(str(exc)[:200])}</code>")


async def lock(update, context): await set_lock(update, context, True)
async def unlock(update, context): await set_lock(update, context, False)


async def set_toggle(update, context, key):
    if not await require_admin(update, context):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await reply(update, f"Usage: /{key} on or /{key} off")
        return
    value = context.args[0].lower()
    db.set_setting(update.effective_chat.id, key, value)
    await reply(update, f"✅ <b>{key.title()} messages:</b> {value.upper()}")
    await log_action(context, update.effective_chat.id, f"{key.title()} messages set to {value}.")


async def welcome_cmd(update, context): await set_toggle(update, context, "welcome")
async def goodbye_cmd(update, context): await set_toggle(update, context, "goodbye")


async def setrules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return
    text = " ".join(context.args).strip()
    if not text:
        await reply(update, "Usage: /setrules Be respectful; no spam.")
        return
    db.set_setting(update.effective_chat.id, "rules", text[:3000])
    await reply(update, "📜 <b>Group rules updated.</b>")
    await log_action(context, update.effective_chat.id, "Group rules updated.")


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        await reply(update, "Use /rules inside a group.")
        return
    await reply(update, "📜 <b>GROUP RULES</b>\n" + escape(db.get_setting(update.effective_chat.id, "rules", "No rules configured yet.")))


async def filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return
    raw = update.effective_message.text.partition(" ")[2].strip()
    parts = raw.split(" ", 1)
    if len(parts) < 2 or parts[0] not in ("add", "remove"):
        await reply(update, "Usage:\n/filter add keyword | response\n/filter remove keyword")
        return
    if parts[0] == "add":
        if "|" not in parts[1]:
            await reply(update, "Use: /filter add keyword | response")
            return
        keyword, response = [x.strip() for x in parts[1].split("|", 1)]
        if not keyword or not response:
            await reply(update, "Keyword and response are both required.")
            return
        db.add_filter(update.effective_chat.id, keyword, response)
        await reply(update, f"✅ Filter added for <code>{escape(keyword)}</code>.")
    else:
        db.remove_filter(update.effective_chat.id, parts[1].strip())
        await reply(update, "🗑️ Filter removed if it existed.")


async def filters_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = db.get_filters(update.effective_chat.id)
    if not items:
        await reply(update, "🧩 No custom filters configured.")
        return
    body = "\n".join(f"• <code>{escape(k)}</code>" for k, _ in items[:40])
    await reply(update, "🧩 <b>ACTIVE FILTERS</b>\n" + body)



async def adminlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        await reply(update, "👥 Use /adminlist inside a group.")
        return
    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        lines = [f"• {escape(a.user.full_name)}" + (" 👑" if a.status == "creator" else " 🛡️") for a in admins]
        await reply(update, "👑 <b>GROUP ADMINISTRATORS</b>\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines))
    except TelegramError:
        await reply(update, "⚠️ I couldn't retrieve the administrator list.")


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        await reply(update, "🚩 /report works inside a group.")
        return
    target_msg = update.effective_message.reply_to_message
    if not target_msg or not target_msg.from_user:
        await reply(update, "↪️ Reply to the message you want admins to review, then send /report [reason].")
        return
    target = target_msg.from_user
    reason = " ".join(context.args).strip() or "No reason supplied"
    report_text = (f"🚩 <b>MEMBER REPORT</b>\nChat: <code>{update.effective_chat.id}</code>\n"
                   f"Reported: {escape(target.full_name)} (<code>{target.id}</code>)\n"
                   f"By: {escape(update.effective_user.full_name)} (<code>{update.effective_user.id}</code>)\n"
                   f"Reason: {escape(reason)}")
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    sent = 0
    for admin in admins:
        if admin.user.is_bot:
            continue
        try:
            await context.bot.send_message(admin.user.id, report_text, parse_mode=ParseMode.HTML)
            sent += 1
        except TelegramError:
            continue
    await reply(update, "🚩 <b>Report submitted.</b> Group admins have been notified where private messages are available.")
    await log_action(context, update.effective_chat.id, f"Report submitted against {escape(target.full_name)}. Reason: {escape(reason)}")


async def kickme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        return
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        if member.status in ("administrator", "creator"):
            await reply(update, "⚠️ Group admins should leave using Telegram's group controls.")
            return
        await context.bot.ban_chat_member(update.effective_chat.id, update.effective_user.id)
        await context.bot.unban_chat_member(update.effective_chat.id, update.effective_user.id)
        await reply(update, "👋 You have left the group. You can rejoin if you have an invite link.")
    except TelegramError as exc:
        await reply(update, f"⚠️ I couldn't remove you: <code>{escape(str(exc)[:180])}</code>")


async def blocklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return
    if not context.args or context.args[0].lower() not in ("add", "remove", "list", "clear"):
        await reply(update, "Usage: /blocklist add phrase | /blocklist remove phrase | /blocklist list | /blocklist clear")
        return
    action = context.args[0].lower()
    phrase = " ".join(context.args[1:]).strip()
    chat_id = update.effective_chat.id
    if action == "list":
        entries = db.get_blocklist(chat_id)
        await reply(update, "🚫 <b>BLOCKLIST</b>\n" + ("\n".join("• " + escape(x) for x in entries[:50]) or "No blocked phrases."))
    elif action == "clear":
        db.clear_blocklist(chat_id)
        await reply(update, "🧹 Blocklist cleared.")
    elif not phrase:
        await reply(update, "Please provide a phrase.")
    elif action == "add":
        db.add_blocklist(chat_id, phrase)
        await reply(update, f"🚫 Added <code>{escape(phrase)}</code> to the blocklist.")
    else:
        db.remove_blocklist(chat_id, phrase)
        await reply(update, f"🗑️ Removed <code>{escape(phrase)}</code> if it existed.")
    await log_action(context, chat_id, f"Blocklist updated: {action} {escape(phrase)}")


async def locklinks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await reply(update, "Usage: /locklinks on or /locklinks off")
        return
    value = context.args[0].lower()
    db.set_setting(update.effective_chat.id, "locklinks", value)
    await reply(update, f"🔗 Link blocking is now <b>{value.upper()}</b>.")
    await log_action(context, update.effective_chat.id, f"Link blocking set to {value}.")


async def setflood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context):
        return
    if not context.args:
        current = db.get_setting(update.effective_chat.id, "flood_limit", str(SPAM_LIMIT))
        await reply(update, f"🌊 Current flood limit: <b>{current} messages per {SPAM_WINDOW}s</b>\nUse /setflood 2-20")
        return
    try:
        limit = int(context.args[0])
        if not 2 <= limit <= 20:
            raise ValueError
    except ValueError:
        await reply(update, "⚠️ Choose a flood limit from 2 to 20.")
        return
    db.set_setting(update.effective_chat.id, "flood_limit", str(limit))
    await reply(update, f"🌊 Anti-flood threshold set to <b>{limit}</b> messages per {SPAM_WINDOW} seconds.")
    await log_action(context, update.effective_chat.id, f"Flood threshold set to {limit}.")


async def note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        await reply(update, "🗒️ Notes are available inside groups.")
        return
    raw = update.effective_message.text.partition(" ")[2].strip()
    if raw.startswith("save "):
        if not await require_admin(update, context): return
        body = raw[5:]
        if "|" not in body:
            await reply(update, "Usage: /note save name | note content"); return
        name, content = [x.strip() for x in body.split("|", 1)]
        if not name or not content:
            await reply(update, "A note name and content are required."); return
        db.save_note(update.effective_chat.id, name, content)
        await reply(update, f"🗒️ Saved note <code>{escape(name)}</code>.")
    else:
        await reply(update, "Usage: /note save name | content")


async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update) or not context.args:
        await reply(update, "Usage: /get note_name"); return
    name = " ".join(context.args)
    content = db.get_note(update.effective_chat.id, name)
    await reply(update, f"🗒️ <b>{escape(name)}</b>\n{escape(content)}" if content else "No note found with that name.")


async def notes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update): return
    names = db.list_notes(update.effective_chat.id)
    await reply(update, "🗒️ <b>SAVED NOTES</b>\n" + ("\n".join("• " + escape(n) for n in names) or "No saved notes."))


async def delnote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_admin(update, context): return
    if not context.args:
        await reply(update, "Usage: /delnote note_name"); return
    name = " ".join(context.args)
    db.remove_note(update.effective_chat.id, name)
    await reply(update, f"🗑️ Note <code>{escape(name)}</code> removed if it existed.")


async def new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat:
        return
    for member in update.effective_message.new_chat_members:
        if member.is_bot:
            continue
        db.increment_member_count(chat.id)
        if db.get_setting(chat.id, "welcome", "on") == "on":
            name = escape(member.first_name)
            text = (f"🌑 <b>WELCOME TO {escape(chat.title or 'THE GROUP').upper()}!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n👋 Hey {name}, glad you're here!\n"
                    "📜 Please read the group rules and respect everyone.\n"
                    "🛡️ Protected by <b>SAINT GUARD</b>.")
            await context.bot.send_message(chat.id, text, parse_mode=ParseMode.HTML)
        await log_action(context, chat.id, f"New member joined: {escape(member.full_name)} (<code>{member.id}</code>)")


async def left_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    member = update.effective_message.left_chat_member
    if chat and member and not member.is_bot:
        db.decrement_member_count(chat.id)
        if db.get_setting(chat.id, "goodbye", "off") == "on":
            await context.bot.send_message(chat.id, f"👋 <b>{escape(member.first_name)}</b> has left the group.", parse_mode=ParseMode.HTML)
        await log_action(context, chat.id, f"Member left: {escape(member.full_name)} (<code>{member.id}</code>)")


async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update) or not update.effective_message or not update.effective_user:
        return
    msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if user.is_bot:
        return

    # Don't moderate group administrators.
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status in ("administrator", "creator"):
            return
    except TelegramError:
        pass

    # Flood guard: message bursts within a rolling window.
    now = time.time()
    key = (chat.id, user.id)
    q = recent_messages[key]
    while q and now - q[0] > SPAM_WINDOW:
        q.popleft()
    q.append(now)
    try:
        flood_limit = int(db.get_setting(chat.id, "flood_limit", str(SPAM_LIMIT)))
    except ValueError:
        flood_limit = SPAM_LIMIT
    if len(q) > flood_limit:
        try:
            await msg.delete()
            await context.bot.restrict_chat_member(
                chat.id, user.id, ChatPermissions(can_send_messages=False),
                until_date=int(now) + MUTE_MINUTES * 60
            )
            await log_action(context, chat.id, f"Anti-spam: muted <code>{user.id}</code> for {MUTE_MINUTES} minutes after flooding.")
        except TelegramError:
            log.info("Anti-spam action unavailable; check bot permissions.")
        q.clear()
        return

    # Repeated identical text detector.
    text = (msg.text or msg.caption or "").strip()
    if text:
        norm = re.sub(r"\s+", " ", text).lower()
        blocked = next((phrase for phrase in db.get_blocklist(chat.id) if phrase in norm), None)
        if blocked:
            try:
                await msg.delete()
                await log_action(context, chat.id, f"Blocklist match removed from user <code>{user.id}</code>.")
            except TelegramError:
                pass
            return
        if db.get_setting(chat.id, "locklinks", "off") == "on" and re.search(r"https?://|t\.me/|www\.", norm):
            try:
                await msg.delete()
            except TelegramError:
                pass
            return
        duplicate_key = (chat.id, user.id, "last_text")
        previous = context.chat_data.get(duplicate_key)
        if previous == norm and len(norm) > 3:
            try:
                await msg.delete()
                return
            except TelegramError:
                pass
        context.chat_data[duplicate_key] = norm

        # Custom keyword filters, exact phrase substring match.
        for keyword, response in db.get_filters(chat.id):
            if keyword.lower() in norm:
                await msg.reply_text(response, disable_web_page_preview=True)
                break


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled bot error", exc_info=context.error)


class HealthHandler(BaseHTTPRequestHandler):
    """Small HTTP server used by Render to confirm the container is alive."""

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path not in ("/", "/health", "/health/"):
            self.send_error(404)
            return
        body = b'{"status":"ok","service":"saint-guard-bot"}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        log.info("health %s", format % args)


def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, name="health-server", daemon=True)
    thread.start()
    log.info("Health endpoint listening on 0.0.0.0:%s", port)
    return server


def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN is missing. Copy .env.example to .env and add your token.")
    health_server = start_health_server()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^menu_"))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("warnings", warnings))
    app.add_handler(CommandHandler("purge", purge))
    app.add_handler(CommandHandler("lock", lock))
    app.add_handler(CommandHandler("unlock", unlock))
    app.add_handler(CommandHandler("welcome", welcome_cmd))
    app.add_handler(CommandHandler("goodbye", goodbye_cmd))
    app.add_handler(CommandHandler("setrules", setrules))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("filter", filter_cmd))
    app.add_handler(CommandHandler("filters", filters_cmd))
    app.add_handler(CommandHandler("adminlist", adminlist))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("kickme", kickme))
    app.add_handler(CommandHandler("blocklist", blocklist_cmd))
    app.add_handler(CommandHandler("locklinks", locklinks))
    app.add_handler(CommandHandler("setflood", setflood))
    app.add_handler(CommandHandler("flood", setflood))
    app.add_handler(CommandHandler("note", note_cmd))
    app.add_handler(CommandHandler("get", get_note))
    app.add_handler(CommandHandler("notes", notes_cmd))
    app.add_handler(CommandHandler("delnote", delnote))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, left_member))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, group_message))
    app.add_error_handler(error_handler)
    log.info("SAINT GUARD is starting...")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        health_server.shutdown()


if __name__ == "__main__":
    main()
