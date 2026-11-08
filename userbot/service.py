import asyncio
import time
from collections import defaultdict

from .telegram import AUTH_ERRORS, LOG, WAIT_ERRORS, disconnect, new_client, rpc
from .worker import Worker


class Service:
    def __init__(self, settings, store):
        self.settings = settings
        self.store = store
        self.workers = {}
        self.guards = defaultdict(asyncio.Lock)

    def guard(self, user_id):
        return self.guards[user_id]

    async def attach_locked(self, user_id, client):
        if not await self.store.allowed(user_id):
            raise ValueError("Access has been revoked")
        if user_id in self.workers:
            raise ValueError("This account is already connected")
        worker = Worker(self, user_id, client, await self.store.preferences(user_id))
        await self.store.save_session(user_id, client.session.save())
        self.workers[user_id] = worker
        worker.install()

    async def restore(self):
        capacity = asyncio.Semaphore(3)

        async def restore_one(user_id):
            async with capacity:
                await self.restore_one(user_id)

        await asyncio.gather(
            *(restore_one(user_id) for user_id in await self.store.session_users())
        )

    async def restore_one(self, user_id):
        async with self.guard(user_id):
            worker = self.workers.get(user_id)
            if worker and worker.client.is_connected():
                return
            if worker:
                self.workers.pop(user_id)
                worker.uninstall()
                await self.store.save_session(user_id, worker.client.session.save())
                await disconnect(worker.client)
            if not await self.store.allowed(user_id):
                await self.store.delete_session(user_id)
                return
            if await self.store.blocked_until(f"account:{user_id}") > time.time():
                return
            session = await self.store.session(user_id)
            if not session:
                return
            client = new_client(self.settings, session)
            attached = False
            try:
                await rpc(client.connect())
                me = await rpc(client.get_me())
                if me is None or me.bot or me.id != user_id:
                    await self.store.delete_session(user_id)
                    return
                await self.attach_locked(user_id, client)
                attached = True
            except WAIT_ERRORS as exc:
                await self.store.block(f"account:{user_id}", time.time() + exc.seconds)
                LOG.warning("Account %s restoration is rate limited", user_id)
            except AUTH_ERRORS:
                await self.store.delete_session(user_id)
                LOG.warning("Account %s requires a fresh login", user_id)
            except Exception as exc:
                await self.store.block(f"account:{user_id}", time.time() + 60)
                LOG.warning("Account %s restore failed: %s", user_id, type(exc).__name__)
            finally:
                if not attached:
                    await disconnect(client)

    async def supervise(self):
        while True:
            await asyncio.sleep(30)
            await self.restore()

    async def logout_locked(self, user_id):
        worker = self.workers.pop(user_id, None)
        client = worker.client if worker else None
        remote_revoked = False
        if worker:
            worker.uninstall()
        try:
            if client is None:
                session = await self.store.session(user_id)
                if session:
                    client = new_client(self.settings, session)
                    await rpc(client.connect())
            if client:
                remote_revoked = bool(await rpc(client.log_out()))
            else:
                remote_revoked = True
        except Exception as exc:
            LOG.warning("Account %s remote logout failed: %s", user_id, type(exc).__name__)
        finally:
            await disconnect(client)
            await self.store.delete_session(user_id)
            preferences = await self.store.preferences(user_id)
            preferences.enabled = False
            await self.store.save_preferences(user_id, preferences)
        return remote_revoked

    async def close(self):
        for user_id in list(self.workers):
            async with self.guard(user_id):
                worker = self.workers.pop(user_id)
                worker.uninstall()
                try:
                    await self.store.save_session(user_id, worker.client.session.save())
                except Exception as exc:
                    LOG.warning("Session save failed for %s: %s", user_id, type(exc).__name__)
                finally:
                    await disconnect(worker.client)
