from datetime import UTC, datetime

import pytest
from telethon import types

from userbot.policy import matches, original_post, parse_values, verified_root

from .conftest import post


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Anyone selling noktel? Looking for ready stock.", True),
        ("Looking for a cheap premium account.", False),
        ("Looking for a Netflix premium seller.", True),
        ("prefixNOKTELsuffix", True),
        ("SPOTIFY", True),
        ("", False),
    ],
)
def test_keyword_scenarios(text, expected):
    assert matches(text, ["noktel", "netflix", "spotify"]) is expected


def test_original_metadata():
    result = original_post(post())
    assert (result.channel_id, result.post_id, result.group_id) == (500, 11, 700)


@pytest.mark.parametrize(
    "change", ["reply", "user_sender", "self", "no_forward", "other_channel", "service"]
)
def test_ignore_non_original(change):
    message = post()
    if change == "reply":
        message.reply_to = types.MessageReplyHeader(reply_to_msg_id=42)
    elif change == "user_sender":
        message.from_id = types.PeerUser(200)
    elif change == "self":
        message.out = True
    elif change == "no_forward":
        message.fwd_from = None
    elif change == "other_channel":
        message.from_id = types.PeerChannel(900)
    else:
        message = types.MessageService(
            id=1,
            peer_id=types.PeerChannel(700),
            date=datetime.now(UTC),
            action=types.MessageActionPinMessage(),
        )
    assert original_post(message) is None


def test_comment_as_linked_channel_still_ignored():
    message = post(reply_to=types.MessageReplyHeader(reply_to_msg_id=42))
    assert original_post(message) is None


def test_manual_forward_cannot_substitute_root():
    candidate = post(mid=99)
    assert verified_root([post(mid=42)], candidate, original_post(candidate)) is None


def test_wrong_group_or_source_cannot_be_root():
    candidate = post()
    assert (
        verified_root([post(group=701), post(source=501)], candidate, original_post(candidate))
        is None
    )


def test_album_uses_common_canonical_root():
    candidate = post(mid=43, grouped_id=1234)
    root = post(mid=42, post_id=10, grouped_id=1234)
    assert verified_root([candidate, root], candidate, original_post(candidate)).id == 42
    assert original_post(candidate).key == original_post(root).key


def test_unicode_casefold_and_empty_keywords():
    assert matches("STRASSE", ["Straße"])
    assert not matches("anything", [""])


def test_parse_values_deduplicates_and_trims():
    assert parse_values("one, two,,one", ",", 50, 128) == ["one", "two"]


@pytest.mark.parametrize("value", ["", " , , ", "one,two,three", "a" * 129])
def test_parse_values_rejects_invalid(value):
    with pytest.raises(ValueError):
        parse_values(value, ",", 2, 128)
