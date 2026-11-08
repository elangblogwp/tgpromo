# Telegram Discussion Userbot

A Python 3.12 application with a BotFather management bot, an HTTPS login page accessible directly at your VPS public IPv4 address, and one Telethon user session per authorized user. No domain is required. For a complete fresh Ubuntu installation in Indonesian, read `PANDUAN_UBUNTU.md`. It replies to verified original channel posts in explicitly selected linked discussion groups. Ordinary comments never enter the keyword-matching path.

The command `docker compose run --rm --no-deps userbot python -m userbot.account_id` can display IDs of private users who recently sent `/start` to this fresh bot, before the main service is started. It reads `BOT_TOKEN` from the container environment and never prints the token. Select your own account ID; the helper grants no access.

Source files contain no comments. Documentation is kept here. The package includes automated tests and Docker/Caddy deployment files.

## What you need

- A Linux server with outbound access to Telegram and Python 3.12+, or Docker Engine with Docker Compose.
- Your own `API_ID` and `API_HASH` from [Telegram API development tools](https://my.telegram.org/apps). A BotFather token alone cannot authenticate a user account.
- A bot token created with [@BotFather](https://t.me/BotFather).
- Your numeric Telegram account ID for `OWNER_ID`.
- A stable public IPv4 address assigned to your VPS, with inbound TCP ports 80 and 443 available for Caddy validation and HTTPS. UDP 443 is optional. A private address, a shared NAT address without these port forwards, or a server whose provider blocks certificate issuance will not work with this deployment.

The bot manages access; promotional replies are sent by the logged-in user account. Users must join the desired discussion groups manually. This application never joins groups or sends direct-message promotions automatically.

Use only groups where the administrators permit your promotional replies. Telegram does not publish a universally safe posting rate. This implementation cannot promise a low ban probability or eliminate bans; unsolicited or repetitive promotion may still be restricted.

## Quick setup with Docker and HTTPS

Unzip the project and open its `telegram-userbot` directory.

```bash
cp .env.example .env
chmod 600 .env
docker compose build userbot
docker compose run --rm --no-deps userbot python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Copy the generated value into `SESSION_KEY` in `.env`. Set the remaining required values:

| Setting | Value |
| --- | --- |
| `API_ID` | Your Telegram application ID |
| `API_HASH` | Your 32-character Telegram application hash |
| `BOT_TOKEN` | Your BotFather token |
| `OWNER_ID` | Your own numeric Telegram user ID |
| `SESSION_KEY` | The generated Fernet encryption key |
| `PUBLIC_IP` | Your VPS public IPv4 address, with no scheme or port |
| `PUBLIC_BASE_URL` | `https://` followed by that same public IPv4 address, with no path or custom port |

Then start the service:

```bash
docker compose up -d
docker compose logs --tail=100 userbot
```

Caddy 2.11.8 explicitly uses Let's Encrypt's `shortlived` ACME profile to obtain and renew a publicly trusted certificate for the IP address. The global `default_sni` selects that public IP certificate for browsers that omit SNI when connecting to an IP, including when Caddy runs inside Docker. IP certificates last about six days, so keep Caddy running and ports reachable for automatic renewal. This configuration does not use a self-signed fallback. Its access log is disabled by default. The Python service has no published Docker port; it is accessible through Caddy. The application runs as a non-root container user. Named volumes retain encrypted sessions, configuration, duplicate records, and TLS state across ordinary container restarts.

Replace the documentation-only address `203.0.113.10` in both example settings with your real VPS public IPv4 address. Check that `https://YOUR_PUBLIC_IP` opens the login page without a certificate warning before using `/login`. Without a login link, the page correctly tells you to start in the Telegram bot.

Do not run multiple replicas against one data directory, or copies of one Telegram session on multiple servers. A process lock rejects a second local process. Do not remove the data volume during an upgrade. `docker compose down -v` permanently deletes stored sessions and duplicate history.

## Native Python setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Fill in `.env`, then run:

```bash
.venv/bin/python -m userbot
```

For native deployment, keep `BIND_HOST=127.0.0.1` and place your HTTPS reverse proxy in front of port 8080. In a host Caddyfile, replace `{$PUBLIC_IP}` and `{$PUBLIC_BASE_URL}` with your literal public IPv4 address and `https://` origin, since Caddy does not automatically read the Python application's `.env` file. Replace the Docker Caddy upstream `userbot:8080` with `127.0.0.1:8080` if running Caddy on the host. Preserve the public `Host` header. Do not expose port 8080 directly. Use a service manager to restart the application if the process exits. Native execution uses Linux `fcntl` locking; Windows users should use a Linux container or WSL.

The login panel deliberately requires HTTPS. Secure cookies will not work over an ordinary HTTP URL.

## Login and access management

1. Open your BotFather bot and send `/start`.
2. As the owner, authorize a user with `/adduser 123456789`. The owner is automatically authorized. A user can obtain their ID with `/id`; this command does not grant access.
3. The authorized user sends `/login +15551234567`, using their own phone number with country code and no spaces.
4. Tap **Connect my Telegram account** and verify that the IP address is your VPS's expected public IP and that HTTPS has no certificate warning.
5. Tap **Send verification code**, then enter the code on the HTTPS page. Enter the two-step verification password on that same page if prompted.
6. After connection, open **Saved Messages** in the same Telegram account and send `.help`.

The connected account ID must match the Telegram user who requested `/login`. An authorized user cannot connect somebody else's account through their own panel login.

Each login link expires after ten minutes by default and can be exchanged once. Keep the page open during login. If you reload it, change browsers, or lose the session, request a new `/login` link. The application attempts to delete the `/login` phone-number message after sending the link; deletion can fail, so the command should still be treated as information sent to the bot.

**Never send verification codes or two-step passwords into the bot chat.** Telegram automatically invalidates login codes sent into another Telegram chat. The bot opens an HTTPS form for this reason; it does not work around that protection with spaced codes or message tricks.

| Bot command | Access | Purpose |
| --- | --- | --- |
| `/start`, `/help` | Authorized users | Show the management panel |
| `/id` | Any private-chat user | Show only that sender's Telegram user ID |
| `/login <phone>` | Authorized users | Begin a private login for their own account |
| `/status` | Authorized users | Inspect their connection, configuration, and processing result |
| `/cancel` | Authorized users | Cancel their pending login |
| `/logout` | Authorized users | Stop their userbot, remove its stored session, and attempt Telegram session revocation |
| `/adduser <user_id>` | Owner only | Grant access |
| `/deluser <user_id>` | Owner only | Revoke access, cancel login, and disconnect that user's session |
| `/users` | Owner only | List authorized IDs |

Commands are registered automatically with Telegram at startup. You can also copy the following into BotFather's `/setcommands` interface:

```text
start - Open the login and management panel
login - Connect your account using your phone number
adduser - Owner: authorize a user ID
deluser - Owner: revoke a user ID
users - Owner: list authorized users
status - Show connection and reply settings
cancel - Cancel an unfinished login
logout - Disconnect and remove your session
id - Show your Telegram user ID
```

The management panel only responds in private bot chats. Removing a user preserves their duplicate history and settings, but pauses automatic replies. If remote session revocation fails, the panel tells you to terminate the session in **Telegram Settings → Devices**. The owner cannot remove their own authorization using `/deluser`.

## Configure automatic replies

Send each command as a separate message in **Saved Messages**, from the account you connected:

```text
.keyword noktel, netflix, spotify
.text Ready stock, DM me!|Fast response, contact me!|Cheap prices available, PM me!
.listgc
```

Choose a linked discussion group from the returned list. Add its exact numeric group ID, then enable replies:

```text
.watch -1001234567890
.on
.status
```

`.watch` is an explicit selection of a group where you have permission to promote. Repeat it for additional discussion groups. Automatic replies are initially off. Existing enabled settings are restored after a restart, but old messages are not replayed.

| Userbot command | Description |
| --- | --- |
| `.help` | Display every userbot command |
| `.ping` | Measure Telegram RPC round-trip and command-response time in milliseconds |
| `.listgc` | List joined groups, including IDs; large results become a text attachment |
| `.keyword <word1,word2>` | Replace keywords with case-insensitive substring matches |
| `.keyword` | Show current keywords |
| `.keyword --clear` | Remove keywords and pause replies |
| `.text <text1\|text2>` | Replace promotional text variations; one is randomly selected for each reply |
| `.text` | Show current variations |
| `.text --clear` | Remove variations and pause replies |
| `.watch <group_id>` | Add a joined supergroup with a linked channel |
| `.unwatch <group_id>` | Remove that discussion group |
| `.on` | Enable automatic replies once keywords, texts, and groups exist |
| `.off` | Pause automatic replies |
| `.status` | Show settings, account cooldown, and the last processing result |

Userbot commands only run in Saved Messages. This keeps configuration private and prevents promotional replies that happen to begin with a dot command from invoking commands. Replies are plain text, with link previews disabled. Commas delimit keywords; vertical bars delimit variations. Literal delimiters inside an individual value are not supported. The limits are 50 keywords, 128 UTF-16 units per keyword, 10 text variations, 2,000 UTF-16 units per variation, and 100 selected groups per account.

`.ping` measures this process's round-trip to Telegram and the time to perform an initial message edit. It is not a bandwidth benchmark, server CPU benchmark, or measurement of the user's device network.

## How original-post filtering works

The receive handler uses `NewMessage` updates from the user session. It does not poll channel history.

1. Reject outgoing messages, messages with reply metadata, ordinary user senders, service messages, and messages without a channel-forward header. A comment is rejected before keyword matching.
2. Require the sender channel to match the forwarded source channel and require a source channel-post ID.
3. Require an explicitly selected discussion group, configured text, enabled replies, a fresh post, and a keyword match in the forwarded original text or caption.
4. Look up the group's `linked_chat_id` with `channels.getFullChannel`. Cache that relationship for ten minutes.
5. Call `messages.getDiscussionMessage` for the source channel post. Require the received message to be Telegram's canonical discussion root, or an item in that same verified album. A manually forwarded message with plausible metadata but a different message ID fails this check.
6. Atomically reserve a durable duplicate key in SQLite before sending.
7. Send a message into the discussion group with `reply_to_msg_id` and `top_msg_id` set to the verified root ID, using the authenticated user as sender.

The bot does not use the source channel's message ID as the discussion group's reply ID. It does not treat a comment's `reply_to_msg_id` as permission to respond. Unverifiable metadata fails closed: no reply is sent.

| Event | Result |
| --- | --- |
| Original post: “Anyone selling noktel? Looking for ready stock.” | Reply in that post's discussion thread |
| User comment: “I also need noktel, does anyone have it?” | Ignore completely |
| Original post: “Looking for a cheap premium account.” | Ignore: no keyword |
| Original post: “Looking for a Netflix premium seller.” | Reply: case-insensitive keyword match |
| Matching comment posted as a channel | Ignore: reply metadata or canonical-root verification rejects it |
| Matching manually forwarded post | Ignore unless Telegram independently identifies that exact message as the canonical discussion root |
| Userbot's own promotional reply | Ignore |
| A repeated delivery of the same update | Ignore after the first reservation |

Keyword matching is on Telegram text/captions, not OCR, audio, button labels, link destinations, or expanded webpages. Edited posts are not reprocessed. Album members share a duplicate key, so a matching caption triggers at most one reply per verified album.

## Limits, retries, and reliability

| Setting | Default | Behavior |
| --- | --- | --- |
| `MIN_REPLY_INTERVAL` | `60` seconds | Minimum interval between reserved promotional sends per account |
| `MAX_REPLIES_PER_HOUR` | `6` | Rolling hourly cap per account, across all selected groups |
| `MAX_POST_AGE` | `120` seconds | Skip stale posts instead of replaying an old backlog |
| `LOGIN_TTL` | `600` seconds | One-time link and browser login lifetime |
| `LOGIN_COOLDOWN` | `60` seconds | Minimum interval between verification-code requests per user and hashed phone |
| `MAX_USERS` | `25` | Maximum active authorized users, including the owner |

The first eligible post is processed immediately. There is no random sleep, typing animation, scheduled promotional queue, or catch-up burst. Posts that exceed a configured cap or an active Telegram cooldown are skipped, not delayed for later sending. This means not every matching post will receive a reply.

FloodWait and FloodPremiumWait deadlines are persisted. SlowModeWait is scoped to the affected discussion group. The application never tries to bypass these waits. PeerFlood pauses an account's automatic replies; group write restrictions remove that group from the selected list. Check `/status` in the bot when an account cannot respond to `.status` because it is rate limited.

Duplicate reservations and rate history survive restarts. Each reply has a random Telegram request ID, and the same post is never intentionally retried after an attempted send. This is an **at-most-once attempt policy**, not a claim of exactly-once delivery: a timeout or crash after reservation may leave the post unanswered. Retrying an ambiguous send could create a duplicate, so ambiguous reservations remain consumed. Do not delete the database to “retry” a post.

SQLite uses WAL mode and synchronous durable commits. An account-level lock serializes login, revocation, configuration changes, and replies. Explicit revocation stops subsequent activity once any already-running operation completes. Telethon reconnects transient connections; a bounded supervisor retries offline stored sessions after failures and honors stored cooldowns. Housekeeping timers do not delay the event-driven reply path. The service never scans all group members.

Each user has separate keywords, texts, group selection, session, and duplicate history. Multiple authorized accounts can independently reply to one post; the duplicate guarantee applies per account, not across all users.

## Credential handling and trust

- Session strings are encrypted using Fernet authenticated encryption before SQLite storage. The database includes a key-check marker so an incorrect encryption key fails startup rather than silently replacing sessions.
- `SESSION_KEY`, `BOT_TOKEN`, and `API_HASH` are secrets. Keep `.env` private and back up the encryption key separately from the database. Losing the key makes saved sessions unreadable.
- Encryption protects a database-only disclosure. It does not protect accounts from an attacker or operator who controls the running server or has both the database and the key. Host the application only for people who trust that operator.
- Verification codes, two-step passwords, and raw phone numbers are not persisted by the application. Pending login state is held in memory with expiration. Submitted passwords exist transiently in process memory while authentication runs; Python does not guarantee zeroization of string buffers.
- Login links carry a random token in the URL fragment. The browser removes it from its address bar and exchanges it once. Server storage keeps token/cookie hashes, not their bearer values.
- The login cookie is `Secure`, `HttpOnly`, `SameSite=Strict`, and uses a `__Host-` name. Actions require a matching CSRF token, exact origin, expected host, and JSON body. The server applies a strict CSP, prevents framing, disables caching, and suppresses request access logs.
- Five incorrect credential attempts close the pending login and impose a five-minute application lockout. Telegram's own limits always take precedence.
- Avoid logging HTTP request bodies in your reverse proxy, hosting provider, monitoring, or debug tools. Do not enable verbose Telethon logs around authentication.
- `.env`, local databases, sessions, caches, and tests are excluded from the Docker build context as appropriate. No actual credentials are included in this archive.

## Testing

```bash
.venv/bin/pip install 'pytest>=9,<10' 'pytest-asyncio>=1.4,<2' 'ruff>=0.17,<1'
.venv/bin/pytest -q
.venv/bin/ruff check .
```

When running the test suite, Telegram clients are mocked. Tests exercise original-post filtering, the four requested scenarios, thread routing, channel-sender comments, canonical-root validation, albums, concurrent duplicate claims, restart persistence, timeouts, rate limits, authorization, 2FA, account-ID binding, one-time links, revocation, CSRF, cookies, and HTTP limits. They make no live Telegram requests and use no real account credentials.

Validation completed on November 9, 2026: all 93 automated tests passed, Ruff checks passed, Python compilation and JavaScript syntax checks passed, and the installed dependency set passed `pip check`. Python source was also checked for the requested absence of comments. The Caddy configuration was adapted with the official Caddy 2.11.8 binary and inspected for the production ACME issuer, shortlived profile, and public-IP certificate selection without SNI. The official Docker image tag was verified as available. A browser could not be launched in the build environment, so visual browser verification remains outstanding; the HTTP login endpoints and cookie attributes were tested directly.

Before enabling real promotions, perform a live smoke test in a channel/discussion group you control:

1. Log in and configure one keyword, one harmless test message, and that group's ID.
2. Publish a matching original channel post and verify exactly one reply inside its comment thread.
3. Add matching comments as a user and, if available, as a channel; verify there are no replies to either comment.
4. After the configured interval, publish a nonmatching post and then a mixed-case matching post. Verify only the matching original receives a reply.
5. Publish an album with a matching caption and verify at most one reply in the expected thread.
6. Restart the application and verify saved configuration is restored without replaying old promotions.
7. Verify a non-owner cannot `/adduser`, an unauthorized user cannot log in, and `/deluser` disconnects a test user.

This project has not been connected to a live Telegram account during creation. Docker deployment, certificate issuance, Telegram code delivery, and real linked-group behavior require this environment-specific smoke test. Standard phone-code login and two-step passwords are implemented. Telegram flows requiring email setup, email verification, Firebase-specific SMS, or other additional authentication steps are deliberately rejected with an error rather than guessed or bypassed.

## Troubleshooting

- **The app exits immediately:** check all required `.env` values, Python version, the data directory, and that only one process is using the directory. Do not change `SESSION_KEY` for an existing database. Inspect the reported exception class without posting secrets.
- **The login page rejects the request:** use the exact `PUBLIC_BASE_URL` with your real public IPv4 address, HTTPS, and the host-preserving reverse proxy. `PUBLIC_IP` must contain the same IP. If the browser shows a certificate warning, check Caddy logs and TCP ports 80/443; do not submit login credentials until HTTPS validates. Open a fresh bot link if the page was reloaded or opened previously.
- **No verification code arrives:** Telegram chooses the delivery method and may restrict unofficial-client login. Check the official Telegram app and wait out any stated cooldown; do not repeatedly resend requests.
- **A saved session is reconnecting:** check `/status` after the recovery interval. To discard that session deliberately, use `/logout`, then start `/login` again.
- **The group is absent:** join it manually and run `.listgc` again. A broadcast channel ID is not the same as its discussion group ID.
- **A matching post is skipped:** inspect `/status`. Confirm `.on`, nonempty keyword/text settings, `.watch`, group permissions, and that it is a new original post. Check rate caps, cooldowns, stale-post age, and canonical-root verification. Telegram may deny source-channel lookup when the account lacks access; join the source channel manually if needed.
- **A channel was relinked to a different discussion group:** reselect the group with `.watch` to refresh the cache, or wait up to ten minutes. Unverified relinked posts are skipped in the meantime.
- **The account is restricted:** stop promotions, review group rules, and use Telegram's own [@SpamBot](https://t.me/SpamBot) to inspect restrictions. The application does not automate appeals or restriction bypasses.

## Project layout

```text
userbot/account_id.py   Read your own user ID from fresh bot updates
userbot/config.py       Environment validation
userbot/store.py        SQLite state, encrypted sessions, deduplication, limits
userbot/policy.py       Pure original-post and keyword checks
userbot/worker.py       Telegram commands, verification, and threaded replies
userbot/service.py      Per-account lifecycle and reconnection
userbot/login.py        Expiring login state and authentication
userbot/web.py          HTTPS-facing login endpoints and security headers
userbot/panel.py        BotFather bot commands and owner access control
userbot/telegram.py     Telethon client options and bounded RPC helpers
userbot/__main__.py     Startup, locking, monitoring, and shutdown
userbot/static/         Mobile-friendly login page
tests/                  Offline automated tests
```

## Primary references

- [Telegram discussion groups and automatic forwards](https://core.telegram.org/api/discussion)
- [Telegram getDiscussionMessage](https://core.telegram.org/method/messages.getDiscussionMessage)
- [Telegram sendMessage](https://core.telegram.org/method/messages.sendMessage)
- [Telegram authentication and code invalidation](https://core.telegram.org/api/auth)
- [Obtaining an API ID and Telegram's abuse restrictions](https://core.telegram.org/api/obtaining_api_id)
- [Telethon signing in](https://docs.telethon.dev/en/stable/basic/signing-in.html)
- [Telethon session security](https://docs.telethon.dev/en/stable/concepts/sessions.html)
- [Telethon FloodWait and account restrictions](https://docs.telethon.dev/en/stable/quick-references/faq.html)

- [Let's Encrypt IP certificates and short-lived profiles](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)
- [Caddy ACME profile configuration](https://caddyserver.com/docs/caddyfile/directives/tls)
- [Caddy public-IP certificate support](https://github.com/caddyserver/caddy/issues/7118)
