import asyncio
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from telethon import errors

from userbot.login import Login, LoginError


@pytest_asyncio.fixture
async def login(service, client, monkeypatch):
    monkeypatch.setattr("userbot.login.new_client", lambda settings: client)
    client.send_code_request.return_value = SimpleNamespace(
        phone_code_hash="hash", type=SimpleNamespace()
    )
    client.get_me.return_value = SimpleNamespace(id=100, bot=False)
    result = Login(service)
    yield result
    await result.close()


async def start(login, user_id=100, phone="+15551234567"):
    url = await login.issue(user_id, phone)
    cookie, csrf, suffix = await login.exchange(url.split("#")[1])
    assert suffix == phone[-4:]
    await login.action(cookie, csrf, "send")
    return cookie, csrf


async def test_only_authorized_users_can_get_link(login):
    with pytest.raises(LoginError) as result:
        await login.issue(200, "+15551234567")
    assert result.value.status == 403


@pytest.mark.parametrize("phone", ["1234567", "+001234567", "+1 555 123", "invalid", "+1"])
async def test_phone_format(login, phone):
    with pytest.raises(LoginError):
        await login.issue(100, phone)


async def test_one_time_link_consumption(login):
    url = await login.issue(100, "+15551234567")
    token = url.split("#")[1]
    await login.exchange(token)
    with pytest.raises(LoginError):
        await login.exchange(token)


async def test_concurrent_link_exchange_only_one_succeeds(login):
    url = await login.issue(100, "+15551234567")
    results = await asyncio.gather(
        *(login.exchange(url.split("#")[1]) for _ in range(5)), return_exceptions=True
    )
    assert sum(isinstance(result, tuple) for result in results) == 1


async def test_expired_link(login):
    url = await login.issue(100, "+15551234567")
    login.pending[100].expires = 0
    with pytest.raises(LoginError):
        await login.exchange(url.split("#")[1])


async def test_revoked_access_blocks_pending_login(login, store):
    await store.grant(200, 25)
    url = await login.issue(200, "+15551234567")
    await store.revoke(200)
    with pytest.raises(LoginError):
        await login.exchange(url.split("#")[1])


async def test_csrf_rejected(login, client):
    cookie, csrf = await start(login)
    with pytest.raises(LoginError):
        await login.action(cookie, "bad-token", "verify", "12345")
    client.sign_in.assert_not_awaited()


async def test_successful_login_keeps_only_encrypted_session(login, service, client, store):
    cookie, csrf = await start(login)
    result = await login.action(cookie, csrf, "verify", "12345")
    assert result["step"] == "done"
    assert 100 in service.workers
    assert not login.pending and not login.cookies
    assert await store.session(100) == "test-session-secret"
    assert "15551234567" not in str(await store.all("SELECT * FROM sessions"))
    client.sign_in.assert_awaited_once_with(
        phone="+15551234567", code="12345", phone_code_hash="hash"
    )
    with pytest.raises(LoginError):
        await login.action(cookie, csrf, "verify", "12345")


async def test_two_step_password(login, client):
    cookie, csrf = await start(login)
    client.sign_in.side_effect = [errors.SessionPasswordNeededError(None), None]
    first = await login.action(cookie, csrf, "verify", "12345")
    assert first["step"] == "password"
    second = await login.action(cookie, csrf, "verify", "private-password")
    assert second["step"] == "done"
    assert client.sign_in.call_args.kwargs == {"password": "private-password"}


async def test_account_cannot_impersonate_another_id(login, client, service, store):
    cookie, csrf = await start(login)
    client.get_me.return_value = SimpleNamespace(id=200, bot=False)
    with pytest.raises(LoginError) as result:
        await login.action(cookie, csrf, "verify", "12345")
    assert result.value.status == 403
    assert not service.workers
    assert not await store.session(100)
    client.log_out.assert_awaited_once()
    assert not login.pending


async def test_incorrect_attempt_limit(login, client, store):
    cookie, csrf = await start(login)
    client.sign_in.side_effect = errors.PhoneCodeInvalidError(None)
    for _ in range(5):
        with pytest.raises(LoginError):
            await login.action(cookie, csrf, "verify", "11111")
    assert not login.pending
    assert await store.blocked_until("login:100") > time.time() + 290


async def test_expired_code_cancels(login, client):
    cookie, csrf = await start(login)
    client.sign_in.side_effect = errors.PhoneCodeExpiredError(None)
    with pytest.raises(LoginError):
        await login.action(cookie, csrf, "verify", "11111")
    assert not login.pending


async def test_code_request_cooldown_survives_new_link(login, client):
    await start(login)
    url = await login.issue(100, "+15551234567")
    cookie, csrf, _ = await login.exchange(url.split("#")[1])
    with pytest.raises(LoginError) as result:
        await login.action(cookie, csrf, "send")
    assert result.value.status == 429
    assert client.send_code_request.await_count == 1


async def test_floodwait_on_verification_is_honored(login, client, store):
    cookie, csrf = await start(login)
    client.sign_in.side_effect = errors.FloodWaitError(None, capture=90)
    with pytest.raises(LoginError):
        await login.action(cookie, csrf, "verify", "12345")
    assert await store.blocked_until("login:100") > time.time() + 85
    with pytest.raises(LoginError):
        await login.action(cookie, csrf, "verify", "12345")
    assert client.sign_in.await_count == 1


async def test_cancellation_clears_pending_secrets(login, client):
    cookie, csrf = await start(login)
    pending = login.pending[100]
    result = await login.action(cookie, csrf, "cancel")
    assert result["step"] == "cancelled"
    assert pending.phone == "" and pending.phone_code_hash == ""
    assert not login.pending and not login.cookies and not login.links
    client.disconnect.assert_awaited()


async def test_saved_session_cannot_be_silently_overwritten(login, store):
    await store.save_session(100, "old-session")
    with pytest.raises(LoginError):
        await login.issue(100, "+15551234567")
    assert await store.session(100) == "old-session"
