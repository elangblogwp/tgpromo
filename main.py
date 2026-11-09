import asyncio
import json
import logging
import os
import random
import re
import time
from collections import OrderedDict
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, errors, events, functions, utils
from telethon.tl.types import Channel, Chat, PeerChannel

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
SEND_GAP = float(os.getenv("SEND_GAP", "0.5"))
MAX_FLOOD_WAIT = int(os.getenv("MAX_FLOOD_WAIT", "120"))

BASE_DIR = Path(__file__).resolve().parent
SESSION_DIR = BASE_DIR / "sessions"
DATA_FILE = BASE_DIR / "data.json"
SERVICE_ID = 777000
SEEN_LIMIT = 4096
MAX_POST_LEN = 99
CHAT_GAP = 1.0
QUEUE_LIMIT = 256
MUTE_SECONDS = 600
LOGIN_TTL = 300
CHUNK = 4000

COMMAND_RE = r"(?is)^\.(help|ping|listgc|addgc|rmgc|addallgc|keyword|text|addprice|open|close)(?:[ \n](.*))?$"

HELP_TEXT = "\n".join(
    (
        "「 Ruby UBot BETA 」",
        "",
        ".help",
        ".ping",
        ".listgc",
        ".addgc <group id>",
        ".rmgc <group id>",
        ".addallgc",
        ".keyword <a, b, c>",
        ".text <a|b|c>",
        ".addprice <keyword> <text>",
        ".open",
        ".close",
        "",
        "Made with love by @Ruby_Supremacy",
    )
)

PANEL_HELP = (
    "Panel commands\n\n"
    "/login <telegram_number> - connect your account\n"
    "/logout - disconnect your account\n"
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
    "(?:[\U0001F1E6-\U0001F1FF]{2}"
    f"|[0-9#*]{_VS16}?\u20e3"
    "|\U0001F3F4[\U000E0020-\U000E007E]+\U000E007F"
    f"|{_BASE}(?:[\U0001F3FB-\U0001F3FF]|{_VS16})?)"
)
EMOJI_RE = re.compile(f"{_ITEM}(?:\u200d{_ITEM})*")


def _scan(text):
    return () if text.isascii() else EMOJI_RE.finditer(text)


def content_emojis(text):
    found = []
    pos = 0
    leading = True
    for match in _scan(text):
        if leading and not text[pos:match.start()].strip():
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
    extra = [item for item in extra if item.replace(_VS16, "") not in present]
    if not extra:
        return template
    separator = "" if template[-1:].isspace() else " "
    return template + separator + "".join(extra)


def parse_group_id(arg):
    try:
        value = int(arg.strip())
    except ValueError:
        return None
    return utils.get_peer_id(PeerChannel(value)) if value > 0 else value


class Store:
    def __init__(self, path):
        self.path = path
        self.data = {"users": [], "settings": {}}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                log.exception("could not read %s", path)

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
        cfg.setdefault("active", True)
        return cfg


