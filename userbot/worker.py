import io
import secrets
import time
from datetime import UTC, datetime

from telethon import errors, events, functions, types, utils

from .policy import matches, original_post, parse_values, verified_root
from .telegram import AUTH_ERRORS, LOG, WAIT_ERRORS, rpc

HELP = """Discussion Userbot
Send these commands in Saved Messages:

.help — Show this menu
.ping — Measure Telegram round-trip and command response time
.listgc — List joined Telegram groups and their IDs
.keyword <one,two> — Set case-insensitive substring keywords
.keyword — Show keywords
.keyword --clear — Remove keywords
.text <one|two> — Set promotional text variations
.text — Show text variations
.text --clear — Remove text variations
.watch <group_id> — Enable a linked discussion group you may promote in
.unwatch <group_id> — Remove a discussion group
.on — Enable automatic replies
.off — Pause automatic replies
.status — Show settings and last processing result

Only verified original channel posts can trigger replies.
Comments, your messages, old posts, and duplicate posts are ignored.
Configure keywords, texts, and at least one group before .on.
"""


class Worker:
    def __init__(self, service, user_id, client, preferences):
        self.service = service
        self.settings = service.settings
        self.store = service.store
        self.user_id = user_id
        self.client = client
        self.preferences = preferences
        self.started = int(time.time())
        self.links = {}
        self.last_result = "Waiting for a new original post"

    def install(self):
        self.client.add_event_handler(self.incoming, events.NewMessage(incoming=True))
        self.client.add_event_handler(
            self.command, events.NewMessage(outgoing=True, pattern=r"^\.")
        )

    def uninstall(self):
        self.client.remove_event_handler(self.incoming)
        self.client.remove_event_handler(self.command)

    async def linked_channel(self, group, source=None):
        group_id = utils.get_peer_id(group)
        cached = self.links.get(group_id)
        if cached and cached[0] > time.monotonic():
            if source is not None and cached[1] != source:
                return None
            return cached[2]
        full = await rpc(self.client(functions.channels.GetFullChannelRequest(group)))
        channel_id = getattr(full.full_chat, "linked_chat_id", None)
        entity = next((chat for chat in full.chats if chat.id == channel_id), None)
        peer = None
        if channel_id:
            peer = (
                utils.get_input_peer(entity)
                if entity
                else await rpc(self.client.get_input_entity(types.PeerChannel(channel_id)))
            )
        self.links[group_id] = (time.monotonic() + 600, channel_id, peer)
        return peer if source is None or channel_id == source else None

    async def incoming(self, event):
        message = event.message
        post = original_post(message)
        preferences = self.preferences
        if (
            not post
            or not preferences.enabled
            or event.chat_id not in preferences.groups
            or not preferences.texts
            or not matches(message.message, preferences.keywords)
        ):
            return
        async with self.service.guard(self.user_id):
            if self.service.workers.get(self.user_id) is not self:
                return
            preferences = self.preferences
            if (
                not preferences.enabled
                or event.chat_id not in preferences.groups
                or not preferences.texts
                or not matches(message.message, preferences.keywords)
                or not await self.store.allowed(self.user_id)
            ):
                return
            now = time.time()
            age = now - message.date.timestamp()
            if (
                message.date.timestamp() < self.started
                or not -5 <= age <= self.settings.max_post_age
            ):
                return
            if await self.store.seen(self.user_id, post.group_id, post.key):
                self.last_result = "Duplicate original post ignored"
                return
            if await self.blocked(post.group_id):
                self.last_result = "Telegram cooldown active; post skipped"
                return
            if not await self.store.can_send(
                self.user_id,
                now,
                self.settings.min_reply_interval,
                self.settings.max_replies_per_hour,
            ):
                self.last_result = "Configured rate limit; post skipped"
                return
            reserved = False
            try:
                group = await rpc(event.get_input_chat())
                source = await self.linked_channel(group, post.channel_id)
                if not source:
                    self.last_result = "Forward does not match the linked channel"
                    return
                discussion = await rpc(
                    self.client(
                        functions.messages.GetDiscussionMessageRequest(
                            peer=source,
                            msg_id=post.post_id,
                        )
                    )
                )
                root = verified_root(discussion.messages, message, post)
                if root is None:
                    self.last_result = "Not the canonical original discussion post"
                    return
                if time.time() - message.date.timestamp() > self.settings.max_post_age:
                    self.last_result = "Post expired during verification"
                    return
                random_id = await self.store.reserve(
                    self.user_id,
                    post.group_id,
                    post.key,
                    root.id,
                    time.time(),
                    self.settings.min_reply_interval,
                    self.settings.max_replies_per_hour,
                )
                if random_id is None:
                    self.last_result = "Duplicate or configured rate limit; post skipped"
                    return
                reserved = True
                await rpc(
                    self.client(
                        functions.messages.SendMessageRequest(
                            peer=group,
                            message=secrets.choice(preferences.texts),
                            random_id=random_id,
                            reply_to=types.InputReplyToMessage(
                                reply_to_msg_id=root.id, top_msg_id=root.id
                            ),
                            send_as=types.InputPeerSelf(),
                            no_webpage=True,
                            entities=[],
                            allow_paid_stars=0,
                        )
                    )
                )
                await self.store.mark(self.user_id, post.group_id, post.key, "sent")
                self.last_result = f"Reply sent to original post {root.id}"
            except WAIT_ERRORS as exc:
                key = (
                    f"group:{self.user_id}:{post.group_id}"
                    if isinstance(exc, errors.SlowModeWaitError)
                    else f"account:{self.user_id}"
                )
                await self.store.block(key, time.time() + exc.seconds)
                if reserved:
                    await self.store.mark(self.user_id, post.group_id, post.key, "rate_limited")
                self.last_result = f"Telegram requires a {exc.seconds}s cooldown; post skipped"
            except (errors.PeerFloodError, *AUTH_ERRORS) as exc:
                self.preferences.enabled = False
                await self.store.save_preferences(self.user_id, self.preferences)
                if reserved:
                    await self.store.mark(self.user_id, post.group_id, post.key, "blocked")
                self.last_result = f"Paused: {type(exc).__name__}; check Telegram before resuming"
            except (
                errors.ChatWriteForbiddenError,
                errors.ChatRestrictedError,
                errors.UserBannedInChannelError,
                errors.ChatAdminRequiredError,
            ) as exc:
                self.preferences.groups = [
                    item for item in preferences.groups if item != event.chat_id
                ]
                await self.store.save_preferences(self.user_id, self.preferences)
                if reserved:
                    await self.store.mark(self.user_id, post.group_id, post.key, "forbidden")
                self.last_result = f"Group disabled: {type(exc).__name__}"
            except Exception as exc:
                if reserved:
                    await self.store.mark(self.user_id, post.group_id, post.key, "uncertain")
                self.last_result = f"Skipped: {type(exc).__name__}"
                LOG.warning("User %s processing failed: %s", self.user_id, type(exc).__name__)

    async def blocked(self, group_id=None):
        now = time.time()
        if await self.store.blocked_until(f"account:{self.user_id}") > now:
            return True
        return (
            group_id is not None
            and await self.store.blocked_until(f"group:{self.user_id}:{group_id}") > now
        )

    async def output(self, event, text):
        if len(text.encode("utf-16-le")) // 2 <= 3500:
            await rpc(event.edit(text, parse_mode=None, link_preview=False))
        else:
            document = io.BytesIO(text.encode())
            document.name = "userbot-results.txt"
            await rpc(self.client.send_file("me", document, caption="Userbot results"))
            await rpc(event.edit("Results sent as a text file.", parse_mode=None))

    async def command(self, event):
        if event.chat_id != self.user_id or event.sender_id != self.user_id or event.fwd_from:
            return
        async with self.service.guard(self.user_id):
            if self.service.workers.get(self.user_id) is not self or not await self.store.allowed(
                self.user_id
            ):
                return
            if await self.blocked():
                return
            try:
                text = await self.run_command(event)
                if text is not None:
                    await self.output(event, text)
            except WAIT_ERRORS as exc:
                await self.store.block(f"account:{self.user_id}", time.time() + exc.seconds)
                self.last_result = f"Telegram cooldown: {exc.seconds}s"
            except (errors.MessageNotModifiedError, errors.MessageIdInvalidError):
                pass
            except ValueError as exc:
                try:
                    await self.output(event, str(exc))
                except WAIT_ERRORS as wait:
                    await self.store.block(f"account:{self.user_id}", time.time() + wait.seconds)
                except Exception:
                    pass
            except Exception as exc:
                self.last_result = f"Command failed: {type(exc).__name__}"
                LOG.warning("User %s command failed: %s", self.user_id, type(exc).__name__)

    async def run_command(self, event):
        command, _, argument = event.raw_text.partition(" ")
        argument = argument.strip()
        preferences = self.preferences
        match command.casefold():
            case ".help":
                return HELP
            case ".ping":
                start = time.perf_counter()
                await rpc(self.client(functions.PingRequest(ping_id=secrets.randbits(63))))
                rtt = (time.perf_counter() - start) * 1000
                await rpc(event.edit("Measuring response…", parse_mode=None))
                response = (time.perf_counter() - start) * 1000
                return (
                    f"Pong\nTelegram round-trip: {rtt:.1f} ms\nCommand response: {response:.1f} ms"
                )
            case ".listgc":
                lines = []
                async for dialog in self.client.iter_dialogs():
                    if dialog.is_group:
                        lines.append(f"{dialog.name} | {dialog.id}")
                return "Joined groups\n\n" + ("\n".join(lines) or "No groups found")
            case ".keyword" | ".text":
                attr = "keywords" if command.casefold() == ".keyword" else "texts"
                if argument:
                    values = (
                        []
                        if argument == "--clear"
                        else parse_values(
                            argument.casefold() if attr == "keywords" else argument,
                            "," if attr == "keywords" else "|",
                            50 if attr == "keywords" else 10,
                            128 if attr == "keywords" else 2000,
                        )
                    )
                    setattr(preferences, attr, values)
                    if not values:
                        preferences.enabled = False
                    await self.store.save_preferences(self.user_id, preferences)
                return (
                    attr.capitalize()
                    + ":\n"
                    + ("\n".join(getattr(preferences, attr)) or "None configured")
                )
            case ".watch" | ".unwatch":
                try:
                    group_id = int(argument)
                except ValueError:
                    raise ValueError(
                        "Use .watch <group_id> or .unwatch <group_id>; see .listgc"
                    ) from None
                _, peer_type = utils.resolve_id(group_id)
                if peer_type != types.PeerChannel:
                    raise ValueError(
                        "Use a discussion supergroup ID starting with -100 from .listgc"
                    )
                if command.casefold() == ".unwatch":
                    preferences.groups = [item for item in preferences.groups if item != group_id]
                else:
                    if len(preferences.groups) >= 100 and group_id not in preferences.groups:
                        raise ValueError("Maximum 100 selected discussion groups per account")
                    peer = None
                    async for dialog in self.client.iter_dialogs():
                        if dialog.id == group_id and dialog.is_group:
                            peer = dialog.input_entity
                            break
                    if peer is None:
                        raise ValueError("Join this discussion group manually first")
                    self.links.pop(group_id, None)
                    if not await self.linked_channel(peer):
                        raise ValueError("This group has no linked channel")
                    preferences.groups = list(dict.fromkeys([*preferences.groups, group_id]))
                if not preferences.groups:
                    preferences.enabled = False
                await self.store.save_preferences(self.user_id, preferences)
                return "Selected discussion groups:\n" + (
                    "\n".join(map(str, preferences.groups)) or "None"
                )
            case ".on":
                if not preferences.keywords or not preferences.texts or not preferences.groups:
                    raise ValueError("Configure .keyword, .text, and .watch first")
                preferences.enabled = True
                await self.store.save_preferences(self.user_id, preferences)
                return (
                    "Automatic replies enabled for selected discussion groups. Use .off to pause."
                )
            case ".off":
                preferences.enabled = False
                await self.store.save_preferences(self.user_id, preferences)
                return "Automatic replies paused."
            case ".status":
                return await self.status()
        return None

    async def status(self):
        until = await self.store.blocked_until(f"account:{self.user_id}")
        cooldown = datetime.fromtimestamp(until, UTC).isoformat() if until > time.time() else "None"
        return (
            f"Auto-reply: {'on' if self.preferences.enabled else 'off'}\n"
            f"Keywords: {', '.join(self.preferences.keywords) or 'none'}\n"
            f"Text variations: {len(self.preferences.texts)}\n"
            f"Selected groups: {', '.join(map(str, self.preferences.groups)) or 'none'}\n"
            f"Limits: {self.settings.min_reply_interval}s minimum, "
            f"{self.settings.max_replies_per_hour}/hour\n"
            f"Account cooldown until: {cooldown}\n"
            f"Last result: {self.last_result}"
        )
