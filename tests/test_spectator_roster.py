import base64
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from web_bots import spectator_roster as roster


class RosterPublisherTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = MagicMock()
        self.page.is_closed.return_value = False
        url = "http://127.0.0.1:1234/bot/lily"
        self.page.main_frame.url = url
        self.source = {"frame": self.page.main_frame}
        self.page.evaluate_handle = AsyncMock()
        self.ticket = "1" * 32
        self.fp = "a" * 64
        self.events = []
        self.publisher = roster.ZoneRosterPublisher(self.page, url, lambda: 7,
                                                   lambda **event: self.events.append(event))

    async def test_requires_host_frame_current_room_ticket_and_fingerprint(self):
        for source, room, ticket, fp in [
            ({"frame": MagicMock()}, 7, self.ticket, self.fp),
            (self.source, 9, self.ticket, self.fp),
            (self.source, 7, "", self.fp),
            (self.source, 7, self.ticket, "invalid"),
        ]:
            self.assertFalse(await self.publisher.requested(source, room, ticket, fp))
        self.page.main_frame.url += "/other"
        self.assertFalse(await self.publisher.requested(self.source, 7, self.ticket, self.fp))
        self.page.evaluate_handle.assert_not_awaited()

    async def test_denied_upload_stops_before_reading_blocks_and_clears_busy(self):
        plan = self.page.evaluate_handle.return_value
        plan.evaluate.return_value = {"streamSize": 99, "sha256": self.fp}
        with patch.object(roster.aiohttp, "ClientSession") as factory:
            session = MagicMock()
            factory.return_value.__aenter__.return_value = session
            response = session.put.return_value.__aenter__.return_value
            response.status = 403
            self.assertFalse(await self.publisher.requested(self.source, 7, self.ticket, self.fp))
        session.put.assert_called_once()
        args, kwargs = session.put.call_args
        self.assertEqual(args, (f"{roster.ZONE}/feed/7/mod/{self.fp}/info",))
        self.assertEqual(kwargs["params"], {"up": self.ticket})
        self.assertFalse(kwargs["allow_redirects"])
        plan.evaluate.assert_awaited_once()
        plan.dispose.assert_awaited_once()
        self.assertIsNone(self.publisher.active)
        self.assertFalse(self.publisher.last_success)
        self.assertEqual(self.events[-1]["event"], "spectator_roster_failed")
        self.assertNotIn(self.ticket, repr(self.events))

    async def test_duplicate_is_cached_but_new_ticket_uploads_with_2xx_and_native_pacing(self):
        raw = b"A" * 4096
        plan = self.page.evaluate_handle.return_value
        plan.evaluate.side_effect = lambda expr, *_: (
            {"streamSize": len(raw), "sha256": self.fp} if expr != roster.READ_BLOCK else base64.b64encode(raw)
        )
        with patch.object(roster.aiohttp, "ClientSession") as factory, patch.object(roster, "time") as clock, \
                patch.object(roster.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            clock.monotonic.return_value = 1000.0
            session = MagicMock()
            factory.return_value.__aenter__.return_value = session
            session.put.return_value.__aenter__.return_value.status = 204
            for ticket in (self.ticket, self.ticket, "2" * 32, self.ticket):
                self.assertTrue(await self.publisher.requested(self.source, 7, ticket, self.fp))
            self.assertEqual(session.put.call_count, 4)  # manifest + block for each ticket
            block_body = session.put.call_args.kwargs["data"]
            self.assertEqual(block_body, roster.encode_block(raw))
            self.assertEqual([c.args[0] for c in sleep.await_args_list], [len(block_body) / roster.UPLOAD_RATE] * 2)
            clock.monotonic.return_value += roster.UPLOAD_COOLDOWN
            self.assertTrue(await self.publisher.requested(self.source, 7, self.ticket, self.fp))
            self.assertEqual(session.put.call_count, 6)

    async def test_page_teardown_during_dispose_preserves_original_outcome(self):
        plan = self.page.evaluate_handle.return_value
        plan.evaluate.side_effect = ValueError("Invalid manifest")
        plan.dispose.side_effect = RuntimeError("Navigation destroyed the execution context")
        self.page.is_closed.side_effect = [False, True]
        self.assertFalse(await self.publisher.requested(self.source, 7, self.ticket, self.fp))
        self.assertEqual(self.events, [{"event": "spectator_roster_failed", "room": 7, "reason": "ValueError"}])
        self.assertIsNone(self.publisher.active)

    @unittest.skipUnless(shutil.which("node"), "Node is required for the bundled JKWeb modules")
    def test_packed_roster_excludes_retail_contents_and_rebuilds(self):
        root = Path(__file__).resolve().parents[1]
        subprocess.run(["node", root / "tests/fixtures/spectator_roster_share.js",
                        root / "bin/bots-jkweb/openjkdf2.js"], input=roster.PREPARE,
                       text=True, check=True, timeout=20)
