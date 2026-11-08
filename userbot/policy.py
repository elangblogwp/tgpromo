from dataclasses import dataclass

from telethon import types


@dataclass(frozen=True)
class OriginalPost:
    channel_id: int
    post_id: int
    group_id: int
    key: str


def original_post(message):
    if not isinstance(message, types.Message) or message.out or message.reply_to:
        return None
    if not isinstance(message.peer_id, types.PeerChannel):
        return None
    if not isinstance(message.from_id, types.PeerChannel):
        return None
    forward = message.fwd_from
    if not forward or forward.imported or not isinstance(forward.from_id, types.PeerChannel):
        return None
    source = forward.from_id.channel_id
    if source != message.from_id.channel_id or source == message.peer_id.channel_id:
        return None
    if not forward.channel_post or forward.channel_post <= 0:
        return None
    suffix = f"album:{message.grouped_id}" if message.grouped_id else f"post:{forward.channel_post}"
    return OriginalPost(
        source, forward.channel_post, message.peer_id.channel_id, f"{source}:{suffix}"
    )


def matches(text, keywords):
    normalized = (text or "").casefold()
    return any(word.casefold() in normalized for word in keywords if word)


def verified_root(messages, candidate, post):
    roots = []
    for message in messages:
        root = original_post(message)
        if not root or root.group_id != post.group_id or root.channel_id != post.channel_id:
            continue
        same_message = message.id == candidate.id and root.post_id == post.post_id
        same_album = bool(candidate.grouped_id and message.grouped_id == candidate.grouped_id)
        if same_message or same_album:
            roots.append(message)
    return min(roots, key=lambda item: item.id) if roots else None


def parse_values(text, separator, maximum, length):
    values = list(dict.fromkeys(part.strip() for part in text.split(separator) if part.strip()))
    if not values or len(values) > maximum:
        raise ValueError(f"Enter between 1 and {maximum} nonempty values")
    if any(len(value.encode("utf-16-le")) // 2 > length for value in values):
        raise ValueError(f"Each value must fit within {length} Telegram text units")
    return values
