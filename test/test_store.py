import asyncio
import time

import pytest
from cryptography.fernet import Fernet, InvalidToken

from userbot.store import Store


async def test_encrypted_session_round_trip(store):
    await store.save_session(100, "sensitive-telegram-session")
    row = await store.one("SELECT value FROM sessions WHERE id=100")
    assert b"sensitive-telegram-session" not in row[0]
    assert await store.session(100) == "sensitive-telegram-session"


async def test_wrong_key_rejected(store, settings):
    other = Store(store.path, Fernet.generate_key().decode(), settings.owner_id)
    try:
        with pytest.raises(InvalidToken):
            await other.open()
    finally:
        await other.close()


async def test_duplicate_claim_survives_reopen(store, settings):
    first = await store.reserve(100, 700, "500:post:11", 42, time.time() - 5, 1, 6)
    assert first
    other = Store(store.path, settings.session_key, settings.owner_id)
    try:
        await other.open()
        assert await other.reserve(100, 700, "500:post:11", 42, time.time(), 1, 6) is None
        assert await other.seen(100, 700, "500:post:11")
    finally:
        await other.close()


async def test_atomic_concurrent_claims(store):
    values = await asyncio.gather(
        *[store.reserve(100, 700, "same", 42, time.time(), 0, 100) for _ in range(15)]
    )
    assert sum(value is not None for value in values) == 1


async def test_hourly_rate_and_account_isolation(store):
    for index in range(3):
        assert await store.reserve(100, 700, str(index), index, time.time() - 10 + index, 0, 3)
    assert await store.reserve(100, 700, "next", 99, time.time(), 0, 3) is None
    assert await store.reserve(101, 700, "next", 99, time.time(), 0, 3)


async def test_owner_cannot_be_revoked(store):
    with pytest.raises(ValueError):
        await store.revoke(100)
    assert await store.allowed(100)


async def test_grant_limit_and_revocation(store):
    await store.grant(200, 2)
    assert await store.allowed(200)
    with pytest.raises(ValueError):
        await store.grant(300, 2)
    await store.revoke(200)
    assert not await store.allowed(200)
    await store.grant(300, 2)
    assert await store.allowed(300)


async def test_cooldown_never_shortens(store):
    await store.block("account:100", 9999)
    await store.block("account:100", 10)
    assert await store.blocked_until("account:100") == 9999
