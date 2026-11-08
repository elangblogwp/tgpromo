from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from telethon import types

from userbot.config import Settings
from userbot.service import Service
from userbot.store import Preferences, Store
from userbot.worker import Worker


@pytest.fixture
def settings(tmp_path):
    return Settings(
        api_id=12345,
        api_hash="a" * 32,
        bot_token="12345:" + "a" * 32,
        owner_id=100,
        session_key=Fernet.generate_key().decode(),
        public_base_url="https://login.example.test",
        data_dir=tmp_path,
        min_reply_interval=1,
        max_replies_per_hour=6,
    )


@pytest_asyncio.fixture
async def store(settings):
    database = Store(settings.data_dir / "test.sqlite3", settings.session_key, settings.owner_id)
    await database.open()
    yield database
    await database.close()


@pytest.fixture
def service(settings, store):
    return Service(settings, store)


@pytest.fixture
def client():
    result = AsyncMock()
    result.session = SimpleNamespace(save=lambda: "test-session-secret")
    result.add_event_handler = MagicMock()
    result.remove_event_handler = MagicMock()
    return result


def post(text="Anyone selling noktel?", mid=42, source=500, group=700, post_id=11, **kwargs):
    return types.Message(
        id=mid,
        peer_id=types.PeerChannel(group),
        from_id=types.PeerChannel(source),
        date=datetime.now(UTC),
        message=text,
        fwd_from=types.MessageFwdHeader(
            date=datetime.now(UTC),
            from_id=types.PeerChannel(source),
            channel_post=post_id,
        ),
        **kwargs,
    )


def event(message):
    return SimpleNamespace(
        message=message,
        chat_id=-1000000000700,
        sender_id=-1000000000500,
        get_input_chat=AsyncMock(return_value=types.InputPeerChannel(700, 1)),
    )


@pytest.fixture
def worker(service, client):
    preferences = Preferences(
        keywords=["noktel", "netflix", "spotify"],
        texts=["Ready stock, DM me!"],
        groups=[-1000000000700],
        enabled=True,
    )
    result = Worker(service, 100, client, preferences)
    result.started = 0
    result.linked_channel = AsyncMock(return_value=types.InputPeerChannel(500, 2))
    service.workers[100] = result
    return result
