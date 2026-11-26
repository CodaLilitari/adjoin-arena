"""Native Zone host publisher for a spectator's request for this match's roster.

The host receives the room's upload ticket from WSRelay. JKWeb supplies the
same retail-reference plan it uses for joiners. No retail install, destination
URL, or arbitrary request body is accepted from a spectator.
"""
import asyncio
import base64
import json
import math
import re
import time
import zlib

import aiohttp

BLOCK = 1024 * 1024
UPLOAD_RATE = 256 * 1024  # JKWeb feed bandwidth budget in bytes per second.
UPLOAD_COOLDOWN = 60
ZONE = "https://jediknight.zone"

# Use the pinned engine's own packer and retail-file exclusion rules.
PREPARE = """async fp => {
    const {jkMods: mods, jkMaps: maps} = window.Module;
    const current = mods.current();
    if (!current || current.fp !== fp || current.path !== 'jkmods/companion')
        throw new Error('The requested roster is no longer mounted.');
    const root = maps.core.gameRoot();
    const pack = mods.lib.pack(root + '/' + current.path);
    if (pack.entries.length !== 1 || pack.entries[0].name !== 'lilitari.gob' ||
        await maps.lib.sha256(pack.bytes) !== fp)
        throw new Error('The mounted roster differs from the advertised file.');
    const plan = await maps.lib.planShareRanges(pack.bytes, mods.lib.shareRanges(pack),
                                                maps.core.retailSources(root, 'gob'));
    if (!plan.ok) throw new Error('JKWeb refused to share this roster.');
    return {stream: plan.stream, info: {status:'ok', name:current.name, ext:'gob',
        size:pack.bytes.length, sha256:fp, streamSize:plan.stream.length, refsBytes:plan.refsBytes}};
}"""
READ_BLOCK = """(plan, [offset, count]) => {
    const bytes = plan.stream.read(offset, count);
    let text = '';
    for (let i=0; i<bytes.length; i+=16384)
        text += String.fromCharCode(...bytes.subarray(i, i+16384));
    return btoa(text);
}"""


def encode_block(data):
    compressor = zlib.compressobj(wbits=-15)
    small = compressor.compress(data) + compressor.flush()
    return b"\x01" + small if len(small) < len(data) else b"\x00" + data


class ZoneRosterPublisher:
    def __init__(self, page, page_url, current_room, log):
        self.page, self.page_url = page, page_url
        self.current_room, self.log = current_room, log
        self.serial = asyncio.Lock()
        self.active = None
        self.last_success = {}

    async def requested(self, source, room, ticket, fingerprint):
        frame = source["frame"]
        if (frame != self.page.main_frame or frame.url != self.page_url or
                type(room) is not int or room != self.current_room() or
                not isinstance(ticket, str) or not re.fullmatch(r"[0-9a-f]{32}", ticket) or
                not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)):
            return False
        key = (room, ticket, fingerprint)
        if self.active == key:
            return True
        async with self.serial:
            if self.page.is_closed() or frame.url != self.page_url or room != self.current_room():
                return False
            now = time.monotonic()
            self.last_success = {k: t for k, t in self.last_success.items() if now - t < UPLOAD_COOLDOWN}
            if key in self.last_success:
                return True
            self.active = key
            try:
                if not await self._publish(room, ticket, fingerprint):
                    return False
                self.last_success[key] = time.monotonic()
                return True
            finally:
                self.active = None

    async def _publish(self, room, ticket, fingerprint):
        plan = None
        try:
            plan = await self.page.evaluate_handle(PREPARE, fingerprint)
            info = await plan.evaluate("p => p.info")
            total = info["streamSize"]
            parts = math.ceil(total / BLOCK)
            if info["sha256"] != fingerprint or not 0 < total <= 1024**3 + 8*1024**2:
                raise ValueError("Invalid roster manifest")
            info.update(z=BLOCK, parts=parts)
            self.log(event="spectator_roster_requested", room=room, fingerprint=fingerprint, parts=parts)
            base = f"{ZONE}/feed/{room}/mod/{fingerprint}"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                async def put(part, body):
                    for attempt in range(3):
                        if self.page.is_closed() or self.current_room() != room:
                            raise RuntimeError("Host closed")
                        try:
                            async with session.put(f"{base}/{part}", params={"up":ticket}, data=body,
                                                   allow_redirects=False, headers={"Content-Type":"application/octet-stream"}) as response:
                                status = response.status
                        except (aiohttp.ClientError, asyncio.TimeoutError):
                            status = 0
                        if 200 <= status < 300:
                            return
                        if attempt == 2 or (status and status != 429 and status < 500):
                            raise RuntimeError(f"Zone returned {status} for part {part}")
                        await asyncio.sleep(2 ** (attempt + 1))

                await put("info", json.dumps(info, separators=(",", ":")).encode())
                for n in range(parts):
                    count = min(BLOCK, total - n * BLOCK)
                    raw = base64.b64decode(await plan.evaluate(READ_BLOCK, [n * BLOCK, count]), validate=True)
                    if len(raw) != count:
                        raise ValueError("Incomplete roster block")
                    body = await asyncio.to_thread(encode_block, raw)
                    began = time.monotonic()
                    await put(n, body)
                    took = time.monotonic() - began
                    budget = len(body) / UPLOAD_RATE
                    await asyncio.sleep(took / 2 if took > budget else budget - took)
            self.log(event="spectator_roster_sent", room=room, fingerprint=fingerprint, parts=parts)
            return True
        except Exception as error:
            # Browser and HTTP exception strings can contain signed URLs.
            reason = str(error) if type(error) is RuntimeError and str(error).startswith("Zone returned ") else type(error).__name__
            self.log(event="spectator_roster_failed", room=room, reason=reason)
            return False
        finally:
            if plan is not None:
                try:
                    await plan.dispose()
                except Exception as error:
                    # Page teardown can destroy its handles after the final PUT.
                    if not self.page.is_closed():
                        self.log(event="spectator_roster_cleanup_failed", room=room, reason=type(error).__name__)
