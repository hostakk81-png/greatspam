import asyncio
import aiohttp
import json
import time
import sqlite3
import html
import os
import re
import shutil
import unicodedata
import logging
from urllib.parse import urlparse
from typing import Any, Awaitable, Callable, Dict

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ChatMemberStatus, ParseMode, ContentType
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    BufferedInputFile,
    MessageEntity,
    TelegramObject,
    User,
)
from telethon import TelegramClient, utils as tl_utils
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
    PhoneNumberFloodError,
    PhoneNumberAppSignupForbiddenError,
    PhoneMigrateError,
)
from telethon.errors.rpcerrorlist import FolderIdInvalidError
try:
    from telethon.tl.functions.messages import GetDialogFiltersRequest
except ImportError:
    GetDialogFiltersRequest = None

logger = logging.getLogger(__name__)

import mailing_ext as mex

TOKEN = "8968384221:AAEMWGn-k-YLS2C3XGmMHrrk3TCjaMrZ32w"
CRYPTO_PAY_TOKEN = "604180:AASnBhWqYHjnSOK1FuscIPbPXisSP3ALMg2"
CRYPTO_PAY_BASE_URL = "https://pay.crypt.bot/api"
XROCKET_PAY_TOKEN = os.getenv("XROCKET_PAY_TOKEN", "89cb8571af90a147128132018")
XROCKET_PAY_BASE_URL = "https://pay.xrocket.exchange"
TONKEEPER_WALLET = ""
TONCENTER_BASE_URL = "https://toncenter.com/api/v2"
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "7528568061,8305845726")
TG_API_ID = 28563482
TG_API_HASH = "914e598bf5ca977a5f53d3c3b4f6f148"

dp = Dispatcher()
pending_invoices = {}
awaiting_rub_amount = {}
pending_xrocket_invoices = {}
awaiting_xrocket_amount = {}
pending_ton_invoices = {}
awaiting_ton_rub_amount = {}
awaiting_promo_input = {}
admin_action_state = {}
admin_broadcast_state = {}
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(
    os.getenv(
        "DATA_DIR",
        os.getenv(
            "RAILWAY_VOLUME_MOUNT_PATH",
            os.getenv("PERSISTENT_DATA_DIR", _BOT_DIR),
        ),
    )
)
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "blackwire.db"))
SESSIONS_DIR = os.getenv("SESSIONS_DIR", os.path.join(DATA_DIR, "sessions"))
account_login_state = {}
mailing_input_state = {}
mailing_tasks = {}
mandatory_sub_admin_state: dict[int, dict] = {}
ACC_PAGE_SIZE = 5
CHAT_PAGE_SIZE = 6
DEFAULT_ACCOUNT_SLOTS = 5
BALANCE_CURRENCY = "USDT"
MAILING_MEDIA_DIR = os.getenv("MAILING_MEDIA_DIR", os.path.join(DATA_DIR, "mailing_media"))
ADMIN_BROADCAST_MEDIA_DIR = os.getenv(
    "ADMIN_BROADCAST_MEDIA_DIR",
    os.path.join(DATA_DIR, "admin_broadcast_media"),
)
DEFAULT_BANNER_PATH = os.path.join(_BOT_DIR, "media", "banner.png")
DEFAULT_MAILING_VIDEO_PATH = DEFAULT_BANNER_PATH


def parse_admin_ids(raw: str) -> set[int]:
    admin_ids = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            admin_ids.add(int(part))
        except ValueError:
            logger.warning("Invalid admin id ignored: %r", part)
    return admin_ids


ADMIN_IDS = parse_admin_ids(ADMIN_IDS_RAW)


def is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return int(user_id) in ADMIN_IDS


def prepare_persistent_storage() -> None:
    for path in (DATA_DIR, SESSIONS_DIR, MAILING_MEDIA_DIR, ADMIN_BROADCAST_MEDIA_DIR):
        os.makedirs(path, exist_ok=True)

    old_db = os.path.join(_BOT_DIR, "blackwire.db")
    if os.path.abspath(DB_PATH) != os.path.abspath(old_db):
        db_parent = os.path.dirname(os.path.abspath(DB_PATH))
        if db_parent:
            os.makedirs(db_parent, exist_ok=True)
        if os.path.isfile(old_db) and not os.path.exists(DB_PATH):
            try:
                shutil.copy2(old_db, DB_PATH)
                logger.info("Copied existing DB to persistent storage: %s", DB_PATH)
            except OSError:
                logger.exception("Failed to copy DB to persistent storage")

    old_sessions = os.path.join(_BOT_DIR, "sessions")
    if os.path.abspath(SESSIONS_DIR) != os.path.abspath(old_sessions) and os.path.isdir(old_sessions):
        for name in os.listdir(old_sessions):
            if not name.endswith((".session", ".session-journal")):
                continue
            src = os.path.join(old_sessions, name)
            dst = os.path.join(SESSIONS_DIR, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    logger.exception("Failed to copy session file to persistent storage: %s", name)

PEN_EMOJI_ID = "5258331647358540449"
INFO_EMOJI_ID = "5258503720928288433"
CROSS_EMOJI_ID = "5258474669769497337"
PLUS_EMOJI_ID = "5775937998948404844"
TRASH_EMOJI_ID = "5327934298219624721"
BACK_EMOJI_ID = "5258236805890710909"
RENAME_EMOJI_ID = "5879841310902324730"
CHANGE_EMOJI_ID = "6039779802741739617"
CREATE_EMOJI_ID = "6010362983320916413"
TICK_EMOJI_ID = "5776375003280838798"
CATEGORY_EMOJI_ID = "5888620056551625531"
COMAND_EMOJI_ID = "5877396173135811032"
SEND_EMOJI_ID = "5875465628285931233"
TIME_EMOJI_ID = "5985616167740379273"
ID_EMOJI_ID = "5402160575864132968"
REPEAT_EMOJI_ID = "6005843436479975944"
CHANNEL_EMOJI_ID = "5771695636411847302"
STATISTICS_EMOJI_ID = "5877485980901971030"
ERROR_EMOJI_ID = "5881702736843511327"
USER_EMOJI_ID = "5260399854500191689"
PROFILE_EMOJI_ID = "5954175920506933873"
SECRET_EMOJI_ID = "5879937509579820068"
PHOTO_EMOJI_ID = "5890744068203352126"
VIDEO_EMOJI_ID = "5775981206319402773"
GOLOS_EMOJI_ID = "5897554554894946515"
ROUND_EMOJI_ID = "5900130736408629854"
QUESTION_EMOJI_ID = "5220053623211305785"
STICK_EMOJI_ID = "5784982040432611567"
DOCUMENT_EMOJI_ID = "5875206779196935950"
GIF_EMOJI_ID = "5785035744703680213"
COLOR_EMOJI_ID = "5814690801665446789"
CLICK_EMOJI_ID = "5884106131822875141"
AUDIO_EMOJI_ID = "5890997763331591703"
GEM_EMOJI_ID = "5345892681765645532"
STARS_EMOJI_ID = "5874948844935974490"
CRYPTOBOT_EMOJI_ID = "5361914370068613491"
XROCKET_EMOJI_ID = "5415897719522744378"

_INLINE_EMOJI_ID_MAP = {
    "5193179982775476271": CRYPTOBOT_EMOJI_ID,
    "5206222720416643915": TIME_EMOJI_ID,
    "5206401524200145033": BACK_EMOJI_ID,
    "5206510891247371052": BACK_EMOJI_ID,
    "5206626000665868017": DOCUMENT_EMOJI_ID,
    "5255933397750014894": CRYPTOBOT_EMOJI_ID,
    "5275979556308674886": USER_EMOJI_ID,
    "5276037216244624892": USER_EMOJI_ID,
    "5276111746812112286": STARS_EMOJI_ID,
    "5276220667182736079": PLUS_EMOJI_ID,
    "5276229330131772747": GEM_EMOJI_ID,
    "5276240711795107620": ERROR_EMOJI_ID,
    "5276384644739129761": TRASH_EMOJI_ID,
    "5276395476646653290": CLICK_EMOJI_ID,
    "5276412364458059956": TIME_EMOJI_ID,
    "5276422526350681413": STARS_EMOJI_ID,
    "5276442772826515132": COLOR_EMOJI_ID,
    "5278411813468269386": TICK_EMOJI_ID,
    "5278413853577734640": CREATE_EMOJI_ID,
    "5278528159837348960": CHANNEL_EMOJI_ID,
    "5278540791336165644": GEM_EMOJI_ID,
    "5278578973595427038": CROSS_EMOJI_ID,
    "5278602437001767574": INFO_EMOJI_ID,
    "5298668674532538341": CHANNEL_EMOJI_ID,
    "5427168083074628963": GEM_EMOJI_ID,
    "5429181348994648222": CRYPTOBOT_EMOJI_ID,
    "5436113877181941026": QUESTION_EMOJI_ID,
}
_AiogramInlineKeyboardButton = InlineKeyboardButton


def InlineKeyboardButton(*args, **kwargs):
    icon_id = kwargs.get("icon_custom_emoji_id")
    if icon_id is not None:
        kwargs["icon_custom_emoji_id"] = str(icon_id)
    return _AiogramInlineKeyboardButton(*args, **kwargs)


async def safe_edit_caption(message, caption, reply_markup):
    try:
        await message.edit_caption(caption=caption, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        error_text = str(e)
        if "there is no caption in the message to edit" in error_text:
            try:
                await message.edit_text(text=caption, reply_markup=reply_markup)
                return
            except TelegramBadRequest as inner_e:
                if "message is not modified" in str(inner_e):
                    return
                raise
        if "message is not modified" not in error_text:
            raise


async def safe_edit_text(message, text, reply_markup=None):
    try:
        await message.edit_text(text=text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def safe_delete_message(message):
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


def normalize_phone(raw: str) -> str | None:
    if not raw:
        return None
    s = unicodedata.normalize("NFKC", raw.strip())
    s = re.sub(r"[\u200b-\u200d\ufeff\u00a0\u202f\u2060]+", "", s)
    low = s.lower()
    if low.startswith("tel:"):
        s = s[4:]
    elif low.startswith("whatsapp:") or low.startswith("sip:"):
        s = s.split(":", 1)[-1]
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits[0] == "8" and digits[1] == "9":
        digits = "7" + digits[1:]
    if len(digits) < 5 or len(digits) > 15:
        return None
    return "+" + digits


def get_balance(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return float(row[0]) if row else 0.0


def add_balance(user_id, amount):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, balance, subscription_months, subscription_weeks, is_banned)
            VALUES (?, ?, 0, 0, 0)
            ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance
            """,
            (user_id, float(amount)),
        )
        conn.commit()


def get_subscription_weeks(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT subscription_weeks FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return int(row[0]) if row else 0


def get_subscription_text(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT subscription_months, subscription_weeks, lifetime_access, message_credits FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return "неактивна"
    months, weeks = int(row[0]), int(row[1])
    lifetime = int(row[2] or 0)
    credits = int(row[3] or 0)
    if lifetime:
        return "навсегда"
    if months <= 0 and weeks <= 0 and credits <= 0:
        return "неактивна"
    parts = []
    if weeks > 0:
        parts.append(f"{weeks} нед.")
    if months > 0:
        parts.append(f"{months} мес.")
    if credits > 0:
        parts.append(f"{credits} сообщений")
    return "активна (" + ", ".join(parts) + ")"


def is_banned(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return bool(row and int(row[0]) == 1)


def get_subscription_months(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT subscription_months FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return int(row[0]) if row else 0


def is_subscription_active(user_id):
    return has_unlimited_mailing(user_id) or get_message_credits(user_id) > 0


def has_unlimited_mailing(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT subscription_months, subscription_weeks, lifetime_access FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return False
    return int(row[0] or 0) > 0 or int(row[1] or 0) > 0 or int(row[2] or 0) == 1


def get_message_credits(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT message_credits FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return int(row[0]) if row else 0


def ensure_user(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, balance, subscription_months, subscription_weeks, is_banned, message_credits, account_slots, lifetime_access)
            VALUES (?, 0, 0, 0, 0, 0, ?, 0)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (int(user_id), DEFAULT_ACCOUNT_SLOTS),
        )
        conn.commit()


def get_known_user_ids() -> list[int]:
    user_ids: set[int] = set()
    with sqlite3.connect(DB_PATH) as conn:
        for (uid,) in conn.execute("SELECT user_id FROM users").fetchall():
            user_ids.add(int(uid))
        for (uid,) in conn.execute("SELECT DISTINCT user_id FROM accounts").fetchall():
            user_ids.add(int(uid))
    return sorted(user_ids)


def get_admin_broadcast_recipients(target: str) -> list[int]:
    if target == "admins":
        return sorted(ADMIN_IDS)
    return [uid for uid in get_known_user_ids() if not is_banned(uid)]


def add_message_credits(user_id, amount):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, balance, subscription_months, subscription_weeks, is_banned, message_credits, account_slots, lifetime_access)
            VALUES (?, 0, 0, 0, 0, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                message_credits = message_credits + excluded.message_credits
            """,
            (user_id, int(amount), DEFAULT_ACCOUNT_SLOTS),
        )
        conn.commit()


def set_lifetime_access(user_id, on=True):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, balance, subscription_months, subscription_weeks, is_banned, message_credits, account_slots, lifetime_access)
            VALUES (?, 0, 0, 0, 0, 0, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET lifetime_access = excluded.lifetime_access
            """,
            (user_id, DEFAULT_ACCOUNT_SLOTS, 1 if on else 0),
        )
        conn.commit()


def can_send_mailing_message(user_id):
    return has_unlimited_mailing(user_id) or get_message_credits(user_id) > 0


def consume_message_credit_if_needed(user_id):
    if has_unlimited_mailing(user_id):
        return True
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT message_credits FROM users WHERE user_id = ?", (user_id,)).fetchone()
        credits = int(row[0] or 0) if row else 0
        if credits <= 0:
            return False
        conn.execute(
            "UPDATE users SET message_credits = message_credits - 1 WHERE user_id = ? AND message_credits > 0",
            (user_id,),
        )
        conn.commit()
        return True


def get_account_slots(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT account_slots FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return int(row[0]) if row and row[0] is not None else DEFAULT_ACCOUNT_SLOTS


def add_account_slots(user_id, amount):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, balance, subscription_months, subscription_weeks, is_banned, message_credits, account_slots, lifetime_access)
            VALUES (?, 0, 0, 0, 0, 0, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET account_slots = account_slots + ?
            """,
            (user_id, DEFAULT_ACCOUNT_SLOTS + int(amount), int(amount)),
        )
        conn.commit()


def add_subscription_weeks(user_id, weeks):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, balance, subscription_months, subscription_weeks, is_banned)
            VALUES (?, 0, 0, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                subscription_weeks = subscription_weeks + excluded.subscription_weeks
            """,
            (user_id, int(weeks)),
        )
        conn.commit()


def add_subscription_months(user_id, months):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, balance, subscription_months, subscription_weeks, is_banned)
            VALUES (?, 0, ?, 0, 0)
            ON CONFLICT(user_id) DO UPDATE SET subscription_months = subscription_months + excluded.subscription_months
            """,
            (user_id, int(months)),
        )
        conn.commit()


def set_ban_status(user_id, is_ban):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users(user_id, balance, subscription_months, subscription_weeks, is_banned)
            VALUES (?, 0, 0, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET is_banned = excluded.is_banned
            """,
            (user_id, 1 if is_ban else 0),
        )
        conn.commit()


def create_or_update_promo(code, amount, uses):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO promos(code, amount, uses)
            VALUES (?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET amount = excluded.amount, uses = excluded.uses
            """,
            (code.upper(), float(amount), int(uses)),
        )
        conn.commit()


def use_promo(code):
    normalized = code.upper()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT amount, uses FROM promos WHERE code = ?", (normalized,)).fetchone()
        if not row:
            return None
        amount, uses = float(row[0]), int(row[1])
        if uses <= 0:
            return None
        conn.execute("UPDATE promos SET uses = uses - 1 WHERE code = ?", (normalized,))
        conn.commit()
        return amount


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL NOT NULL DEFAULT 0,
                subscription_months INTEGER NOT NULL DEFAULT 0,
                subscription_weeks INTEGER NOT NULL DEFAULT 0,
                lifetime_access INTEGER NOT NULL DEFAULT 0,
                message_credits INTEGER NOT NULL DEFAULT 0,
                account_slots INTEGER NOT NULL DEFAULT 5,
                is_banned INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        ucols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "subscription_weeks" not in ucols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN subscription_weeks INTEGER NOT NULL DEFAULT 0"
            )
        if "lifetime_access" not in ucols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN lifetime_access INTEGER NOT NULL DEFAULT 0"
            )
        if "message_credits" not in ucols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN message_credits INTEGER NOT NULL DEFAULT 0"
            )
        if "account_slots" not in ucols:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN account_slots INTEGER NOT NULL DEFAULT {DEFAULT_ACCOUNT_SLOTS}"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS promos (
                code TEXT PRIMARY KEY,
                amount REAL NOT NULL,
                uses INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                session_name TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        mex.init_mailing_table(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL UNIQUE,
                invite_link TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


def get_enabled_required_channels() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, chat_id, invite_link, enabled FROM required_channels WHERE enabled = 1"
        ).fetchall()
        return [dict(r) for r in rows]


