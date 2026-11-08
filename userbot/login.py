import asyncio
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

from telethon import errors

from .telegram import LOG, WAIT_ERRORS, disconnect, new_client, rpc


class LoginError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass
class Pending:
    user_id: int
    phone: str
    expires: float
    link_hash: str
    cookie_hash: str = ""
    csrf: str = ""
    step: str = "send"
    client: object = None
    phone_code_hash: str = ""
    attempts: int = 0


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Login:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.settings = service.settings
        self.pending = {}
        self.links = {}
        self.cookies = {}
        self.code_guard = asyncio.Lock()

    async def issue(self, user_id, phone):
        if not re.fullmatch(r"\+[1-9][0-9]{6,14}", phone):
            raise LoginError("Use /login +countrycodephonenumber, with digits only after +")
        async with self.service.guard(user_id):
            if not await self.store.allowed(user_id):
                raise LoginError("Access denied", 403)
            if user_id in self.service.workers:
                raise LoginError("Already connected. Use /status or /logout first.")
            if await self.store.session(user_id):
                raise LoginError(
                    "A saved session is reconnecting. Check /status shortly, or use /logout before a new login."
                )
            await self.cancel_locked(user_id)
            token = secrets.token_urlsafe(32)
            pending = Pending(
                user_id, phone, time.monotonic() + self.settings.login_ttl, digest(token)
            )
            self.pending[user_id] = pending
            self.links[pending.link_hash] = pending
            return f"{self.settings.public_base_url}/#{token}"

    async def cancel_locked(self, user_id):
        pending = self.pending.pop(user_id, None)
        if pending:
            self.links.pop(pending.link_hash, None)
            self.cookies.pop(pending.cookie_hash, None)
            if pending.client:
                await disconnect(pending.client)
            pending.phone = ""
            pending.phone_code_hash = ""
            pending.csrf = ""

    async def check_locked(self, pending):
        if self.pending.get(pending.user_id) is not pending:
            raise LoginError("This login is no longer active. Start again with /login.", 401)
        if pending.expires <= time.monotonic() or not await self.store.allowed(pending.user_id):
            await self.cancel_locked(pending.user_id)
            raise LoginError("Login expired or access was removed. Start again with /login.", 401)

    async def exchange(self, token):
        pending = self.links.get(digest(token)) if len(token) <= 128 else None
        if pending is None:
            raise LoginError(
                "This link is invalid, expired, or already opened. Request a new /login.", 401
            )
        async with self.service.guard(pending.user_id):
            await self.check_locked(pending)
            if self.links.pop(pending.link_hash, None) is not pending:
                raise LoginError("This link was already opened. Request a new /login.", 401)
            cookie = secrets.token_urlsafe(32)
            pending.cookie_hash = digest(cookie)
            pending.csrf = secrets.token_urlsafe(32)
            self.cookies[pending.cookie_hash] = pending
            return cookie, pending.csrf, pending.phone[-4:]

    async def action(self, cookie, csrf, action, value=""):
        pending = self.cookies.get(digest(cookie)) if len(cookie) <= 128 else None
        if not pending or not hmac.compare_digest(pending.csrf, csrf):
            raise LoginError("Login session is invalid. Request a new /login.", 401)
        async with self.service.guard(pending.user_id):
            await self.check_locked(pending)
            if action == "cancel":
                await self.cancel_locked(pending.user_id)
                return {"step": "cancelled", "message": "Login cancelled."}
            blocked = await self.store.blocked_until(f"login:{pending.user_id}")
            if blocked > time.time():
                raise LoginError(
                    f"Wait {max(1, int(blocked - time.time()) + 1)} seconds before trying again.",
                    429,
                )
            if pending.step == "send" and action == "send":
                return await self.send_code_locked(pending)
            if pending.step not in {"code", "password"} or action != "verify":
                raise LoginError("Invalid login step. Start again with /login.")
            if pending.step == "code" and not re.fullmatch(r"[0-9]{4,8}", value):
                raise LoginError("Enter the numeric login code from Telegram.")
            if pending.step == "password" and not 1 <= len(value) <= 1024:
                raise LoginError("Enter your Telegram two-step verification password.")
            try:
                if pending.step == "code":
                    await rpc(
                        pending.client.sign_in(
                            phone=pending.phone,
                            code=value,
                            phone_code_hash=pending.phone_code_hash,
                        )
                    )
                else:
                    await rpc(pending.client.sign_in(password=value))
                return await self.complete_locked(pending)
            except errors.SessionPasswordNeededError:
                pending.step = "password"
                return {
                    "step": "password",
                    "message": "Enter your Telegram two-step verification password.",
                }
            except (errors.PhoneCodeInvalidError, errors.PasswordHashInvalidError):
                pending.attempts += 1
                if pending.attempts >= 5:
                    await self.store.block(f"login:{pending.user_id}", time.time() + 300)
                    await self.cancel_locked(pending.user_id)
                    raise LoginError(
                        "Too many incorrect attempts. Wait five minutes, then use /login.", 429
                    ) from None
                raise LoginError("Incorrect code or password. Please try again.") from None
            except errors.PhoneCodeExpiredError:
                await self.cancel_locked(pending.user_id)
                raise LoginError("Telegram expired the code. Request a fresh /login.") from None
            except WAIT_ERRORS as exc:
                await self.store.block(f"login:{pending.user_id}", time.time() + exc.seconds)
                raise LoginError(f"Telegram requires a {exc.seconds}-second wait.", 429) from None
            except LoginError:
                raise
            except Exception as exc:
                await self.cancel_locked(pending.user_id)
                LOG.warning("Login verification failed: %s", type(exc).__name__)
                raise LoginError(
                    "Telegram login could not complete. Request a new /login.", 502
                ) from None

    async def send_code_locked(self, pending):
        phone_key = hmac.new(
            self.settings.session_key.encode(), pending.phone.encode(), hashlib.sha256
        ).hexdigest()
        keys = [f"code:{pending.user_id}", f"phone:{phone_key}"]
        async with self.code_guard:
            now = time.time()
            until = max([await self.store.blocked_until(key) for key in keys])
            if until > now:
                raise LoginError(
                    f"Wait {int(until - now) + 1} seconds before requesting another code.", 429
                )
            for key in keys:
                await self.store.block(key, now + self.settings.login_cooldown)
        pending.client = new_client(self.settings)
        try:
            await rpc(pending.client.connect())
            sent = await rpc(pending.client.send_code_request(pending.phone))
            if not getattr(sent, "phone_code_hash", None):
                raise LoginError("Telegram requires a login method this panel does not support.")
            kind = type(sent.type).__name__
            if kind in {
                "SentCodeTypeSetUpEmailRequired",
                "SentCodeTypeEmailCode",
                "SentCodeTypeFirebaseSms",
            }:
                raise LoginError(
                    "Telegram requires an email or app-specific login flow. Use an official client to resolve it."
                )
            pending.phone_code_hash = sent.phone_code_hash
            pending.step = "code"
            return {
                "step": "code",
                "message": "Enter the verification code Telegram sends to your app, phone, or call.",
            }
        except WAIT_ERRORS as exc:
            for key in [*keys, f"login:{pending.user_id}"]:
                await self.store.block(key, time.time() + exc.seconds)
            await self.cancel_locked(pending.user_id)
            raise LoginError(
                f"Telegram requires a {exc.seconds}-second wait. Try /login later.", 429
            ) from None
        except (errors.PhoneNumberInvalidError, errors.PhoneNumberBannedError):
            await self.cancel_locked(pending.user_id)
            raise LoginError("Telegram rejected this phone number.") from None
        except LoginError:
            await self.cancel_locked(pending.user_id)
            raise
        except Exception as exc:
            await self.cancel_locked(pending.user_id)
            LOG.warning("Code request failed: %s", type(exc).__name__)
            raise LoginError(
                "Unable to request a code. Try /login later or check your Telegram account.", 502
            ) from None

    async def complete_locked(self, pending):
        me = await rpc(pending.client.get_me())
        if me is None or me.bot or me.id != pending.user_id:
            try:
                await rpc(pending.client.log_out())
            finally:
                await self.cancel_locked(pending.user_id)
            raise LoginError(
                "You may only connect the same Telegram account that opened the bot.", 403
            )
        await self.check_locked(pending)
        await self.service.attach_locked(pending.user_id, pending.client)
        pending.client = None
        await self.cancel_locked(pending.user_id)
        return {
            "step": "done",
            "message": "Account connected. Open Saved Messages and send .help to configure your userbot.",
        }

    async def cleanup(self):
        while True:
            await asyncio.sleep(30)
            for user_id, pending in list(self.pending.items()):
                if pending.expires <= time.monotonic():
                    async with self.service.guard(user_id):
                        if self.pending.get(user_id) is pending:
                            await self.cancel_locked(user_id)

    async def close(self):
        for user_id in list(self.pending):
            async with self.service.guard(user_id):
                await self.cancel_locked(user_id)
