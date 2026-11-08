import asyncio
import io
import time

from telethon import Button, events, functions, types

from .login import LoginError
from .telegram import LOG, WAIT_ERRORS, rpc

PANEL_HELP = """Discussion Userbot

/login +countrycodephonenumber — Connect your own Telegram account
/status — Show connection and reply settings
/cancel — Cancel an unfinished login
/logout — Stop the userbot and remove its session
/id — Show your Telegram user ID

Owner commands:
/adduser <user_id> — Authorize a user
/deluser <user_id> — Revoke access and stop their userbot
/users — List authorized user IDs

After login, configure the userbot in Saved Messages with .help.
Never send verification codes or passwords to this bot.
"""


class Panel:
    def __init__(self, bot, service, login):
        self.bot = bot
        self.service = service
        self.store = service.store
        self.login = login
        self.owner_id = service.settings.owner_id
        self.next_message = {}
        self.guard = asyncio.Lock()

    async def install(self):
        self.bot.add_event_handler(self.handle, events.NewMessage(incoming=True))
        commands = [
            ("start", "Open the login and management panel"),
            ("login", "Connect your own account: /login +phone"),
            ("adduser", "Owner: authorize a user ID"),
            ("deluser", "Owner: revoke a user ID"),
            ("users", "Owner: list authorized users"),
            ("status", "Show your connection and reply settings"),
            ("cancel", "Cancel an unfinished login"),
            ("logout", "Disconnect and remove your session"),
            ("id", "Show your Telegram user ID"),
        ]
        try:
            if await self.store.blocked_until("panel") <= time.time():
                await rpc(
                    self.bot(
                        functions.bots.SetBotCommandsRequest(
                            scope=types.BotCommandScopeDefault(),
                            lang_code="",
                            commands=[
                                types.BotCommand(name, description)
                                for name, description in commands
                            ],
                        )
                    )
                )
        except WAIT_ERRORS as exc:
            await self.store.block("panel", time.time() + exc.seconds)
        except Exception as exc:
            LOG.warning("Could not register bot commands: %s", type(exc).__name__)

    async def respond(self, event, text, buttons=None):
        if len(text.encode("utf-16-le")) // 2 > 3500:
            document = io.BytesIO(text.encode())
            document.name = "panel-results.txt"
            await rpc(self.bot.send_file(event.chat_id, document, caption="Userbot panel results"))
        else:
            await rpc(event.respond(text, buttons=buttons, parse_mode=None, link_preview=False))

    async def handle(self, event):
        if not event.is_private or not event.sender_id or event.fwd_from:
            return
        async with self.guard:
            if await self.store.blocked_until("panel") > time.time():
                return
            user_id = event.sender_id
            now = time.monotonic()
            if self.next_message.get(user_id, 0) > now:
                return
            self.next_message = {
                key: value for key, value in self.next_message.items() if value > now
            }
            self.next_message[user_id] = now + 1
            command, _, argument = event.raw_text.strip().partition(" ")
            command = command.split("@", 1)[0].casefold()
            argument = argument.strip()
            try:
                if command == "/id":
                    await self.respond(event, f"Your Telegram user ID: {user_id}")
                    return
                if not await self.store.allowed(user_id):
                    await self.respond(
                        event,
                        f"Access is restricted. Ask the owner to authorize user ID {user_id}.",
                    )
                    return
                if command in {"/adduser", "/deluser", "/users"}:
                    if user_id != self.owner_id:
                        await self.respond(event, "Only the configured owner can manage users.")
                        return
                    await self.manage(event, command, argument)
                    return
                match command:
                    case "/start" | "/help":
                        await self.respond(event, PANEL_HELP)
                    case "/login":
                        link = await self.login.issue(user_id, argument)
                        await self.respond(
                            event,
                            "Open your private login page below. It expires shortly and can be opened once. "
                            "Enter your code and two-step password only on that page. "
                            "Connect only your own account and only if you trust this server's operator.",
                            [[Button.url("Connect my Telegram account", link)]],
                        )
                        try:
                            await rpc(event.delete())
                        except WAIT_ERRORS:
                            raise
                        except Exception:
                            pass
                    case "/cancel":
                        async with self.service.guard(user_id):
                            await self.login.cancel_locked(user_id)
                        await self.respond(event, "Pending login cancelled.")
                    case "/logout":
                        async with self.service.guard(user_id):
                            await self.login.cancel_locked(user_id)
                            revoked = await self.service.logout_locked(user_id)
                        await self.respond(event, self.logout_text(revoked))
                    case "/status":
                        async with self.service.guard(user_id):
                            worker = self.service.workers.get(user_id)
                            status = (
                                await worker.status()
                                if worker
                                else "Not connected. Use /login +your_number."
                            )
                        await self.respond(event, status)
                    case _:
                        await self.respond(
                            event,
                            "Use /start to open the panel. Never send codes or passwords here.",
                        )
            except (LoginError, ValueError) as exc:
                try:
                    await self.respond(event, str(exc))
                except WAIT_ERRORS as wait:
                    await self.store.block("panel", time.time() + wait.seconds)
                except Exception:
                    pass
            except WAIT_ERRORS as exc:
                await self.store.block("panel", time.time() + exc.seconds)
            except Exception as exc:
                LOG.warning("Bot command failed: %s", type(exc).__name__)

    async def manage(self, event, command, argument):
        if command == "/users":
            await self.respond(
                event, "Authorized user IDs:\n" + "\n".join(map(str, await self.store.users()))
            )
            return
        if not argument.isascii() or not argument.isdigit() or not 0 < int(argument) < 2**63:
            raise ValueError(f"Use {command} <positive_numeric_user_id>")
        user_id = int(argument)
        async with self.service.guard(user_id):
            if command == "/adduser":
                await self.store.grant(user_id, self.service.settings.max_users)
                text = f"User {user_id} is authorized. They can now open this bot and use /login."
            else:
                await self.store.revoke(user_id)
                await self.login.cancel_locked(user_id)
                revoked = await self.service.logout_locked(user_id)
                text = f"Access removed for {user_id}. " + self.logout_text(revoked)
        await self.respond(event, text)

    @staticmethod
    def logout_text(revoked):
        return "Userbot stopped and session removed." + (
            " Telegram session revoked."
            if revoked
            else " Telegram could not confirm remote revocation. Terminate the Discussion Userbot "
            "session in Telegram Settings → Devices."
        )
