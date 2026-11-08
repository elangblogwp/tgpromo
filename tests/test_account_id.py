from userbot import account_id


def test_private_senders_use_user_id_and_ignore_groups():
    updates = [
        {
            "message": {
                "chat": {"id": 999, "type": "private"},
                "from": {"id": 100, "username": "owner"},
            }
        },
        {"message": {"chat": {"type": "group"}, "from": {"id": 200}}},
        {"message": {"chat": {"type": "private"}, "from": {"id": 300, "is_bot": True}}},
        {"message": {"chat": {"type": "private"}, "from": {"id": 100, "username": "owner"}}},
    ]
    assert account_id.private_senders(updates) == [{"id": 100, "username": "owner", "name": ""}]


def test_lookup_failure_does_not_print_token(monkeypatch, capsys):
    token = "12345:" + "a" * 32
    monkeypatch.setenv("BOT_TOKEN", token)

    def fail(*args, **kwargs):
        raise OSError(token)

    monkeypatch.setattr(account_id, "urlopen", fail)
    assert account_id.main() == 1
    assert token not in capsys.readouterr().out
