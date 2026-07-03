"""
Рассылка через Telethon: настройки в БД, сущности, медиа, интервал, автозапуск по МСК.
"""
from __future__ import annotations

import asyncio
import random
from collections import deque
from threading import Lock
from typing import Any
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telethon import TelegramClient, utils as tl_utils
from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import (
    ChatForbiddenError,
    ChatSendGifsForbiddenError,
    ChatWriteForbiddenError,
    SlowModeWaitError,
    UserAlreadyParticipantError,
    UserNotParticipantError,
)
try:
    from telethon.errors.rpcerrorlist import FloodPremiumWaitError
except ImportError:
    class FloodPremiumWaitError(Exception):
        pass
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import (
    Channel,
    User,
    MessageEntityBold,
    MessageEntityItalic,
    MessageEntityUnderline,
    MessageEntityStrike,
    MessageEntitySpoiler,
    MessageEntityCode,
    MessageEntityPre,
    MessageEntityTextUrl,
    MessageEntityCustomEmoji,
    MessageEntityBlockquote,
    MessageEntityMention,
    MessageEntityHashtag,
    MessageEntityCashtag,
    MessageEntityBotCommand,
    MessageEntityUrl,
    MessageEntityEmail,
    MessageEntityPhone,
    MessageEntityMentionName,
)

logger = logging.getLogger(__name__)

try:
    MSK = ZoneInfo("Europe/Moscow")
except Exception:
    # Windows без пакета tzdata: фиксированное МСК (UTC+3)
    MSK = timezone(timedelta(hours=3))

DEFAULT_INTERVAL = 60
# Пауза между чатами (сек). 0 — максимальная скорость; при FloodWait Telegram вернёт паузу сам.
MAIL_PEER_DELAY_SEC = 0.0

# Slow mode по чату: (user_id рассылки, account_id, peer_id) -> time.monotonic() до какого момента не слать
_slowmode_skip: dict[tuple[int, int, int], float] = {}

SUBSCRIBE_HINT_KEYS = (
    "подпис",
    "subscribe",
    "канал",
    "channel",
    "необходимо",
)

VARIANTS_MAX = 5

MAIL_LOG_MAX_LINES = 300
_mailing_logs: dict[int, deque[str]] = {}
_mailing_log_lock = Lock()


def mailing_log_append(user_id: int, message: str) -> None:
    """Кольцевой буфер последних MAIL_LOG_MAX_LINES строк на пользователя."""
    ts = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts} MSK] {message}"
    with _mailing_log_lock:
        _mailing_logs.setdefault(user_id, deque(maxlen=MAIL_LOG_MAX_LINES)).append(line)
    logger.info("mailing[%s] %s", user_id, message)


def mailing_log_export_text(user_id: int) -> str:
    with _mailing_log_lock:
        lines = list(_mailing_logs.get(user_id, ()))
    if not lines:
        return "(пока нет записей в логе рассылки)\n"
    return "\n".join(lines) + "\n"


