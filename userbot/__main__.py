import asyncio
import fcntl
import logging
import os
import signal
import time

from aiohttp import web

from .config import Settings
from .login import Login
from .panel import Panel
from .service import Service
from .store import Store
from .telegram import LOG, WAIT_ERRORS, disconnect, new_client, rpc
from .web import make_app


async def main():
    os.umask(0o077)
    settings = Settings.load()
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.data_dir.chmod(0o700)
    with (settings.data_dir / "process.lock").open("a") as process_lock:
        try:
            fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another process is already using this data directory") from None
        store = Store(settings.data_dir / "state.sqlite3", settings.session_key, settings.owner_id)
        service = None
        login = None
        runner = None
        bot = None
        cleanup = None
        supervisor = None
        shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown.set)
        try:
            await store.open()
            for path in settings.data_dir.glob("state.sqlite3*"):
                path.chmod(0o600)
            until = await store.blocked_until("bot-login")
            if until > time.time():
                LOG.warning("Waiting for Telegram's bot authentication cooldown")
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=until - time.time())
                    return
                except TimeoutError:
                    pass
            bot = new_client(settings, await store.session(0))
            await rpc(bot.connect())
            await rpc(bot.start(bot_token=settings.bot_token))
            me = await rpc(bot.get_me())
            if not me.bot or me.id != int(settings.bot_token.split(":", 1)[0]):
                raise RuntimeError(
                    "Stored bot session does not match BOT_TOKEN; use a separate DATA_DIR"
                )
            await store.save_session(0, bot.session.save())
            service = Service(settings, store)
            login = Login(service)
            await service.restore()
            panel = Panel(bot, service, login)
            await panel.install()
            runner = web.AppRunner(make_app(login), access_log=None)
            await runner.setup()
            await web.TCPSite(runner, settings.bind_host, settings.port).start()
            cleanup = asyncio.create_task(login.cleanup())
            supervisor = asyncio.create_task(service.supervise())
            LOG.info("Bot and login panel are ready; %s account(s) connected", len(service.workers))
            stopped = asyncio.create_task(shutdown.wait())
            disconnected = asyncio.ensure_future(bot.disconnected)
            done, pending = await asyncio.wait(
                [stopped, disconnected, cleanup, supervisor], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
        except WAIT_ERRORS as exc:
            await store.block("bot-login", time.time() + exc.seconds)
            LOG.error("Telegram requires a %ss startup cooldown", exc.seconds)
            raise
        finally:
            if runner:
                try:
                    await runner.cleanup()
                except Exception as exc:
                    LOG.warning("Web shutdown failed: %s", type(exc).__name__)
            for task in (cleanup, supervisor):
                if task:
                    task.cancel()
            await asyncio.gather(
                *(task for task in (cleanup, supervisor) if task), return_exceptions=True
            )
            for component in (login, service):
                if component:
                    try:
                        await component.close()
                    except Exception as exc:
                        LOG.warning("Component shutdown failed: %s", type(exc).__name__)
            if bot:
                await disconnect(bot)
            if hasattr(store, "db"):
                await store.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("telethon").setLevel(logging.CRITICAL)
    logging.getLogger("aiohttp").setLevel(logging.CRITICAL)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        LOG.error(
            "Service stopped: %s. Check configuration and server connectivity.", type(exc).__name__
        )
        raise SystemExit(1) from None