def list_all_required_channels() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, chat_id, invite_link, enabled, created_at FROM required_channels ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_required_channel(chat_id: str, invite_link: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO required_channels (chat_id, invite_link, enabled, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                invite_link = excluded.invite_link,
                enabled = 1
            """,
            (chat_id.strip(), invite_link.strip(), int(time.time())),
        )
        conn.commit()


def toggle_required_channel_row(row_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT enabled FROM required_channels WHERE id = ?", (row_id,)).fetchone()
        if not row:
            return
        new_en = 0 if int(row[0]) else 1
        conn.execute("UPDATE required_channels SET enabled = ? WHERE id = ?", (new_en, row_id))
        conn.commit()


def delete_required_channel_row(row_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM required_channels WHERE id = ?", (row_id,))
        conn.commit()


def parse_chat_id_for_api(chat_id: str) -> int | str:
    s = (chat_id or "").strip()
    if s.startswith("@"):
        return s
    try:
        return int(s)
    except ValueError:
        return s


def normalize_admin_channel_id(raw: str) -> str | None:
    raw = (raw or "").strip()
    if raw.startswith("@"):
        return raw.split()[0] if raw.split()[0] else None
    if re.fullmatch(r"-?\d+", raw.replace(" ", "")):
        return raw.replace(" ", "")
    return None


def normalize_invite_link(raw: str) -> str | None:
    s = (raw or "").strip().split()[0]
    low = s.lower()
    if low.startswith("https://t.me/") or low.startswith("http://t.me/"):
        return s
    if low.startswith("https://telegram.me/") or low.startswith("http://telegram.me/"):
        return s
    if low.startswith("t.me/"):
        return "https://" + s
    return None


def display_link_for_channel(row: dict) -> str:
    link = (row.get("invite_link") or "").strip()
    if link:
        return link
    cid = row.get("chat_id") or ""
    if cid.startswith("@"):
        return f"https://t.me/{cid[1:]}"
    return "https://t.me/"


async def check_mandatory_subscriptions(bot: Bot, user_id: int) -> tuple[bool, list[dict]]:
    rows = get_enabled_required_channels()
    if not rows:
        return True, []
    missing: list[dict] = []
    for row in rows:
        cid = parse_chat_id_for_api(row["chat_id"])
        try:
            member = await bot.get_chat_member(chat_id=cid, user_id=user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                missing.append(row)
        except TelegramBadRequest as e:
            logger.warning("Проверка подписки: get_chat_member %s — %s", cid, e)
    return (len(missing) == 0, missing)


def build_mandatory_sub_caption() -> str:
    return (
        "<b><tg-emoji emoji-id='5298668674532538341'>👥️</tg-emoji> Нужна подписка на каналы</b>\n\n"
        "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> "
        "Нажмите на <b>название канала</b> в кнопках — откроется подписка. "
        "Когда подпишитесь на все, нажмите "
        "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Проверить подписку</b>.</b></blockquote>"
    )


async def build_mandatory_sub_keyboard(bot: Bot, missing: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in missing:
        cid = parse_chat_id_for_api(row["chat_id"])
        try:
            chat = await bot.get_chat(cid)
            title = (chat.title or "Канал").strip() or "Канал"
        except TelegramBadRequest:
            title = "Канал"
        if len(title) > 64:
            title = title[:61] + "…"
        url = display_link_for_channel(row)
        rows.append(
            [
                InlineKeyboardButton(
                    text=title,
                    url=url,
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Проверить подписку",
                callback_data="mandatory_sub_check",
                style="success",
                icon_custom_emoji_id="5278411813468269386",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


class MandatorySubMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        bot: Bot = data["bot"]
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        if user is None:
            return await handler(event, data)
        if is_admin(user.id):
            return await handler(event, data)
        if is_banned(user.id):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "mandatory_sub_check":
            return await handler(event, data)
        ok, missing = await check_mandatory_subscriptions(bot, user.id)
        if ok:
            return await handler(event, data)
        caption = build_mandatory_sub_caption()
        markup = await build_mandatory_sub_keyboard(bot, missing)
        if isinstance(event, CallbackQuery):
            await event.answer(
                "Сначала подпишитесь на каналы",
                show_alert=True,
            )
            try:
                await event.message.answer(caption, reply_markup=markup)
            except TelegramBadRequest:
                pass
            return None
        await event.answer(caption, reply_markup=markup, disable_web_page_preview=True)
        return None


def get_user_accounts(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, phone, session_name FROM accounts WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
        return [{"id": int(r[0]), "phone": r[1], "session_name": r[2]} for r in rows]


def get_all_accounts():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, user_id, phone, session_name FROM accounts ORDER BY id DESC"
        ).fetchall()
        return [
            {
                "id": int(r[0]),
                "user_id": int(r[1]),
                "phone": r[2],
                "session_name": r[3],
            }
            for r in rows
        ]


def add_user_account(user_id, phone, session_name):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO accounts(user_id, phone, session_name, created_at) VALUES (?, ?, ?, ?)",
            (user_id, phone, session_name, int(time.time())),
        )
        conn.commit()


def get_account_by_id(account_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, user_id, phone, session_name FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        if not row:
            return None
        return {"id": int(row[0]), "user_id": int(row[1]), "phone": row[2], "session_name": row[3]}


def delete_account_by_id(account_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()

# 📹 старт текст
START_CAPTION = """
<b><tg-emoji emoji-id="5278411813468269386">✅</tg-emoji> Добро пожаловать в Great Spam</b>

<blockquote><b><tg-emoji emoji-id="5298668674532538341">👥️</tg-emoji> Добавь свой аккаунт и начни рассылку за секунды</b>

<b><tg-emoji emoji-id="5276127848644503161">🤖</tg-emoji> Полная автоматизация — бот делает всё за тебя</b>

<b><tg-emoji emoji-id="5278647306525108244">🖥</tg-emoji> Точная доставка сообщений в нужную аудиторию</b>

<b><tg-emoji emoji-id="5278753302023004775">ℹ️</tg-emoji> Безопасность и контроль каждого действия</b>
</blockquote>

<b><tg-emoji emoji-id="5276229330131772747">👑</tg-emoji> Приятного использования!</b>
"""

# 👤 профиль текст
def profile_text(user_id, username):
    balance = get_balance(user_id)
    subscription = get_subscription_text(user_id)
    acc_count = len(get_user_accounts(user_id))
    acc_slots = get_account_slots(user_id)
    return f"""
<b><tg-emoji emoji-id="5276395476646653290">🔍</tg-emoji> Ваш профиль</b>

<blockquote><b><tg-emoji emoji-id="5275979556308674886">👤</tg-emoji> Юзер - @{username}</b>

<b><tg-emoji emoji-id="5255933397750014894">💱</tg-emoji> Баланс - {balance:.2f} {BALANCE_CURRENCY}</b>

<b><tg-emoji emoji-id="5276314275994954605">🔨</tg-emoji> Аккаунты - {acc_count}/{acc_slots}</b>

<b><tg-emoji emoji-id="5276229330131772747">👑</tg-emoji> Подписка - {subscription}</b></blockquote>

<b>Great Spam - не лучший выбор но лучше некоторых</b>
"""

# 💎 текст подписки
SUBSCRIPTIONS_CAPTION = """
<b><tg-emoji emoji-id='5276314275994954605'>🔨</tg-emoji> Выберите тариф подписки</b>

<blockquote><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> <b>Месячный абонемент</b> — 30$ за неограниченную рассылку на месяц

<tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> <b>Разовый абонемент</b> — 10$ за 100 успешных отправок

<tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> <b>Доступ навсегда</b> — 100$ без лимита по времени

<tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> <b>Слоты аккаунтов</b> — 5 слотов включены, +5 слотов за 5$</blockquote>

<b><tg-emoji emoji-id='5206626000665868017'>📚</tg-emoji> Подписка активируется автоматически после оплаты с баланса</b>
"""

# ❓ текст почему мы
WHY_US_CAPTION = """
<b><tg-emoji emoji-id="5436113877181941026">❓</tg-emoji> Почему именно Great Spam?</b>

<blockquote><b><tg-emoji emoji-id="5276412364458059956">🕓</tg-emoji> Скорость</b> — рассылка за секунды

<b><tg-emoji emoji-id="5278753302023004775">ℹ️</tg-emoji> Безопасность</b> — полная защита аккаунтов

<b><tg-emoji emoji-id="5276127848644503161">🤖</tg-emoji> Автоматизация</b> — бот делает всё за вас

<b><tg-emoji emoji-id="5206222720416643915">🔔</tg-emoji> Поддержка 24/7</b> — всегда поможем

<b><tg-emoji emoji-id="5298668674532538341">👥️</tg-emoji> Точное таргетирование</b> — доставка нужной аудитории</blockquote>

<b><tg-emoji emoji-id="5278411813468269386">✅</tg-emoji> Выбирай лучшее — выбирай Great Spam!</b>
"""

# 💳 текст пополнения
DEPOSIT_CAPTION = """
<b><tg-emoji emoji-id="5255933397750014894">💱</tg-emoji> Пополнить баланс</b>

<blockquote><b><tg-emoji emoji-id="5429181348994648222">👛</tg-emoji> Выберите способ пополнения</b>
</blockquote>

<b><tg-emoji emoji-id="5278753302023004775">ℹ️</tg-emoji> После оплаты баланс обновится автоматически</b>
"""

TONKEEPER_CAPTION = """
<b><tg-emoji emoji-id="5193179982775476271">🪙</tg-emoji> Tonkeeper</b>

<blockquote><b><tg-emoji emoji-id="5278753302023004775">ℹ️</tg-emoji> Введите сумму в USDT, бот рассчитает TON и создаст ссылку на оплату</b>
</blockquote>

<b><tg-emoji emoji-id="5278528159837348960">📢</tg-emoji> После оплаты нажмите «Проверить платеж» или дождитесь авто-проверки</b>
"""

XROCKET_CAPTION = f"""
<b><tg-emoji emoji-id="{XROCKET_EMOJI_ID}">💱</tg-emoji> XRocket</b>

<blockquote><b><tg-emoji emoji-id="5278753302023004775">ℹ️</tg-emoji> Введите сумму в USDT, бот создаст точный счёт XRocket</b>
</blockquote>

<b><tg-emoji emoji-id="5278528159837348960">📢</tg-emoji> После оплаты нажмите «Проверить платеж» или дождитесь авто-проверки</b>
"""

CRYPTOBOT_CAPTION = """
<b><tg-emoji emoji-id="5429181348994648222">👛</tg-emoji> CryptoBot</b>

<blockquote><b><tg-emoji emoji-id="5278753302023004775">ℹ️</tg-emoji> Введите сумму в USDT, бот создаст точный счёт CryptoBot</b>
</blockquote>

<b><tg-emoji emoji-id="5278528159837348960">📢</tg-emoji> После оплаты нажмите «Проверить платеж» или дождитесь авто-проверки</b>
"""

# 📢 текст рассылки
MAIL_CAPTION = """
<b><tg-emoji emoji-id="5278528159837348960">📢</tg-emoji> Панель рассылки</b>

<blockquote><b><tg-emoji emoji-id="5278753302023004775">ℹ️</tg-emoji> Управляйте аккаунтами и параметрами рассылки</b></blockquote>
"""

# 🔘 INLINE ГЛАВНОЕ МЕНЮ
def main_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Начать рассылку",
                    callback_data="mail", 
                    icon_custom_emoji_id="5278528159837348960"  # 📢
                )
            ],
            [
                InlineKeyboardButton(
                    text="Подписки", 
                    callback_data="subscriptions", 
                    icon_custom_emoji_id="5427168083074628963"  # 💎
                ),
                InlineKeyboardButton(
                    text="Менеджер", 
                    url="https://t.me/theevrey",
                    icon_custom_emoji_id="5276240711795107620"  # ⚠️
                )
            ],
            [
                InlineKeyboardButton(
                    text="Почему мы?", 
                    callback_data="why_us",
                    icon_custom_emoji_id="5436113877181941026"  # ❓
                )
            ],
            [
                InlineKeyboardButton(
                    text="Профиль", 
                    callback_data="profile",
                    icon_custom_emoji_id="5275979556308674886"  # 👤
                )
            ]
        ]
    )

def subscriptions_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Месяц безлимит - 30$",
                    callback_data="sub_month_unlimited",
                    style="primary",
                    icon_custom_emoji_id="5278540791336165644",  # 📦
                ),
            ],
            [
                InlineKeyboardButton(
                    text="100 сообщений - 10$",
                    callback_data="sub_pack100",
                    style="primary",
                    icon_custom_emoji_id="5278540791336165644",  # 📦
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Навсегда - 100$",
                    callback_data="sub_lifetime",
                    style="primary",
                    icon_custom_emoji_id="5278540791336165644",  # 📦
                ),
            ],
            [
                InlineKeyboardButton(
                    text="+5 слотов - 5$",
                    callback_data="sub_slots5",
                    style="primary",
                    icon_custom_emoji_id="5278540791336165644",  # 📦
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="back",
                    icon_custom_emoji_id="5206510891247371052",  # 🔽
                )
            ],
        ]
    )

def why_us_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="back",
                    icon_custom_emoji_id="5206510891247371052"  # 🔽
                )
            ]
        ]
    )

# 🔘 INLINE ПРОФИЛЬ
def profile_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пополнить",
                    callback_data="deposit",
                    icon_custom_emoji_id="5255933397750014894"  # 💱
                ),
                InlineKeyboardButton(
                    text="Ввести промокод",
                    callback_data="enter_promo",
                    style="primary",
                    icon_custom_emoji_id="5276422526350681413"  # 🎁
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="back",
                    icon_custom_emoji_id="5206510891247371052"  # 🔽
                )
            ],
        ]
    )


def admin_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Забанить", callback_data="admin_ban", style="danger", icon_custom_emoji_id="5278578973595427038"),  # 🚫
                InlineKeyboardButton(text="Разбанить", callback_data="admin_unban", style="success", icon_custom_emoji_id="5278411813468269386"),  # ✅
            ],
            [
                InlineKeyboardButton(text="Создать промо", callback_data="admin_promo", style="primary", icon_custom_emoji_id="5276422526350681413"),  # 🎁
                InlineKeyboardButton(text="Выдать баланс", callback_data="admin_balance", style="primary", icon_custom_emoji_id="5255933397750014894"),  # 💱
            ],
            [
                InlineKeyboardButton(text="Выдать подписку", callback_data="admin_sub", style="primary", icon_custom_emoji_id="5276229330131772747"),  # 👑
            ],
            [
                InlineKeyboardButton(
                    text="Рассылка",
                    callback_data="adm_broadcast",
                    style="primary",
                    icon_custom_emoji_id="5875465628285931233",  # ✈️
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Сессии",
                    callback_data="adm_sessions",
                    style="primary",
                    icon_custom_emoji_id="5276037216244624892",  # 💼
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Добавить оп",
                    callback_data="admin_reqadd",
                    style="primary",
                    icon_custom_emoji_id="5276220667182736079",  # 📥
                ),
                InlineKeyboardButton(
                    text="Управлять оп",
                    callback_data="admin_reqmanage",
                    style="primary",
                    icon_custom_emoji_id="5276442772826515132",  # 🎨
                ),
            ],
            [
                InlineKeyboardButton(text="Назад на главную", callback_data="admin_back_main", icon_custom_emoji_id="5278413853577734640"),  # 🏠
            ],
        ]
    )


def admin_sessions_inline(page=0):
    rows = []
    accs = get_all_accounts()
    total = len(accs)
    pages = max(1, (total + ACC_PAGE_SIZE - 1) // ACC_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = accs[page * ACC_PAGE_SIZE : page * ACC_PAGE_SIZE + ACC_PAGE_SIZE]
    for acc in chunk:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"+{acc['phone']} | {acc['user_id']}",
                    callback_data=f"adm_sopen_{acc['id']}_{page}",
                    icon_custom_emoji_id="5276037216244624892",
                )
            ]
        )
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀",
                callback_data=f"adm_spage_{page - 1}",
                icon_custom_emoji_id="5206401524200145033",
            )
        )
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="mail_accountsnoop"))
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="▶",
                callback_data=f"adm_spage_{page + 1}",
                icon_custom_emoji_id="5206510891247371052",
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад в админку",
                callback_data="admin_req_back",
                icon_custom_emoji_id="5206510891247371052",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_session_manage_inline(account_id, page=0):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Получить код входа",
                    callback_data=f"adm_scode_{account_id}",
                    style="primary",
                    icon_custom_emoji_id="5877396173135811032",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Удалить сессию",
                    callback_data=f"adm_sdel_{account_id}",
                    style="danger",
                    icon_custom_emoji_id="5276384644739129761",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад к сессиям",
                    callback_data=f"adm_spage_{page}",
                    icon_custom_emoji_id="5206510891247371052",
                )
            ],
        ]
    )


def _admin_bc_default() -> dict:
    return {
        "text": "",
        "entities_json": "[]",
        "media_path": "",
        "media_type": "",
        "buttons": [],
        "target": "all",
        "copy_from_chat_id": None,
        "copy_message_id": None,
        "panel_chat_id": None,
        "panel_message_id": None,
        "stage": "",
    }


def admin_bc_state(user_id: int) -> dict:
    st = admin_broadcast_state.get(user_id)
    if not st:
        st = _admin_bc_default()
        admin_broadcast_state[user_id] = st
    return st


def admin_bc_reset(user_id: int) -> dict:
    st = _admin_bc_default()
    admin_broadcast_state[user_id] = st
    return st


def admin_bc_has_content(st: dict) -> bool:
    return bool(
        (st.get("copy_from_chat_id") and st.get("copy_message_id"))
        or (st.get("media_path") and os.path.isfile(st.get("media_path") or ""))
        or (st.get("text") or "").strip()
    )


def admin_bc_buttons_markup(st: dict) -> InlineKeyboardMarkup | None:
    rows = []
    for item in st.get("buttons") or []:
        text = (item.get("text") or "").strip()
        url = (item.get("url") or "").strip()
        if not text or not url:
            continue
        kwargs = {"text": text, "url": url}
        style = (item.get("style") or "primary").strip()
        if style and style != "default":
            kwargs["style"] = style
        rows.append([InlineKeyboardButton(**kwargs)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def admin_broadcast_caption(user_id: int) -> str:
    st = admin_bc_state(user_id)
    text_status = "пост" if st.get("copy_message_id") else ("есть" if (st.get("text") or "").strip() else "нет")
    photo_status = "есть" if st.get("media_path") else "нет"
    target = "админам" if st.get("target") == "admins" else "всем"
    buttons = st.get("buttons") or []
    btn_lines = []
    for i, item in enumerate(buttons, 1):
        label = html.escape(str(item.get("text") or "")[:32])
        style = html.escape(str(item.get("style") or "primary"))
        btn_lines.append(f"{i}. {label} — <code>{style}</code>")
    btn_text = "\n".join(btn_lines) if btn_lines else "нет"
    return (
        "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> Рассылка сообщений</b>\n\n"
        "<i>Настройка рассылки за пару кликов.</i>\n\n"
        f"<b>• Текст/пост:</b> <code>{text_status}</code>\n"
        f"<b>• Фото:</b> <code>{photo_status}</code>\n"
        f"<b>• Кнопок:</b> <code>{len(buttons)}</code>\n"
        f"<b>• Кому:</b> <code>{target}</code>\n\n"
        f"<blockquote><b>Инлайн кнопки:</b>\n{btn_text}</blockquote>\n\n"
        "<b>Выберите действие ниже</b>"
    )


def admin_broadcast_inline(user_id: int) -> InlineKeyboardMarkup:
    st = admin_bc_state(user_id)
    all_mark = "✓ " if st.get("target") != "admins" else ""
    admins_mark = "✓ " if st.get("target") == "admins" else ""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Текст",
                    callback_data="adm_bc_text",
                    style="primary",
                    icon_custom_emoji_id="5258331647358540449",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Фото",
                    callback_data="adm_bc_photo",
                    style="primary",
                    icon_custom_emoji_id="5890744068203352126",
                ),
                InlineKeyboardButton(
                    text="Инлайн кнопка",
                    callback_data="adm_bc_buttons",
                    style="primary",
                    icon_custom_emoji_id="5884106131822875141",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Пост",
                    callback_data="adm_bc_post",
                    style="primary",
                    icon_custom_emoji_id="5875206779196935950",
                ),
                InlineKeyboardButton(
                    text="Предпросмотр",
                    callback_data="adm_bc_preview",
                    style="primary",
                    icon_custom_emoji_id="5877485980901971030",
                ),
            ],
            [
                InlineKeyboardButton(text=f"{all_mark}Всем", callback_data="adm_bc_target_all"),
                InlineKeyboardButton(text=f"{admins_mark}Админам", callback_data="adm_bc_target_admins"),
            ],
            [
                InlineKeyboardButton(
                    text="Отправить рассылку",
                    callback_data="adm_bc_send",
                    style="success",
                    icon_custom_emoji_id="5776375003280838798",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="adm_bc_cancel",
                    style="danger",
                    icon_custom_emoji_id="5258474669769497337",
                )
            ],
        ]
    )


def admin_bc_photo_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Без фото",
                    callback_data="adm_bc_no_photo",
                    style="danger",
                    icon_custom_emoji_id="5258474669769497337",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="adm_broadcast",
                    icon_custom_emoji_id="5258236805890710909",
                )
            ],
        ]
    )


def admin_bc_buttons_menu_inline(user_id: int) -> InlineKeyboardMarkup:
    st = admin_bc_state(user_id)
    rows = [
        [
            InlineKeyboardButton(
                text="Добавить кнопку",
                callback_data="adm_bc_btn_add",
                style="primary",
                icon_custom_emoji_id="5775937998948404844",
            )
        ]
    ]
    for i, item in enumerate(st.get("buttons") or []):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{i + 1}. {(item.get('text') or 'кнопка')[:32]}",
                    callback_data=f"adm_bc_btn_edit_{i}",
                    icon_custom_emoji_id="5884106131822875141",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="adm_broadcast",
                icon_custom_emoji_id="5258236805890710909",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_bc_button_manage_inline(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Изменить", callback_data=f"adm_bc_btn_change_{index}", style="primary"),
                InlineKeyboardButton(text="Стиль", callback_data=f"adm_bc_btn_style_{index}", style="primary"),
            ],
            [
                InlineKeyboardButton(text="Выше", callback_data=f"adm_bc_btn_up_{index}"),
                InlineKeyboardButton(text="Ниже", callback_data=f"adm_bc_btn_down_{index}"),
            ],
            [
                InlineKeyboardButton(text="Удалить", callback_data=f"adm_bc_btn_del_{index}", style="danger"),
            ],
            [
                InlineKeyboardButton(
                    text="Назад к кнопкам",
                    callback_data="adm_bc_buttons",
                    icon_custom_emoji_id="5258236805890710909",
                )
            ],
        ]
    )


async def admin_bc_show(bot: Bot, user_id: int) -> None:
    st = admin_bc_state(user_id)
    chat_id = st.get("panel_chat_id")
    message_id = st.get("panel_message_id")
    if chat_id and message_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=admin_broadcast_caption(user_id),
                reply_markup=admin_broadcast_inline(user_id),
                parse_mode=ParseMode.HTML,
            )
            return
        except TelegramBadRequest:
            pass
    msg = await bot.send_message(
        user_id,
        admin_broadcast_caption(user_id),
        reply_markup=admin_broadcast_inline(user_id),
        parse_mode=ParseMode.HTML,
    )
    st["panel_chat_id"] = msg.chat.id
    st["panel_message_id"] = msg.message_id


def _valid_button_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"http", "https", "tg"} and bool(parsed.netloc or parsed.scheme == "tg")


def _next_button_style(style: str) -> str:
    styles = ["primary", "success", "danger", "default"]
    try:
        return styles[(styles.index(style) + 1) % len(styles)]
    except ValueError:
        return "primary"


async def admin_bc_deliver(bot: Bot, chat_id: int, st: dict) -> None:
    reply_markup = admin_bc_buttons_markup(st)
    if st.get("copy_from_chat_id") and st.get("copy_message_id"):
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=int(st["copy_from_chat_id"]),
            message_id=int(st["copy_message_id"]),
            reply_markup=reply_markup,
        )
        return

    text = st.get("text") or ""
    entities = entities_json_to_aiogram_entities(st.get("entities_json") or "[]")
    media_path = st.get("media_path") or ""
    media_type = st.get("media_type") or "photo"
    if media_path and os.path.isfile(media_path):
        if media_type == "photo":
            await bot.send_photo(
                chat_id,
                FSInputFile(media_path),
                caption=text or None,
                caption_entities=entities or None,
                parse_mode=None,
                reply_markup=reply_markup,
            )
        elif media_type == "animation":
            await bot.send_animation(
                chat_id,
                FSInputFile(media_path),
                caption=text or None,
                caption_entities=entities or None,
                parse_mode=None,
                reply_markup=reply_markup,
            )
        else:
            await bot.send_video(
                chat_id,
                FSInputFile(media_path),
                caption=text or None,
                caption_entities=entities or None,
                parse_mode=None,
                reply_markup=reply_markup,
            )
        return

    await bot.send_message(
        chat_id,
        text,
        entities=entities or None,
        parse_mode=None,
        reply_markup=reply_markup,
    )


async def admin_bc_send_to_recipients(bot: Bot, admin_id: int) -> tuple[int, int]:
    st = admin_bc_state(admin_id)
    recipients = get_admin_broadcast_recipients(st.get("target") or "all")
    ok = 0
    fail = 0
    for uid in recipients:
        try:
            await admin_bc_deliver(bot, uid, st)
            ok += 1
        except Exception:
            fail += 1
            logger.exception("admin broadcast failed uid=%s", uid)
        await asyncio.sleep(0.04)
    return ok, fail


def required_channels_manage_inline(rows: list[dict]) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = []
    for r in rows:
        rid = int(r["id"])
        en = int(r["enabled"])
        kb.append(
            [
                InlineKeyboardButton(
                    text="Выключить" if en else "Включить",
                    callback_data=f"admin_req_to_{rid}",
                    style="danger" if en else "success",
                    icon_custom_emoji_id="5278578973595427038" if en else "5278411813468269386",
                ),
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"admin_req_rm_{rid}",
                    style="danger",
                    icon_custom_emoji_id="5276384644739129761",
                ),
            ]
        )
    kb.append(
        [
            InlineKeyboardButton(
                text="Назад в админку",
                callback_data="admin_req_back",
                icon_custom_emoji_id="5206510891247371052",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=kb)


def mail_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Мои аккаунты",
                    callback_data="mail_accounts",
                    style="primary",
                    icon_custom_emoji_id="5276037216244624892"  # 💼
                ),
                InlineKeyboardButton(
                    text="Настройки",
                    callback_data="mail_settings",
                    style="primary",
                    icon_custom_emoji_id="5276442772826515132"  # 🎨
                ),
                InlineKeyboardButton(
                    text="Начать",
                    callback_data="mail_run_start",
                    style="success",
                    icon_custom_emoji_id="5278411813468269386",  # ✅
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Остановить",
                    callback_data="mail_run_stop",
                    style="danger",
                    icon_custom_emoji_id="5278578973595427038",  # 🚫
                ),
                InlineKeyboardButton(
                    text="Логи",
                    callback_data="mail_logs",
                    style="primary",
                    icon_custom_emoji_id="5278753302023004775",  # ℹ️
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="back",
                    icon_custom_emoji_id="5206510891247371052"  # 🔽
                )
            ]
        ]
    )


def settings_mail_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Интервал",
                    callback_data="mail_set_interval",
                    style="primary",
                    icon_custom_emoji_id="5276412364458059956",  # 🕓
                ),
                InlineKeyboardButton(
                    text="Текст",
                    callback_data="mail_set_text",
                    style="primary",
                    icon_custom_emoji_id="5278528159837348960",  # 📢
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Тексты #1–5 (рандом)",
                    callback_data="mail_variants",
                    style="primary",
                    icon_custom_emoji_id="5276442772826515132",  # 🎨
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Автозапуск",
                    callback_data="mail_set_autostart",
                    style="primary",
                    icon_custom_emoji_id="5206222720416643915",  # 🔔
                ),
                InlineKeyboardButton(
                    text="Фото",
                    callback_data="mail_set_media",
                    style="primary",
                    icon_custom_emoji_id="5276442772826515132",  # 🎨
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Чаты",
                    callback_data="mail_set_chats",
                    style="primary",
                    icon_custom_emoji_id="5298668674532538341",  # 👥️
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Предпросмотр",
                    callback_data="mail_preview",
                    style="primary",
                    icon_custom_emoji_id="5276442772826515132",  # 🎨
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Аккаунты",
                    callback_data="mail_pick_accounts",
                    style="primary",
                    icon_custom_emoji_id="5275979556308674886",  # 👤
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="mail",
                    icon_custom_emoji_id="5206510891247371052",  # 🔽
                )
            ],
        ]
    )


def _mailing_parse_state(st):
    if st is None:
        return None, None, None
    if isinstance(st, dict):
        return (
            st.get("stage"),
            st.get("panel_chat_id"),
            st.get("panel_message_id"),
        )
    if isinstance(st, str):
        return st, None, None
    return None, None, None


def _set_mailing_wait(callback: CallbackQuery, stage: str) -> None:
    mailing_input_state[callback.from_user.id] = {
        "stage": stage,
        "panel_chat_id": callback.message.chat.id,
        "panel_message_id": callback.message.message_id,
    }


def mailing_settings_message_caption(user_id: int) -> str:
    cfg = mex.get_mailing_config(DB_PATH, user_id)
    iv = cfg["interval_sec"]
    ch = cfg["chats_filter"]
    selected_chats = len(mex.get_selected_chat_ids(DB_PATH, user_id))
    au = cfg["autostart_str"] or "выкл"
    vn = mex.count_filled_variants(cfg)
    return (
        "<b><tg-emoji emoji-id='5276442772826515132'>🎨</tg-emoji> Настройки рассылки</b>\n\n"
        f"<blockquote><b><tg-emoji emoji-id='5276412364458059956'>🕓</tg-emoji> Интервал: <code>{iv}</code> сек</b>\n"
        f"<b><tg-emoji emoji-id='5298668674532538341'>👥️</tg-emoji> Чаты: <code>{ch}</code></b>\n"
        f"<b><tg-emoji emoji-id='5276395476646653290'>🔍</tg-emoji> Конкретных чатов: <code>{selected_chats}</code></b>\n"
        f"<b><tg-emoji emoji-id='5206222720416643915'>🔔</tg-emoji> Автозапуск (МСК): <code>{au}</code></b>\n"
        f"<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> Варианты текста (рандом): <code>{vn}</code> / 5</b>"
        f"</blockquote>\n\n"
        "<b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Выберите раздел ниже</b>"
    )


def mail_variants_menu_caption(user_id: int) -> str:
    cfg = mex.get_mailing_config(DB_PATH, user_id)
    n = mex.count_filled_variants(cfg)
    return (
        "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> Варианты текста (рандом)</b>\n\n"
        "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> До пяти разных текстов. "
        "В каждый чат уходит случайный из заполненных слотов.</b>\n\n"
        f"<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Заполнено слотов: <code>{n}</code> / 5</b>\n"
        "<b><tg-emoji emoji-id='5276395476646653290'>🔍</tg-emoji> Если все пусты — используется обычный раздел «Текст».</b>"
        "</blockquote>\n\n"
        "<b><tg-emoji emoji-id='5276127848644503161'>🤖</tg-emoji> Нажмите номер слота ниже</b>"
    )


def mail_variants_menu_inline(user_id: int) -> InlineKeyboardMarkup:
    cfg = mex.get_mailing_config(DB_PATH, user_id)
    vars_ = mex.normalize_variants(cfg.get("body_variants_json"))

    def btn(idx: int) -> InlineKeyboardButton:
        filled = bool((vars_[idx].get("text") or "").strip())
        return InlineKeyboardButton(
            text=f"Текст #{idx + 1}",
            callback_data=f"mail_var_slot_{idx}",
            icon_custom_emoji_id=(
                "5278411813468269386" if filled else "5276395476646653290"
            ),
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(0), btn(1)],
            [btn(2), btn(3)],
            [btn(4)],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="mail_settings",
                    icon_custom_emoji_id="5206510891247371052",
                ),
            ],
        ]
    )


def mail_variant_slot_caption(user_id: int, slot: int) -> str:
    cfg = mex.get_mailing_config(DB_PATH, user_id)
    vars_ = mex.normalize_variants(cfg.get("body_variants_json"))
    cur = vars_[slot].get("text") or ""
    snip = cur.replace("\n", " ").replace("\r", "")
    if len(snip) > 140:
        snip = snip[:140] + "…"
    if not snip:
        snip = "(пусто)"
    return (
        f"<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> Текст #{slot + 1}</b>\n\n"
        "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Отправьте сообщение с форматированием Telegram — "
        "сохранится только в этом слоте.</b>\n\n"
        f"<b><tg-emoji emoji-id='5276395476646653290'>🔍</tg-emoji> Сейчас:</b> <code>{html.escape(snip)}</code>"
        "</blockquote>"
    )


def mail_variant_slot_keyboard(slot: int, filled: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if filled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Удалить текст",
                    callback_data=f"mail_var_del_{slot}",
                    style="danger",
                    icon_custom_emoji_id="5276384644739129761",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data="mail_variants",
                icon_custom_emoji_id="5206510891247371052",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _set_mailing_variant_wait(callback: CallbackQuery, slot: int) -> None:
    mailing_input_state[callback.from_user.id] = {
        "stage": "mail_w_variant",
        "variant_slot": slot,
        "panel_chat_id": callback.message.chat.id,
        "panel_message_id": callback.message.message_id,
    }


async def refresh_mail_variants_after_input(
    message: Message, panel_chat_id: int | None, panel_message_id: int | None
) -> None:
    bot = message.bot
    uid = message.from_user.id
    if panel_chat_id is not None and panel_message_id is not None:
        try:
            await bot.delete_message(panel_chat_id, panel_message_id)
        except TelegramBadRequest:
            pass
    await message.answer(
        mail_variants_menu_caption(uid),
        reply_markup=mail_variants_menu_inline(uid),
        parse_mode=ParseMode.HTML,
    )


def entities_json_to_aiogram_entities(json_str: str) -> list[MessageEntity]:
    try:
        data = json.loads(json_str or "[]")
    except json.JSONDecodeError:
        return []
    out: list[MessageEntity] = []
    for e in data:
        t = str(e.get("type") or "").lower()
        off = int(e["offset"])
        ln = int(e["length"])
        kw: dict = {"type": t, "offset": off, "length": ln}
        if t == "text_link":
            kw["url"] = e.get("url") or ""
        elif t == "custom_emoji":
            doc = e.get("document_id") if e.get("document_id") is not None else e.get("custom_emoji_id")
            if doc is not None:
                kw["custom_emoji_id"] = str(doc)
        elif t == "pre":
            kw["language"] = e.get("language") or ""
        elif t == "blockquote":
            if e.get("collapsed") is not None:
                kw["collapsed"] = bool(e["collapsed"])
        elif t == "expandable_blockquote":
            kw["type"] = "blockquote"
            kw["collapsed"] = True
        elif t == "text_mention":
            uid = int(e.get("user_id") or 0)
            if not uid:
                continue
            kw["user"] = User(id=uid, is_bot=False, first_name="User")
        out.append(MessageEntity(**kw))
    return out


async def refresh_mail_settings_after_input(
    message: Message, panel_chat_id: int | None, panel_message_id: int | None
) -> None:
    bot = message.bot
    uid = message.from_user.id
    if panel_chat_id is not None and panel_message_id is not None:
        try:
            await bot.delete_message(panel_chat_id, panel_message_id)
        except TelegramBadRequest:
            pass
    await message.answer(
        mailing_settings_message_caption(uid),
        reply_markup=settings_mail_inline(),
        parse_mode=ParseMode.HTML,
    )


def chats_filter_inline(current: str):
    def mark(name, val):
        prefix = "✓ " if current == val else ""
        return f"{prefix}{name}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=mark("Все", "all"),
                    callback_data="mail_chat_all",
                    icon_custom_emoji_id="5276111746812112286",  # ⭐️
                ),
                InlineKeyboardButton(
                    text=mark("Личные", "private"),
                    callback_data="mail_chat_private",
                    icon_custom_emoji_id="5275979556308674886",  # 👤
                ),
            ],
            [
                InlineKeyboardButton(
                    text=mark("Группы", "groups"),
                    callback_data="mail_chat_groups",
                    icon_custom_emoji_id="5298668674532538341",  # 👥️
                ),
                InlineKeyboardButton(
                    text=mark("Каналы", "channels"),
                    callback_data="mail_chat_channels",
                    icon_custom_emoji_id="5278528159837348960",  # 📢
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Выбрать конкретные чаты",
                    callback_data="mail_chat_accounts",
                    style="primary",
                    icon_custom_emoji_id="5276395476646653290",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Сбросить конкретный выбор",
                    callback_data="mail_chat_clear_selected",
                    style="danger",
                    icon_custom_emoji_id="5276384644739129761",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="mail_settings",
                    icon_custom_emoji_id="5206510891247371052",  # 🔽
                )
            ],
        ]
    )


def accounts_inline(user_id, page=0):
    rows = []
    accs = get_user_accounts(user_id)
    total = len(accs)
    pages = max(1, (total + ACC_PAGE_SIZE - 1) // ACC_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = accs[page * ACC_PAGE_SIZE : page * ACC_PAGE_SIZE + ACC_PAGE_SIZE]
    for acc in chunk:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"+{acc['phone']}",
                    callback_data=f"account_{acc['id']}",
                    icon_custom_emoji_id="5276037216244624892",  # 💼
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Добавить аккаунт",
                callback_data="add_account",
                style="primary",
                icon_custom_emoji_id="5276220667182736079",  # 📥
            )
        ]
    )
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀",
                callback_data=f"mail_acc_p_{page - 1}",
                icon_custom_emoji_id="5206401524200145033",  # 🔼
            )
        )
    nav.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{pages}",
            callback_data="mail_accountsnoop",
        )
    )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="▶",
                callback_data=f"mail_acc_p_{page + 1}",
                icon_custom_emoji_id="5206510891247371052",  # 🔽
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="mail",
                icon_custom_emoji_id="5206510891247371052",  # 🔽
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mail_select_accounts_inline(user_id, page=0):
    rows = []
    accs = get_user_accounts(user_id)
    sel = set(mex.get_selected_ids(DB_PATH, user_id))
    total = len(accs)
    pages = max(1, (total + ACC_PAGE_SIZE - 1) // ACC_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = accs[page * ACC_PAGE_SIZE : page * ACC_PAGE_SIZE + ACC_PAGE_SIZE]
    for acc in chunk:
        mark = "✓ " if acc["id"] in sel else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}+{acc['phone']}",
                    callback_data=f"msel_{acc['id']}_{page}",
                    icon_custom_emoji_id="5276037216244624892",  # 💼
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Выбрать все",
                callback_data=f"msel_all_{page}",
                style="primary",
                icon_custom_emoji_id="5278411813468269386",  # ✅
            )
        ]
    )
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀",
                callback_data=f"mail_pick_p_{page - 1}",
                icon_custom_emoji_id="5206401524200145033",
            )
        )
    nav.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{pages}",
            callback_data="mail_accountsnoop",
        )
    )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="▶",
                callback_data=f"mail_pick_p_{page + 1}",
                icon_custom_emoji_id="5206510891247371052",
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="mail_settings",
                icon_custom_emoji_id="5206510891247371052",  # 🔽
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_manage_inline(account_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить аккаунт",
                    callback_data=f"delete_account_{account_id}",
                    style="danger",
                    icon_custom_emoji_id="5276384644739129761",  # 🗑
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="mail_accounts",
                    icon_custom_emoji_id="5206510891247371052",  # 🔽
                )
            ],
        ]
    )


def account_cancel_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="mail_accounts",
                    icon_custom_emoji_id="5206510891247371052",  # 🔽
                )
            ]
        ]
    )


def chat_accounts_inline(user_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for acc in get_user_accounts(user_id):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"+{acc['phone']}",
                    callback_data=f"mchacc_{acc['id']}",
                    icon_custom_emoji_id="5276037216244624892",
                )
            ]
        )
    if not rows:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Добавить аккаунт",
                    callback_data="add_account",
                    style="primary",
                    icon_custom_emoji_id="5276220667182736079",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="mail_set_chats",
                icon_custom_emoji_id="5206510891247371052",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def chat_folders_inline(account_id: int, folders: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in folders:
        rows.append(
            [
                InlineKeyboardButton(
                    text=item["title"],
                    callback_data=f"mfold_{account_id}_{item['key']}_0",
                    icon_custom_emoji_id="5298668674532538341",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="mail_chat_accounts",
                icon_custom_emoji_id="5206510891247371052",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _account_client(account: dict) -> TelegramClient | None:
    session_path = mex.resolve_session_path(account["session_name"])
    if not session_path or not os.path.isfile(session_path + ".session"):
        return None
    client = TelegramClient(session_path, TG_API_ID, TG_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        return None
    return client


async def get_session_user_label(account: dict) -> str:
    client = await _account_client(account)
    if client is None:
        return "сессия не подключается"
    try:
        me = await client.get_me()
        username = f"@{me.username}" if getattr(me, "username", None) else "без username"
        name = " ".join(
            part for part in (getattr(me, "first_name", ""), getattr(me, "last_name", "")) if part
        ).strip()
        return f"{html.escape(name or username)} | {html.escape(username)} | ID: <code>{me.id}</code>"
    except Exception:
        logger.exception("get session user failed account_id=%s", account.get("id"))
        return "не удалось получить пользователя"
    finally:
        await client.disconnect()


async def get_latest_login_code(account: dict) -> tuple[str | None, str]:
    client = await _account_client(account)
    if client is None:
        return None, "Сессия не найдена или не авторизована"
    try:
        service = await client.get_entity(777000)
        async for msg in client.iter_messages(service, limit=10):
            text = msg.message or ""
            match = re.search(r"(?<!\d)(\d{5,6})(?!\d)", text)
            if match:
                date_text = msg.date.strftime("%Y-%m-%d %H:%M:%S UTC") if msg.date else "без даты"
                return match.group(1), date_text
        return None, "Код не найден. Сначала начните вход в Telegram с нового устройства."
    except Exception as e:
        logger.exception("get latest login code failed account_id=%s", account.get("id"))
        return None, f"Не удалось получить код: {html.escape(str(e))}"
    finally:
        await client.disconnect()


def _folder_title(folder_key: str) -> str:
    if folder_key == "archive":
        return "Архив"
    if folder_key == "main":
        return "Основные"
    if folder_key.startswith("f"):
        return f"Папка {folder_key[1:]}"
    return "Чаты"


def _dialog_type_label(dialog) -> str:
    ent = dialog.entity
    if getattr(dialog, "is_user", False):
        return "ЛС"
    if getattr(dialog, "is_channel", False) and not getattr(ent, "megagroup", False):
        return "Канал"
    return "Группа"


def _iter_dialog_filters(result) -> list:
    if result is None:
        return []
    if hasattr(result, "filters"):
        return _iter_dialog_filters(getattr(result, "filters"))
    if hasattr(result, "dialog_filters"):
        return _iter_dialog_filters(getattr(result, "dialog_filters"))
    if isinstance(result, (list, tuple, set)):
        return list(result)
    try:
        return list(result)
    except TypeError:
        if hasattr(result, "id") or hasattr(result, "title"):
            return [result]
        return []


async def load_account_folders(user_id: int, account_id: int) -> list[dict]:
    acc = get_account_by_id(account_id)
    if not acc or acc["user_id"] != user_id:
        return []
    client = await _account_client(acc)
    if client is None:
        return []
    folders = [{"key": "main", "title": "Основные"}, {"key": "archive", "title": "Архив"}]
    try:
        if GetDialogFiltersRequest is not None:
            filters_result = await client(GetDialogFiltersRequest())
            for f in _iter_dialog_filters(filters_result):
                fid = int(getattr(f, "id", 0) or 0)
                if fid <= 0:
                    continue
                title = getattr(f, "title", None) or f"Папка {fid}"
                title_text = getattr(title, "text", title)
                folders.append({"key": f"f{fid}", "title": str(title_text)})
    except Exception:
        logger.exception("load dialog folders failed account_id=%s", account_id)
    finally:
        await client.disconnect()
    return folders


async def load_account_dialogs(
    user_id: int,
    account_id: int,
    folder_key: str,
    query: str = "",
    limit: int = 120,
) -> list[dict]:
    acc = get_account_by_id(account_id)
    if not acc or acc["user_id"] != user_id:
        return []
    client = await _account_client(acc)
    if client is None:
        return []
    out: list[dict] = []
    q = (query or "").strip().lower()
    try:
        kwargs: dict[str, Any] = {}
        wanted_folder_id: int | None = None
        if folder_key == "archive":
            kwargs["archived"] = True
        elif folder_key.startswith("f") and folder_key[1:].isdigit():
            kwargs["archived"] = False
            wanted_folder_id = int(folder_key[1:])
        else:
            kwargs["archived"] = False
        try:
            iterator = client.iter_dialogs(**kwargs)
        except TypeError:
            iterator = client.iter_dialogs(archived=(folder_key == "archive"))
        async for dialog in iterator:
            if wanted_folder_id is not None:
                dialog_folder_id = getattr(dialog, "folder_id", None)
                if dialog_folder_id is None:
                    dialog_folder_id = getattr(getattr(dialog, "dialog", None), "folder_id", None)
                if int(dialog_folder_id or 0) != wanted_folder_id:
                    continue
            name = (getattr(dialog, "name", None) or "").strip() or "Без названия"
            if q and q not in name.lower():
                continue
            peer_id = tl_utils.get_peer_id(dialog.entity)
            out.append(
                {
                    "peer_id": int(peer_id),
                    "name": name,
                    "type": _dialog_type_label(dialog),
                }
            )
            if len(out) >= limit:
                break
    except Exception:
        logger.exception("load dialogs failed account_id=%s folder=%s", account_id, folder_key)
    finally:
        await client.disconnect()
    return out


def chat_picker_inline(
    user_id: int,
    account_id: int,
    folder_key: str,
    page: int,
    dialogs: list[dict],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    selected = set(mex.get_selected_chat_ids(DB_PATH, user_id))
    pages = max(1, (len(dialogs) + CHAT_PAGE_SIZE - 1) // CHAT_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = dialogs[page * CHAT_PAGE_SIZE : page * CHAT_PAGE_SIZE + CHAT_PAGE_SIZE]
    for item in chunk:
        mark = "✓ " if item["peer_id"] in selected else ""
        name = item["name"]
        if len(name) > 34:
            name = name[:31] + "..."
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{name} · {item['type']}",
                    callback_data=f"mtog_{item['peer_id']}",
                    icon_custom_emoji_id="5278411813468269386" if item["peer_id"] in selected else "5298668674532538341",
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"mpage_{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="mail_accountsnoop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"mpage_{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(text="Поиск", callback_data="msearch", style="primary"),
            InlineKeyboardButton(text="Сбросить выбор", callback_data="mclear", style="danger"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="Папки",
                callback_data=f"mchacc_{account_id}",
                icon_custom_emoji_id="5298668674532538341",
            ),
            InlineKeyboardButton(
                text="Назад",
                callback_data="mail_set_chats",
                icon_custom_emoji_id="5206510891247371052",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def edit_chat_picker(
    bot: Bot,
    chat_id: int,
    message_id: int,
    user_id: int,
    account_id: int,
    folder_key: str,
    page: int = 0,
    query: str = "",
) -> None:
    dialogs = await load_account_dialogs(user_id, account_id, folder_key, query=query)
    selected_count = len(mex.get_selected_chat_ids(DB_PATH, user_id))
    acc = get_account_by_id(account_id)
    phone = acc["phone"] if acc else "?"
    mailing_input_state[user_id] = {
        "stage": "mail_chat_browse",
        "account_id": account_id,
        "folder_key": folder_key,
        "query": query,
        "page": page,
        "panel_chat_id": chat_id,
        "panel_message_id": message_id,
    }
    caption = (
        "<b><tg-emoji emoji-id='5298668674532538341'>👥️</tg-emoji> Выбор чатов</b>\n\n"
        f"<blockquote><b>Аккаунт: +{html.escape(str(phone))}</b>\n"
        f"<b>Папка: <code>{html.escape(_folder_title(folder_key))}</code></b>\n"
        f"<b>Найдено: <code>{len(dialogs)}</code></b>\n"
        f"<b>Выбрано всего: <code>{selected_count}</code></b>"
        + (f"\n<b>Поиск: <code>{html.escape(query)}</code></b>" if query else "")
        + "</blockquote>"
    )
    await bot.edit_message_caption(
        chat_id=chat_id,
        message_id=message_id,
        caption=caption,
        reply_markup=chat_picker_inline(user_id, account_id, folder_key, page, dialogs),
        parse_mode=ParseMode.HTML,
    )


def mail_settings_cancel_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="mail_settings",
                    icon_custom_emoji_id="5206510891247371052",  # 🔽
                )
            ]
        ]
    )

# 🔘 INLINE ПОПОЛНЕНИЕ
def deposit_inline():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="XRocket",
                    callback_data="deposit_xrocket",
                    style="primary",
                    icon_custom_emoji_id=XROCKET_EMOJI_ID
                ),
            ],
            [
                InlineKeyboardButton(
                    text="CryptoBot",
                    callback_data="deposit_cryptobot",
                    style="primary",
                    icon_custom_emoji_id="5429181348994648222"  # 👛
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="profile",
                    icon_custom_emoji_id="5206510891247371052"  # 🔽
                ),
            ],
        ]
    )

# 🔘 INLINE TONKEEPER
def tonkeeper_inline(pay_url=None, show_enter_amount=True):
    rows = []
    if show_enter_amount:
        rows.append([
            InlineKeyboardButton(
                text="Ввести сумму (USDT)",
                callback_data="enter_tonkeeper_amount",
                style="primary",
                icon_custom_emoji_id="5255933397750014894"  # 💱
            )
        ])
    if pay_url:
        rows.append([
            InlineKeyboardButton(
                text="Оплатить через Tonkeeper",
                url=pay_url,
                icon_custom_emoji_id="5193179982775476271"  # 🪙
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text="Проверить платеж",
                callback_data="check_tonkeeper_payment",
                style="success",
                icon_custom_emoji_id="5278411813468269386"  # ✅
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="deposit",
            icon_custom_emoji_id="5206510891247371052"  # 🔽
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def xrocket_inline(invoice_url=None, show_enter_amount=True):
    rows = []
    if show_enter_amount:
        rows.append([
            InlineKeyboardButton(
                text="Ввести сумму (USDT)",
                callback_data="enter_xrocket_amount",
                style="primary",
                icon_custom_emoji_id="5255933397750014894"  # 💱
            )
        ])
    if invoice_url:
        rows.append([
            InlineKeyboardButton(
                text="Оплатить через XRocket",
                url=invoice_url,
                icon_custom_emoji_id=XROCKET_EMOJI_ID
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text="Проверить платеж",
                callback_data="check_xrocket_payment",
                style="success",
                icon_custom_emoji_id="5278411813468269386"  # ✅
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="deposit",
            icon_custom_emoji_id="5206510891247371052"  # 🔽
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# 🔘 INLINE CRYPTOBOT
def cryptobot_inline(invoice_url=None, show_enter_amount=True):
    rows = []
    if show_enter_amount:
        rows.append([
            InlineKeyboardButton(
                text="Ввести сумму (USDT)",
                callback_data="enter_cryptobot_amount",
                style="primary",
                icon_custom_emoji_id="5255933397750014894"  # 💱
            )
        ])
    if invoice_url:
        rows.append([
            InlineKeyboardButton(
                text="Оплатить счет",
                url=invoice_url,
                icon_custom_emoji_id="5255933397750014894"  # 💱
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text="Проверить платеж",
                callback_data="check_cryptobot_payment",
                style="success",
                icon_custom_emoji_id="5278411813468269386"  # ✅
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="deposit",
            icon_custom_emoji_id="5206510891247371052"  # 🔽
        )
    ])
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def crypto_headers():
    return {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}


def xrocket_headers():
    return {"Rocket-Pay-Key": XROCKET_PAY_TOKEN}


def _xrocket_error_text(api_data):
    if not isinstance(api_data, dict):
        return "unknown_error"
    if api_data.get("message"):
        return str(api_data.get("message"))
    err = api_data.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("name") or err.get("code") or "unknown_error")
    if err:
        return str(err)
    errors = api_data.get("errors")
    if errors:
        return str(errors)
    return "unknown_error"


async def create_xrocket_invoice(user_id, amount):
    if not XROCKET_PAY_TOKEN:
        return None, "XROCKET_PAY_TOKEN is empty"
    payload = {
        "amount": round(float(amount), 9),
        "numPayments": 1,
        "currency": "USDT",
        "description": f"Great Spam top up {float(amount):.2f} USDT for {user_id}",
        "hiddenMessage": "Thank you",
        "commentsEnabled": False,
        "payload": str(user_id),
        "expiredIn": 7200,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{XROCKET_PAY_BASE_URL}/tg-invoices",
            headers=xrocket_headers(),
            json=payload,
            timeout=15,
        ) as resp:
            data = await resp.json(content_type=None)
            if 200 <= resp.status < 300 and data.get("success", True):
                invoice = data.get("data") if isinstance(data.get("data"), dict) else data
                if invoice and invoice.get("id") and invoice.get("link"):
                    return invoice, None
            return None, _xrocket_error_text(data)


async def get_xrocket_invoice(invoice_id):
    if not XROCKET_PAY_TOKEN:
        return None
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{XROCKET_PAY_BASE_URL}/tg-invoices/{invoice_id}",
            headers=xrocket_headers(),
            timeout=15,
        ) as resp:
            data = await resp.json(content_type=None)
            if not (200 <= resp.status < 300):
                return None
            return data.get("data") if isinstance(data.get("data"), dict) else data


async def create_cryptobot_invoice(user_id, rub_amount):
    def extract_error_text(api_data):
        if not isinstance(api_data, dict):
            return "unknown_error"
        err = api_data.get("error")
        if isinstance(err, dict):
            return str(
                err.get("name")
                or err.get("code")
                or err.get("message")
                or "unknown_error"
            )
        if err:
            return str(err)
        return "unknown_error"

    payload = {
        "asset": "USDT",
        "amount": f"{rub_amount:.2f}",
        "description": f"Great Spam top up {rub_amount:.2f} USDT for {user_id}",
        "payload": str(user_id),
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CRYPTO_PAY_BASE_URL}/createInvoice",
            headers=crypto_headers(),
            json=payload,
            timeout=15,
        ) as resp:
            data = await resp.json(content_type=None)
            if data.get("ok"):
                return data.get("result"), None

            fallback_payload = {
                "currency_type": "crypto",
                "asset": "USDT",
                "amount": f"{rub_amount:.2f}",
                "description": f"Great Spam top up {rub_amount:.2f} USDT for {user_id}",
                "payload": str(user_id),
            }
            async with session.post(
                f"{CRYPTO_PAY_BASE_URL}/createInvoice",
                headers=crypto_headers(),
                json=fallback_payload,
                timeout=15,
            ) as fallback_resp:
                fallback_data = await fallback_resp.json(content_type=None)
                if fallback_data.get("ok"):
                    return fallback_data.get("result"), None

            return None, f"{extract_error_text(data)} / {extract_error_text(fallback_data)}"


async def get_cryptobot_invoice(invoice_id):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{CRYPTO_PAY_BASE_URL}/getInvoices",
            headers=crypto_headers(),
            params={"invoice_ids": str(invoice_id)},
            timeout=15,
        ) as resp:
            data = await resp.json()
            if not data.get("ok"):
                return None
            items = data.get("result", {}).get("items", [])
            return items[0] if items else None


async def get_ton_rub_rate():
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{CRYPTO_PAY_BASE_URL}/getExchangeRates",
            headers=crypto_headers(),
            timeout=15,
        ) as resp:
            data = await resp.json(content_type=None)
            if not data.get("ok"):
                return None
            for item in data.get("result", []):
                source = str(item.get("source", "")).upper()
                target = str(item.get("target", "")).upper()
                rate = item.get("rate")
                try:
                    rate = float(rate)
                except (TypeError, ValueError):
                    continue
                if rate <= 0:
                    continue
                if source == "TON" and target == "USDT":
                    return rate
                if source == "USDT" and target == "TON":
                    return 1.0 / rate
    return None


def build_tonkeeper_url(wallet, amount_nanoton, comment):
    return f"https://app.tonkeeper.com/transfer/{wallet}?amount={amount_nanoton}&text={comment}"


async def find_ton_payment(comment, min_nanoton, created_after):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{TONCENTER_BASE_URL}/getTransactions",
            params={"address": TONKEEPER_WALLET, "limit": 30, "archival": "true"},
            timeout=15,
        ) as resp:
            data = await resp.json(content_type=None)
            if not data.get("ok"):
                return False

            for tx in data.get("result", []):
                try:
                    utime = int(tx.get("utime", 0))
                except (TypeError, ValueError):
                    utime = 0
                if utime < created_after:
                    continue

                in_msg = tx.get("in_msg") or {}
                msg_text = in_msg.get("message") or ""
                if not msg_text:
                    msg_data = in_msg.get("msg_data") or {}
                    msg_text = msg_data.get("text") or ""

                try:
                    value = int(in_msg.get("value", 0))
                except (TypeError, ValueError):
                    value = 0

                if msg_text == comment and value >= min_nanoton:
                    return True
    return False


async def auto_check_payment(user_id):
    # 5 минут проверки (60 * 5), шаг 5 секунд => 60 итераций
    for _ in range(60):
        await asyncio.sleep(5)
        pending = pending_invoices.get(user_id)
        if not pending:
            return
        invoice = await get_cryptobot_invoice(pending["invoice_id"])
        if invoice and invoice.get("status") == "paid":
            pending["paid"] = True
            return
    # Если за 5 минут не оплатили — удаляем счет
    pending_invoices.pop(user_id, None)


async def auto_check_xrocket_payment(user_id):
    for _ in range(60):
        await asyncio.sleep(5)
        pending = pending_xrocket_invoices.get(user_id)
        if not pending:
            return
        invoice = await get_xrocket_invoice(pending["invoice_id"])
        if invoice and invoice.get("status") == "paid":
            pending["paid"] = True
            return
        if invoice and invoice.get("status") == "expired":
            pending_xrocket_invoices.pop(user_id, None)
            return
    pending_xrocket_invoices.pop(user_id, None)


async def auto_check_ton_payment(user_id):
    for _ in range(60):
        await asyncio.sleep(5)
        pending = pending_ton_invoices.get(user_id)
        if not pending:
            return
        paid = await find_ton_payment(
            comment=pending["comment"],
            min_nanoton=pending["amount_nanoton"],
            created_after=pending["created_at"],
        )
        if paid:
            pending["paid"] = True
            return
    pending_ton_invoices.pop(user_id, None)


@dp.message(F.text == "/admin")
async def admin_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Доступ запрещен")
        return
    await message.answer(
        _admin_panel_caption(),
        reply_markup=admin_inline(),
    )


@dp.callback_query(F.data == "admin_back_main")
async def admin_back_main_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    await safe_delete_message(callback.message)
    banner = FSInputFile(DEFAULT_BANNER_PATH)
    await callback.message.answer_photo(
        photo=banner,
        caption=START_CAPTION,
        reply_markup=main_inline()
    )


def _admin_panel_caption() -> str:
    return (
        "<b><tg-emoji emoji-id='5276229330131772747'>👑</tg-emoji> Админ-панель</b>\n\n"
        "<blockquote><b>Управление пользователями и балансом</b></blockquote>"
    )


@dp.callback_query(F.data == "admin_reqadd")
async def admin_reqadd_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    mandatory_sub_admin_state[callback.from_user.id] = {"step": "chat_id"}
    await callback.answer()
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5276220667182736079'>📥</tg-emoji> Обязательная подписка — шаг 1</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Отправьте ID канала или @username</b>\n"
            "Пример: <code>-1001234567890</code> или <code>@mychannel</code></blockquote>\n\n"
            "<b><tg-emoji emoji-id='5276240711795107620'>⚠️</tg-emoji> Дальше попросим ссылку-приглашение и напомним про права бота.</b>\n\n"
            "<i>/cancel — отмена</i>"
        ),
        reply_markup=None,
    )


@dp.callback_query(F.data == "admin_reqmanage")
async def admin_reqmanage_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    rows = list_all_required_channels()
    await callback.answer()
    if not rows:
        await safe_edit_text(
            callback.message,
            text=(
                "<b><tg-emoji emoji-id='5276442772826515132'>🎨</tg-emoji> Обязательные каналы</b>\n\n"
                "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Список пуст — нажмите «Добавить оп» в админке.</b></blockquote>"
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Назад в админку",
                            callback_data="admin_req_back",
                            icon_custom_emoji_id="5206510891247371052",
                        ),
                    ]
                ]
            ),
        )
        return
    lines = [
        "<b><tg-emoji emoji-id='5276442772826515132'>🎨</tg-emoji> Обязательные каналы</b>\n\n",
        "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Вкл/Выкл и удаление. "
        "Выключенный канал не проверяется у пользователей.</b></blockquote>\n\n",
    ]
    for r in rows:
        st = "✅" if int(r["enabled"]) else "⏸"
        cid = html.escape(str(r["chat_id"]))
        lines.append(f"{st} <code>{cid}</code>\n")
    await safe_edit_text(
        callback.message,
        text="".join(lines),
        reply_markup=required_channels_manage_inline(rows),
    )


@dp.callback_query(F.data == "admin_req_back")
async def admin_req_back_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    mandatory_sub_admin_state.pop(callback.from_user.id, None)
    await callback.answer()
    await safe_edit_text(
        callback.message,
        text=_admin_panel_caption(),
        reply_markup=admin_inline(),
    )


@dp.callback_query(F.data.startswith("admin_req_to_"))
async def admin_req_toggle_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    try:
        rid = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    toggle_required_channel_row(rid)
    await callback.answer("Сохранено")
    rows = list_all_required_channels()
    if not rows:
        await safe_edit_text(
            callback.message,
            text=(
                "<b><tg-emoji emoji-id='5276442772826515132'>🎨</tg-emoji> Обязательные каналы</b>\n\n"
                "<blockquote>Список пуст.</blockquote>"
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Назад в админку",
                            callback_data="admin_req_back",
                            icon_custom_emoji_id="5206510891247371052",
                        ),
                    ]
                ]
            ),
        )
        return
    lines = [
        "<b><tg-emoji emoji-id='5276442772826515132'>🎨</tg-emoji> Обязательные каналы</b>\n\n",
        "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Вкл/Выкл и удаление.</b></blockquote>\n\n",
    ]
    for r in rows:
        st = "✅" if int(r["enabled"]) else "⏸"
        cid = html.escape(str(r["chat_id"]))
        lines.append(f"{st} <code>{cid}</code>\n")
    await safe_edit_text(
        callback.message,
        text="".join(lines),
        reply_markup=required_channels_manage_inline(rows),
    )


@dp.callback_query(F.data.startswith("admin_req_rm_"))
async def admin_req_delete_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    try:
        rid = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    delete_required_channel_row(rid)
    await callback.answer("Удалено")
    rows = list_all_required_channels()
    if not rows:
        await safe_edit_text(
            callback.message,
            text=(
                "<b><tg-emoji emoji-id='5276442772826515132'>🎨</tg-emoji> Обязательные каналы</b>\n\n"
                "<blockquote>Список пуст.</blockquote>"
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Назад в админку",
                            callback_data="admin_req_back",
                            icon_custom_emoji_id="5206510891247371052",
                        ),
                    ]
                ]
            ),
        )
        return
    lines = [
        "<b><tg-emoji emoji-id='5276442772826515132'>🎨</tg-emoji> Обязательные каналы</b>\n\n",
        "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Вкл/Выкл и удаление.</b></blockquote>\n\n",
    ]
    for r in rows:
        st = "✅" if int(r["enabled"]) else "⏸"
        cid = html.escape(str(r["chat_id"]))
        lines.append(f"{st} <code>{cid}</code>\n")
    await safe_edit_text(
        callback.message,
        text="".join(lines),
        reply_markup=required_channels_manage_inline(rows),
    )


@dp.callback_query(F.data == "adm_sessions")
async def admin_sessions_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    total = len(get_all_accounts())
    await callback.answer()
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5276037216244624892'>💼</tg-emoji> Управление сессиями</b>\n\n"
            f"<blockquote><b>Всего сессий: <code>{total}</code></b>\n"
            "<b>Выберите сессию для управления.</b></blockquote>"
        ),
        reply_markup=admin_sessions_inline(0),
    )


@dp.callback_query(F.data.startswith("adm_spage_"))
async def admin_sessions_page_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    try:
        page = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        page = 0
    total = len(get_all_accounts())
    await callback.answer()
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5276037216244624892'>💼</tg-emoji> Управление сессиями</b>\n\n"
            f"<blockquote><b>Всего сессий: <code>{total}</code></b>\n"
            "<b>Выберите сессию для управления.</b></blockquote>"
        ),
        reply_markup=admin_sessions_inline(page),
    )


@dp.callback_query(F.data.startswith("adm_sopen_"))
async def admin_session_open_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    try:
        _, _, raw_account_id, raw_page = callback.data.split("_", 3)
        account_id = int(raw_account_id)
        page = int(raw_page)
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    acc = get_account_by_id(account_id)
    if not acc:
        await callback.answer("Сессия не найдена", show_alert=True)
        return
    session_user = await get_session_user_label(acc)
    session_file = html.escape(f"{acc['session_name']}.session")
    await callback.answer()
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5276037216244624892'>💼</tg-emoji> Сессия</b>\n\n"
            f"<blockquote><b>Владелец: <code>{acc['user_id']}</code></b>\n"
            f"<b>Номер: +{html.escape(str(acc['phone']))}</b>\n"
            f"<b>Юзер сессии: {session_user}</b>\n"
            f"<b>Файл: <code>{session_file}</code></b></blockquote>"
        ),
        reply_markup=admin_session_manage_inline(account_id, page),
    )


@dp.callback_query(F.data.startswith("adm_scode_"))
async def admin_session_code_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    account_id = int(callback.data.rsplit("_", 1)[-1])
    acc = get_account_by_id(account_id)
    if not acc:
        await callback.answer("Сессия не найдена", show_alert=True)
        return
    await callback.answer("Проверяю сообщения Telegram...", show_alert=False)
    code, detail = await get_latest_login_code(acc)
    if not code:
        await callback.message.answer(
            "<b><tg-emoji emoji-id='5276240711795107620'>⚠️</tg-emoji> Код входа не найден</b>\n\n"
            f"<blockquote><b>{detail}</b></blockquote>"
        )
        return
    await callback.message.answer(
        "<b><tg-emoji emoji-id='5877396173135811032'>⌨</tg-emoji> Код входа Telegram</b>\n\n"
        f"<blockquote><b>Сессия: +{html.escape(str(acc['phone']))}</b>\n"
        f"<b>Код: <code>{html.escape(code)}</code></b>\n"
        f"<b>Сообщение: <code>{html.escape(detail)}</code></b></blockquote>"
    )


@dp.callback_query(F.data.startswith("adm_sdel_"))
async def admin_session_delete_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    account_id = int(callback.data.rsplit("_", 1)[-1])
    acc = get_account_by_id(account_id)
    if not acc:
        await callback.answer("Сессия не найдена", show_alert=True)
        return
    session_file = f"{acc['session_name']}.session"
    delete_account_by_id(account_id)
    try:
        for file_path in (session_file, f"{session_file}-journal"):
            if os.path.exists(file_path):
                os.remove(file_path)
    except OSError:
        pass
    await callback.answer("Сессия удалена", show_alert=True)
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5276384644739129761'>🗑</tg-emoji> Сессия удалена</b>\n\n"
            f"<blockquote><b>Владелец: <code>{acc['user_id']}</code></b>\n"
            f"<b>Номер: +{html.escape(str(acc['phone']))}</b></blockquote>"
        ),
        reply_markup=admin_sessions_inline(0),
    )


@dp.callback_query(F.data == "adm_broadcast")
async def admin_broadcast_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    st["stage"] = ""
    st["panel_chat_id"] = callback.message.chat.id
    st["panel_message_id"] = callback.message.message_id
    await callback.answer()
    await safe_edit_text(
        callback.message,
        text=admin_broadcast_caption(callback.from_user.id),
        reply_markup=admin_broadcast_inline(callback.from_user.id),
    )


@dp.callback_query(F.data == "adm_bc_cancel")
async def admin_broadcast_cancel_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_broadcast_state.get(callback.from_user.id) or {}
    old = st.get("media_path") or ""
    if old and os.path.isfile(old):
        try:
            os.remove(old)
        except OSError:
            pass
    admin_broadcast_state.pop(callback.from_user.id, None)
    await callback.answer("Отменено", show_alert=True)
    await safe_edit_text(callback.message, text=_admin_panel_caption(), reply_markup=admin_inline())


@dp.callback_query(F.data.in_({"adm_bc_target_all", "adm_bc_target_admins"}))
async def admin_broadcast_target_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    st["target"] = "admins" if callback.data.endswith("_admins") else "all"
    await callback.answer("Сохранено")
    await safe_edit_text(
        callback.message,
        text=admin_broadcast_caption(callback.from_user.id),
        reply_markup=admin_broadcast_inline(callback.from_user.id),
    )


@dp.callback_query(F.data == "adm_bc_text")
async def admin_broadcast_text_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    st["stage"] = "wait_text"
    st["panel_chat_id"] = callback.message.chat.id
    st["panel_message_id"] = callback.message.message_id
    await callback.answer("Отправьте текст", show_alert=True)
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5258331647358540449'>✍️</tg-emoji> Текст рассылки</b>\n\n"
            "<blockquote><b>Отправьте текст с форматированием Telegram.</b>\n"
            "<b>Жирный, ссылки и premium emoji сохранятся автоматически.</b></blockquote>"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="adm_broadcast")]]
        ),
    )


@dp.callback_query(F.data == "adm_bc_post")
async def admin_broadcast_post_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    st["stage"] = "wait_post"
    st["panel_chat_id"] = callback.message.chat.id
    st["panel_message_id"] = callback.message.message_id
    await callback.answer("Пришлите или перешлите пост", show_alert=True)
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5875206779196935950'>📁</tg-emoji> Пост</b>\n\n"
            "<blockquote><b>Пришлите или перешлите готовый пост.</b>\n"
            "<b>Бот скопирует его при рассылке с тем же фото, текстом и premium emoji.</b></blockquote>"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="adm_broadcast")]]
        ),
    )


@dp.callback_query(F.data == "adm_bc_photo")
async def admin_broadcast_photo_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    st["stage"] = "wait_photo"
    st["panel_chat_id"] = callback.message.chat.id
    st["panel_message_id"] = callback.message.message_id
    await callback.answer("Отправьте фото", show_alert=True)
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5890744068203352126'>📷</tg-emoji> Фото рассылки</b>\n\n"
            "<blockquote><b>Отправьте фото.</b>\n"
            "<b>Если фото не нужно, нажмите «Без фото».</b></blockquote>"
        ),
        reply_markup=admin_bc_photo_inline(),
    )


@dp.callback_query(F.data == "adm_bc_no_photo")
async def admin_broadcast_no_photo_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    old = st.get("media_path") or ""
    if old and os.path.isfile(old):
        try:
            os.remove(old)
        except OSError:
            pass
    st["media_path"] = ""
    st["media_type"] = ""
    st["copy_from_chat_id"] = None
    st["copy_message_id"] = None
    st["stage"] = ""
    await callback.answer("Фото убрано")
    await safe_edit_text(
        callback.message,
        text=admin_broadcast_caption(callback.from_user.id),
        reply_markup=admin_broadcast_inline(callback.from_user.id),
    )


@dp.callback_query(F.data == "adm_bc_buttons")
async def admin_broadcast_buttons_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    await callback.answer()
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5884106131822875141'>👆</tg-emoji> Инлайн кнопки</b>\n\n"
            "<blockquote><b>Добавляйте кнопки со ссылками, меняйте стиль и порядок.</b></blockquote>"
        ),
        reply_markup=admin_bc_buttons_menu_inline(callback.from_user.id),
    )


@dp.callback_query(F.data == "adm_bc_btn_add")
async def admin_broadcast_button_add_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    st["stage"] = "wait_button"
    st["panel_chat_id"] = callback.message.chat.id
    st["panel_message_id"] = callback.message.message_id
    await callback.answer("Отправьте текст и ссылку", show_alert=True)
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5775937998948404844'>➕</tg-emoji> Новая кнопка</b>\n\n"
            "<blockquote><b>Отправьте одной строкой:</b>\n"
            "<code>Текст кнопки | https://example.com</code></blockquote>"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data="adm_bc_buttons")]]
        ),
    )


@dp.callback_query(F.data.startswith("adm_bc_btn_edit_"))
async def admin_broadcast_button_edit_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    idx = int(callback.data.rsplit("_", 1)[-1])
    buttons = admin_bc_state(callback.from_user.id).get("buttons") or []
    if idx < 0 or idx >= len(buttons):
        await callback.answer("Кнопка не найдена", show_alert=True)
        return
    item = buttons[idx]
    await callback.answer()
    await safe_edit_text(
        callback.message,
        text=(
            f"<b><tg-emoji emoji-id='5884106131822875141'>👆</tg-emoji> Кнопка #{idx + 1}</b>\n\n"
            f"<blockquote><b>Текст:</b> <code>{html.escape(item.get('text') or '')}</code>\n"
            f"<b>Ссылка:</b> <code>{html.escape(item.get('url') or '')}</code>\n"
            f"<b>Стиль:</b> <code>{html.escape(item.get('style') or 'primary')}</code></blockquote>"
        ),
        reply_markup=admin_bc_button_manage_inline(idx),
    )


@dp.callback_query(F.data.startswith("adm_bc_btn_style_"))
async def admin_broadcast_button_style_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    idx = int(callback.data.rsplit("_", 1)[-1])
    st = admin_bc_state(callback.from_user.id)
    buttons = st.get("buttons") or []
    if idx < 0 or idx >= len(buttons):
        await callback.answer("Кнопка не найдена", show_alert=True)
        return
    buttons[idx]["style"] = _next_button_style(buttons[idx].get("style") or "primary")
    await callback.answer(f"Стиль: {buttons[idx]['style']}")
    item = buttons[idx]
    await safe_edit_text(
        callback.message,
        text=(
            f"<b><tg-emoji emoji-id='5884106131822875141'>👆</tg-emoji> Кнопка #{idx + 1}</b>\n\n"
            f"<blockquote><b>Текст:</b> <code>{html.escape(item.get('text') or '')}</code>\n"
            f"<b>Ссылка:</b> <code>{html.escape(item.get('url') or '')}</code>\n"
            f"<b>Стиль:</b> <code>{html.escape(item.get('style') or 'primary')}</code></blockquote>"
        ),
        reply_markup=admin_bc_button_manage_inline(idx),
    )


@dp.callback_query(F.data.startswith("adm_bc_btn_change_"))
async def admin_broadcast_button_change_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    idx = int(callback.data.rsplit("_", 1)[-1])
    buttons = admin_bc_state(callback.from_user.id).get("buttons") or []
    if idx < 0 or idx >= len(buttons):
        await callback.answer("Кнопка не найдена", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    st["stage"] = "wait_button_edit"
    st["edit_button_index"] = idx
    st["panel_chat_id"] = callback.message.chat.id
    st["panel_message_id"] = callback.message.message_id
    await callback.answer("Отправьте новый текст и ссылку", show_alert=True)
    await safe_edit_text(
        callback.message,
        text=(
            f"<b><tg-emoji emoji-id='5258331647358540449'>✍️</tg-emoji> Изменить кнопку #{idx + 1}</b>\n\n"
            "<blockquote><b>Отправьте одной строкой:</b>\n"
            "<code>Новый текст | https://example.com</code></blockquote>"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Назад к кнопкам", callback_data="adm_bc_buttons")]]
        ),
    )


@dp.callback_query(F.data.startswith("adm_bc_btn_del_"))
async def admin_broadcast_button_delete_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    idx = int(callback.data.rsplit("_", 1)[-1])
    buttons = admin_bc_state(callback.from_user.id).get("buttons") or []
    if 0 <= idx < len(buttons):
        buttons.pop(idx)
    await callback.answer("Удалено")
    await safe_edit_text(
        callback.message,
        text="<b><tg-emoji emoji-id='5884106131822875141'>👆</tg-emoji> Инлайн кнопки</b>",
        reply_markup=admin_bc_buttons_menu_inline(callback.from_user.id),
    )


@dp.callback_query(F.data.startswith("adm_bc_btn_up_"))
@dp.callback_query(F.data.startswith("adm_bc_btn_down_"))
async def admin_broadcast_button_move_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    idx = int(callback.data.rsplit("_", 1)[-1])
    buttons = admin_bc_state(callback.from_user.id).get("buttons") or []
    if not (0 <= idx < len(buttons)):
        await callback.answer("Кнопка не найдена", show_alert=True)
        return
    new_idx = idx - 1 if "_up_" in callback.data else idx + 1
    if 0 <= new_idx < len(buttons):
        buttons[idx], buttons[new_idx] = buttons[new_idx], buttons[idx]
        idx = new_idx
    await callback.answer("Порядок изменён")
    await safe_edit_text(
        callback.message,
        text="<b><tg-emoji emoji-id='5884106131822875141'>👆</tg-emoji> Инлайн кнопки</b>",
        reply_markup=admin_bc_buttons_menu_inline(callback.from_user.id),
    )


@dp.callback_query(F.data == "adm_bc_preview")
async def admin_broadcast_preview_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    if not admin_bc_has_content(st):
        await callback.answer("Сначала добавьте текст, фото или пост", show_alert=True)
        return
    await callback.answer("Показываю предпросмотр")
    await admin_bc_deliver(callback.bot, callback.message.chat.id, st)


@dp.callback_query(F.data == "adm_bc_send")
async def admin_broadcast_send_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    st = admin_bc_state(callback.from_user.id)
    if not admin_bc_has_content(st):
        await callback.answer("Сначала добавьте текст, фото или пост", show_alert=True)
        return
    recipients = get_admin_broadcast_recipients(st.get("target") or "all")
    if not recipients:
        await callback.answer("Получатели не найдены", show_alert=True)
        return
    await callback.answer("Рассылка запущена", show_alert=True)
    ok, fail = await admin_bc_send_to_recipients(callback.bot, callback.from_user.id)
    await callback.message.answer(
        "<b><tg-emoji emoji-id='5776375003280838798'>✅</tg-emoji> Рассылка завершена</b>\n\n"
        f"<blockquote><b>Успешно: <code>{ok}</code></b>\n"
        f"<b>Ошибок: <code>{fail}</code></b></blockquote>",
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("admin_"))
async def admin_action_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    action = callback.data.replace("admin_", "")
    prompts = {
        "ban": "Введите ID пользователя для бана:\n<code>123456789</code>",
        "unban": "Введите ID пользователя для разбана:\n<code>123456789</code>",
        "promo": "Введите промокод:\n<code>CODE 10 10</code>\nгде 10 — USDT, 10 — кол-во активаций",
        "balance": "Выдать баланс:\n<code>123456789 500</code>",
        "sub": "Выдать подписку:\n<code>123456789 1</code> (месяцы)",
    }
    mapped = {
        "ban": "ban",
        "unban": "unban",
        "promo": "promo",
        "balance": "balance",
        "sub": "sub",
    }
    key = mapped.get(action)
    if not key:
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    admin_action_state[callback.from_user.id] = {"action": key}
    await callback.answer("Ожидаю данные", show_alert=True)
    await safe_edit_text(
        callback.message,
        text=(
            "<b><tg-emoji emoji-id='5276127848644503161'>🤖</tg-emoji> Админ-действие</b>\n\n"
            f"<blockquote><b>{prompts[key]}</b></blockquote>"
        ),
        reply_markup=None,
    )


@dp.message(F.text.startswith("/promo "))
async def promo_handler(message: Message):
    if is_banned(message.from_user.id):
        return
    code = message.text.split(maxsplit=1)[1].strip().upper()
    amount = use_promo(code)
    if amount is None:
        await message.answer("Промокод недействителен")
        return
    add_balance(message.from_user.id, amount)
    await message.answer(
        f"Промокод активирован ✅\nНачислено: {amount:.2f} {BALANCE_CURRENCY}\nТекущий баланс: {get_balance(message.from_user.id):.2f} {BALANCE_CURRENCY}"
    )

# 🚀 СТАРТ
@dp.message(F.text == "/start")
async def start_handler(message: Message):
    ensure_user(message.from_user.id)
    if is_banned(message.from_user.id):
        await message.answer("<b><tg-emoji emoji-id='5278578973595427038'>🚫</tg-emoji> Вы заблокированы администратором</b>")
        return
    banner = FSInputFile(DEFAULT_BANNER_PATH)

    await message.answer_photo(
        photo=banner,
        caption=START_CAPTION,
        reply_markup=main_inline()
    )


@dp.callback_query(F.data == "mandatory_sub_check")
async def mandatory_sub_check_handler(callback: CallbackQuery):
    if is_admin(callback.from_user.id):
        await callback.answer()
        return
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    bot = callback.bot
    ok, missing = await check_mandatory_subscriptions(bot, callback.from_user.id)
    if ok:
        await callback.answer(
            "Всё отлично — добро пожаловать!",
            show_alert=True,
        )
        chat_id = callback.message.chat.id
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        banner = FSInputFile(DEFAULT_BANNER_PATH)
        await bot.send_photo(
            chat_id=chat_id,
            photo=banner,
            caption=START_CAPTION,
            reply_markup=main_inline(),
        )
        return
    await callback.answer(
        "Пока не все каналы — откройте кнопки и подпишитесь",
        show_alert=True,
    )
    caption = build_mandatory_sub_caption()
    markup = await build_mandatory_sub_keyboard(bot, missing)
    try:
        await callback.message.edit_text(
            text=caption,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
    except TelegramBadRequest:
        pass


# 👤 ПРОФИЛЬ
@dp.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    username = callback.from_user.username or "no_username"

    await safe_edit_caption(
        callback.message,
        caption=profile_text(callback.from_user.id, username),
        reply_markup=profile_inline()
    )

# 🔙 НАЗАД
@dp.callback_query(F.data == "back")
async def back_handler(callback: CallbackQuery):
    await safe_edit_caption(
        callback.message,
        caption=START_CAPTION,
        reply_markup=main_inline()
    )

# 💳 ПОПОЛНЕНИЕ
@dp.callback_query(F.data == "deposit")
async def deposit_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=DEPOSIT_CAPTION,
        reply_markup=deposit_inline()
    )

@dp.callback_query(F.data == "deposit_tonkeeper")
async def deposit_tonkeeper_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=XROCKET_CAPTION,
        reply_markup=xrocket_inline(),
    )
    await callback.answer("Tonkeeper заменён на XRocket", show_alert=True)


@dp.callback_query(F.data == "enter_tonkeeper_amount")
async def enter_tonkeeper_amount_handler(callback: CallbackQuery):
    awaiting_xrocket_amount[callback.from_user.id] = {
        "chat_id": callback.message.chat.id,
        "message_id": callback.message.message_id,
    }
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> Введите сумму пополнения в USDT</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Пример: <code>10</code> или <code>30.50</code></b></blockquote>\n\n"
            "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> После отправки суммы будет создан счёт XRocket</b>"
        ),
        reply_markup=xrocket_inline(),
    )
    await callback.answer("Отправьте сумму сообщением", show_alert=True)


@dp.callback_query(F.data == "deposit_xrocket")
async def deposit_xrocket_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=XROCKET_CAPTION,
        reply_markup=xrocket_inline(),
    )


@dp.callback_query(F.data == "enter_xrocket_amount")
async def enter_xrocket_amount_handler(callback: CallbackQuery):
    awaiting_xrocket_amount[callback.from_user.id] = {
        "chat_id": callback.message.chat.id,
        "message_id": callback.message.message_id,
    }
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> Введите сумму пополнения в USDT</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Пример: <code>10</code> или <code>30.50</code></b></blockquote>\n\n"
            "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> После отправки суммы будет создан счёт XRocket</b>"
        ),
        reply_markup=xrocket_inline(),
    )
    await callback.answer("Отправьте сумму сообщением", show_alert=True)

@dp.callback_query(F.data == "deposit_cryptobot")
async def deposit_cryptobot_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=CRYPTOBOT_CAPTION,
        reply_markup=cryptobot_inline(),
    )


@dp.callback_query(F.data == "enter_cryptobot_amount")
async def enter_cryptobot_amount_handler(callback: CallbackQuery):
    awaiting_rub_amount[callback.from_user.id] = {
        "chat_id": callback.message.chat.id,
        "message_id": callback.message.message_id,
    }
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> Введите сумму пополнения в USDT</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Пример: <code>10</code> или <code>30.50</code></b></blockquote>\n\n"
            "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> После отправки суммы будет создан инлайн-счёт CryptoBot</b>"
        ),
        reply_markup=cryptobot_inline(),
    )
    await callback.answer("Отправьте сумму сообщением", show_alert=True)


@dp.callback_query(F.data == "enter_promo")
async def enter_promo_handler(callback: CallbackQuery):
    awaiting_promo_input[callback.from_user.id] = True
    await callback.answer("Отправьте промокод сообщением", show_alert=True)
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5276422526350681413'>🎁</tg-emoji> Введите промокод</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Просто отправьте код одним сообщением</b></blockquote>"
        ),
        reply_markup=profile_inline(),
    )


async def process_mailing_text_input(message: Message) -> bool:
    uid = message.from_user.id
    st = mailing_input_state.get(uid)
    stage, pch, pmid = _mailing_parse_state(st)
    if not stage:
        return False

    if stage == "mail_w_variant":
        slot = st.get("variant_slot") if isinstance(st, dict) else None
        if slot is None:
            mailing_input_state.pop(uid, None)
            return False
        slot = int(slot)
        if not (0 <= slot < mex.VARIANTS_MAX):
            mailing_input_state.pop(uid, None)
            return True
        raw_full = message.text or message.caption or ""
        ents_direct = message.entities or message.caption_entities
        await safe_delete_message(message)
        if not raw_full.strip():
            await message.answer("Отправьте непустой текст")
            return True
        mex.set_body_variant(
            DB_PATH,
            uid,
            slot,
            raw_full,
            mex.entities_aiogram_to_json(ents_direct),
        )
        mailing_input_state.pop(uid, None)
        await refresh_mail_variants_after_input(message, pch, pmid)
        return True

    if stage == "mail_w_media":
        raw = (message.text or "").strip()
        if raw in ("0", "0️⃣"):
            await safe_delete_message(message)
            cfg = mex.get_mailing_config(DB_PATH, uid)
            default_abs = os.path.abspath(DEFAULT_MAILING_VIDEO_PATH)
            media_root = os.path.abspath(MAILING_MEDIA_DIR)
            old = (cfg.get("media_path") or "").strip()
            old_abs = os.path.abspath(old) if old else ""
            if old_abs and os.path.isfile(old_abs) and old_abs != default_abs:
                if old_abs.startswith(media_root + os.sep):
                    try:
                        os.remove(old_abs)
                    except OSError:
                        pass
            mex.set_mailing_field(
                DB_PATH,
                uid,
                media_path=default_abs,
                media_type="photo",
            )
            mailing_input_state.pop(uid, None)
            await refresh_mail_settings_after_input(message, pch, pmid)
            return True
        await message.answer(
            "Отправьте <b>фото</b>, <b>видео</b> или <b>GIF</b>. "
            "<code>0</code> — сбросить на стандартный баннер <code>media/banner.png</code>.",
            parse_mode=ParseMode.HTML,
        )
        return True

    if stage == "mail_w_interval":
        raw_txt = (message.text or "").strip()
        await safe_delete_message(message)
        try:
            sec = int(raw_txt)
        except ValueError:
            await message.answer("Укажите целое число секунд, минимум 5")
            return True
        sec = max(5, sec)
        mex.set_mailing_field(DB_PATH, uid, interval_sec=sec)
        mailing_input_state.pop(uid, None)
        await refresh_mail_settings_after_input(message, pch, pmid)
        return True

    if stage == "mail_w_text":
        raw_full = message.text or message.caption or ""
        ents_direct = message.entities or message.caption_entities
        await safe_delete_message(message)
        if not raw_full.strip():
            await message.answer("Отправьте непустой текст")
            return True
        mex.set_mailing_field(
            DB_PATH,
            uid,
            body_text=raw_full,
            body_entities_json=mex.entities_aiogram_to_json(ents_direct),
            buttons_json="",
            postbot_code="",
        )
        mailing_input_state.pop(uid, None)
        await refresh_mail_settings_after_input(message, pch, pmid)
        return True

    if stage == "mail_w_auto":
        s = (message.text or "").strip()
        await safe_delete_message(message)
        mex.set_mailing_field(DB_PATH, uid, autostart_str=s)
        mailing_input_state.pop(uid, None)
        await refresh_mail_settings_after_input(message, pch, pmid)
        return True

    if stage == "mail_chat_search":
        query = (message.text or "").strip()
        await safe_delete_message(message)
        if query in ("0", "0️⃣"):
            query = ""
        account_id = int(st.get("account_id"))
        folder_key = str(st.get("folder_key") or "main")
        if pch is None or pmid is None:
            mailing_input_state.pop(uid, None)
            return True
        await edit_chat_picker(
            message.bot,
            pch,
            pmid,
            uid,
            account_id,
            folder_key,
            0,
            query,
        )
        return True

    return False


@dp.message(
    F.content_type.in_(
        {ContentType.PHOTO, ContentType.VIDEO, ContentType.ANIMATION}
    ),
    lambda m: _mailing_parse_state(mailing_input_state.get(m.from_user.id))[0]
    == "mail_w_media",
)
async def mailing_media_upload_handler(message: Message):
    if is_banned(message.from_user.id):
        return
    await safe_delete_message(message)
    os.makedirs(MAILING_MEDIA_DIR, exist_ok=True)
    ts = int(time.time())
    uid = message.from_user.id
    if message.photo:
        path = os.path.abspath(os.path.join(MAILING_MEDIA_DIR, f"{uid}_{ts}.jpg"))
        await message.bot.download(message.photo[-1], destination=path)
        mtype = "photo"
    elif message.video:
        path = os.path.abspath(os.path.join(MAILING_MEDIA_DIR, f"{uid}_{ts}.mp4"))
        await message.bot.download(message.video, destination=path)
        mtype = "video"
    else:
        path = os.path.abspath(os.path.join(MAILING_MEDIA_DIR, f"{uid}_{ts}.gif.mp4"))
        await message.bot.download(message.animation, destination=path)
        mtype = "animation"
    old = mex.get_mailing_config(DB_PATH, uid).get("media_path")
    if old and os.path.isfile(old):
        try:
            os.remove(old)
        except OSError:
            pass
    cap = message.caption or ""
    cent = message.caption_entities
    fields = {"media_path": path, "media_type": mtype, "postbot_code": ""}
    if cap.strip():
        fields["body_text"] = cap
        fields["body_entities_json"] = mex.entities_aiogram_to_json(cent or [])
    mex.set_mailing_field(DB_PATH, uid, **fields)
    _, pch, pmid = _mailing_parse_state(mailing_input_state.pop(uid, None))
    await refresh_mail_settings_after_input(message, pch, pmid)


def _mail_text_message_filter(message: Message) -> bool:
    if is_banned(message.from_user.id):
        return False
    stage, _, _ = _mailing_parse_state(mailing_input_state.get(message.from_user.id))
    if stage not in ("mail_w_text", "mail_w_variant"):
        return False
    return bool((message.text or message.caption or "").strip())


@dp.message(_mail_text_message_filter)
async def mail_text_message_handler(message: Message):
    await process_mailing_text_input(message)


async def process_admin_broadcast_text_input(message: Message) -> bool:
    if not message.from_user or not is_admin(message.from_user.id):
        return False
    st = admin_broadcast_state.get(message.from_user.id)
    if not st or not st.get("stage"):
        return False
    stage = st.get("stage")

    if stage == "wait_button":
        raw = (message.text or "").strip()
        await safe_delete_message(message)
        if "|" not in raw:
            await message.answer("Формат: <code>Текст кнопки | https://example.com</code>")
            return True
        label, url = [part.strip() for part in raw.split("|", 1)]
        if not label or not _valid_button_url(url):
            await message.answer("Проверьте текст кнопки и ссылку. Ссылка должна начинаться с http(s):// или tg://")
            return True
        st.setdefault("buttons", []).append({"text": label, "url": url, "style": "primary"})
        st["stage"] = ""
        await admin_bc_show(message.bot, message.from_user.id)
        return True

    if stage == "wait_button_edit":
        raw = (message.text or "").strip()
        await safe_delete_message(message)
        idx = int(st.get("edit_button_index", -1))
        buttons = st.get("buttons") or []
        if not (0 <= idx < len(buttons)):
            st["stage"] = ""
            await message.answer("Кнопка не найдена")
            return True
        if "|" not in raw:
            await message.answer("Формат: <code>Текст кнопки | https://example.com</code>")
            return True
        label, url = [part.strip() for part in raw.split("|", 1)]
        if not label or not _valid_button_url(url):
            await message.answer("Проверьте текст кнопки и ссылку. Ссылка должна начинаться с http(s):// или tg://")
            return True
        buttons[idx]["text"] = label
        buttons[idx]["url"] = url
        st["stage"] = ""
        st.pop("edit_button_index", None)
        await admin_bc_show(message.bot, message.from_user.id)
        return True

    if stage == "wait_post":
        st["copy_from_chat_id"] = message.chat.id
        st["copy_message_id"] = message.message_id
        st["text"] = ""
        st["entities_json"] = "[]"
        st["media_path"] = ""
        st["media_type"] = ""
        st["stage"] = ""
        await admin_bc_show(message.bot, message.from_user.id)
        return True

    if stage == "wait_text":
        raw = message.text or message.caption or ""
        if not raw.strip():
            await message.answer("Отправьте непустой текст")
            return True
        ents = message.entities or message.caption_entities or []
        await safe_delete_message(message)
        st["text"] = raw
        st["entities_json"] = mex.entities_aiogram_to_json(ents)
        st["copy_from_chat_id"] = None
        st["copy_message_id"] = None
        st["stage"] = ""
        await admin_bc_show(message.bot, message.from_user.id)
        return True

    if stage == "wait_photo":
        await message.answer("Отправьте фото или нажмите «Без фото»")
        return True

    return False


@dp.message(
    F.content_type.in_(
        {
            ContentType.PHOTO,
            ContentType.VIDEO,
            ContentType.ANIMATION,
            ContentType.DOCUMENT,
        }
    ),
    lambda m: bool(
        m.from_user
        and
        admin_broadcast_state.get(m.from_user.id)
        and admin_broadcast_state.get(m.from_user.id, {}).get("stage") in {"wait_photo", "wait_post", "wait_text"}
    ),
)
async def admin_broadcast_media_input_handler(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    st = admin_bc_state(message.from_user.id)
    stage = st.get("stage")

    if stage == "wait_post" or stage == "wait_text":
        st["copy_from_chat_id"] = message.chat.id
        st["copy_message_id"] = message.message_id
        st["text"] = ""
        st["entities_json"] = "[]"
        st["media_path"] = ""
        st["media_type"] = ""
        st["stage"] = ""
        await admin_bc_show(message.bot, message.from_user.id)
        return

    if stage != "wait_photo":
        return
    if not message.photo:
        await message.answer("Для этого раздела пришлите именно фото или нажмите «Без фото»")
        return

    os.makedirs(ADMIN_BROADCAST_MEDIA_DIR, exist_ok=True)
    path = os.path.abspath(
        os.path.join(ADMIN_BROADCAST_MEDIA_DIR, f"{message.from_user.id}_{int(time.time())}.jpg")
    )
    await message.bot.download(message.photo[-1], destination=path)
    old = st.get("media_path") or ""
    if old and os.path.isfile(old):
        try:
            os.remove(old)
        except OSError:
            pass
    cap = message.caption or ""
    ents = message.caption_entities or []
    await safe_delete_message(message)
    st["media_path"] = path
    st["media_type"] = "photo"
    st["copy_from_chat_id"] = None
    st["copy_message_id"] = None
    if cap.strip():
        st["text"] = cap
        st["entities_json"] = mex.entities_aiogram_to_json(ents)
    st["stage"] = ""
    await admin_bc_show(message.bot, message.from_user.id)


async def handle_mandatory_sub_admin_wizard(message: Message) -> bool:
    """Обработка шагов «Добавить оп». Возвращает True, если сообщение поглощено."""
    if not message.from_user or not is_admin(message.from_user.id):
        return False
    st = mandatory_sub_admin_state.get(message.from_user.id)
    if not st:
        return False
    raw_full = (message.text or "").strip()
    await safe_delete_message(message)
    if raw_full.lower() in ("/cancel", "отмена"):
        mandatory_sub_admin_state.pop(message.from_user.id, None)
        await message.answer(
            "<b><tg-emoji emoji-id='5278578973595427038'>🚫</tg-emoji> Отменено</b>",
            reply_markup=admin_inline(),
        )
        return True
    step = st.get("step")
    if step == "chat_id":
        cid = normalize_admin_channel_id(raw_full)
        if not cid:
            await message.answer(
                "<b><tg-emoji emoji-id='5276240711795107620'>⚠️</tg-emoji> Неверный формат</b>\n\n"
                "Нужен <code>-100…</code> или <code>@username</code>"
            )
            return True
        mandatory_sub_admin_state[message.from_user.id] = {"step": "link", "chat_id": cid}
        await message.answer(
            "<b><tg-emoji emoji-id='5276220667182736079'>📥</tg-emoji> Шаг 2 — ссылка</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Пришлите приглашение, "
            "по которому пользователь сможет подписаться:</b>\n"
            "<code>https://t.me/+AbCd…</code> или <code>https://t.me/channelname</code></blockquote>\n\n"
            "<b><tg-emoji emoji-id='5276127848644503161'>🤖</tg-emoji> Добавьте этого бота администратором канала "
            "(нужна возможность проверять участников — обычно достаточно быть админом).</b>\n\n"
            "<i>/cancel — отмена</i>"
        )
        return True
    if step == "link":
        link = normalize_invite_link(raw_full)
        if not link:
            await message.answer(
                "<b><tg-emoji emoji-id='5276240711795107620'>⚠️</tg-emoji> Нужна ссылка на t.me</b>\n"
                "Например: <code>https://t.me/+invite</code>"
            )
            return True
        chat_id = st.get("chat_id")
        upsert_required_channel(chat_id, link)
        mandatory_sub_admin_state.pop(message.from_user.id, None)
        await message.answer(
            "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Канал сохранён</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5298668674532538341'>👥️</tg-emoji> ID: <code>"
            + html.escape(str(chat_id))
            + "</code></b>\n"
            "<b><tg-emoji emoji-id='5276220667182736079'>📥</tg-emoji> Ссылка: "
            + html.escape(link)
            + "</b></blockquote>\n\n"
            "<b><tg-emoji emoji-id='5276127848644503161'>🤖</tg-emoji> Убедитесь, что бот — админ канала, "
            "иначе проверка подписки не сработает.</b>",
            reply_markup=admin_inline(),
        )
        return True
    return False


@dp.message(F.text)
async def rub_amount_input_handler(message: Message):
    if is_banned(message.from_user.id):
        return

    if await process_admin_broadcast_text_input(message):
        return

    if await handle_mandatory_sub_admin_wizard(message):
        return

    if await process_mailing_text_input(message):
        return

    account_state = account_login_state.get(message.from_user.id)
    if account_state:
        stage = account_state.get("stage")

        if stage == "phone":
            raw_phone = (message.text or "").strip()
            phone = normalize_phone(raw_phone)
            if not phone:
                await message.answer(
                    "Не удалось разобрать номер. Вставьте цифры с кодом страны (5–15 цифр), например "
                    "<code>+13826002273</code>, <code>+79991234567</code>, <code>8 999 123-45-67</code>"
                )
                return

            await safe_delete_message(message)
            os.makedirs(SESSIONS_DIR, exist_ok=True)
            session_name = os.path.join(SESSIONS_DIR, f"{message.from_user.id}_{int(time.time())}")
            client = TelegramClient(session_name, TG_API_ID, TG_API_HASH)
            try:
                await client.connect()
                sent = await client.send_code_request(phone)
            except FloodWaitError as e:
                await message.answer(
                    f"Лимит запросов Telegram. Подождите <b>{e.seconds}</b> сек. и попробуйте снова."
                )
                await client.disconnect()
                account_login_state.pop(message.from_user.id, None)
                return
            except PhoneNumberFloodError:
                await message.answer(
                    "С этого номера недавно слишком много попыток входа. Подождите несколько часов или войдите через официальный Telegram."
                )
                await client.disconnect()
                account_login_state.pop(message.from_user.id, None)
                return
            except PhoneNumberInvalidError:
                await message.answer(
                    "Telegram не считает этот номер допустимым. Проверьте код страны (например Украина — <code>+380</code>, а не <code>+1 380</code>)."
                )
                await client.disconnect()
                account_login_state.pop(message.from_user.id, None)
                return
            except PhoneNumberBannedError:
                await message.answer("Этот номер заблокирован в Telegram.")
                await client.disconnect()
                account_login_state.pop(message.from_user.id, None)
                return
            except PhoneNumberAppSignupForbiddenError:
                await message.answer("Регистрация с этого номера через API запрещена. Используйте официальное приложение Telegram.")
                await client.disconnect()
                account_login_state.pop(message.from_user.id, None)
                return
            except PhoneMigrateError:
                await message.answer(
                    "Номер привязан к другому дата-центру Telegram. Попробуйте позже или войдите через официальный клиент на этом телефоне."
                )
                await client.disconnect()
                account_login_state.pop(message.from_user.id, None)
                return
            except Exception:
                logger.exception("send_code_request failed for %s", phone)
                await message.answer(
                    "Не удалось отправить код (ошибка сервера Telegram или сети). Попробуйте позже или войдите через официальный Telegram с этого номера."
                )
                await client.disconnect()
                account_login_state.pop(message.from_user.id, None)
                return

            account_login_state[message.from_user.id] = {
                "stage": "code",
                "phone": phone,
                "phone_code_hash": sent.phone_code_hash,
                "client": client,
                "session_name": session_name,
                "chat_id": account_state.get("chat_id"),
                "message_id": account_state.get("message_id"),
            }
            try:
                await message.bot.edit_message_text(
                    chat_id=account_state.get("chat_id"),
                    message_id=account_state.get("message_id"),
                    text=(
                        "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Код отправлен</b>\n\n"
                        "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Введите код в формате: <code>1-2-3-4-5</code></b></blockquote>"
                    ),
                    reply_markup=account_cancel_inline(),
                )
            except TelegramBadRequest:
                await message.answer(
                    "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Код отправлен</b>\n\n"
                    "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Введите код в формате: <code>1-2-3-4-5</code></b></blockquote>",
                    reply_markup=account_cancel_inline(),
                )
            return

        if stage == "code":
            await safe_delete_message(message)
            code = "".join(ch for ch in (message.text or "") if ch.isdigit())
            if len(code) < 4:
                await message.answer("Неверный код. Пример: 1-2-3-4-5")
                return

            client = account_state["client"]
            try:
                await client.sign_in(
                    phone=account_state["phone"],
                    code=code,
                    phone_code_hash=account_state["phone_code_hash"],
                )
                phone_clean = account_state["phone"].lstrip("+")
                add_user_account(message.from_user.id, phone_clean, account_state["session_name"])
                await message.answer("Аккаунт успешно добавлен ✅")
                await client.disconnect()
                account_login_state.pop(message.from_user.id, None)
            except SessionPasswordNeededError:
                account_state["stage"] = "password"
                try:
                    await message.bot.edit_message_text(
                        chat_id=account_state.get("chat_id"),
                        message_id=account_state.get("message_id"),
                        text=(
                            "<b><tg-emoji emoji-id='5278602437001767574'>🔓</tg-emoji> Требуется 2FA</b>\n\n"
                            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Введите пароль двухэтапной защиты</b></blockquote>"
                        ),
                        reply_markup=account_cancel_inline(),
                    )
                except TelegramBadRequest:
                    await message.answer(
                        "<b><tg-emoji emoji-id='5278602437001767574'>🔓</tg-emoji> Требуется 2FA</b>\n\n"
                        "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Введите пароль двухэтапной защиты</b></blockquote>",
                        reply_markup=account_cancel_inline(),
                    )
            except Exception:
                await message.answer("Неверный код или ошибка входа")
            return

        if stage == "password":
            await safe_delete_message(message)
            client = account_state["client"]
            try:
                await client.sign_in(password=(message.text or "").strip())
                phone_clean = account_state["phone"].lstrip("+")
                add_user_account(message.from_user.id, phone_clean, account_state["session_name"])
                await message.answer("Аккаунт успешно добавлен ✅")
            except Exception:
                try:
                    await message.bot.edit_message_text(
                        chat_id=account_state.get("chat_id"),
                        message_id=account_state.get("message_id"),
                        text=(
                            "<b><tg-emoji emoji-id='5276240711795107620'>⚠️</tg-emoji> Неверный 2FA пароль</b>\n\n"
                            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Попробуйте снова</b></blockquote>"
                        ),
                        reply_markup=account_cancel_inline(),
                    )
                except TelegramBadRequest:
                    await message.answer(
                        "<b><tg-emoji emoji-id='5276240711795107620'>⚠️</tg-emoji> Неверный 2FA пароль</b>\n\n"
                        "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Попробуйте снова</b></blockquote>",
                        reply_markup=account_cancel_inline(),
                    )
                return
            finally:
                await client.disconnect()
            account_login_state.pop(message.from_user.id, None)
            return

    if awaiting_promo_input.get(message.from_user.id):
        await safe_delete_message(message)
        code = (message.text or "").strip().upper()
        amount = use_promo(code)
        awaiting_promo_input.pop(message.from_user.id, None)
        if amount is None:
            await message.answer("Промокод недействителен")
            return
        add_balance(message.from_user.id, amount)
        await message.answer(
            f"Промокод активирован ✅\nНачислено: {amount:.2f} {BALANCE_CURRENCY}\n"
            f"Текущий баланс: {get_balance(message.from_user.id):.2f} {BALANCE_CURRENCY}"
        )
        return

    admin_state = admin_action_state.get(message.from_user.id)
    if admin_state and is_admin(message.from_user.id):
        text = (message.text or "").strip()
        await safe_delete_message(message)
        parts = text.split()
        action = admin_state.get("action")

        try:
            if action == "ban" and len(parts) == 1:
                target_id = int(parts[0])
                set_ban_status(target_id, True)
                await message.answer(
                    f"<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Пользователь забанен</b>\n"
                    f"<b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> ID: <code>{target_id}</code></b>"
                )
            elif action == "unban" and len(parts) == 1:
                target_id = int(parts[0])
                set_ban_status(target_id, False)
                await message.answer(
                    f"<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Пользователь разбанен</b>\n"
                    f"<b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> ID: <code>{target_id}</code></b>"
                )
            elif action == "promo" and len(parts) == 3:
                code = parts[0].upper()
                amount = float(parts[1])
                uses = int(parts[2])
                create_or_update_promo(code, amount, uses)
                await message.answer(
                    "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Промокод создан</b>\n"
                    f"<b><tg-emoji emoji-id='5276422526350681413'>🎁</tg-emoji> Код: <code>{code}</code></b>\n"
                    f"<b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> Сумма: {amount:.2f} {BALANCE_CURRENCY}</b>\n"
                    f"<b><tg-emoji emoji-id='5276412364458059956'>🕓</tg-emoji> Использований: {uses}</b>"
                )
            elif action == "balance" and len(parts) == 2:
                target_id = int(parts[0])
                amount = float(parts[1])
                add_balance(target_id, amount)
                await message.answer(
                    "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Баланс выдан</b>\n"
                    f"<b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> ID: <code>{target_id}</code></b>\n"
                    f"<b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> +{amount:.2f} {BALANCE_CURRENCY}</b>"
                )
            elif action == "sub" and len(parts) == 2:
                target_id = int(parts[0])
                months = int(parts[1])
                add_subscription_months(target_id, months)
                await message.answer(
                    "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Подписка выдана</b>\n"
                    f"<b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> ID: <code>{target_id}</code></b>\n"
                    f"<b><tg-emoji emoji-id='5276229330131772747'>👑</tg-emoji> Месяцев: +{months}</b>"
                )
            else:
                raise ValueError
        except Exception:
            await message.answer(
                "Неверный формат.\n"
                "Бан/Разбан: <code>user_id</code>\n"
                "Промо: <code>CODE amount uses</code>\n"
                "Баланс: <code>user_id amount</code>\n"
                "Подписка: <code>user_id months</code>"
            )
        finally:
            admin_action_state.pop(message.from_user.id, None)
        return

    pending_xrocket_input = awaiting_xrocket_amount.get(message.from_user.id)
    if pending_xrocket_input:
        await safe_delete_message(message)
        raw = (message.text or "").strip().replace(",", ".").replace(" ", "")
        try:
            rub_amount = float(raw)
        except ValueError:
            await message.answer("Введите корректную сумму в USDT, например: 10 или 30.50")
            return

        if rub_amount <= 0:
            await message.answer("Сумма должна быть больше 0")
            return

        invoice, invoice_error = await create_xrocket_invoice(message.from_user.id, rub_amount)
        if not invoice:
            await message.answer(
                "Не удалось создать счёт. Попробуйте еще раз.\n"
                f"Причина XRocket: {invoice_error}"
            )
            return

        pending_xrocket_invoices[message.from_user.id] = {
            "invoice_id": invoice["id"],
            "rub_amount": rub_amount,
            "paid": False,
        }
        awaiting_xrocket_amount.pop(message.from_user.id, None)
        asyncio.create_task(auto_check_xrocket_payment(message.from_user.id))

        try:
            await message.bot.edit_message_caption(
                chat_id=pending_xrocket_input["chat_id"],
                message_id=pending_xrocket_input["message_id"],
                caption=(
                    f"<b><tg-emoji emoji-id='5276220667182736079'>📥</tg-emoji> Счет #{invoice['id']} на {rub_amount:.2f} {BALANCE_CURRENCY} создан</b>\n\n"
                    "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Оплатите счёт XRocket и нажмите «Проверить платеж»</b></blockquote>"
                ),
                reply_markup=xrocket_inline(invoice.get("link"), show_enter_amount=False),
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        return

    pending_ton_input = awaiting_ton_rub_amount.get(message.from_user.id)
    if pending_ton_input:
        await safe_delete_message(message)
        raw = (message.text or "").strip().replace(",", ".").replace(" ", "")
        try:
            rub_amount = float(raw)
        except ValueError:
            await message.answer("Введите корректную сумму в USDT, например: 10 или 30.50")
            return

        if rub_amount <= 0:
            await message.answer("Сумма должна быть больше 0")
            return

        ton_rub_rate = await get_ton_rub_rate()
        if not ton_rub_rate:
            await message.answer("Не удалось получить курс TON/USDT. Попробуйте еще раз.")
            return

        ton_amount = round(rub_amount / ton_rub_rate, 6)
        amount_nanoton = int(ton_amount * 1_000_000_000)
        if amount_nanoton <= 0:
            await message.answer("Слишком маленькая сумма для оплаты в TON")
            return

        comment = f"BW{message.from_user.id}_{int(time.time())}"
        pay_url = build_tonkeeper_url(TONKEEPER_WALLET, amount_nanoton, comment)
        pending_ton_invoices[message.from_user.id] = {
            "comment": comment,
            "amount_nanoton": amount_nanoton,
            "rub_amount": rub_amount,
            "ton_amount": ton_amount,
            "created_at": int(time.time()) - 10,
            "paid": False,
        }
        awaiting_ton_rub_amount.pop(message.from_user.id, None)
        asyncio.create_task(auto_check_ton_payment(message.from_user.id))

        try:
            await message.bot.edit_message_caption(
                chat_id=pending_ton_input["chat_id"],
                message_id=pending_ton_input["message_id"],
                caption=(
                    f"<b><tg-emoji emoji-id='5276220667182736079'>📥</tg-emoji> Счет на {rub_amount:.2f} {BALANCE_CURRENCY} создан</b>\n\n"
                    f"<blockquote><b><tg-emoji emoji-id='5193179982775476271'>🪙</tg-emoji> К оплате: {ton_amount:.6f} TON</b>\n"
                    f"<b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Комментарий: <code>{comment}</code></b></blockquote>"
                ),
                reply_markup=tonkeeper_inline(pay_url=pay_url, show_enter_amount=False),
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        return

    pending_input = awaiting_rub_amount.get(message.from_user.id)
    if not pending_input:
        return

    await safe_delete_message(message)
    raw = (message.text or "").strip().replace(",", ".").replace(" ", "")
    try:
        rub_amount = float(raw)
    except ValueError:
        await message.answer("Введите корректную сумму в USDT, например: 10 или 30.50")
        return

    if rub_amount <= 0:
        await message.answer("Сумма должна быть больше 0")
        return

    invoice, invoice_error = await create_cryptobot_invoice(message.from_user.id, rub_amount)
    if not invoice:
        await message.answer(
            "Не удалось создать счёт. Попробуйте еще раз.\n"
            f"Причина CryptoBot: {invoice_error}"
        )
        return

    pending_invoices[message.from_user.id] = {
        "invoice_id": invoice["invoice_id"],
        "rub_amount": rub_amount,
        "paid": False,
    }
    awaiting_rub_amount.pop(message.from_user.id, None)
    asyncio.create_task(auto_check_payment(message.from_user.id))

    try:
        await message.bot.edit_message_caption(
            chat_id=pending_input["chat_id"],
            message_id=pending_input["message_id"],
            caption=(
                f"<b><tg-emoji emoji-id='5276220667182736079'>📥</tg-emoji> Счет #{invoice['invoice_id']} на {rub_amount:.2f} {BALANCE_CURRENCY} создан</b>\n\n"
                "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Оплатите счет и нажмите «Проверить платеж»</b></blockquote>"
            ),
            reply_markup=cryptobot_inline(invoice.get("pay_url"), show_enter_amount=False),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@dp.callback_query(F.data == "check_xrocket_payment")
async def check_xrocket_payment_handler(callback: CallbackQuery):
    pending = pending_xrocket_invoices.get(callback.from_user.id)
    if not pending:
        await callback.answer("Активный счет не найден", show_alert=True)
        return

    invoice = await get_xrocket_invoice(pending["invoice_id"])
    if not invoice and not pending.get("paid"):
        await callback.answer("Ошибка проверки платежа", show_alert=True)
        return

    if pending.get("paid") or invoice.get("status") == "paid":
        amount_rub = float(pending["rub_amount"])
        add_balance(callback.from_user.id, amount_rub)
        pending_xrocket_invoices.pop(callback.from_user.id, None)

        await safe_edit_caption(
            callback.message,
            caption=(
                "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Ваш баланс пополнен</b>\n\n"
                f"<blockquote><b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> Зачислено: {amount_rub:.2f} {BALANCE_CURRENCY}</b>\n"
                f"<b><tg-emoji emoji-id='5276395476646653290'>🔍</tg-emoji> Текущий баланс: {get_balance(callback.from_user.id):.2f} {BALANCE_CURRENCY}</b></blockquote>\n\n"
                "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> Средства уже доступны для использования</b>"
            ),
            reply_markup=deposit_inline(),
        )
        await callback.answer("Платеж подтвержден ✅", show_alert=True)
        return

    if invoice.get("status") == "expired":
        pending_xrocket_invoices.pop(callback.from_user.id, None)
        await callback.answer("Счет истек, создайте новый", show_alert=True)
        return

    await callback.answer("Платеж пока не найден", show_alert=True)


@dp.callback_query(F.data == "check_cryptobot_payment")
async def check_cryptobot_payment_handler(callback: CallbackQuery):
    pending = pending_invoices.get(callback.from_user.id)
    if not pending:
        await callback.answer("Активный счет не найден", show_alert=True)
        return

    invoice = await get_cryptobot_invoice(pending["invoice_id"])
    if not invoice:
        await callback.answer("Ошибка проверки платежа", show_alert=True)
        return

    if invoice.get("status") == "paid" or pending.get("paid"):
        amount_rub = float(pending["rub_amount"])
        add_balance(callback.from_user.id, amount_rub)
        pending_invoices.pop(callback.from_user.id, None)

        await safe_edit_caption(
            callback.message,
            caption=(
                "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Ваш баланс пополнен</b>\n\n"
                f"<blockquote><b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> Зачислено: {amount_rub:.2f} {BALANCE_CURRENCY}</b>\n"
                f"<b><tg-emoji emoji-id='5276395476646653290'>🔍</tg-emoji> Текущий баланс: {get_balance(callback.from_user.id):.2f} {BALANCE_CURRENCY}</b></blockquote>\n\n"
                "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> Средства уже доступны для использования</b>"
            ),
            reply_markup=deposit_inline(),
        )
        await callback.answer("Платеж подтвержден ✅", show_alert=True)
        return

    await callback.answer("Платеж пока не найден", show_alert=True)


@dp.callback_query(F.data == "check_tonkeeper_payment")
async def check_tonkeeper_payment_handler(callback: CallbackQuery):
    pending = pending_ton_invoices.get(callback.from_user.id)
    if not pending:
        await callback.answer("Активный счет не найден", show_alert=True)
        return

    paid = await find_ton_payment(
        comment=pending["comment"],
        min_nanoton=pending["amount_nanoton"],
        created_after=pending["created_at"],
    )
    if paid or pending.get("paid"):
        amount_rub = float(pending["rub_amount"])
        add_balance(callback.from_user.id, amount_rub)
        pending_ton_invoices.pop(callback.from_user.id, None)

        await safe_edit_caption(
            callback.message,
            caption=(
                "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Ваш баланс пополнен</b>\n\n"
                f"<blockquote><b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> Зачислено: {amount_rub:.2f} {BALANCE_CURRENCY}</b>\n"
                f"<b><tg-emoji emoji-id='5276395476646653290'>🔍</tg-emoji> Текущий баланс: {get_balance(callback.from_user.id):.2f} {BALANCE_CURRENCY}</b></blockquote>\n\n"
                "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> Средства уже доступны для использования</b>"
            ),
            reply_markup=deposit_inline(),
        )
        await callback.answer("Платеж подтвержден ✅", show_alert=True)
        return

    await callback.answer("Платеж пока не найден", show_alert=True)

# 📢 РАССЫЛКА
@dp.callback_query(F.data == "mail")
async def mail_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    if not is_subscription_active(callback.from_user.id):
        await callback.answer("У вас нету активной подписки...", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=MAIL_CAPTION,
        reply_markup=mail_inline()
    )


@dp.callback_query(F.data == "mail_accounts")
async def mail_accounts_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5276037216244624892'>💼</tg-emoji> Мои аккаунты</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Выберите аккаунт или добавьте новый</b></blockquote>"
        ),
        reply_markup=accounts_inline(callback.from_user.id, 0),
    )


@dp.callback_query(F.data == "add_account")
async def add_account_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    used_slots = len(get_user_accounts(callback.from_user.id))
    total_slots = get_account_slots(callback.from_user.id)
    if used_slots >= total_slots:
        await callback.answer(
            f"Лимит аккаунтов: {used_slots}/{total_slots}. Купите +5 слотов в подписках.",
            show_alert=True,
        )
        return
    account_login_state[callback.from_user.id] = {
        "stage": "phone",
        "chat_id": callback.message.chat.id,
        "message_id": callback.message.message_id,
    }
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5276220667182736079'>📥</tg-emoji> Добавление аккаунта</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Отправьте номер телефона в формате: <code>+79991234567</code></b></blockquote>"
        ),
        reply_markup=account_cancel_inline(),
    )
    await callback.answer("Ожидаю номер телефона", show_alert=True)


@dp.callback_query(F.data.startswith("account_"))
async def account_item_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    account_id = int(callback.data.split("_", 1)[1])
    acc = get_account_by_id(account_id)
    if not acc or acc["user_id"] != callback.from_user.id:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5276037216244624892'>💼</tg-emoji> Управление аккаунтом</b>\n\n"
            f"<blockquote><b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> Номер: +{acc['phone']}</b></blockquote>"
        ),
        reply_markup=account_manage_inline(account_id),
    )


@dp.callback_query(F.data.startswith("delete_account_"))
async def delete_account_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    account_id = int(callback.data.split("_", 2)[2])
    acc = get_account_by_id(account_id)
    if not acc or acc["user_id"] != callback.from_user.id:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    session_file = f"{acc['session_name']}.session"
    delete_account_by_id(account_id)
    try:
        for file_path in (session_file, f"{session_file}-journal"):
            if os.path.exists(file_path):
                os.remove(file_path)
    except OSError:
        pass
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5276384644739129761'>🗑</tg-emoji> Аккаунт удален</b>\n\n"
            f"<blockquote><b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> Номер: +{acc['phone']}</b></blockquote>"
        ),
        reply_markup=accounts_inline(callback.from_user.id, 0),
    )


@dp.callback_query(F.data == "mail_accountsnoop")
async def mail_accounts_noop_handler(callback: CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("mail_acc_p_"))
async def mail_accounts_page_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    page = int(callback.data.rsplit("_", 1)[-1])
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5276037216244624892'>💼</tg-emoji> Мои аккаунты</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Выберите аккаунт или добавьте новый</b></blockquote>"
        ),
        reply_markup=accounts_inline(callback.from_user.id, page),
    )


@dp.callback_query(F.data == "mail_settings")
async def mail_settings_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    mailing_input_state.pop(callback.from_user.id, None)
    await safe_edit_caption(
        callback.message,
        caption=mailing_settings_message_caption(callback.from_user.id),
        reply_markup=settings_mail_inline(),
    )


@dp.callback_query(F.data == "mail_set_interval")
async def mail_set_interval_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    _set_mailing_wait(callback, "mail_w_interval")
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5276412364458059956'>🕓</tg-emoji> Интервал между циклами</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Укажите секунды паузы после полного прохода по чатам</b>\n"
            "<b>Минимум <code>5</code> секунд</b></blockquote>"
        ),
        reply_markup=mail_settings_cancel_inline(),
    )
    await callback.answer("Отправьте число секунд", show_alert=True)


@dp.callback_query(F.data == "mail_set_text")
async def mail_set_text_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    _set_mailing_wait(callback, "mail_w_text")
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> Текст рассылки</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Отправьте сообщение как в Telegram: цитата, жирный, ссылки, спойлер, премиум-эмодзи — всё сохранится и уйдёт в рассылку.</b>\n\n"
            "<b><tg-emoji emoji-id='5276442772826515132'>🎨</tg-emoji> До пяти разных текстов — раздел «Тексты #1–5 (рандом)»; если слоты пусты, используется этот текст.</b></blockquote>"
        ),
        reply_markup=mail_settings_cancel_inline(),
    )
    await callback.answer("Отправьте текст", show_alert=True)


@dp.callback_query(F.data == "mail_variants")
async def mail_variants_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    mailing_input_state.pop(callback.from_user.id, None)
    await safe_edit_caption(
        callback.message,
        caption=mail_variants_menu_caption(callback.from_user.id),
        reply_markup=mail_variants_menu_inline(callback.from_user.id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("mail_var_slot_"))
async def mail_var_slot_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    uid = callback.from_user.id
    try:
        slot = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    if not (0 <= slot < mex.VARIANTS_MAX):
        await callback.answer("Неверный слот", show_alert=True)
        return
    _set_mailing_variant_wait(callback, slot)
    cfg = mex.get_mailing_config(DB_PATH, uid)
    vars_ = mex.normalize_variants(cfg.get("body_variants_json"))
    filled = bool((vars_[slot].get("text") or "").strip())
    await safe_edit_caption(
        callback.message,
        caption=mail_variant_slot_caption(uid, slot),
        reply_markup=mail_variant_slot_keyboard(slot, filled),
    )
    await callback.answer("Отправьте текст сообщением")


@dp.callback_query(F.data.startswith("mail_var_del_"))
async def mail_var_del_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    try:
        slot = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    if not (0 <= slot < mex.VARIANTS_MAX):
        await callback.answer("Неверный слот", show_alert=True)
        return
    mex.clear_body_variant(DB_PATH, callback.from_user.id, slot)
    mailing_input_state.pop(callback.from_user.id, None)
    await safe_edit_caption(
        callback.message,
        caption=mail_variants_menu_caption(callback.from_user.id),
        reply_markup=mail_variants_menu_inline(callback.from_user.id),
    )
    await callback.answer("Текст удалён")


@dp.callback_query(F.data == "mail_set_autostart")
async def mail_set_autostart_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    _set_mailing_wait(callback, "mail_w_auto")
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5206222720416643915'>🔔</tg-emoji> Автозапуск по Москве</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Время в часовом поясе <code>МСК</code></b>\n"
            "<b>• Только старт: <code>15:00</code> (с этого времени до конца дня)</b>\n"
            "<b>• Старт и стоп: <code>15:00-18:00</code></b></blockquote>\n\n"
            "<b><tg-emoji emoji-id='5278578973595427038'>🚫</tg-emoji> <code>0</code> или <code>выкл</code> — без ограничения по времени</b>"
        ),
        reply_markup=mail_settings_cancel_inline(),
    )
    await callback.answer("Отправьте время", show_alert=True)


@dp.callback_query(F.data == "mail_set_media")
async def mail_set_media_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    _set_mailing_wait(callback, "mail_w_media")
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5276442772826515132'>🎨</tg-emoji> Медиа к тексту</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Отправьте фото, GIF или видео (MP4)</b>\n"
            "<b>Подпись к медиа = текст рассылки (цитата, жирный, ссылки и т.д.).</b>\n"
            "<b>Текст из раздела «Текст» тоже сохранится, если подпись не менять.</b>\n"
        ),
        reply_markup=mail_settings_cancel_inline(),
    )
    await callback.answer("Отправьте медиа", show_alert=True)


@dp.callback_query(F.data == "mail_preview")
async def mail_preview_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    uid = callback.from_user.id
    cfg = mex.get_mailing_config(DB_PATH, uid)
    media_path = cfg.get("media_path") or ""
    resolved = mex.resolve_mailing_media_or_default(media_path)
    media_type = mex.infer_mailing_media_type(resolved, cfg.get("media_type") or "")

    vr = mex.pick_random_variant_record(cfg)
    if vr:
        raw_body, ej_raw = vr
        cap_ents = entities_json_to_aiogram_entities(ej_raw)
        text = raw_body if cap_ents else raw_body.strip()
        nvar = mex.count_filled_variants(cfg)
        preview_tag = f"случайный из {nvar} вариантов"
    else:
        raw_body = cfg.get("body_text") or ""
        cap_ents = entities_json_to_aiogram_entities(cfg.get("body_entities_json") or "[]")
        text = raw_body if cap_ents else raw_body.strip()
        preview_tag = "основной текст (раздел «Текст»)"

    if not mex.mailing_has_any_text(cfg) and not (resolved and os.path.isfile(resolved)):
        await callback.answer(
            "Нет текста и файла медиа — задайте «Текст», слоты #1–5 или «Фото»",
            show_alert=True,
        )
        return

    await callback.answer()
    chat_id = callback.message.chat.id
    bot = callback.bot
    caption = text if text else None
    if not caption:
        cap_ents = []

    try:
        if resolved and os.path.isfile(resolved):
            if media_type == "photo":
                await bot.send_photo(
                    chat_id,
                    FSInputFile(resolved),
                    caption=caption,
                    caption_entities=cap_ents or None,
                    parse_mode=None,
                )
            elif media_type == "animation":
                await bot.send_animation(
                    chat_id,
                    FSInputFile(resolved),
                    caption=caption,
                    caption_entities=cap_ents or None,
                    parse_mode=None,
                )
            else:
                await bot.send_video(
                    chat_id,
                    FSInputFile(resolved),
                    caption=caption,
                    caption_entities=cap_ents or None,
                    parse_mode=None,
                )
        elif text:
            await bot.send_message(
                chat_id,
                text,
                entities=cap_ents or None,
                parse_mode=None,
            )
        await bot.send_message(
            chat_id,
            "<b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Так увидят получатели рассылки.</b> "
            f"<b><tg-emoji emoji-id='5276395476646653290'>🔍</tg-emoji></b> "
            f"<code>{html.escape(preview_tag)}</code>",
            parse_mode=ParseMode.HTML,
        )
    except TelegramBadRequest as e:
        await bot.send_message(
            chat_id,
            f"<b>Не удалось показать предпросмотр:</b> <code>{html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )


@dp.callback_query(F.data == "mail_set_chats")
async def mail_set_chats_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    cfg = mex.get_mailing_config(DB_PATH, callback.from_user.id)
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5298668674532538341'>👥️</tg-emoji> Куда слать</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Выберите тип чатов для одного круга рассылки</b></blockquote>"
        ),
        reply_markup=chats_filter_inline(cfg["chats_filter"]),
    )


@dp.callback_query(F.data.in_({"mail_chat_all", "mail_chat_private", "mail_chat_groups", "mail_chat_channels"}))
async def mail_chat_filter_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    key = callback.data.replace("mail_chat_", "")
    mapping = {"all": "all", "private": "private", "groups": "groups", "channels": "channels"}
    if key not in mapping:
        return
    mex.set_mailing_field(DB_PATH, callback.from_user.id, chats_filter=mapping[key])
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5298668674532538341'>👥️</tg-emoji> Куда слать</b>\n\n"
            f"<blockquote><b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Выбрано: <code>{mapping[key]}</code></b></blockquote>"
        ),
        reply_markup=chats_filter_inline(mapping[key]),
    )
    await callback.answer("Сохранено")


@dp.callback_query(F.data == "mail_chat_clear_selected")
async def mail_chat_clear_selected_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    mex.clear_selected_chats(DB_PATH, callback.from_user.id)
    cfg = mex.get_mailing_config(DB_PATH, callback.from_user.id)
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5298668674532538341'>👥️</tg-emoji> Куда слать</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Конкретный выбор чатов сброшен</b></blockquote>"
        ),
        reply_markup=chats_filter_inline(cfg["chats_filter"]),
    )
    await callback.answer("Выбор очищен")


@dp.callback_query(F.data == "mail_chat_accounts")
async def mail_chat_accounts_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    mailing_input_state.pop(callback.from_user.id, None)
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> Аккаунт для выбора чатов</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Выберите аккаунт, из которого нужно посмотреть папки и чаты</b></blockquote>"
        ),
        reply_markup=chat_accounts_inline(callback.from_user.id),
    )


@dp.callback_query(F.data.startswith("mchacc_"))
async def mail_chat_account_folders_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    account_id = int(callback.data.rsplit("_", 1)[-1])
    acc = get_account_by_id(account_id)
    if not acc or acc["user_id"] != callback.from_user.id:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    await callback.answer("Загружаю папки...")
    folders = await load_account_folders(callback.from_user.id, account_id)
    if not folders:
        await callback.answer("Не удалось открыть сессию аккаунта", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5298668674532538341'>👥️</tg-emoji> Папки аккаунта</b>\n\n"
            f"<blockquote><b>Аккаунт: +{html.escape(str(acc['phone']))}</b>\n"
            "<b>Выберите папку или архив</b></blockquote>"
        ),
        reply_markup=chat_folders_inline(account_id, folders),
    )


@dp.callback_query(F.data.startswith("mfold_"))
async def mail_chat_folder_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    parts = callback.data.split("_")
    if len(parts) < 4:
        await callback.answer("Ошибка", show_alert=True)
        return
    account_id = int(parts[1])
    folder_key = parts[2]
    page = int(parts[3])
    await callback.answer("Загружаю чаты...")
    await edit_chat_picker(
        callback.bot,
        callback.message.chat.id,
        callback.message.message_id,
        callback.from_user.id,
        account_id,
        folder_key,
        page,
    )


@dp.callback_query(F.data.startswith("mpage_"))
async def mail_chat_page_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    st = mailing_input_state.get(callback.from_user.id) or {}
    if st.get("stage") != "mail_chat_browse":
        await callback.answer("Откройте выбор чатов заново", show_alert=True)
        return
    page = int(callback.data.rsplit("_", 1)[-1])
    await edit_chat_picker(
        callback.bot,
        callback.message.chat.id,
        callback.message.message_id,
        callback.from_user.id,
        int(st["account_id"]),
        str(st["folder_key"]),
        page,
        str(st.get("query") or ""),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("mtog_"))
async def mail_chat_toggle_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    st = mailing_input_state.get(callback.from_user.id) or {}
    if st.get("stage") != "mail_chat_browse":
        await callback.answer("Откройте выбор чатов заново", show_alert=True)
        return
    peer_id = int(callback.data.split("_", 1)[1])
    mex.toggle_selected_chat(DB_PATH, callback.from_user.id, peer_id)
    await edit_chat_picker(
        callback.bot,
        callback.message.chat.id,
        callback.message.message_id,
        callback.from_user.id,
        int(st["account_id"]),
        str(st["folder_key"]),
        int(st.get("page") or 0),
        str(st.get("query") or ""),
    )
    await callback.answer("Ок")


@dp.callback_query(F.data == "mclear")
async def mail_chat_picker_clear_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    st = mailing_input_state.get(callback.from_user.id) or {}
    mex.clear_selected_chats(DB_PATH, callback.from_user.id)
    if st.get("stage") == "mail_chat_browse":
        await edit_chat_picker(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            callback.from_user.id,
            int(st["account_id"]),
            str(st["folder_key"]),
            int(st.get("page") or 0),
            str(st.get("query") or ""),
        )
    await callback.answer("Выбор очищен")


@dp.callback_query(F.data == "msearch")
async def mail_chat_search_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    st = mailing_input_state.get(callback.from_user.id) or {}
    if st.get("stage") != "mail_chat_browse":
        await callback.answer("Откройте выбор чатов заново", show_alert=True)
        return
    mailing_input_state[callback.from_user.id] = {
        "stage": "mail_chat_search",
        "account_id": int(st["account_id"]),
        "folder_key": str(st["folder_key"]),
        "panel_chat_id": callback.message.chat.id,
        "panel_message_id": callback.message.message_id,
    }
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5276395476646653290'>🔍</tg-emoji> Поиск чатов</b>\n\n"
            "<blockquote><b>Отправьте часть названия чата одним сообщением.</b>\n"
            "<b><code>0</code> — показать все чаты в этой папке.</b></blockquote>"
        ),
        reply_markup=mail_settings_cancel_inline(),
    )
    await callback.answer("Введите запрос сообщением")


@dp.callback_query(F.data == "mail_pick_accounts")
async def mail_pick_accounts_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> Аккаунты для рассылки</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Нажмите номер чтобы отметить ✓</b></blockquote>"
        ),
        reply_markup=mail_select_accounts_inline(callback.from_user.id, 0),
    )


@dp.callback_query(F.data.startswith("mail_pick_p_"))
async def mail_pick_page_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    page = int(callback.data.rsplit("_", 1)[-1])
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> Аккаунты для рассылки</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Нажмите номер чтобы отметить ✓</b></blockquote>"
        ),
        reply_markup=mail_select_accounts_inline(callback.from_user.id, page),
    )


@dp.callback_query(F.data.startswith("msel_"))
async def mail_select_toggle_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    parts = callback.data.split("_")
    if parts[1] == "all":
        page = int(parts[2])
        all_ids = [a["id"] for a in get_user_accounts(callback.from_user.id)]
        mex.select_all_accounts(DB_PATH, callback.from_user.id, all_ids)
    else:
        acc_id = int(parts[1])
        page = int(parts[2])
        mex.toggle_selected_account(DB_PATH, callback.from_user.id, acc_id)
    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5275979556308674886'>👤</tg-emoji> Аккаунты для рассылки</b>\n\n"
            "<blockquote><b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Нажмите номер чтобы отметить ✓</b></blockquote>"
        ),
        reply_markup=mail_select_accounts_inline(callback.from_user.id, page),
    )
    await callback.answer("Ок")


def _acc_resolver(acc_id, owner_id):
    row = get_account_by_id(acc_id)
    if row and row["user_id"] == owner_id:
        return row
    return None


def _start_mailing_task(user_id: int) -> None:
    t = mailing_tasks.get(user_id)
    if t and not t.done():
        return

    async def log_to_user(msg: str) -> None:
        mex.mailing_log_append(user_id, msg)

    async def can_send() -> bool:
        return can_send_mailing_message(user_id)

    async def after_success() -> None:
        consume_message_credit_if_needed(user_id)

    async def runner() -> None:
        try:
            await mex.run_mailing_loop(
                DB_PATH,
                user_id,
                TG_API_ID,
                TG_API_HASH,
                _acc_resolver,
                log_fn=log_to_user,
                can_send_fn=can_send,
                after_success_fn=after_success,
            )
        except asyncio.CancelledError:
            mex.mailing_log_append(user_id, "Задача рассылки отменена (остановка).")
            raise
        except Exception as e:
            mex.mailing_log_append(user_id, f"Критическая ошибка цикла рассылки: {e!r}")
            logger.exception("mailing loop uid=%s", user_id)

    mailing_tasks[user_id] = asyncio.create_task(runner())


@dp.callback_query(F.data == "mail_run_start")
async def mail_run_start_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    uid = callback.from_user.id
    cfg = mex.get_mailing_config(DB_PATH, uid)
    resolved = mex.resolve_mailing_media_or_default(cfg.get("media_path") or "")
    has_media = bool(resolved and os.path.isfile(resolved))
    ids = mex.get_selected_ids(DB_PATH, uid)
    au = (cfg.get("autostart_str") or "").strip() or "выкл"
    nv = mex.count_filled_variants(cfg)

    if not mex.mailing_has_any_text(cfg) and not has_media:
        mex.mailing_log_append(
            uid,
            "Старт отклонён: нет ни основного текста, ни слотов #1–5, ни файла медиа (в т.ч. media/banner.png).",
        )
        await callback.answer("Сначала задайте текст, слоты #1–5 или медиа", show_alert=True)
        return
    if not ids:
        mex.mailing_log_append(uid, "Старт отклонён: не выбран ни один аккаунт в «Аккаунты».")
        await callback.answer("Выберите аккаунты в настройках", show_alert=True)
        return
    if not can_send_mailing_message(uid):
        mex.mailing_log_append(uid, "Старт отклонён: нет активного безлимита или пакета сообщений.")
        await callback.answer("Купите месячный тариф, пакет сообщений или доступ навсегда", show_alert=True)
        return

    mex.mailing_log_append(
        uid,
        f"Запуск: аккаунтов {len(ids)}, автозапуск «{au}», медиа={'да' if has_media else 'нет'}, "
        f"вариантов рандом {nv}/5, символов основного текста {len(cfg.get('body_text') or '')}.",
    )
    mex.set_running(DB_PATH, uid, True)
    _start_mailing_task(uid)
    await callback.answer("Рассылка запущена", show_alert=True)


@dp.callback_query(F.data == "mail_logs")
async def mail_logs_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    uid = callback.from_user.id
    body = mex.mailing_log_export_text(uid).encode("utf-8")
    await callback.answer()
    await callback.message.answer_document(
        BufferedInputFile(body, filename=f"mailing_log_{uid}.txt"),
        caption=(
            "<b><tg-emoji emoji-id='5278753302023004775'>ℹ️</tg-emoji> Лог рассылки</b> "
            f"(последние {mex.MAIL_LOG_MAX_LINES} строк, МСК)"
        ),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "mail_run_stop")
async def mail_run_stop_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        return
    uid = callback.from_user.id
    mex.mailing_log_append(uid, "Нажато «Остановить» — рассылка выключается.")
    mex.set_running(DB_PATH, uid, False)
    t = mailing_tasks.pop(uid, None)
    if t and not t.done():
        t.cancel()
    await callback.answer("Остановлено", show_alert=True)

# 💎 ПОДПИСКИ
@dp.callback_query(F.data == "subscriptions")
async def subscriptions_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=SUBSCRIPTIONS_CAPTION,
        reply_markup=subscriptions_inline()
    )

# ❓ ПОЧЕМУ МЫ
@dp.callback_query(F.data == "why_us")
async def why_us_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    await safe_edit_caption(
        callback.message,
        caption=WHY_US_CAPTION,
        reply_markup=why_us_inline()
    )

# 💎 ОБРАБОТЧИКИ ПОДПИСОК
@dp.callback_query(F.data.startswith("sub_"))
async def sub_purchase_handler(callback: CallbackQuery):
    if is_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы", show_alert=True)
        return
    sub_type = callback.data.split("_", 1)[1]
    tariffs = {
        "month_unlimited": {"price": 30.0, "label": "Месячный безлимит"},
        "pack100": {"price": 10.0, "label": "100 сообщений"},
        "lifetime": {"price": 100.0, "label": "Доступ навсегда"},
        "slots5": {"price": 5.0, "label": "+5 слотов аккаунтов"},
    }
    if sub_type not in tariffs:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    price = tariffs[sub_type]["price"]
    tariff_label = tariffs[sub_type]["label"]
    balance = get_balance(callback.from_user.id)

    if balance < price:
        need = price - balance
        await safe_edit_caption(
            callback.message,
            caption=(
                "<b><tg-emoji emoji-id='5276240711795107620'>⚠️</tg-emoji> Недостаточно средств на балансе</b>\n\n"
                f"<blockquote><b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> Текущий баланс: {balance:.2f} {BALANCE_CURRENCY}</b>\n"
                f"<b><tg-emoji emoji-id='5278602437001767574'>🔓</tg-emoji> Необходимо: {price:.2f} {BALANCE_CURRENCY}</b>\n"
                f"<b><tg-emoji emoji-id='5276384644739129761'>🗑</tg-emoji> Не хватает: {need:.2f} {BALANCE_CURRENCY}</b></blockquote>\n\n"
                "<b><tg-emoji emoji-id='5206626000665868017'>📚</tg-emoji> Пополните баланс и попробуйте снова</b>"
            ),
            reply_markup=subscriptions_inline(),
        )
        return

    add_balance(callback.from_user.id, -price)
    if sub_type == "month_unlimited":
        add_subscription_months(callback.from_user.id, 1)
    elif sub_type == "pack100":
        add_message_credits(callback.from_user.id, 100)
    elif sub_type == "lifetime":
        set_lifetime_access(callback.from_user.id, True)
    elif sub_type == "slots5":
        add_account_slots(callback.from_user.id, 5)

    await safe_edit_caption(
        callback.message,
        caption=(
            "<b><tg-emoji emoji-id='5278411813468269386'>✅</tg-emoji> Тариф успешно активирован</b>\n\n"
            f"<blockquote><b><tg-emoji emoji-id='5276229330131772747'>👑</tg-emoji> Тариф: {tariff_label}</b>\n"
            f"<b><tg-emoji emoji-id='5255933397750014894'>💱</tg-emoji> Списано: {price:.2f} {BALANCE_CURRENCY}</b>\n"
            f"<b><tg-emoji emoji-id='5276395476646653290'>🔍</tg-emoji> Остаток: {get_balance(callback.from_user.id):.2f} {BALANCE_CURRENCY}</b></blockquote>\n\n"
            "<b><tg-emoji emoji-id='5278528159837348960'>📢</tg-emoji> Доступ к рассылке уже открыт</b>"
        ),
        reply_markup=subscriptions_inline()
    )

async def main():
    prepare_persistent_storage()
    logger.info("Persistent data dir: %s", DATA_DIR)
    logger.info("SQLite DB path: %s", DB_PATH)
    logger.info("Sessions dir: %s", SESSIONS_DIR)
    init_db()
    dp.message.middleware(MandatorySubMiddleware())
    dp.callback_query.middleware(MandatorySubMiddleware())
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