def init_mailing_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mailing_config (
            user_id INTEGER PRIMARY KEY,
            body_text TEXT NOT NULL DEFAULT '',
            body_entities_json TEXT NOT NULL DEFAULT '[]',
            interval_sec INTEGER NOT NULL DEFAULT 60,
            autostart_str TEXT NOT NULL DEFAULT '',
            buttons_json TEXT NOT NULL DEFAULT '',
            chats_filter TEXT NOT NULL DEFAULT 'all',
            media_path TEXT NOT NULL DEFAULT '',
            media_type TEXT NOT NULL DEFAULT '',
            selected_account_ids TEXT NOT NULL DEFAULT '[]',
            selected_chat_ids_json TEXT NOT NULL DEFAULT '[]',
            is_running INTEGER NOT NULL DEFAULT 0,
            postbot_code TEXT NOT NULL DEFAULT '',
            body_variants_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mailing_config)").fetchall()}
    if "postbot_code" not in cols:
        conn.execute(
            "ALTER TABLE mailing_config ADD COLUMN postbot_code TEXT NOT NULL DEFAULT ''"
        )
    if "body_variants_json" not in cols:
        conn.execute(
            "ALTER TABLE mailing_config ADD COLUMN body_variants_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "selected_chat_ids_json" not in cols:
        conn.execute(
            "ALTER TABLE mailing_config ADD COLUMN selected_chat_ids_json TEXT NOT NULL DEFAULT '[]'"
        )


def _conn(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def get_mailing_config(db_path: str, user_id: int) -> dict:
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT body_text, body_entities_json, interval_sec, autostart_str, buttons_json, "
            "chats_filter, media_path, media_type, selected_account_ids, is_running, postbot_code, "
            "body_variants_json, selected_chat_ids_json "
            "FROM mailing_config WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return {
            "body_text": "",
            "body_entities_json": "[]",
            "interval_sec": DEFAULT_INTERVAL,
            "autostart_str": "",
            "buttons_json": "",
            "chats_filter": "all",
            "media_path": "",
            "media_type": "",
            "selected_account_ids": "[]",
            "selected_chat_ids_json": "[]",
            "is_running": 0,
            "postbot_code": "",
            "body_variants_json": "[]",
        }
    return {
        "body_text": row[0] or "",
        "body_entities_json": row[1] or "[]",
        "interval_sec": int(row[2] or DEFAULT_INTERVAL),
        "autostart_str": row[3] or "",
        "buttons_json": row[4] or "",
        "chats_filter": row[5] or "all",
        "media_path": row[6] or "",
        "media_type": row[7] or "",
        "selected_account_ids": row[8] or "[]",
        "selected_chat_ids_json": row[12] if len(row) > 12 and row[12] is not None else "[]",
        "is_running": int(row[9] or 0),
        "postbot_code": row[10] or "",
        "body_variants_json": row[11] if len(row) > 11 and row[11] is not None else "[]",
    }


def _upsert(db_path: str, user_id: int, **fields) -> None:
    cfg = get_mailing_config(db_path, user_id)
    cfg.update(fields)
    with _conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO mailing_config(
                user_id, body_text, body_entities_json, interval_sec, autostart_str,
                buttons_json, chats_filter, media_path, media_type, selected_account_ids, is_running,
                postbot_code, body_variants_json, selected_chat_ids_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                body_text = excluded.body_text,
                body_entities_json = excluded.body_entities_json,
                interval_sec = excluded.interval_sec,
                autostart_str = excluded.autostart_str,
                buttons_json = excluded.buttons_json,
                chats_filter = excluded.chats_filter,
                media_path = excluded.media_path,
                media_type = excluded.media_type,
                selected_account_ids = excluded.selected_account_ids,
                selected_chat_ids_json = excluded.selected_chat_ids_json,
                is_running = excluded.is_running,
                postbot_code = excluded.postbot_code,
                body_variants_json = excluded.body_variants_json
            """,
            (
                user_id,
                cfg["body_text"],
                cfg["body_entities_json"],
                cfg["interval_sec"],
                cfg["autostart_str"],
                cfg["buttons_json"],
                cfg["chats_filter"],
                cfg["media_path"],
                cfg["media_type"],
                cfg["selected_account_ids"],
                cfg["is_running"],
                cfg.get("postbot_code", "") or "",
                cfg.get("body_variants_json", "") or "[]",
                cfg.get("selected_chat_ids_json", "") or "[]",
            ),
        )
        conn.commit()


def set_mailing_field(db_path: str, user_id: int, **fields) -> None:
    _upsert(db_path, user_id, **fields)


def get_selected_ids(db_path: str, user_id: int) -> list[int]:
    raw = get_mailing_config(db_path, user_id)["selected_account_ids"]
    try:
        return [int(x) for x in json.loads(raw)]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def toggle_selected_account(db_path: str, user_id: int, account_id: int) -> None:
    ids = set(get_selected_ids(db_path, user_id))
    if account_id in ids:
        ids.discard(account_id)
    else:
        ids.add(account_id)
    set_mailing_field(db_path, user_id, selected_account_ids=json.dumps(sorted(ids)))


def select_all_accounts(db_path: str, user_id: int, all_ids: list[int]) -> None:
    set_mailing_field(db_path, user_id, selected_account_ids=json.dumps(sorted(all_ids)))


def get_selected_chat_ids(db_path: str, user_id: int) -> list[int]:
    raw = get_mailing_config(db_path, user_id).get("selected_chat_ids_json") or "[]"
    try:
        data = json.loads(raw)
        return [int(x) for x in data]
    except Exception:
        return []


def toggle_selected_chat(db_path: str, user_id: int, peer_id: int) -> None:
    ids = set(get_selected_chat_ids(db_path, user_id))
    pid = int(peer_id)
    if pid in ids:
        ids.discard(pid)
    else:
        ids.add(pid)
    set_mailing_field(
        db_path,
        user_id,
        selected_chat_ids_json=json.dumps(sorted(ids)),
    )


def clear_selected_chats(db_path: str, user_id: int) -> None:
    set_mailing_field(db_path, user_id, selected_chat_ids_json="[]")


def set_running(db_path: str, user_id: int, on: bool) -> None:
    set_mailing_field(db_path, user_id, is_running=1 if on else 0)


def normalize_variants(raw: str | None) -> list[dict[str, str]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        data = []
    if not isinstance(data, list):
        data = []
    out: list[dict[str, str]] = []
    for i in range(VARIANTS_MAX):
        if i < len(data) and isinstance(data[i], dict):
            t = str(data[i].get("text") or "")
            ej = data[i].get("entities_json")
            if isinstance(ej, (list, dict)):
                ej = json.dumps(ej, ensure_ascii=False)
            elif not isinstance(ej, str):
                ej = "[]"
            out.append({"text": t, "entities_json": ej or "[]"})
        else:
            out.append({"text": "", "entities_json": "[]"})
    return out


def variants_to_json(variants: list[dict[str, str]]) -> str:
    trim = variants[:VARIANTS_MAX]
    while len(trim) < VARIANTS_MAX:
        trim.append({"text": "", "entities_json": "[]"})
    return json.dumps(trim, ensure_ascii=False)


def count_filled_variants(cfg: dict) -> int:
    return sum(1 for v in normalize_variants(cfg.get("body_variants_json")) if (v.get("text") or "").strip())


def mailing_has_any_text(cfg: dict) -> bool:
    if (cfg.get("body_text") or "").strip():
        return True
    return count_filled_variants(cfg) > 0


def pick_random_variant_record(cfg: dict) -> tuple[str, str] | None:
    vars_ = normalize_variants(cfg.get("body_variants_json"))
    nonempty = [v for v in vars_ if (v.get("text") or "").strip()]
    if not nonempty:
        return None
    v = random.choice(nonempty)
    return v["text"], v["entities_json"]


def pick_random_mailing_payload(cfg: dict) -> tuple[str, list]:
    r = pick_random_variant_record(cfg)
    if r:
        return r[0], entities_from_json(r[1])
    return cfg.get("body_text") or "", entities_from_json(cfg.get("body_entities_json") or "[]")


def set_body_variant(
    db_path: str, user_id: int, slot: int, text: str, entities_json: str
) -> None:
    if not (0 <= slot < VARIANTS_MAX):
        return
    cfg = get_mailing_config(db_path, user_id)
    vars_ = normalize_variants(cfg.get("body_variants_json"))
    vars_[slot] = {"text": text, "entities_json": entities_json or "[]"}
    set_mailing_field(db_path, user_id, body_variants_json=variants_to_json(vars_))


def clear_body_variant(db_path: str, user_id: int, slot: int) -> None:
    set_body_variant(db_path, user_id, slot, "", "[]")


def parse_autostart(s: str) -> tuple[str | None, str | None]:
    raw = (s or "").strip()
    low = raw.lower()
    if low in ("", "0", "выкл", "off"):
        return None, None
    compact = re.sub(r"\s+", "", raw)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", compact)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}", f"{int(m.group(3)):02d}:{m.group(4)}"
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", compact)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}", None
    return None, None


def within_autostart(autostart_str: str) -> bool:
    raw = (autostart_str or "").strip()
    if not raw or raw.lower() in ("0", "выкл", "off"):
        return True
    start_s, end_s = parse_autostart(raw)
    if start_s is None:
        return True
    now = datetime.now(MSK).time()
    sh, sm = map(int, start_s.split(":"))
    start_t = datetime(2000, 1, 1, sh, sm).time()
    if end_s is None:
        end_t = datetime(2000, 1, 1, 23, 59, 59).time()
        return start_t <= now <= end_t
    eh, em = map(int, end_s.split(":"))
    end_t = datetime(2000, 1, 1, eh, em).time()
    if start_t <= end_t:
        return start_t <= now <= end_t
    return now >= start_t or now <= end_t


def entities_from_json(json_str: str) -> list:
    try:
        data = json.loads(json_str or "[]")
    except json.JSONDecodeError:
        return []
    out = []
    for e in data:
        t = str(e.get("type") or "").lower()
        off = int(e["offset"])
        ln = int(e["length"])
        if t == "bold":
            out.append(MessageEntityBold(offset=off, length=ln))
        elif t == "italic":
            out.append(MessageEntityItalic(offset=off, length=ln))
        elif t == "underline":
            out.append(MessageEntityUnderline(offset=off, length=ln))
        elif t == "strikethrough":
            out.append(MessageEntityStrike(offset=off, length=ln))
        elif t == "spoiler":
            out.append(MessageEntitySpoiler(offset=off, length=ln))
        elif t == "code":
            out.append(MessageEntityCode(offset=off, length=ln))
        elif t == "pre":
            out.append(MessageEntityPre(offset=off, length=ln, language=e.get("language") or ""))
        elif t == "text_link":
            out.append(MessageEntityTextUrl(offset=off, length=ln, url=e.get("url") or ""))
        elif t == "custom_emoji":
            doc = int(e.get("document_id") or e.get("custom_emoji_id") or 0)
            if doc:
                out.append(MessageEntityCustomEmoji(offset=off, length=ln, document_id=doc))
        elif t == "blockquote":
            if e.get("collapsed") is not None:
                out.append(
                    MessageEntityBlockquote(offset=off, length=ln, collapsed=bool(e["collapsed"]))
                )
            else:
                out.append(MessageEntityBlockquote(offset=off, length=ln))
        elif t in ("expandable_blockquote", "expandable blockquote"):
            out.append(MessageEntityBlockquote(offset=off, length=ln, collapsed=True))
        elif t == "mention":
            out.append(MessageEntityMention(offset=off, length=ln))
        elif t == "hashtag":
            out.append(MessageEntityHashtag(offset=off, length=ln))
        elif t == "cashtag":
            out.append(MessageEntityCashtag(offset=off, length=ln))
        elif t == "bot_command":
            out.append(MessageEntityBotCommand(offset=off, length=ln))
        elif t == "url":
            out.append(MessageEntityUrl(offset=off, length=ln))
        elif t == "email":
            out.append(MessageEntityEmail(offset=off, length=ln))
        elif t == "phone_number":
            out.append(MessageEntityPhone(offset=off, length=ln))
        elif t == "text_mention":
            uid = int(e.get("user_id") or 0)
            if uid:
                out.append(MessageEntityMentionName(offset=off, length=ln, user_id=uid))
    out.sort(key=lambda ent: (ent.offset, ent.length))
    return out


def entities_aiogram_to_json(entities) -> str:
    if not entities:
        return "[]"
    data = []
    for ent in entities:
        t = getattr(ent, "type", None)
        if hasattr(t, "value"):
            t = t.value
        t = str(t or "").lower()
        d = {"type": t, "offset": ent.offset, "length": ent.length}
        if t == "custom_emoji":
            cid = getattr(ent, "custom_emoji_id", None)
            if cid is not None:
                d["document_id"] = int(cid)
        elif t == "text_link":
            d["url"] = getattr(ent, "url", "") or ""
        elif t == "pre":
            d["language"] = getattr(ent, "language", "") or ""
        elif t == "blockquote":
            col = getattr(ent, "collapsed", None)
            if col is not None:
                d["collapsed"] = bool(col)
        elif t == "expandable_blockquote":
            d["collapsed"] = True
        elif t == "text_mention":
            u = getattr(ent, "user", None)
            if u is not None:
                uid = getattr(u, "id", None)
                if uid is not None:
                    d["user_id"] = int(uid)
        data.append(d)
    return json.dumps(data, ensure_ascii=False)


def strip_custom_emoji_entities(entities: list) -> list:
    return [e for e in entities if not isinstance(e, MessageEntityCustomEmoji)]


def dialog_matches_filter(dialog, flt: str) -> bool:
    flt = (flt or "all").lower()
    if flt == "all":
        return True
    ent = dialog.entity
    if flt == "private":
        return dialog.is_user
    if flt == "groups":
        return getattr(dialog, "is_group", False) or (
            getattr(dialog, "is_channel", False) and getattr(ent, "megagroup", False)
        )
    if flt == "channels":
        return getattr(dialog, "is_channel", False) and not getattr(ent, "megagroup", False)
    return True


async def iter_dialogs_including_archived(client: TelegramClient):
    """Основная папка + архив; без дубликатов по peer."""
    seen: set[int] = set()
    async for dialog in client.iter_dialogs(archived=False):
        pid = tl_utils.get_peer_id(dialog.entity)
        if pid in seen:
            continue
        seen.add(pid)
        yield dialog
    try:
        async for dialog in client.iter_dialogs(archived=True):
            pid = tl_utils.get_peer_id(dialog.entity)
            if pid in seen:
                continue
            seen.add(pid)
            yield dialog
    except TypeError:
        pass


def infer_mailing_media_type(resolved_path: str, stored_type: str) -> str:
    s = (stored_type or "").lower().strip()
    if s in ("photo", "video", "animation"):
        return s
    bn = os.path.basename(resolved_path or "").lower()
    if bn.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "photo"
    if "gif" in bn:
        return "animation"
    return "video"


def resolve_session_path(session_stored: str) -> str:
    """Путь к сессии Telethon без суффикса .session (как в TelegramClient)."""
    p = (session_stored or "").strip()
    if not p:
        return p
    if p.endswith(".session"):
        p = p[: -len(".session")]
    p = os.path.normpath(p)
    root = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if os.path.isabs(p):
        candidates.append(p)
    else:
        data_dir = os.getenv("DATA_DIR") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or os.getenv("PERSISTENT_DATA_DIR")
        if data_dir:
            data_dir = os.path.abspath(data_dir)
            candidates.append(os.path.join(data_dir, p))
            candidates.append(os.path.join(data_dir, "sessions", os.path.basename(p)))
        candidates.append(os.path.join(root, p))
        candidates.append(os.path.abspath(p))
    for base in candidates:
        if os.path.isfile(base + ".session"):
            return base
    return candidates[0] if candidates else p


def resolve_mailing_media_path(media_path: str | None) -> str:
    """Абсолютный путь к файлу медиа (в БД мог быть относительный путь)."""
    if not media_path or not str(media_path).strip():
        return ""
    p = os.path.normpath(os.path.expanduser(str(media_path)))
    if os.path.isfile(p):
        return os.path.abspath(p)
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (
        os.path.join(here, p),
        os.path.join(here, os.path.basename(p)),
        os.path.join(here, "mailing_media", os.path.basename(p)),
    ):
        if os.path.isfile(c):
            return os.path.abspath(c)
    return p


def default_mailing_video_abspath() -> str:
    """Стандартный баннер рассылки: <корень проекта>/media/banner.png"""
    return os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "media", "banner.png")
    )


def resolve_mailing_media_or_default(media_path: str | None) -> str:
    """Как resolve_mailing_media_path; если пусто или файла нет — пробуем media/banner.png."""
    r = resolve_mailing_media_path(media_path)
    if r and os.path.isfile(r):
        return r
    d = default_mailing_video_abspath()
    return d if os.path.isfile(d) else ""


def _entity_send_variants(entities: list) -> list[list]:
    """Полные сущности → без custom emoji → без форматирования."""
    out: list[list] = []
    if entities:
        out.append(entities)
        stripped = strip_custom_emoji_entities(entities)
        if len(stripped) < len(entities):
            out.append(stripped)
    out.append([])
    return out


def _prune_slowmode_skip() -> None:
    now = time.monotonic()
    for k, until in list(_slowmode_skip.items()):
        if until <= now:
            del _slowmode_skip[k]


def _extract_subscription_targets(text: str) -> list[tuple[str, str]]:
    """
    Из текста антиспама («подпишитесь на канал @x», t.me/+hash) — цели для вступления.
    Возвращает список ('invite', hash) или ('username', name).
    """
    if not (text or "").strip():
        return []
    low = text.lower()
    if not any(k in low for k in SUBSCRIBE_HINT_KEYS):
        return []
    found: list[tuple[str, str]] = []
    for m in re.finditer(
        r"(?:https?://)?t\.me/\+([a-zA-Z0-9_-]+)", text, flags=re.I
    ):
        found.append(("invite", m.group(1)))
    for m in re.finditer(
        r"(?:на\s+канал|канал|channel)\s*[:\s,]+\s*@?\s*([a-zA-Z][a-zA-Z0-9_]{3,31})\b",
        text,
        flags=re.I,
    ):
        found.append(("username", m.group(1)))
    for m in re.finditer(
        r"subscribe\s+(?:to\s+)?(?:the\s+)?channel\s*[:\s,]+\s*@?\s*([a-zA-Z][a-zA-Z0-9_]{3,31})\b",
        text,
        flags=re.I,
    ):
        found.append(("username", m.group(1)))
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


async def try_join_channels_from_chat_hints(
    client: TelegramClient,
    chat_entity,
    log_fn,
    chat_title: str,
) -> bool:
    """
    Читает последние сообщения в чате, ищет просьбу подписаться на канал, вступает.
    Возвращает True, если было успешное вступление или уже участник (можно повторить отправку).
    """
    title_short = (chat_title or "")[:80]
    progressed = False
    tried: set[tuple[str, str]] = set()
    try:
        async for msg in client.iter_messages(chat_entity, limit=30):
            text = getattr(msg, "message", None) or ""
            for kind, val in _extract_subscription_targets(text):
                key = (kind, val)
                if key in tried:
                    continue
                tried.add(key)
                try:
                    if kind == "invite":
                        await client(ImportChatInviteRequest(val))
                        progressed = True
                        if log_fn:
                            await log_fn(
                                f"«{title_short}»: вступили по инвайт-ссылке из сообщения в чате"
                            )
                    else:
                        ent = await client.get_entity(val)
                        if isinstance(ent, Channel):
                            await client(JoinChannelRequest(ent))
                            progressed = True
                            if log_fn:
                                await log_fn(
                                    f"«{title_short}»: подписка на канал @{val} (требование чата)"
                                )
                except UserAlreadyParticipantError:
                    progressed = True
                except Exception:
                    logger.debug(
                        "try_join_channels_from_chat_hints: %s %r failed",
                        kind,
                        val,
                        exc_info=True,
                    )
    except Exception:
        logger.debug(
            "try_join_channels_from_chat_hints: iter_messages failed",
            exc_info=True,
        )
    return progressed


async def send_one_broadcast(
    client: TelegramClient,
    dialog,
    text: str,
    entities: list,
    file_ref: str | Any,
    media_type: str = "",
    *,
    path_for_infer: str = "",
) -> None:
    """
    file_ref — путь к файлу (str) или результат client.upload_file (один раз на круг рассылки).
    path_for_infer — абсолютный путь для определения photo/video/animation, если file_ref уже загружен.
    """
    raw = text or ""
    has_ent = bool(entities)
    # Сущности привязаны к точной строке UTF-16; strip ломает offset/length.
    send_text = raw if has_ent else raw.strip()
    caption = send_text if send_text.strip() else None

    file_for_send: str | Any | None = None
    meta_path = path_for_infer or ""
    if isinstance(file_ref, str):
        resolved = resolve_mailing_media_path(file_ref)
        if resolved and os.path.isfile(resolved):
            file_for_send = resolved
            meta_path = meta_path or resolved
    else:
        file_for_send = file_ref

    if file_for_send is not None:
        mt = infer_mailing_media_type(meta_path, media_type)
        file_kw_variants: list[dict] = []
        base: dict = {}
        if mt == "animation":
            base = {"nosound_video": False, "supports_streaming": True}
        elif mt == "video":
            base = {"supports_streaming": True}
        file_kw_variants.append(base)
        if mt == "animation" and base:
            file_kw_variants.append({})

        last_err: Exception | None = None
        for file_kw in file_kw_variants:
            for ents_try in _entity_send_variants(entities or []):
                send_kw: dict = {}
                if ents_try:
                    send_kw["formatting_entities"] = ents_try
                try:
                    await client.send_file(
                        dialog.entity,
                        file_for_send,
                        caption=caption,
                        **send_kw,
                        **file_kw,
                    )
                    return
                except FloodWaitError:
                    raise
                except SlowModeWaitError:
                    raise
                except FloodPremiumWaitError:
                    raise
                except Exception as e:
                    last_err = e
                    logger.debug(
                        "send_file failed (entities=%s file_kw=%s): %s",
                        bool(ents_try),
                        bool(file_kw),
                        e,
                        exc_info=True,
                    )
        if last_err and isinstance(last_err, ChatSendGifsForbiddenError) and mt == "animation":
            for ents_try in _entity_send_variants(entities or []):
                send_kw: dict = {}
                if ents_try:
                    send_kw["formatting_entities"] = ents_try
                try:
                    await client.send_file(
                        dialog.entity,
                        file_for_send,
                        caption=caption,
                        **send_kw,
                        supports_streaming=True,
                    )
                    return
                except FloodWaitError:
                    raise
                except SlowModeWaitError:
                    raise
                except FloodPremiumWaitError:
                    raise
                except Exception as e:
                    last_err = e
                    logger.debug("send_file as video after GIF ban: %s", e, exc_info=True)
        if last_err:
            raise last_err
        return

    if not caption:
        return
    last_err = None
    for ents_try in _entity_send_variants(entities or []):
        send_kw: dict = {}
        if ents_try:
            send_kw["formatting_entities"] = ents_try
        try:
            await client.send_message(dialog.entity, send_text, **send_kw)
            return
        except FloodWaitError:
            raise
        except SlowModeWaitError:
            raise
        except FloodPremiumWaitError:
            raise
        except Exception as e:
            last_err = e
            logger.debug("send_message failed: %s", e, exc_info=True)
    if last_err:
        raise last_err


async def run_mailing_loop(
    db_path: str,
    user_id: int,
    tg_api_id: int,
    tg_api_hash: str,
    get_accounts_for_user,
    log_fn=None,
    can_send_fn=None,
    after_success_fn=None,
) -> None:
    autostart_waits = 0
    while True:
        cfg = get_mailing_config(db_path, user_id)
        if not cfg["is_running"]:
            if log_fn:
                await log_fn("Цикл остановлен (is_running=0).")
            break

        if not within_autostart(cfg["autostart_str"]):
            autostart_waits += 1
            au = (cfg.get("autostart_str") or "").strip() or "выкл (круглосуточно)"
            if log_fn and (autostart_waits == 1 or autostart_waits % 8 == 0):
                await log_fn(
                    f"Вне окна автозапуска МСК: «{au}». Пауза 15 с… (ожидание #{autostart_waits})"
                )
            await asyncio.sleep(15)
            continue
        autostart_waits = 0

        text_legacy = cfg["body_text"] or ""
        media_path = cfg["media_path"] or ""
        resolved_media = resolve_mailing_media_or_default(media_path)
        has_media = bool(resolved_media and os.path.isfile(resolved_media))
        has_any_text = mailing_has_any_text(cfg)
        if not has_any_text and not has_media:
            if log_fn:
                await log_fn("Нет текста и медиа — остановка рассылки")
            set_running(db_path, user_id, False)
            break

        ids = get_selected_ids(db_path, user_id)
        if not ids:
            if log_fn:
                await log_fn("Не выбраны аккаунты — остановка")
            set_running(db_path, user_id, False)
            break

        media_type = cfg.get("media_type") or ""
        flt = cfg["chats_filter"]
        selected_chat_ids = set(get_selected_chat_ids(db_path, user_id))
        nv = count_filled_variants(cfg)

        if log_fn:
            if nv > 0:
                snippet_src = next(
                    (
                        v["text"]
                        for v in normalize_variants(cfg.get("body_variants_json"))
                        if (v.get("text") or "").strip()
                    ),
                    "",
                )
            else:
                snippet_src = text_legacy
            snippet = snippet_src.replace("\n", " ").replace("\r", "")
            if len(snippet) > 100:
                snippet = snippet[:100] + "…"
            await log_fn(
                f"Круг: аккаунтов {len(ids)}, чаты={flt}, выбрано_чатов={len(selected_chat_ids)}, медиа={'да' if has_media else 'нет'}, "
                f"файл={os.path.basename(resolved_media) if resolved_media else '-'}, "
                f"вариантов текста: {nv}, запасной «Текст»: {'да' if text_legacy.strip() else 'нет'}, "
                f"образец: {snippet!r}"
            )

        for acc_id in ids:
            acc = get_accounts_for_user(acc_id, user_id)
            if not acc:
                if log_fn:
                    await log_fn(f"Аккаунт id={acc_id} не найден или чужой — пропуск")
                continue
            session_path = resolve_session_path(acc["session_name"])
            if not session_path or not os.path.isfile(session_path + ".session"):
                if log_fn:
                    await log_fn(f"Файл сессии не найден: +{acc.get('phone', '')}")
                continue
            if log_fn:
                await log_fn(f"Аккаунт +{acc.get('phone', '')}: подключение…")
            client = TelegramClient(session_path, tg_api_id, tg_api_hash)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    if log_fn:
                        await log_fn(f"Сессия не авторизована: +{acc['phone']}")
                    continue
                me = await client.get_me()

                file_ref: str | Any = media_path
                if has_media and resolved_media and os.path.isfile(resolved_media):
                    try:
                        file_ref = await client.upload_file(resolved_media)
                        if log_fn:
                            await log_fn(f"Аккаунт +{acc['phone']}: медиа загружено в Telegram")
                    except Exception as e:
                        logger.warning(
                            "Предзагрузка медиа не удалась, отправка с диска на каждый чат: %s",
                            e,
                        )
                        if log_fn:
                            await log_fn(f"Аккаунт +{acc['phone']}: предзагрузка медиа не удалась: {e!s}")
                        file_ref = resolved_media or media_path

                n_try = 0
                n_ok = 0
                n_err = 0
                _prune_slowmode_skip()
                async for dialog in iter_dialogs_including_archived(client):
                    if not dialog_matches_filter(dialog, flt):
                        continue
                    ent = dialog.entity
                    if isinstance(ent, User) and me and ent.id == me.id:
                        continue
                    peer_id = tl_utils.get_peer_id(ent)
                    if selected_chat_ids and peer_id not in selected_chat_ids:
                        continue
                    sk = _slowmode_skip.get((user_id, acc_id, peer_id))
                    if sk and time.monotonic() < sk:
                        continue
                    if can_send_fn is not None:
                        allowed = await can_send_fn()
                        if not allowed:
                            if log_fn:
                                await log_fn("Лимит сообщений закончился — рассылка остановлена.")
                            set_running(db_path, user_id, False)
                            return
                    n_try += 1
                    dname = getattr(dialog, "name", None) or str(getattr(dialog, "entity", ""))
                    text, entities = pick_random_mailing_payload(cfg)
                    try:
                        await send_one_broadcast(
                            client,
                            dialog,
                            text,
                            entities,
                            file_ref,
                            media_type,
                            path_for_infer=resolved_media or "",
                        )
                        n_ok += 1
                        if after_success_fn is not None:
                            await after_success_fn()
                    except SlowModeWaitError as e:
                        n_err += 1
                        _slowmode_skip[(user_id, acc_id, peer_id)] = time.monotonic() + float(
                            e.seconds
                        )
                        if log_fn:
                            if e.seconds <= 600:
                                await log_fn(
                                    f"«{dname[:80]}»: slow mode {e.seconds}s — чат пропущен до истечения паузы"
                                )
                            else:
                                logger.info(
                                    "mailing slow mode long skip chat=%r sec=%s",
                                    dname[:60],
                                    e.seconds,
                                )
                    except FloodPremiumWaitError as e:
                        n_err += 1
                        if log_fn:
                            await log_fn(
                                f"FloodPremiumWait {e.seconds}s (+{acc['phone']}), пауза"
                            )
                        await asyncio.sleep(min(e.seconds + 1, 300))
                    except FloodWaitError as e:
                        n_err += 1
                        if log_fn:
                            await log_fn(
                                f"FloodWait {e.seconds}s (+{acc['phone']}), пауза перед продолжением"
                            )
                        await asyncio.sleep(min(e.seconds + 1, 300))
                    except (
                        ChatWriteForbiddenError,
                        ChatForbiddenError,
                        UserNotParticipantError,
                    ) as e:
                        hinted = await try_join_channels_from_chat_hints(
                            client, ent, log_fn, dname
                        )
                        if hinted:
                            try:
                                await send_one_broadcast(
                                    client,
                                    dialog,
                                    text,
                                    entities,
                                    file_ref,
                                    media_type,
                                    path_for_infer=resolved_media or "",
                                )
                                n_ok += 1
                                if after_success_fn is not None:
                                    await after_success_fn()
                                if log_fn:
                                    await log_fn(
                                        f"«{dname[:80]}»: повторная отправка после подписки на канал — успех"
                                    )
                            except Exception as e2:
                                n_err += 1
                                logger.warning(
                                    "Рассылка после подписки: %s: %s",
                                    dname,
                                    e2,
                                    exc_info=True,
                                )
                                if log_fn:
                                    await log_fn(
                                        f"Ошибка → «{dname[:80]}»: {str(e2)[:350]}"
                                    )
                        else:
                            n_err += 1
                            logger.warning(
                                "Рассылка: не удалось отправить в %s: %s",
                                dname,
                                e,
                                exc_info=True,
                            )
                            if log_fn:
                                await log_fn(f"Ошибка → «{dname[:80]}»: {str(e)[:350]}")
                    except Exception as e:
                        low = str(e).lower()
                        if (
                            "can't write in this chat" in low
                            or "cannot write in this chat" in low
                        ):
                            hinted = await try_join_channels_from_chat_hints(
                                client, ent, log_fn, dname
                            )
                            if hinted:
                                try:
                                    await send_one_broadcast(
                                        client,
                                        dialog,
                                        text,
                                        entities,
                                        file_ref,
                                        media_type,
                                        path_for_infer=resolved_media or "",
                                    )
                                    n_ok += 1
                                    if after_success_fn is not None:
                                        await after_success_fn()
                                    if log_fn:
                                        await log_fn(
                                            f"«{dname[:80]}»: повторная отправка после подписки на канал — успех"
                                        )
                                except Exception as e2:
                                    n_err += 1
                                    logger.warning(
                                        "Рассылка после подписки: %s: %s",
                                        dname,
                                        e2,
                                        exc_info=True,
                                    )
                                    if log_fn:
                                        await log_fn(
                                            f"Ошибка → «{dname[:80]}»: {str(e2)[:350]}"
                                        )
                                if MAIL_PEER_DELAY_SEC > 0:
                                    await asyncio.sleep(MAIL_PEER_DELAY_SEC)
                                continue
                        n_err += 1
                        logger.warning(
                            "Рассылка: не удалось отправить в %s: %s",
                            getattr(dialog, "name", None) or dialog.entity,
                            e,
                            exc_info=True,
                        )
                        if log_fn:
                            err_s = str(e)[:350]
                            await log_fn(f"Ошибка → «{dname[:80]}»: {err_s}")
                    if MAIL_PEER_DELAY_SEC > 0:
                        await asyncio.sleep(MAIL_PEER_DELAY_SEC)
                if log_fn:
                    await log_fn(
                        f"Аккаунт +{acc['phone']}: готово — попыток отправки {n_try}, "
                        f"успешно {n_ok}, с ошибками/FloodWait {n_err}"
                    )
            finally:
                await client.disconnect()

        interval = max(5, int(cfg["interval_sec"] or DEFAULT_INTERVAL))
        if log_fn:
            await log_fn(f"Круг завершён. Пауза {interval} с до следующего круга.")
        for _ in range(interval):
            cfg2 = get_mailing_config(db_path, user_id)
            if not cfg2["is_running"]:
                if log_fn:
                    await log_fn("Пауза прервана: рассылка остановлена.")
                return
            await asyncio.sleep(1)
