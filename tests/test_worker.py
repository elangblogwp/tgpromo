import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from telethon import errors, functions, types

from .conftest import event, post


def successful_reply(worker, message):
    worker.client.side_effect = [SimpleNamespace(messages=[message]), SimpleNamespace()]


async def test_matching_original_replies_to_exact_thread(worker):
    message = post()
    successful_reply(worker, message)
    await worker.incoming(event(message))
    assert worker.client.await_count == 2
    request = worker.client.call_args_list[-1].args[0]
    assert isinstance(request, functions.messages.SendMessageRequest)
    assert request.reply_to.reply_to_msg_id == 42
    assert request.reply_to.top_msg_id == 42
    assert request.peer.channel_id == 700
    assert isinstance(request.send_as, types.InputPeerSelf)
    assert request.message == "Ready stock, DM me!"
    assert request.no_webpage is True
    assert request.allow_paid_stars == 0


@pytest.mark.parametrize(
    "kind", ["comment", "no_keyword", "self", "stale", "wrong_group", "disabled", "no_text"]
)
async def test_ignored_events_make_no_api_requests(worker, kind):
    message = post()
    if kind == "comment":
        message.message = "I also need noktel, does anyone have it?"
        message.from_id = types.PeerUser(200)
        message.reply_to = types.MessageReplyHeader(reply_to_msg_id=42)
    elif kind == "no_keyword":
        message.message = "Looking for a cheap premium account."
    elif kind == "self":
        message.out = True
    elif kind == "stale":
        message.date = datetime.now(UTC) - timedelta(minutes=10)
    elif kind == "wrong_group":
        worker.preferences.groups = []
    elif kind == "disabled":
        worker.preferences.enabled = False
    else:
        worker.preferences.texts = []
    await worker.incoming(event(message))
    worker.client.assert_not_awaited()
    worker.linked_channel.assert_not_awaited()


async def test_duplicate_concurrent_updates_send_once(worker):
    message = post()
    successful_reply(worker, message)
    await asyncio.gather(*(worker.incoming(event(message)) for _ in range(10)))
    assert worker.client.await_count == 2


async def test_forged_forward_does_not_reply(worker):
    worker.client.return_value = SimpleNamespace(messages=[post(mid=42)])
    await worker.incoming(event(post(mid=99)))
    assert worker.client.await_count == 1
    assert "canonical" in worker.last_result


async def test_wrong_linked_channel_is_ignored(worker):
    worker.linked_channel.return_value = None
    await worker.incoming(event(post()))
    worker.client.assert_not_awaited()


async def test_timeout_after_send_is_not_retried(worker, store):
    message = post()
    worker.client.side_effect = [SimpleNamespace(messages=[message]), TimeoutError()]
    await worker.incoming(event(message))
    worker.preferences = await store.preferences(100)
    worker.preferences.enabled = True
    worker.preferences.groups = [-1000000000700]
    worker.preferences.keywords = ["noktel"]
    worker.preferences.texts = ["promo"]
    await worker.incoming(event(message))
    assert worker.client.await_count == 2
    row = await store.one("SELECT state FROM deliveries")
    assert row[0] == "uncertain"


async def test_flood_wait_persists_and_blocks_new_posts(worker, store):
    message = post()
    worker.client.side_effect = [
        SimpleNamespace(messages=[message]),
        errors.FloodWaitError(None, capture=120),
    ]
    await worker.incoming(event(message))
    assert await store.blocked_until("account:100") > time.time() + 115
    await worker.incoming(event(post(mid=43, post_id=12)))
    assert worker.client.await_count == 2


async def test_slow_mode_is_scoped_to_group(worker, store):
    message = post()
    worker.client.side_effect = [
        SimpleNamespace(messages=[message]),
        errors.SlowModeWaitError(None, capture=20),
    ]
    await worker.incoming(event(message))
    assert await store.blocked_until("group:100:700") > time.time()
    assert await store.blocked_until("account:100") == 0


async def test_peer_flood_pauses_account(worker):
    message = post()
    worker.client.side_effect = [SimpleNamespace(messages=[message]), errors.PeerFloodError(None)]
    await worker.incoming(event(message))
    assert worker.preferences.enabled is False


async def test_permissions_error_disables_group(worker):
    message = post()
    worker.client.side_effect = [
        SimpleNamespace(messages=[message]),
        errors.ChatWriteForbiddenError(None),
    ]
    await worker.incoming(event(message))
    assert worker.preferences.groups == []


async def test_revoked_user_cannot_reply(worker, store):
    await store.execute("UPDATE users SET active=0 WHERE id=100")
    await worker.incoming(event(post()))
    worker.client.assert_not_awaited()


async def test_album_sends_only_one_reply(worker):
    first = post(grouped_id=4444)
    second = post(mid=43, post_id=12, grouped_id=4444)
    successful_reply(worker, first)
    await worker.incoming(event(first))
    await worker.incoming(event(second))
    assert worker.client.await_count == 2


async def test_multiple_keyword_case_insensitive(worker):
    message = post(text="Looking for a Netflix premium seller.")
    successful_reply(worker, message)
    await worker.incoming(event(message))
    assert worker.client.await_count == 2


async def test_rate_limit_skips_excess_without_queue(worker, store):
    await store.reserve(100, 700, "previous", 1, time.time(), 1, 6)
    message = post()
    worker.client.side_effect = [SimpleNamespace(messages=[message])]
    await worker.incoming(event(message))
    assert worker.client.await_count == 0
    assert "rate limit" in worker.last_result
