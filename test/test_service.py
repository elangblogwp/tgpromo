import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from telethon import errors


async def test_saved_session_restores(service, store, client, monkeypatch):
    await store.save_session(100, "saved-session")
    monkeypatch.setattr("userbot.service.new_client", lambda settings, session: client)
    client.get_me.return_value = SimpleNamespace(id=100, bot=False)
    await service.restore()
    assert service.workers[100].client is client
    client.connect.assert_awaited_once()
    client.disconnect.assert_not_awaited()


async def test_invalid_session_is_removed(service, store, client, monkeypatch):
    await store.save_session(100, "saved-session")
    monkeypatch.setattr("userbot.service.new_client", lambda settings, session: client)
    client.get_me.side_effect = errors.AuthKeyUnregisteredError(None)
    await service.restore()
    assert not service.workers
    assert not await store.session(100)
    client.disconnect.assert_awaited_once()


async def test_restore_respects_flood_wait(service, store, client, monkeypatch):
    await store.save_session(100, "saved-session")
    monkeypatch.setattr("userbot.service.new_client", lambda settings, session: client)
    client.get_me.side_effect = errors.FloodWaitError(None, capture=60)
    await service.restore()
    await service.restore()
    assert not service.workers
    assert await store.session(100)
    assert client.connect.await_count == 1
    assert await store.blocked_until("account:100") > time.time()


async def test_transient_restore_failure_keeps_session_and_backs_off(
    service, store, client, monkeypatch
):
    await store.save_session(100, "saved-session")
    monkeypatch.setattr("userbot.service.new_client", lambda settings, session: client)
    client.connect.side_effect = OSError()
    await service.restore()
    await service.restore()
    assert await store.session(100)
    assert client.connect.await_count == 1
    client.disconnect.assert_awaited_once()


async def test_online_worker_needs_no_periodic_api_requests(service, store, worker, client):
    await store.save_session(100, "saved-session")
    client.is_connected = MagicMock(return_value=True)
    await service.restore()
    client.connect.assert_not_awaited()
    client.get_me.assert_not_awaited()
    assert service.workers[100] is worker


async def test_logout_stops_worker_even_when_remote_revocation_fails(
    service, store, worker, client
):
    await store.save_session(100, "saved-session")
    await store.save_preferences(100, worker.preferences)
    client.log_out.side_effect = OSError()
    async with service.guard(100):
        assert await service.logout_locked(100) is False
    assert not service.workers
    assert not await store.session(100)
    assert (await store.preferences(100)).enabled is False
    client.disconnect.assert_awaited_once()
