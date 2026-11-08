import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    bot_token: str
    owner_id: int
    session_key: str
    public_base_url: str
    data_dir: Path
    bind_host: str = "127.0.0.1"
    port: int = 8080
    max_users: int = 25
    login_ttl: int = 600
    login_cooldown: int = 60
    min_reply_interval: int = 60
    max_replies_per_hour: int = 6
    max_post_age: int = 120

    @classmethod
    def load(cls):
        load_dotenv()

        def required(name):
            value = os.getenv(name, "").strip()
            if not value:
                raise ValueError(f"Missing setting: {name}")
            return value

        def number(name, default=None, minimum=1, maximum=2**63 - 1):
            value = int(required(name) if default is None else os.getenv(name, str(default)))
            if not minimum <= value <= maximum:
                raise ValueError(f"Invalid range for {name}")
            return value

        api_hash = required("API_HASH")
        if not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash):
            raise ValueError("API_HASH must be 32 hexadecimal characters")
        token = required("BOT_TOKEN")
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
            raise ValueError("Invalid BOT_TOKEN format")
        key = required("SESSION_KEY")
        Fernet(key.encode())
        base = required("PUBLIC_BASE_URL").rstrip("/")
        parsed = urlsplit(base)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin without a path")
        return cls(
            api_id=number("API_ID"),
            api_hash=api_hash,
            bot_token=token,
            owner_id=number("OWNER_ID"),
            session_key=key,
            public_base_url=base,
            data_dir=Path(os.getenv("DATA_DIR", "./data")).resolve(),
            bind_host=os.getenv("BIND_HOST", "127.0.0.1"),
            port=number("PORT", 8080, maximum=65535),
            max_users=number("MAX_USERS", 25, maximum=1000),
            login_ttl=number("LOGIN_TTL", 600, minimum=60, maximum=900),
            login_cooldown=number("LOGIN_COOLDOWN", 60, minimum=30),
            min_reply_interval=number("MIN_REPLY_INTERVAL", 60, minimum=1),
            max_replies_per_hour=number("MAX_REPLIES_PER_HOUR", 6, maximum=60),
            max_post_age=number("MAX_POST_AGE", 120, minimum=10, maximum=600),
        )