class Worker:
    def __init__(self, uid, client, store):
        self.uid = uid
        self.client = client
        self.store = store
        self.me_id = 0
        self.active = True
        self.pattern = None
        self.prices = []
        self.texts = []
        self.targets = set()
        self.cooldown = {}
        self.chat_sent = {}
        self.queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self.seen = OrderedDict()
        self.last_send = 0.0
        self.started = time.monotonic()
        self.tasks = []
        self.reload()

    def reload(self):
        cfg = self.store.settings(self.uid)
        words = cfg["keywords"]
        self.active = cfg["active"]
        self.pattern = (
            re.compile("|".join(f"(?P<k{i}>{re.escape(w)})" for i, w in enumerate(words)), re.IGNORECASE)
            if words
            else None
        )
        self.prices = [cfg["prices"].get(w.lower()) for w in words]
        self.texts = list(cfg["texts"])
        self.targets = {int(key) for key in cfg["targets"]}

    def commit(self):
        self.store.save()
        self.reload()

    async def start(self):
        me = await self.client.get_me()
        self.me_id = me.id
        self.client.add_event_handler(self.on_post, events.NewMessage(incoming=True))
        self.client.add_event_handler(self.on_command, events.NewMessage(outgoing=True, pattern=COMMAND_RE))
        self.tasks = [asyncio.create_task(self.sender()), asyncio.create_task(self.warmup())]

    async def warmup(self):
        try:
            async for _ in self.client.iter_dialogs():
                pass
        except Exception:
            log.warning("user %s: dialog warmup failed", self.uid)

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        try:
            await self.client.log_out()
        except Exception:
            log.exception("user %s: logout failed", self.uid)
            await self.client.disconnect()

    async def on_post(self, event):
        if not (self.active and self.pattern and self.texts and self.targets):
            return
        msg = event.message
        text = msg.message
        if not text or len(text) > MAX_POST_LEN or msg.out or msg.post:
            return
        chat_id = msg.chat_id
        if chat_id not in self.targets or self.cooldown.get(chat_id, 0.0) > time.monotonic():
            return
        fwd = msg.fwd_from
        if fwd is None or not fwd.channel_post:
            return
        sender = msg.sender_id
        if sender is None or sender == self.me_id:
            return
        if sender != SERVICE_ID and (fwd.from_id is None or sender != utils.get_peer_id(fwd.from_id)):
            return
        match = self.pattern.search(text)
        if match is None:
            return
        key = (chat_id, msg.grouped_id or msg.id)
        if key in self.seen:
            return
        self.seen[key] = None
        if len(self.seen) > SEEN_LIMIT:
            self.seen.popitem(last=False)
        try:
            self.queue.put_nowait((msg, self.prices[int(match.lastgroup[1:])]))
        except asyncio.QueueFull:
            log.warning("user %s: queue full, post skipped", self.uid)

    async def sender(self):
        while True:
            msg, price = await self.queue.get()
            try:
                await self.reply(msg, price)
            except Exception:
                log.exception("user %s: reply failed", self.uid)

    async def reply(self, msg, price):
        chat_id = msg.chat_id
        if not (self.active and self.texts) or self.cooldown.get(chat_id, 0.0) > time.monotonic():
            return
        body = random.choice(self.texts)
        text = build_reply(f"{price}\n\n{body}" if price else body, msg.message)
        pause = max(self.last_send + SEND_GAP, self.chat_sent.get(chat_id, 0.0) + CHAT_GAP) - time.monotonic()
        if pause > 0:
            await asyncio.sleep(pause)
        for _ in range(2):
            if not self.active:
                return
            try:
                await self.client.send_message(msg.peer_id, text, reply_to=msg.id, parse_mode=None)
            except errors.SlowModeWaitError as e:
                self.cooldown[chat_id] = time.monotonic() + getattr(e, "seconds", 60)
                return
            except errors.FloodError as e:
                wait = getattr(e, "seconds", 0) + 1
                if wait > MAX_FLOOD_WAIT:
                    log.warning("user %s: flood wait %ss, skipped", self.uid, wait)
                    return
                await asyncio.sleep(wait)
            except (errors.ForbiddenError, errors.UserBannedInChannelError):
                self.cooldown[chat_id] = time.monotonic() + MUTE_SECONDS
                log.info("user %s: cannot write in %s, muted", self.uid, chat_id)
                return
            except errors.RPCError as e:
                log.warning("user %s: %s", self.uid, e.__class__.__name__)
                return
            else:
                self.last_send = self.chat_sent[chat_id] = time.monotonic()
                return
        log.warning("user %s: flood retries exhausted in %s", self.uid, chat_id)

    async def on_command(self, event):
        name = event.pattern_match.group(1).lower()
        arg = event.pattern_match.group(2) or ""
        try:
            text = await getattr(self, f"cmd_{name}")(arg)
        except errors.FloodError as e:
            text = f"Rate limited. Retry in {getattr(e, 'seconds', '?')}s."
        except Exception:
            log.exception("user %s: command %s failed", self.uid, name)
            text = "Command failed."
        await self.respond(event, text)

    async def respond(self, event, text):
        chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [" "]
        try:
            await event.edit(chunks[0], parse_mode=None)
            for chunk in chunks[1:]:
                await self.client.send_message(event.chat_id, chunk, parse_mode=None)
        except errors.MessageNotModifiedError:
            pass
        except errors.RPCError as e:
            log.warning("user %s: respond failed: %s", self.uid, e.__class__.__name__)

    async def cmd_help(self, arg):
        return HELP_TEXT

    async def cmd_ping(self, arg):
        t0 = time.perf_counter()
        await self.client(functions.PingRequest(ping_id=random.getrandbits(62)))
        latency = (time.perf_counter() - t0) * 1000
        hours, rest = divmod(int(time.monotonic() - self.started), 3600)
        minutes, seconds = divmod(rest, 60)
        return f"Pong\nLatency: {latency:.0f} ms\nUptime: {hours}h {minutes}m {seconds}s"

    async def cmd_listgc(self, arg):
        targets = self.store.settings(self.uid)["targets"]
        if not targets:
            return "No target groups. Use .addgc <group id> or .addallgc."
        rows = [f"{i}. {name} ({gid})" for i, (gid, name) in enumerate(targets.items(), 1)]
        return f"Target groups ({len(rows)})\n\n" + "\n".join(rows)

    async def cmd_addgc(self, arg):
        gid = parse_group_id(arg)
        if gid is None:
            return "Usage: .addgc <group id>"
        targets = self.store.settings(self.uid)["targets"]
        if str(gid) in targets:
            return "Already in the target list."
        try:
            entity = await self.client.get_entity(gid)
        except (ValueError, errors.RPCError):
            return "Group not found. Make sure the account has joined it."
        if not (isinstance(entity, Chat) or (isinstance(entity, Channel) and entity.megagroup)):
            return "That ID is not a group."
        key = str(utils.get_peer_id(entity))
        if key in targets:
            return "Already in the target list."
        targets[key] = utils.get_display_name(entity)
        self.commit()
        return f"Added: {targets[key]} ({key})\nTotal targets: {len(targets)}"

    async def cmd_rmgc(self, arg):
        gid = parse_group_id(arg)
        if gid is None:
            return "Usage: .rmgc <group id>"
        targets = self.store.settings(self.uid)["targets"]
        name = targets.pop(str(gid), None)
        if name is None:
            return "Not in the target list."
        self.commit()
        return f"Removed: {name} ({gid})\nTotal targets: {len(targets)}"

    async def cmd_addallgc(self, arg):
        found = {}
        async for dialog in self.client.iter_dialogs(ignore_migrated=True):
            if dialog.is_group:
                found[str(dialog.id)] = dialog.name
        targets = self.store.settings(self.uid)["targets"]
        new = {key: name for key, name in found.items() if key not in targets}
        targets.update(new)
        self.commit()
        return f"Added {len(new)} group(s).\nTotal targets: {len(targets)}"

    async def cmd_keyword(self, arg):
        arg = arg.strip()
        cfg = self.store.settings(self.uid)
        if not arg:
            return "Keywords: " + (", ".join(cfg["keywords"]) or "none")
        if arg.lower() == "clear":
            words = []
        else:
            words = list({w.strip().lower(): w.strip() for w in arg.split(",") if w.strip()}.values())
        keep = {w.lower() for w in words}
        cfg["keywords"] = words
        cfg["prices"] = {k: v for k, v in cfg["prices"].items() if k in keep}
        self.commit()
        return f"Keywords set ({len(words)}): " + (", ".join(words) or "none")

    async def cmd_text(self, arg):
        cfg = self.store.settings(self.uid)
        if not arg:
            return "Texts:\n" + ("\n".join(f"{i}. {t}" for i, t in enumerate(cfg["texts"], 1)) or "none")
        texts = [] if arg.strip().lower() == "clear" else [t for t in arg.split("|") if t.strip()]
        cfg["texts"] = texts
        self.commit()
        return f"Texts set ({len(texts)}):\n" + ("\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1)) or "none")

    async def cmd_addprice(self, arg):
        cfg = self.store.settings(self.uid)
        words = cfg["keywords"]
        usage = "Usage: .addprice <keyword> <text>"
        if not arg.strip():
            rows = [f"{w}: {cfg['prices'][w.lower()]}" for w in words if w.lower() in cfg["prices"]]
            return usage + "\n\n" + ("\n".join(rows) or "No prices set.")
        for word in sorted(words, key=len, reverse=True):
            if arg[:len(word)].casefold() == word.casefold() and (len(arg) == len(word) or arg[len(word)].isspace()):
                target, text = word, arg[len(word):].strip()
                break
        else:
            if not words:
                return "Set a keyword first with .keyword"
            if len(words) > 1:
                return f"Keyword not recognized. Registered: {', '.join(words)}\n{usage}"
            target, text = words[0], arg.strip()
        if not text:
            return usage
        key = target.lower()
        if text.lower() == "clear":
            cfg["prices"].pop(key, None)
            self.commit()
            return f"Price cleared for {target}."
        cfg["prices"][key] = text
        self.commit()
        return f"Price set for {target}:\n{text}"

    async def cmd_open(self, arg):
        self.store.settings(self.uid)["active"] = True
        self.commit()
        return "Open. Keyword detection and auto-replies are on."

    async def cmd_close(self, arg):
        self.store.settings(self.uid)["active"] = False
        self.commit()
        while not self.queue.empty():
            self.queue.get_nowait()
        return "Closed. Auto-replies are paused. Send .open to resume."


class Manager:
    def __init__(self, store):
        self.store = store
        self.workers = {}
        self.pending = {}
        self.busy = set()

    @staticmethod
    def session_file(uid):
        return SESSION_DIR / str(uid)

    def make_client(self, uid):
        return TelegramClient(
            str(self.session_file(uid)),
            API_ID,
            API_HASH,
            flood_sleep_threshold=0,
            connection_retries=-1,
        )

    def has_session(self, uid):
        return self.session_file(uid).with_suffix(".session").exists()

    @staticmethod
    def secure(uid):
        for path in SESSION_DIR.glob(f"{uid}.session*"):
            os.chmod(path, 0o600)

    @staticmethod
    def purge(uid):
        for path in SESSION_DIR.glob(f"{uid}.session*"):
            path.unlink(missing_ok=True)

    async def discard(self, client, uid):
        await client.disconnect()
        self.purge(uid)

    async def activate(self, uid, client):
        worker = Worker(uid, client, self.store)
        await worker.start()
        self.workers[uid] = worker
        self.secure(uid)

    async def restore(self):
        async def load(uid):
            client = self.make_client(uid)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    return
                await self.activate(uid, client)
                log.info("user %s: userbot online", uid)
            except Exception:
                log.exception("user %s: restore failed", uid)
                await client.disconnect()

        ids = [uid for uid in self.store.all_users() if self.has_session(uid)]
        await asyncio.gather(*(load(uid) for uid in ids))

    async def begin_login(self, uid, phone):
        self.busy.add(uid)
        try:
            await self.cancel_login(uid)
            client = self.make_client(uid)
            await client.connect()
            try:
                sent = await client.send_code_request(phone)
            except Exception:
                await self.discard(client, uid)
                raise
            state = {"client": client, "phone": phone, "hash": sent.phone_code_hash, "stage": "code", "busy": False}
            self.pending[uid] = state
            state["task"] = asyncio.create_task(self.expire(uid, client))
        finally:
            self.busy.discard(uid)

    async def expire(self, uid, client):
        await asyncio.sleep(LOGIN_TTL)
        state = self.pending.get(uid)
        if state and state["client"] is client:
            self.pending.pop(uid)
            await self.discard(client, uid)

    async def cancel_login(self, uid):
        state = self.pending.pop(uid, None)
        if state:
            state["task"].cancel()
            await self.discard(state["client"], uid)
            return True
        return False

    async def submit(self, uid, text):
        state = self.pending.get(uid)
        if state is None or state["busy"]:
            return None
        state["busy"] = True
        try:
            return await self.advance(uid, state, text)
        finally:
            state["busy"] = False

    async def advance(self, uid, state, text):
        client = state["client"]
        try:
            if state["stage"] == "code":
                digits = re.sub(r"\D", "", text)
                if not digits:
                    return "Send the numeric code."
                await client.sign_in(state["phone"], digits, phone_code_hash=state["hash"])
            else:
                await client.sign_in(password=text)
        except errors.SessionPasswordNeededError:
            state["stage"] = "password"
            return "Two-step verification is enabled. Send your password."
        except errors.PhoneCodeInvalidError:
            return "Invalid code. Try again."
        except errors.PasswordHashInvalidError:
            return "Wrong password. Try again."
        except errors.PhoneCodeExpiredError:
            await self.cancel_login(uid)
            return "Code expired. Send /login again."
        except errors.FloodError as e:
            await self.cancel_login(uid)
            return f"Too many attempts. Retry in {getattr(e, 'seconds', '?')}s."
        except Exception as e:
            log.exception("user %s: login failed", uid)
            await self.cancel_login(uid)
            return f"Login failed ({e.__class__.__name__}). Send /login to retry."
        state["task"].cancel()
        self.pending.pop(uid, None)
        await self.activate(uid, client)
        return "Logged in. The userbot is online. Send .help from your account."

    async def logout(self, uid):
        worker = self.workers.pop(uid, None)
        if worker is None:
            return False
        await worker.stop()
        self.purge(uid)
        return True


def register_panel(bot, store, manager):
    def private(event):
        return event.is_private

    def waiting(event):
        return event.is_private and event.sender_id in manager.pending and not (event.raw_text or "").startswith("/")

    async def deny(event):
        await event.respond(f"Access denied. Send this ID to the owner: {event.sender_id}")

    @bot.on(events.NewMessage(pattern=r"(?i)^/start(?:@\w+)?$", func=private))
    async def start(event):
        if not store.is_authorized(event.sender_id):
            return await deny(event)
        await event.respond(PANEL_HELP)

    @bot.on(events.NewMessage(pattern=r"(?is)^/login(?:@\w+)?(?:\s+(.+))?$", func=private))
    async def login(event):
        uid = event.sender_id
        if not store.is_authorized(uid):
            return await deny(event)
        if uid in manager.workers:
            return await event.respond("Already logged in. Send /logout first.")
        if uid in manager.busy:
            return await event.respond("Please wait a moment.")
        raw = event.pattern_match.group(1)
        if not raw:
            return await event.respond("Usage: /login <telegram_number>\nExample: /login +628123456789")
        digits = re.sub(r"\D", "", raw)
        if not 7 <= len(digits) <= 15:
            return await event.respond("Invalid number. Use international format, e.g. +628123456789")
        try:
            await manager.begin_login(uid, "+" + digits)
        except errors.FloodError as e:
            return await event.respond(f"Too many attempts. Retry in {getattr(e, 'seconds', '?')}s.")
        except errors.PhoneNumberInvalidError:
            return await event.respond("Telegram rejected that number.")
        except errors.PhoneNumberBannedError:
            return await event.respond("That number is banned by Telegram.")
        except errors.RPCError as e:
            log.warning("user %s: send code failed: %s", uid, e.__class__.__name__)
            return await event.respond(f"Could not send the code ({e.__class__.__name__}).")
        await event.respond(
            "Code sent to your Telegram app.\n"
            "Reply with the code with spaces between the digits, e.g. 1 2 3 4 5, "
            "otherwise Telegram may block it."
        )

    @bot.on(events.NewMessage(func=waiting))
    async def secret(event):
        uid = event.sender_id
        text = event.raw_text.strip()
        try:
            await event.delete()
        except errors.RPCError:
            pass
        if uid not in manager.pending:
            return
        reply = await manager.submit(uid, text)
        if reply:
            await event.respond(reply)

    @bot.on(events.NewMessage(pattern=r"(?i)^/logout(?:@\w+)?$", func=private))
    async def logout(event):
        uid = event.sender_id
        if not store.is_authorized(uid):
            return await deny(event)
        if await manager.logout(uid):
            return await event.respond("Logged out and session deleted.")
        if await manager.cancel_login(uid):
            return await event.respond("Login cancelled.")
        await event.respond("Not logged in.")

    @bot.on(events.NewMessage(pattern=r"(?i)^/adduser(?:@\w+)?(?:\s+(\d+))?$", func=private))
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
            await bot.send_message(uid, "You are authorized. Send /login <your_number> to connect your account.")
        except Exception:
            pass

    @bot.on(events.NewMessage(pattern=r"(?i)^/deluser(?:@\w+)?(?:\s+(\d+))?$", func=private))
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
        await manager.cancel_login(uid)
        await manager.logout(uid)
        await event.respond(f"User {uid} removed." if removed else "User was not authorized.")

    @bot.on(events.NewMessage(pattern=r"(?i)^/users(?:@\w+)?$", func=private))
    async def users(event):
        if event.sender_id != OWNER_ID:
            return await event.respond("Owner only.")
        rows = [f"{uid} - {'online' if uid in manager.workers else 'offline'}" for uid in store.all_users()]
        await event.respond("Authorized users\n" + "\n".join(rows))


async def main():
    SESSION_DIR.mkdir(exist_ok=True)
    os.chmod(SESSION_DIR, 0o700)
    store = Store(DATA_FILE)
    manager = Manager(store)
    bot = TelegramClient(str(SESSION_DIR / "panel"), API_ID, API_HASH, connection_retries=-1)
    bot.parse_mode = None
    register_panel(bot, store, manager)
    await manager.restore()
    await bot.start(bot_token=BOT_TOKEN)
    log.info("panel online")
    try:
        await bot.run_until_disconnected()
    finally:
        await asyncio.gather(*(w.client.disconnect() for w in manager.workers.values()), return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
