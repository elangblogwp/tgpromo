from unittest.mock import AsyncMock

from userbot.login import Login
from userbot.panel import Panel


def event(user_id, text):
    value = AsyncMock()
    value.is_private = True
    value.sender_id = user_id
    value.chat_id = user_id
    value.fwd_from = None
    value.raw_text = text
    return value


async def test_non_owner_cannot_add_authorized_user(service, store):
    await store.grant(200, 25)
    panel = Panel(AsyncMock(), service, Login(service))
    message = event(200, "/adduser 300")
    await panel.handle(message)
    assert not await store.allowed(300)
    assert "Only" in message.respond.call_args.args[0]


async def test_owner_can_add_user(service, store):
    panel = Panel(AsyncMock(), service, Login(service))
    await panel.handle(event(100, "/adduser 200"))
    assert await store.allowed(200)


async def test_unauthorized_user_cannot_open_login(service):
    login = Login(service)
    panel = Panel(AsyncMock(), service, login)
    await panel.handle(event(200, "/login +15551234567"))
    assert not login.pending


async def test_group_commands_ignored(service, store):
    panel = Panel(AsyncMock(), service, Login(service))
    message = event(100, "/adduser 200")
    message.is_private = False
    await panel.handle(message)
    assert not await store.allowed(200)


async def test_revocation_cancels_active_link(service, store):
    login = Login(service)
    await store.grant(200, 25)
    await login.issue(200, "+15551234567")
    panel = Panel(AsyncMock(), service, login)
    await panel.handle(event(100, "/deluser 200"))
    assert not login.pending
    assert not await store.allowed(200)


async def test_owner_cannot_remove_self(service, store):
    panel = Panel(AsyncMock(), service, Login(service))
    await panel.handle(event(100, "/deluser 100"))
    assert await store.allowed(100)
