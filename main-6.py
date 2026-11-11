import asyncio
import json
import logging
import os
import random
import re
import sqlite3
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, errors, events, functions, utils
from telethon.tl.types import Channel, Chat, InputReplyToMessage, PeerChannel

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

BASE_DIR = Path(__file__).resolve().parent
SESSION_DIR = BASE_DIR / "sessions"
DATA_FILE = BASE_DIR / "data.json"
SERVICE_ID = 777000
SEEN_LIMIT = 4096
MAX_POST_LEN = 99
SEND_TIMEOUT = max(1.0, float(os.getenv("SEND_TIMEOUT", "30")))
MIGRATION_ERRORS = (errors.PhoneMigrateError, errors.NetworkMigrateError, errors.UserMigrateError)
LOGIN_TTL = 300
HISTORY_INTERVAL = 30
HISTORY_PAGE = 100
CHUNK = 4000

COMMAND_RE = r"(?is)^\.(help|ping|listgc|addgc|rmgc|keyword|text|addprice|open|close)(?:\s+(.*))?$"

HELP_TEXT = "\n".join(
    (
        "「 Ruby UBot BETA 」",
        "",
        ".help",
        ".ping",
        ".listgc",
        ".addgc",
        ".rmgc",
        ".keyword",
        ".text",
        ".addprice",
        ".open",
        ".close",
    )
)

PANEL_HELP = (
    "Panel commands\n\n"
    "/login - hubungkan worker\n"
    "/logout - putuskan seluruh worker\n"
    "/adduser <user_id> - authorize a user (owner)\n"
    "/deluser <user_id> - remove a user (owner)\n"
    "/users - list authorized users (owner)"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("telethon").setLevel(logging.WARNING)
log = logging.getLogger("userbot")


def _class(spec):
    parts = []
    for token in spec.split():
        low, _, high = token.partition("-")
        parts.append(f"{chr(int(low, 16))}-{chr(int(high or low, 16))}")
    return "".join(parts)


_ALWAYS = _class(
    "231A-231B 23E9-23EC 23F0 23F3 25FD-25FE 2614-2615 2648-2653 267F 2693 26A1 26AA-26AB "
    "26BD-26BE 26C4-26C5 26CE 26D4 26EA 26F2-26F3 26F5 26FA 26FD 2705 270A-270B 2728 274C "
    "274E 2753-2755 2757 2795-2797 27B0 27BF 2B1B-2B1C 2B50 2B55 1F004 1F02C-1F02F "
    "1F094-1F09F 1F0AF-1F0B0 1F0C0 1F0CF-1F0D0 1F0F6-1F0FF 1F170-1F171 1F17E-1F17F 1F18E "
    "1F191-1F19A 1F1AE-1F1FF 1F201-1F20F 1F21A 1F22F 1F232-1F23A 1F23C-1F23F 1F249-1F25F "
    "1F266-1F321 1F324-1F393 1F396-1F397 1F399-1F39B 1F39E-1F3F0 1F3F3-1F3F5 1F3F7-1F4FD "
    "1F4FF-1F53D 1F549-1F54E 1F550-1F567 1F56F-1F570 1F573-1F57A 1F587 1F58A-1F58D 1F590 "
    "1F595-1F596 1F5A4-1F5A5 1F5A8 1F5B1-1F5B2 1F5BC 1F5C2-1F5C4 1F5D1-1F5D3 1F5DC-1F5DE "
    "1F5E1 1F5E3 1F5E8 1F5EF 1F5F3 1F5FA-1F64F 1F680-1F6C5 1F6CB-1F6D2 1F6D5-1F6E5 1F6E9 "
    "1F6EB-1F6F0 1F6F3-1F6FF 1F777-1F77A 1F7DA-1F7FF 1F80C-1F80F 1F848-1F84F 1F85A-1F85F "
    "1F888-1F88F 1F8AE-1F8AF 1F8B2-1F8FF 1F90C-1F93A 1F93C-1F945 1F947-1F9FF 1FA54-1FA5F "
    "1FA6E-1FAFF 1FC00-1FFFD"
)
_BARE = _class(
    "2600-2604 260E 2611 2618 261D 2620 2622-2623 2626 262A 262E-262F 2638-263A 2640 2642 "
    "265F-2660 2663 2665-2666 2668 267B 267E 2692 2694-2697 2699 269B-269C 26A0 26A7 "
    "26B0-26B1 26C8 26CF 26D1 26D3 26E9 26F0-26F1 26F4 26F7-26F9 2702 2708-2709 270C-270D "
    "270F 2712 2714 2716 271D 2721 2733-2734 2744 2747 2763-2764 27A1 2934-2935 2B05-2B07 "
    "3030 303D 3297 3299"
)
_NEEDS_VS16 = _class(
    "A9 AE 203C 2049 2122 2139 2194-2199 21A9-21AA 2328 23CF 23ED-23EF 23F1-23F2 "
    "23F8-23FA 24C2 25AA-25AB 25B6 25C0 25FB-25FC"
)
_VS16 = "\ufe0f"
_VS15 = "\ufe0e"
_BASE = f"(?:[{_ALWAYS}]|[{_BARE}]|[{_NEEDS_VS16}](?={_VS16}))(?!{_VS15})"
_ITEM = (
    "(?:[\U0001f1e6-\U0001f1ff]{2}"
    f"|[0-9#*]{_VS16}?\u20e3"
    "|\U0001f3f4[\U000e0020-\U000e007e]+\U000e007f"
    f"|{_BASE}(?:[\U0001f3fb-\U0001f3ff]|{_VS16})?)"
)
EMOJI_RE = re.compile(f"{_ITEM}(?:\u200d{_ITEM})*")


def _scan(text):
    return () if text.isascii() else EMOJI_RE.finditer(text)


def content_emojis(text):
    found = []
    pos = 0
    leading = True
    for match in _scan(text):
        if leading and not text[pos : match.start()].strip():
            pos = match.end()
            continue
        leading = False
        found.append(match.group())
    return list(dict.fromkeys(found))


def build_reply(template, post_text):
    extra = content_emojis(post_text)
    if not extra:
        return template
    present = {match.group().replace(_VS16, "") for match in _scan(template)}
    suffix = []
    for item in extra:
        key = item.replace(_VS16, "")
        if key not in present:
            suffix.append(item)
            present.add(key)
    if not suffix:
        return template
    separator = "" if template[-1:].isspace() else " "
    return template + separator + "".join(suffix)


def parse_group_id(arg):
    try:
        value = int(arg.strip())
    except ValueError:
        return None
    return utils.get_peer_id(PeerChannel(value)) if value > 0 else value


def normalize(text):
    if text.isascii():
        return " ".join(text.lower().split())
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", text).split())


def text_size(text):
    return len(text.encode("utf-16-le")) // 2


def split_text(text, limit=CHUNK):
    parts = []
    chunk = []
    size = 0
    for char in text:
        width = 2 if ord(char) > 0xFFFF else 1
        if size + width > limit:
            parts.append("".join(chunk))
            chunk = []
            size = 0
        chunk.append(char)
        size += width
    if chunk:
        parts.append("".join(chunk))
    return parts or [" "]


class Store:
    def __init__(self, path):
        self.path = path
        self.data = {"users": [], "settings": {}}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"Konfigurasi tidak dapat dibaca: {path}") from exc

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def is_authorized(self, uid):
        return uid == OWNER_ID or uid in self.data["users"]

    def all_users(self):
        return list(dict.fromkeys([OWNER_ID, *self.data["users"]]))

    def add_user(self, uid):
        if uid == OWNER_ID or uid in self.data["users"]:
            return False
        self.data["users"].append(uid)
        self.save()
        return True

    def remove_user(self, uid):
        if uid not in self.data["users"]:
            return False
        self.data["users"].remove(uid)
        self.save()
        return True

    def settings(self, uid):
        cfg = self.data["settings"].setdefault(str(uid), {})
        cfg.setdefault("keywords", [])
        cfg.setdefault("texts", [])
        cfg.setdefault("targets", {})
        cfg.setdefault("prices", {})
        legacy_prefix = cfg.pop("price_text", None)
        if legacy_prefix:
            words = list(
                dict.fromkeys(normalize(word) for word in cfg["keywords"] if normalize(word))
            )
            if len(words) == 1:
                if not any(normalize(key) == words[0] for key in cfg["prices"]):
                    cfg["prices"][words[0]] = legacy_prefix
            else:
                cfg["legacy_price_text"] = legacy_prefix
                log.warning("user %s: shared prefix archived; configure .addprice per keyword", uid)
        cfg.setdefault("worker_count", 2)
        if len(cfg["targets"]) > 1:
            cfg["previous_targets"] = cfg["targets"]
            cfg["targets"] = {}
        cfg.setdefault("active", True)
        return cfg


