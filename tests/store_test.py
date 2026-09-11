"""Очистка контекста, ограничения памяти и конкурентные запросы."""

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from photo_api.sessions import SessionError, SessionStore
from photo_api.settings import ApiSettings
from shared.contracts import MessageRequest


class StoreTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.now = datetime(2026, 9, 11, tzinfo=UTC)
        self.store = SessionStore(
            ApiSettings(session_ttl_seconds=10, max_sessions=2),
            clock=lambda: self.now,
        )

    async def test_expiry_and_capacity_recovery(self) -> None:
        first = await self.store.create()
        await self.store.create()
        with self.assertRaises(SessionError) as error:
            await self.store.create()
        self.assertEqual(error.exception.status_code, 503)
        self.now += timedelta(seconds=10)
        await self.store.sweep()
        self.assertEqual(self.store.sessions, {})
        with self.assertRaises(SessionError):
            await self.store.get(first.session_id)
        await self.store.create()

    async def test_heartbeat_extends_only_its_session(self) -> None:
        first = await self.store.create()
        second = await self.store.create()
        self.now += timedelta(seconds=8)
        await self.store.touch(first.session_id)
        self.now += timedelta(seconds=3)
        await self.store.get(first.session_id)
        with self.assertRaises(SessionError):
            await self.store.get(second.session_id)

    async def test_concurrent_duplicate_is_one_turn(self) -> None:
        session = await self.store.create()
        request = MessageRequest(request_id=uuid4(), text="Расскажи о свете")
        responses = await asyncio.gather(
            *[self.store.send(session.session_id, request) for _ in range(8)]
        )
        self.assertTrue(all(response == responses[0] for response in responses))
        self.assertEqual(len((await self.store.get(session.session_id)).messages), 2)

    async def test_expired_session_cannot_be_revived(self) -> None:
        session = await self.store.create()
        self.now += timedelta(seconds=11)
        with self.assertRaises(SessionError):
            await self.store.touch(session.session_id)
