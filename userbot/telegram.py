import asyncio
import logging

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

WAIT_ERRORS = (errors.FloodWaitError, errors.FloodPremiumWaitError, errors.SlowModeWaitError)
AUTH_ERRORS = (errors.AuthKeyError, errors.UnauthorizedError)
LOG = logging.getLogger("userbot")


def new_client(settings, session=""):
    client = TelegramClient(
        StringSession(session),
        settings.api_id,
        settings.api_hash,
        device_model="Discussion Userbot",
        system_version="Python",
        app_version="1.0.0",
        flood_sleep_threshold=0,
        request_retries=0,
        connection_retries=5,
        retry_delay=2,
        auto_reconnect=True,
        catch_up=False,
        raise_last_call_error=True,
        entity_cache_limit=1000,
    )
    client.parse_mode = None
    return client


async def rpc(awaitable):
    async with asyncio.timeout(30):
        return await awaitable


async def disconnect(client):
    if client:
        try:
            await rpc(client.disconnect())
        except Exception as exc:
            LOG.warning("Disconnect failed: %s", type(exc).__name__)