@dataclass
class Account:
    slot: int
    user_id: int
    client: object
    peer: object = None


@dataclass
class Delivery:
    message: object
    normalized: str
    revision: int
    received: float
    account: object = None
    local_copy: object = None
    copies: object = None
    copy_ready: object = None
    attempted: bool = False
    random_id: int = 0


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS claims (
                chat INTEGER, token TEXT, slot INTEGER, state TEXT,
                PRIMARY KEY (chat, token)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS turns (
                owner INTEGER PRIMARY KEY, turn INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pauses (
                scope TEXT PRIMARY KEY, deadline REAL NOT NULL
            );
        """)
        self.writer = sqlite3.connect(path, check_same_thread=False)
        self.writer.execute("PRAGMA busy_timeout=0")
        self.background_writes = False
        self.inline_available = True
        self.writes = deque()
        self.flusher = None
        self.pauses = dict(self.db.execute("SELECT scope, deadline FROM pauses"))

    def enable_inline(self):
        self.inline_available = True

    def try_inline(self, batch):
        if self.background_writes:
            return None
        start = time.perf_counter()
        results = None
        try:
            results = self.transaction(batch)
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", 0) & 255
            if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
        else:
            if time.perf_counter() - start < 0.001:
                return results
        self.background_writes = True
        self.writer.execute("PRAGMA busy_timeout=5000")
        return results

    def submit(self, operation, *args):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        item = (operation, args, future)
        if self.flusher is None and (self.inline_available or operation == self.claim):
            result = self.try_inline((item,))
            if result is not None:
                future.set_result(result[0])
                if self.inline_available:
                    self.inline_available = False
                    loop.call_soon(self.enable_inline)
                return future
        self.writes.append(item)
        if self.flusher is None:
            self.flusher = asyncio.create_task(self.flush())
        return future

    async def flush(self):
        try:
            while self.writes:
                batch = [self.writes.popleft() for _ in range(min(128, len(self.writes)))]
                try:
                    results = self.try_inline(batch)
                    if results is None:
                        results = await asyncio.to_thread(self.transaction, batch)
                except asyncio.CancelledError:
                    for _, _, future in (*batch, *self.writes):
                        future.cancel()
                    self.writes.clear()
                    raise
                except Exception as exc:
                    for _, _, future in batch:
                        if not future.done():
                            future.set_exception(exc)
                else:
                    for (_, _, future), result in zip(batch, results):
                        if not future.done():
                            future.set_result(result)
                if self.writes:
                    await asyncio.sleep(0)
        finally:
            self.flusher = None

    def transaction(self, batch):
        with self.writer:
            self.writer.execute("BEGIN IMMEDIATE")
            return [operation(*args) for operation, args, _ in batch]

    def claim(self, uid, chat, token, accounts, observer):
        db = self.writer
        row = db.execute("SELECT turn FROM turns WHERE owner=?", (uid,)).fetchone()
        turn = row[0] if row else 0
        account = accounts[(turn // 2) % len(accounts)]
        mark = db.execute(
            "INSERT OR IGNORE INTO claims VALUES (?, ?, ?, 'claimed')",
            (chat, token, account.slot),
        )
        if not mark.rowcount:
            resumed = db.execute(
                "UPDATE claims SET state='claimed' WHERE chat=? AND token=? AND slot=? AND state=?",
                (chat, token, observer.slot, f"await-copy/{uid}/{observer.user_id}"),
            )
            return observer if resumed.rowcount else None
        db.execute("INSERT OR REPLACE INTO turns VALUES (?, ?)", (uid, turn + 1))
        return account

    def finish(self, chat, token, state):
        self.writer.execute(
            "UPDATE claims SET state=? WHERE chat=? AND token=? AND state='claimed'",
            (state, chat, token),
        )

    def release(self, chat, token):
        self.writer.execute(
            "DELETE FROM claims WHERE chat=? AND token=? AND state='claimed'", (chat, token)
        )

    async def close(self):
        if self.flusher is not None:
            await self.flusher
        self.writer.close()
        self.db.close()

    def defer(self, uid, chat, seconds):
        deadline = time.time() + seconds
        with self.db:
            for scope in (f"user/{uid}", f"chat/{chat}"):
                value = max(deadline, self.pauses.get(scope, 0))
                self.db.execute("INSERT OR REPLACE INTO pauses VALUES (?, ?)", (scope, value))
                self.pauses[scope] = value

    def remaining(self, uid, chat):
        return max(
            0.0,
            max(self.pauses.get(f"user/{uid}", 0), self.pauses.get(f"chat/{chat}", 0))
            - time.time(),
        )


class Pool:
    def __init__(self, uid, store, ledger):
        self.uid = uid
        self.store = store
        self.ledger = ledger
        self.accounts = {}
        self.ordered = ()
        self.own_ids = set()
        self.jobs = {}
        self.recent = OrderedDict()
        self.handlers = {}
        self.tasks = set()
        self.epoch = 0
        self.stopped = False
        self.restoring = False
        self.sent = self.failed = self.retries = self.recovered = 0
        self.dispatch_ms = self.ack_ms = None
        self.revision = 0
        self.last_history_start = float("-inf")
        self.reader_index = 0
        self.history_task = None
        self.history_config = None
        self.history_cursors = {}
        self.reload()

    def reload(self):
        cfg = self.store.settings(self.uid)
        self.goal = cfg["worker_count"]
        self.active = cfg["active"]
        self.target = next((int(gid) for gid in cfg["targets"]), None)
        words = sorted(
            dict.fromkeys(filter(None, map(normalize, cfg["keywords"]))), key=len, reverse=True
        )
        self.pattern = re.compile("|".join(map(re.escape, words))) if words else None
        prices = {normalize(k): v for k, v in cfg["prices"].items() if v.strip()}
        self.prices = [(w, prices[w]) for w in words if w in prices]
        self.texts = tuple(t for t in cfg["texts"] if t.strip())
        self.revision += 1
        config = (self.target, self.active, self.goal, tuple(words), bool(self.texts))
        if config != self.history_config:
            self.history_config = config
            self.reset_history()

    def reset_history(self):
        self.history_since = datetime.now(timezone.utc).replace(microsecond=0)
        self.history_cursors.clear()
        self.last_history_start = float("-inf")
        if self.history_task is not None:
            self.history_task.cancel()

    def select_price(self, text):
        return next((price for word, price in self.prices if word in text), None)

    def commit(self):
        self.store.save()
        self.reload()

    def ready(self, chat):
        return (
            not self.stopped
            and not self.restoring
            and self.active
            and self.target == chat
            and len(self.ordered) == self.goal
            and self.goal >= 2
        )

    def add(self, slot, user_id, client):
        if slot in self.accounts or user_id in self.own_ids:
            raise ValueError("Akun tersebut sudah terdaftar sebagai worker.")
        account = Account(slot, user_id, client)
        self.accounts[slot] = account
        self.ordered = tuple(self.accounts[k] for k in sorted(self.accounts))
        self.own_ids.add(user_id)
        if len(self.ordered) == self.goal:
            self.reset_history()

        async def post(event):
            await self.on_post(account, event)

        async def command(event):
            await self.on_command(account, event)

        self.handlers[slot] = (post, command)
        client.add_event_handler(post, events.NewMessage(incoming=True))
        client.add_event_handler(post, events.MessageEdited(incoming=True))
        client.add_event_handler(command, events.NewMessage(outgoing=True, pattern=COMMAND_RE))

    def matching_text(self, msg):
        text = msg.message
        if (
            not self.texts
            or not self.pattern
            or not text
            or len(text) > MAX_POST_LEN
            or msg.out
            or msg.post
        ):
            return None
        fwd = msg.fwd_from
        sender = msg.sender_id
        if not fwd or not fwd.channel_post or sender is None or sender in self.own_ids:
            return None
        if sender != SERVICE_ID and (not fwd.from_id or sender != utils.get_peer_id(fwd.from_id)):
            return None
        value = normalize(text)
        return value if "t.u" not in value and self.pattern.search(value) else None

    @staticmethod
    def token(msg):
        if msg.grouped_id:
            return f"a/{msg.grouped_id}"
        fwd = msg.fwd_from
        if fwd and fwd.from_id and fwd.channel_post:
            return f"f/{utils.get_peer_id(fwd.from_id)}/{fwd.channel_post}"
        if isinstance(msg.peer_id, PeerChannel):
            return f"m/{msg.id}"
        return None

    def observe(self, job, observer, msg):
        if msg.grouped_id and (
            not msg.fwd_from
            or not job.message.fwd_from
            or job.message.fwd_from.channel_post != msg.fwd_from.channel_post
        ):
            return
        stamp = getattr(msg, "edit_date", None)
        previous = getattr(job.message, "edit_date", None)
        if (
            stamp is not None
            and (previous is None or stamp >= previous)
            and (stamp != previous or msg.message != job.message.message)
        ):
            job.message = msg
            job.revision = -1
        if job.copies is not None:
            job.copies[observer.slot] = msg.id
            if observer is job.account:
                job.local_copy = msg.id
                job.copy_ready.set()

    async def on_post(self, observer, event):
        await self.process_message(observer, event.message)

    async def process_message(self, observer, msg, recovered=False):
        chat = msg.chat_id
        if not self.ready(chat) or not msg.fwd_from:
            return
        token = self.token(msg)
        if token is None:
            return
        key = chat, token
        if key in self.recent:
            return
        pending = self.jobs.get(key)
        if pending is not None:
            self.observe(pending, observer, msg)
            return
        start = time.perf_counter()
        normalized = self.matching_text(msg)
        if normalized is None:
            return
        job = Delivery(msg, normalized, self.revision, start, random_id=random.getrandbits(63))
        if isinstance(msg.peer_id, PeerChannel):
            job.local_copy = msg.id
        else:
            job.copies = {observer.slot: msg.id}
            job.copy_ready = asyncio.Event()
        task = asyncio.current_task()
        self.jobs[key] = job
        self.tasks.add(task)
        epoch = self.epoch
        ticket = None
        try:
            ticket = self.ledger.submit(
                self.ledger.claim, self.uid, chat, token, self.ordered, observer
            )
            job.account = await asyncio.shield(ticket)
            if job.account is None:
                if job.copies is not None:
                    for account in self.ordered:
                        if account is not observer and account.slot in job.copies:
                            ticket = self.ledger.submit(
                                self.ledger.claim, self.uid, chat, token, self.ordered, account
                            )
                            job.account = await asyncio.shield(ticket)
                            if job.account is not None:
                                break
                if job.account is None:
                    return
            if job.copies is not None:
                job.local_copy = job.copies.get(job.account.slot)
                if job.local_copy is None:
                    try:
                        await asyncio.wait_for(job.copy_ready.wait(), SEND_TIMEOUT)
                    except asyncio.TimeoutError:
                        if job.local_copy is None:
                            state = f"await-copy/{self.uid}/{job.account.user_id}"
                            await asyncio.shield(
                                self.ledger.submit(self.ledger.finish, chat, token, state)
                            )
                            if job.local_copy is None:
                                return
                            ticket = self.ledger.submit(
                                self.ledger.claim, self.uid, chat, token, self.ordered, job.account
                            )
                            if await asyncio.shield(ticket) is None:
                                return
            state = await self.deliver(job, chat, epoch)
            if state == "withdrawn":
                await asyncio.shield(self.ledger.submit(self.ledger.release, chat, token))
                return
            await asyncio.shield(self.ledger.submit(self.ledger.finish, chat, token, state))
            self.recent[key] = None
            if len(self.recent) > SEEN_LIMIT:
                self.recent.popitem(last=False)
            if state == "sent":
                self.sent += 1
                self.recovered += int(recovered)
            else:
                self.failed += 1
        except asyncio.CancelledError:
            if ticket is not None and await asyncio.shield(ticket) is not None:
                if job.attempted:
                    await asyncio.shield(
                        self.ledger.submit(self.ledger.finish, chat, token, "unknown")
                    )
                else:
                    await asyncio.shield(self.ledger.submit(self.ledger.release, chat, token))
            raise
        except Exception:
            self.failed += 1
            log.exception("owner %s: post %s gagal", self.uid, key)
            if job.account is not None:
                await self.ledger.submit(
                    self.ledger.finish, chat, token, "unknown" if job.attempted else "failed"
                )
            if recovered:
                raise
        finally:
            self.jobs.pop(key, None)
            self.tasks.discard(task)

    def start_history_check(self):
        if not (self.target and self.ready(self.target) and self.pattern and self.texts):
            return
        if (
            self.ledger.remaining(self.uid, self.target)
            or self.history_task
            and not self.history_task.done()
        ):
            return
        now = time.monotonic()
        if now - self.last_history_start < 10:
            return
        self.last_history_start = now
        self.history_task = asyncio.create_task(self.check_history())

    async def check_history(self):
        chat = self.target
        if chat is None or not self.ready(chat):
            return
        supergroup = utils.resolve_id(chat)[1] is PeerChannel
        readers = (
            (self.ordered[self.reader_index % len(self.ordered)],) if supergroup else self.ordered
        )

        async def scan(account):
            reader = 0 if supergroup else account.user_id
            try:
                await self.scan_history(chat, account, reader)
            except (errors.SlowModeWaitError, errors.FloodError) as exc:
                self.rate_limit(exc, chat)
            except (errors.PeerFloodError, errors.UnauthorizedError, errors.ForbiddenError) as exc:
                self.pause(type(exc).__name__)
            except (errors.ServerError, OSError, asyncio.TimeoutError) as exc:
                self.reader_index += 1
                log.warning(
                    "worker %s: riwayat target belum tersedia (%s)",
                    account.slot,
                    type(exc).__name__,
                )
            except Exception:
                log.exception("worker %s: gagal memeriksa riwayat target", account.slot)

        await asyncio.gather(*(scan(account) for account in readers))

    async def scan_history(self, chat, account, reader):
        epoch = self.epoch

        def active():
            return (
                self.ready(chat)
                and epoch == self.epoch
                and not self.ledger.remaining(self.uid, chat)
            )

        if not active():
            return
        peer = account.peer or chat
        checkpoint = self.history_cursors.get(reader)
        if checkpoint is None:
            before = await asyncio.wait_for(
                account.client.get_messages(peer, limit=1, offset_date=self.history_since),
                SEND_TIMEOUT,
            )
            if not active():
                return
            anchor = high = before[0].id if before else 0
            self.history_cursors[reader] = anchor, high
        else:
            anchor, high = checkpoint
        low = max(anchor, high - 32)
        for _ in range(4):
            if not active():
                return
            page = await asyncio.wait_for(
                account.client.get_messages(peer, limit=HISTORY_PAGE, min_id=low, reverse=True),
                SEND_TIMEOUT,
            )
            if not active():
                return
            messages = [msg for msg in page if msg.id > low]
            if not messages:
                return
            await asyncio.gather(
                *(
                    self.process_message(account, msg, recovered=True)
                    for msg in messages
                    if getattr(msg, "message", None)
                    and getattr(msg, "date", self.history_since) >= self.history_since
                )
            )
            if not active():
                return
            low = max(msg.id for msg in messages)
            high = max(high, low)
            self.history_cursors[reader] = anchor, high
            if len(page) < HISTORY_PAGE:
                return

    def invalidate(self):
        self.epoch += 1
        for task in self.tasks:
            if task is not asyncio.current_task():
                task.cancel()

    def pause(self, reason):
        self.invalidate()
        self.store.settings(self.uid)["active"] = False
        self.commit()
        log.warning("owner %s: pool paused (%s)", self.uid, reason)

    def rate_limit(self, exc, chat):
        seconds = getattr(exc, "seconds", None)
        if seconds is None:
            self.pause(type(exc).__name__)
            return False
        self.ledger.defer(self.uid, chat, max(1, seconds))
        return True

    def make_reply(self, job, value):
        price = self.select_price(value)
        body = random.choice(self.texts)
        template = f"{price}\n\n{body}" if price else body
        text = build_reply(template, job.message.message)
        if text_size(text) > 4096:
            text = template
            if text_size(text) > 4096:
                raise ValueError("Promosi melebihi batas pesan Telegram.")
        return functions.messages.SendMessageRequest(
            peer=job.account.peer,
            message=text,
            random_id=job.random_id,
            reply_to=InputReplyToMessage(reply_to_msg_id=job.local_copy),
        )

    async def deliver(self, job, chat, epoch):
        account = job.account
        request = None
        transport_retried = False
        uncertain = False
        while self.ready(chat) and self.epoch == epoch:
            wait = self.ledger.remaining(self.uid, chat)
            if wait:
                await asyncio.sleep(wait)
                continue
            try:
                if account.peer is None:
                    peer = await asyncio.wait_for(
                        account.client.get_input_entity(chat), SEND_TIMEOUT
                    )
                    if self.epoch != epoch:
                        return "withdrawn"
                    account.peer = peer
                    continue
                if job.revision != self.revision:
                    job.normalized = self.matching_text(job.message)
                    job.revision = self.revision
                if job.normalized is None:
                    return "unknown" if uncertain else "withdrawn"
                if request is None:
                    request = self.make_reply(job, job.normalized)
                sending = time.perf_counter()
                if not job.attempted:
                    self.dispatch_ms = (sending - job.received) * 1000
                job.attempted = True
                await asyncio.wait_for(account.client(request), SEND_TIMEOUT)
                self.ack_ms = (time.perf_counter() - sending) * 1000
                return "sent"
            except errors.RandomIdDuplicateError:
                return "sent"
            except (errors.SlowModeWaitError, errors.FloodError) as exc:
                job.attempted = uncertain
                if not uncertain:
                    request = None
                if not self.rate_limit(exc, chat):
                    return "failed"
                self.retries += 1
            except (
                errors.PeerFloodError,
                errors.ForbiddenError,
                errors.UserBannedInChannelError,
                errors.ChatAdminRequiredError,
                errors.UnauthorizedError,
            ) as exc:
                self.pause(type(exc).__name__)
                return "failed"
            except (OSError, asyncio.TimeoutError, errors.ServerError, errors.RpcCallFailError):
                uncertain = uncertain or job.attempted
                if transport_retried:
                    return "unknown" if uncertain else "withdrawn"
                transport_retried = True
                self.retries += 1
            except errors.RPCError as exc:
                log.warning("worker %s: %s", account.slot, type(exc).__name__)
                return "unknown" if uncertain else "failed"
        return "unknown" if uncertain else "withdrawn"

    async def on_command(self, account, event):
        name = event.pattern_match.group(1).lower()
        arg = event.pattern_match.group(2) or ""
        try:
            if name == "ping":
                text = await self.cmd_ping(account)
            else:
                text = await getattr(self, f"cmd_{name}")(arg)
            chunks = split_text(text)
            try:
                await event.edit(chunks[0], parse_mode=None)
            except errors.MessageNotModifiedError:
                pass
            for chunk in chunks[1:]:
                await account.client.send_message(event.chat_id, chunk, parse_mode=None)
        except errors.FloodError as exc:
            self.rate_limit(exc, self.target)
        except Exception:
            log.exception("owner %s: command %s failed", self.uid, name)
            await event.respond("Perintah gagal. Periksa log bot.")

    async def cmd_help(self, arg):
        return HELP_TEXT

    async def cmd_ping(self, account):
        start = time.perf_counter()
        await account.client(functions.PingRequest(ping_id=random.getrandbits(62)))
        dispatch = "-" if self.dispatch_ms is None else f"{self.dispatch_ms:.2f} ms"
        ack = "-" if self.ack_ms is None else f"{self.ack_ms:.2f} ms"
        return (
            f"Pong {(time.perf_counter()-start)*1000:.0f} ms\n"
            f"Worker {len(self.accounts)}/{self.goal}\nTarget {self.target or '-'}\n"
            f"Status {'open' if self.active else 'closed'}\nSedang diproses {len(self.jobs)}\n"
            f"Post dipulihkan {self.recovered}\nEvent ke percobaan kirim {dispatch}\nKirim ke konfirmasi {ack}\n"
            f"Terkirim {self.sent}\nGagal/tidak pasti {self.failed}\nRetry {self.retries}\n"
            f"Rate limit {self.ledger.remaining(self.uid, self.target):.1f}s"
        )

    async def cmd_listgc(self, arg):
        targets = self.store.settings(self.uid)["targets"]
        return (
            "\n".join(f"{name} ({gid})" for gid, name in targets.items())
            or "Belum ada target. Gunakan .addgc <id>."
        )

    @staticmethod
    async def group_entity(client, gid):
        try:
            return await client.get_entity(gid)
        except ValueError:
            async for dialog in client.iter_dialogs(ignore_migrated=True):
                if dialog.is_group and dialog.id == gid:
                    return dialog.entity
            raise ValueError("Grup tidak ditemukan dalam daftar dialog.")

    async def cmd_addgc(self, arg):
        gid = parse_group_id(arg)
        if not gid:
            return "Gunakan .addgc <id grup>."
        accounts = self.ordered
        epoch = self.epoch
        peers = []
        for account in accounts:
            try:
                entity = await self.group_entity(account.client, gid)
            except (ValueError, errors.NotFoundError):
                return f"Worker {account.slot} tidak dapat mengakses grup tersebut."
            if not (isinstance(entity, Chat) or isinstance(entity, Channel) and entity.megagroup):
                return "ID tersebut bukan grup."
            if getattr(entity, "left", False) or getattr(entity, "deactivated", False):
                return f"Worker {account.slot} belum menjadi anggota grup."
            peers.append(utils.get_input_peer(entity))
        if self.epoch != epoch or accounts != self.ordered or not peers:
            return "Daftar worker atau target berubah. Ulangi perintah."
        self.invalidate()
        for account, peer in zip(accounts, peers):
            account.peer = peer
        self.store.settings(self.uid)["targets"] = {str(gid): utils.get_display_name(entity)}
        self.commit()
        return f"Target: {utils.get_display_name(entity)} ({gid})."

    async def cmd_rmgc(self, arg):
        if self.target is None or parse_group_id(arg) != self.target:
            return "Gunakan .rmgc <id grup target>."
        self.invalidate()
        self.store.settings(self.uid)["targets"] = {}
        for account in self.ordered:
            account.peer = None
        self.commit()
        return "Target dihapus."

    async def cmd_keyword(self, arg):
        arg = arg.strip()
        cfg = self.store.settings(self.uid)
        if not arg:
            return "Keywords: " + (", ".join(cfg["keywords"]) or "none")
        if arg.lower() == "clear":
            words = []
        else:
            words = list({normalize(w): w.strip() for w in arg.split(",") if normalize(w)}.values())
            if not words:
                return "Masukkan keyword atau gunakan .keyword clear."
        keep = {normalize(w) for w in words}
        cfg["keywords"] = words
        cfg["prices"] = {k: v for k, v in cfg["prices"].items() if normalize(k) in keep}
        self.commit()
        return f"Keywords set ({len(words)}): " + (", ".join(words) or "none")

    async def cmd_text(self, arg):
        cfg = self.store.settings(self.uid)
        if not arg:
            return "Texts:\n" + (
                "\n".join(f"{i}. {t}" for i, t in enumerate(cfg["texts"], 1)) or "none"
            )
        texts = [] if arg.strip().lower() == "clear" else [t for t in arg.split("|") if t.strip()]
        if not texts and arg.strip().casefold() != "clear":
            return "Masukkan teks promosi atau gunakan .text clear."
        largest_price = max((text_size(p) for p in cfg["prices"].values()), default=0)
        if any(text_size(t) + (largest_price + 2 if largest_price else 0) > 4096 for t in texts):
            return "Text plus price must not exceed 4096 Telegram characters."
        cfg["texts"] = texts
        self.commit()
        return f"Texts set ({len(texts)}):\n" + (
            "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1)) or "none"
        )

    async def cmd_addprice(self, arg):
        arg = arg.strip()
        cfg = self.store.settings(self.uid)
        words = {normalize(word): word for word in cfg["keywords"] if normalize(word)}
        prices = {normalize(key): value for key, value in cfg["prices"].items()}
        usage = "Usage: .addprice <keyword> <text>"
        if not arg:
            rows = [f"{word}: {prices[key]}" for key, word in words.items() if key in prices]
            return usage + "\n\n" + ("\n".join(rows) or "No prices set.")
        if not words:
            return "Set a keyword first with .keyword"
        target = None
        text = ""
        longest = max(map(len, words))
        for boundary in re.finditer(r"\s+|$", arg):
            key = normalize(arg[: boundary.start()])
            if len(key) > longest:
                break
            if key in words:
                target = key
                text = arg[boundary.end() :].strip()
        if target is None:
            return f"Keyword not recognized. Registered: {', '.join(words.values())}\n{usage}"
        word = words[target]
        if not text:
            return f"{word}:\n" + (prices.get(target) or "No price set.")
        if text.casefold() == "clear":
            cfg["prices"] = {
                key: value for key, value in cfg["prices"].items() if normalize(key) != target
            }
            self.commit()
            return f"Price cleared for {word}."
        largest_text = max((text_size(value) for value in cfg["texts"]), default=0)
        if text_size(text) + (largest_text + 2 if largest_text else 0) > 4096:
            return "Price plus text must not exceed 4096 Telegram characters."
        cfg["prices"] = {
            key: value for key, value in cfg["prices"].items() if normalize(key) != target
        }
        cfg["prices"][target] = text
        self.commit()
        return f"Price set for {word}:\n{text}"

    async def cmd_open(self, arg):
        if len(self.accounts) != self.goal or self.target is None:
            return "Lengkapi worker dengan /login dan pilih satu grup dengan .addgc <id>."
        self.store.settings(self.uid)["active"] = True
        self.commit()
        return "Open."

    async def cmd_close(self, arg):
        self.pause(".close")
        return "Closed."

    async def stop(self, logout=False):
        self.stopped = True
        self.epoch += 1
        tasks = list(self.tasks)
        if self.history_task is not None:
            tasks.append(self.history_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for slot, account in self.accounts.items():
            for handler in self.handlers[slot]:
                account.client.remove_event_handler(handler)
            try:
                if logout:
                    await account.client.log_out()
            except (OSError, errors.RPCError):
                log.exception("worker %s: logout failed", slot)
            finally:
                await account.client.disconnect()


@dataclass
class Login:
    stage: str = "count"
    slot: int = 0
    phone: str = ""
    code_hash: str = ""
    signed_in: bool = False
    client: object = None
    timer: object = None

    async def request(self, method, *args, **kwargs):
        redirects = set()
        while True:
            try:
                return await method(*args, **kwargs)
            except MIGRATION_ERRORS as exc:
                dc = exc.new_dc
                if dc != self.client.session.dc_id or dc in redirects or len(redirects) >= 2:
                    raise
                redirects.add(dc)


class Manager:
    def __init__(self, store, ledger):
        self.store = store
        self.ledger = ledger
        self.workers = {}
        self.pending = {}
        self.locks = {}

    def lock(self, uid):
        return self.locks.setdefault(uid, asyncio.Lock())

    def pool(self, uid):
        if uid not in self.workers:
            self.workers[uid] = Pool(uid, self.store, self.ledger)
        return self.workers[uid]

    @staticmethod
    def session(uid, slot):
        return SESSION_DIR / (str(uid) if slot == 1 else f"{uid}_{slot}")

    def slots(self, uid):
        prefix = f"{uid}_"
        slots = {1} if self.session(uid, 1).with_suffix(".session").is_file() else set()
        for path in SESSION_DIR.glob(f"{uid}_*.session"):
            suffix = path.stem[len(prefix) :]
            if suffix.isascii() and suffix.isdecimal() and int(suffix) >= 2:
                slots.add(int(suffix))
        return sorted(slots)

    def make_client(self, uid, slot):
        return TelegramClient(
            str(self.session(uid, slot)),
            API_ID,
            API_HASH,
            catch_up=True,
            flood_sleep_threshold=0,
            connection_retries=3,
            request_retries=0,
            raise_last_call_error=True,
        )

    def purge(self, uid, slot):
        base = self.session(uid, slot).with_suffix(".session")
        for suffix in ("", "-journal", "-shm", "-wal"):
            Path(str(base) + suffix).unlink(missing_ok=True)

    async def attach(self, uid, slot, client):
        me = await client.get_me()
        if me is None:
            raise errors.UnauthorizedError(request=None, message="SESSION_UNAUTHORIZED", code=401)
        if getattr(me, "bot", False):
            raise ValueError("Gunakan akun pengguna Telegram.")
        pool = self.pool(uid)
        target = pool.target
        peer = None
        target_unavailable = False
        if target is not None:
            try:
                peer = await client.get_input_entity(target)
            except ValueError:
                try:
                    entity = await pool.group_entity(client, target)
                    if getattr(entity, "left", False) or getattr(entity, "deactivated", False):
                        raise ValueError("Worker belum menjadi anggota grup.")
                    peer = utils.get_input_peer(entity)
                except (ValueError, errors.NotFoundError, errors.ChannelPrivateError):
                    target_unavailable = True
                except errors.FloodError as exc:
                    pool.rate_limit(exc, target)
            except errors.FloodError as exc:
                pool.rate_limit(exc, target)
        for other in self.workers.values():
            if me.id in other.own_ids:
                raise ValueError("Akun Telegram ini sudah terhubung sebagai worker.")
        pool.add(slot, me.id, client)
        if pool.target == target:
            pool.accounts[slot].peer = peer
            if target_unavailable:
                pool.pause("akses target perlu diperiksa dengan .addgc")

    async def restore_slot(self, uid, slot):
        client = None
        try:
            client = self.make_client(uid, slot)
            await client.connect()
            await self.attach(uid, slot, client)
        except errors.UnauthorizedError:
            if client is not None:
                await client.disconnect()
            self.purge(uid, slot)
            return False
        except Exception:
            log.exception("owner %s: could not restore worker %s", uid, slot)
            if client is not None:
                await client.disconnect()
            return False
        return True

    async def restore(self):
        for uid in self.store.all_users():
            slots = self.slots(uid)
            if not slots:
                continue
            pool = self.pool(uid)
            pool.restoring = True
            try:
                for slot in slots:
                    await self.restore_slot(uid, slot)
            finally:
                pool.restoring = False
            for account in pool.ordered:
                try:
                    await account.client.catch_up()
                except Exception:
                    log.exception("owner %s: catch-up failed for worker %s", uid, account.slot)

    def arm(self, uid, state):
        if state.timer:
            state.timer.cancel()
        state.timer = asyncio.create_task(self.expire(uid, state))

    async def expire(self, uid, state):
        await asyncio.sleep(LOGIN_TTL)
        async with self.lock(uid):
            if self.pending.get(uid) is state:
                await self.drop(uid)

    async def drop(self, uid):
        state = self.pending.pop(uid, None)
        if state is None:
            return
        if state.timer and state.timer is not asyncio.current_task():
            state.timer.cancel()
        await self.release_login_client(uid, state)

    async def release_login_client(self, uid, state):
        if state.client is not None:
            try:
                if state.signed_in:
                    await state.client.log_out()
            except (OSError, errors.RPCError):
                log.warning("worker %s: could not revoke the incomplete login", state.slot)
            finally:
                await state.client.disconnect()
                self.purge(uid, state.slot)
                state.client = None
                state.signed_in = False
        state.phone = ""
        state.code_hash = ""

    async def retry_slot(self, uid, state, reason):
        await self.release_login_client(uid, state)
        return f"{reason}\n{self.prompt_phone(self.pool(uid), state)}"

    async def begin_login(self, uid):
        async with self.lock(uid):
            if not self.store.is_authorized(uid):
                return "Access denied."
            await self.drop(uid)
            state = self.pending[uid] = Login()
            self.arm(uid, state)
            connected = len(self.pool(uid).accounts)
            return f"Berapa worker yang ingin dipakai? Minimal {max(2, connected)}. Sudah terhubung: {connected}."

    def prompt_phone(self, pool, state):
        state.slot = 1
        while state.slot in pool.accounts:
            state.slot += 1
        state.stage = "phone"
        return f"Worker {state.slot}/{pool.goal}: kirim nomor Telegram dengan kode negara."

    async def submit(self, uid, text):
        async with self.lock(uid):
            state = self.pending.get(uid)
            if state is None:
                return None
            if not self.store.is_authorized(uid):
                await self.drop(uid)
                return "Access denied."
            pool = self.pool(uid)
            if state.timer:
                state.timer.cancel()
            try:
                if state.stage == "count":
                    raw = text.strip()
                    if not re.fullmatch(r"[0-9]+", raw) or int(raw) < max(2, len(pool.accounts)):
                        return f"Kirim angka minimal {max(2, len(pool.accounts))}."
                    count = int(raw)
                    if count != pool.goal:
                        pool.invalidate()
                    self.store.settings(uid)["worker_count"] = count
                    pool.commit()
                    if len(pool.accounts) == count:
                        await self.drop(uid)
                        return f"{count} worker siap. Pilih satu grup dengan .addgc <id>."
                    return self.prompt_phone(pool, state)
                if state.stage == "phone":
                    phone = re.sub(r"[\s()-]", "", text.strip())
                    if not re.fullmatch(r"\+?[0-9]{7,15}", phone):
                        return "Nomor tidak valid. Sertakan kode negara."
                    path = self.session(uid, state.slot).with_suffix(".session")
                    if path.exists():
                        if await self.restore_slot(uid, state.slot):
                            if len(pool.accounts) == pool.goal:
                                await self.drop(uid)
                                return f"{pool.goal} worker terhubung."
                            return f"Sesi worker {state.slot} berhasil dipulihkan.\n{self.prompt_phone(pool, state)}"
                        if path.exists():
                            return f"Sesi worker {state.slot} belum bisa dibuka. Periksa log lalu kirim kembali nomor."
                    state.phone = "+" + phone.lstrip("+")
                    state.client = self.make_client(uid, state.slot)
                    await state.client.connect()
                    try:
                        result = await state.request(state.client.send_code_request, state.phone)
                    except RuntimeError:
                        if await state.client.get_me() is None:
                            raise
                    else:
                        state.code_hash = result.phone_code_hash
                        state.stage = "code"
                        return f"Worker {state.slot}: masukkan kode verifikasi Telegram."
                elif state.stage == "code":
                    code = "".join(text.split())
                    if not re.fullmatch(r"[0-9]+", code):
                        return "Kirim kode verifikasi numerik."
                    await state.request(
                        state.client.sign_in, state.phone, code, phone_code_hash=state.code_hash
                    )
                else:
                    await state.request(state.client.sign_in, password=text)
                state.signed_in = True
                await self.attach(uid, state.slot, state.client)
                state.client = None
                state.signed_in = False
                if len(pool.accounts) == pool.goal:
                    await self.drop(uid)
                    return f"{pool.goal} worker terhubung. Gunakan .addgc <id>, .keyword, .text dan .open."
                return self.prompt_phone(pool, state)
            except errors.SessionPasswordNeededError:
                state.stage = "password"
                return f"Worker {state.slot}: masukkan password verifikasi dua langkah."
            except errors.PhoneCodeExpiredError:
                return await self.retry_slot(
                    uid, state, "Kode kedaluwarsa. Minta kode baru untuk worker ini."
                )
            except (errors.PhoneNumberInvalidError, errors.PhoneNumberBannedError) as exc:
                return await self.retry_slot(
                    uid, state, f"Telegram menolak nomor tersebut ({type(exc).__name__})."
                )
            except MIGRATION_ERRORS:
                return await self.retry_slot(
                    uid, state, "Pengalihan pusat data belum selesai. Coba kembali."
                )
            except (errors.PhoneCodeInvalidError, errors.PasswordHashInvalidError):
                return "Kode atau password salah. Silakan ulangi."
            except errors.FloodError as exc:
                await self.drop(uid)
                return f"Telegram membatasi login. Coba /login setelah {getattr(exc, 'seconds', '?')} detik."
            except ValueError as exc:
                if state.stage != "count":
                    return await self.retry_slot(uid, state, f"Login gagal: {exc}.")
                return "Jumlah worker tidak valid."
            except (
                errors.RPCError,
                OSError,
                asyncio.TimeoutError,
                RuntimeError,
                sqlite3.Error,
            ) as exc:
                log.warning(
                    "owner %s worker %s: login failed (%s)", uid, state.slot, type(exc).__name__
                )
                await self.drop(uid)
                return f"Login gagal ({type(exc).__name__}). Lanjutkan dengan /login."
            finally:
                if self.pending.get(uid) is state:
                    self.arm(uid, state)

    async def logout(self, uid):
        async with self.lock(uid):
            await self.drop(uid)
            pool = self.workers.pop(uid, None)
            if pool:
                await pool.stop(logout=True)
            for slot in self.slots(uid):
                self.purge(uid, slot)
            return "Login dibatalkan dan seluruh sesi worker lokal dihapus."

    async def monitor_history(self):
        while True:
            for pool in tuple(self.workers.values()):
                pool.start_history_check()
            await asyncio.sleep(HISTORY_INTERVAL)

    async def shutdown(self):
        for uid in list(self.pending):
            async with self.lock(uid):
                await self.drop(uid)
        for pool in self.workers.values():
            await pool.stop()


def register_panel(bot, store, manager):
    def private(event):
        return event.is_private

    def waiting(event):
        return (
            event.is_private
            and event.sender_id in manager.pending
            and not re.match(
                r"(?i)^/(?:start|login|logout|adduser|deluser|users)(?:@\w+)?(?:\s|$)",
                event.raw_text or "",
            )
        )

    async def deny(event):
        await event.respond(f"Access denied. Send this ID to the owner: {event.sender_id}")

    @bot.on(events.NewMessage(incoming=True, pattern=r"(?i)^/start(?:@\w+)?$", func=private))
    async def start(event):
        if not store.is_authorized(event.sender_id):
            return await deny(event)
        await event.respond(PANEL_HELP)

    @bot.on(
        events.NewMessage(
            incoming=True, pattern=r"(?is)^/login(?:@\w+)?(?:\s+(.+))?$", func=private
        )
    )
    async def login(event):
        uid = event.sender_id
        if not store.is_authorized(uid):
            return await deny(event)
        await event.respond(await manager.begin_login(uid))

    @bot.on(events.NewMessage(incoming=True, func=waiting))
    async def secret(event):
        uid = event.sender_id
        text = event.raw_text or ""
        try:
            await event.delete()
        except errors.RPCError:
            pass
        if uid not in manager.pending:
            return
        reply = await manager.submit(uid, text)
        if reply:
            await event.respond(reply)

    @bot.on(events.NewMessage(incoming=True, pattern=r"(?i)^/logout(?:@\w+)?$", func=private))
    async def logout(event):
        uid = event.sender_id
        if not store.is_authorized(uid):
            return await deny(event)
        await event.respond(await manager.logout(uid))

    @bot.on(
        events.NewMessage(
            incoming=True, pattern=r"(?i)^/adduser(?:@\w+)?(?:\s+(\d+))?$", func=private
        )
    )
    async def adduser(event):
        if event.sender_id != OWNER_ID:
            return await event.respond("Owner only.")
        raw = event.pattern_match.group(1)
        if not raw:
            return await event.respond("Usage: /adduser <user_id>")
        uid = int(raw)
        if not store.add_user(uid):
            return await event.respond("Already authorized.")
        await event.respond(f"User {uid} authorized.")
        try:
            await bot.send_message(uid, "You are authorized. Send /login to connect your workers.")
        except Exception:
            pass

    @bot.on(
        events.NewMessage(
            incoming=True, pattern=r"(?i)^/deluser(?:@\w+)?(?:\s+(\d+))?$", func=private
        )
    )
    async def deluser(event):
        if event.sender_id != OWNER_ID:
            return await event.respond("Owner only.")
        raw = event.pattern_match.group(1)
        if not raw:
            return await event.respond("Usage: /deluser <user_id>")
        uid = int(raw)
        if uid == OWNER_ID:
            return await event.respond("The owner cannot be removed.")
        removed = store.remove_user(uid)
        await manager.logout(uid)
        await event.respond(f"User {uid} removed." if removed else "User was not authorized.")

    @bot.on(events.NewMessage(incoming=True, pattern=r"(?i)^/users(?:@\w+)?$", func=private))
    async def users(event):
        if event.sender_id != OWNER_ID:
            return await event.respond("Owner only.")
        rows = [
            f"{uid} - {'online' if uid in manager.workers and manager.workers[uid].accounts else 'offline'}"
            for uid in store.all_users()
        ]
        for chunk in split_text("Authorized users\n" + "\n".join(rows)):
            await event.respond(chunk)


class ChannelSyncWarning(logging.Handler):
    pattern = re.compile(
        r"Getting difference for channel updates (\d+) caused PersistentTimestamp(?:Outdated|Invalid)Error"
    )

    def __init__(self, manager):
        super().__init__(logging.WARNING)
        self.manager = manager
        self.loop = asyncio.get_running_loop()

    def emit(self, record):
        match = self.pattern.search(record.getMessage())
        if match and not self.loop.is_closed():
            chat = utils.get_peer_id(PeerChannel(int(match[1])))
            self.loop.call_soon_threadsafe(self.check_target, chat)

    def check_target(self, chat):
        for pool in self.manager.workers.values():
            if pool.target == chat:
                pool.start_history_check()


async def main():
    os.umask(0o077)
    SESSION_DIR.mkdir(exist_ok=True)
    os.chmod(SESSION_DIR, 0o700)
    store = Store(DATA_FILE)
    ledger = Ledger(SESSION_DIR / "deliveries.sqlite3")
    manager = Manager(store, ledger)
    bot = TelegramClient(str(SESSION_DIR / "panel"), API_ID, API_HASH, connection_retries=-1)
    bot.parse_mode = None
    register_panel(bot, store, manager)
    monitor = None
    updates_log = logging.getLogger("telethon.client.updates")
    warning_handler = ChannelSyncWarning(manager)
    updates_log.addHandler(warning_handler)
    try:
        await manager.restore()
        monitor = asyncio.create_task(manager.monitor_history())
        await bot.start(bot_token=BOT_TOKEN)
        log.info("panel online")
        await bot.run_until_disconnected()
    finally:
        updates_log.removeHandler(warning_handler)
        warning_handler.close()
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        await manager.shutdown()
        await ledger.close()
        await bot.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
