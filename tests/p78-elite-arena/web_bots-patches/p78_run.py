"""TEMP (Wren, AI collaborator, via Grok Bot, 2026-11-25): one Darth_Lilitari JKWeb bot in
single-player Debug Play of JK1MP m10 (Canyon Oasis) with SM Sith Lord's Elite Arena P78 mod,
via the TEMP "sp" role of the adapter engine build. Records the canvas. Test-only, not for PR4.

    python -m web_bots.p78_run --data /workspace/jk-data/JK --engine-dir ENGINE --p78 P78.GOB \
        --skin-gob SKIN.gob --runtime RUNS --record --max-seconds 700
"""
import argparse, asyncio, contextlib, json, os, re, shutil, time
from pathlib import Path
from aiohttp import web
from web_bots.serve import Host
from web_bots.headless import SOFTWARE_GL, QUIET

async def main(a):
    from playwright.async_api import async_playwright
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run = Path(a.runtime).resolve() / ("p78-" + stamp); run.mkdir(parents=True)
    host = Host(a.data, a.engine_dir, run / "lily", "P78SP", a.skin_gob, False, "ff-guns", p78_gob=a.p78)
    runner = web.AppRunner(host.app(), access_log=None, shutdown_timeout=1.)
    await runner.setup(); await web.TCPSite(runner, "127.0.0.1", 0).start()
    host.set_port(runner.addresses[0][1])
    url = host.url + "/bot/lily"; token = host.tokens["lily"]
    t0 = time.monotonic()
    log = (run / "lily.console.log").open("a", encoding="utf-8")
    events = {"start": None, "end": None, "crash": False}
    def note(kind, text):
        text = str(text).replace(token, "[redacted]")
        log.write(f"{time.monotonic()-t0:8.2f} {kind} {text[:800]}\n"); log.flush()
        if "P78_ADAPTER start_match" in text and events["start"] is None: events["start"] = time.monotonic()
        if events["start"] and events["end"] is None and ("P78_ADAPTER match_over" in text or
                re.search(r"P78_HUD .*(\bWINS?\b|\bDRAW\b)", text)):
            events["end"] = time.monotonic()
    async with async_playwright() as pw:
        env = dict(os.environ); env["CHROME_LOG_FILE"] = str(run / "chrome.log")
        browser = await pw.chromium.launch(executable_path=a.chrome, headless=not a.headed, env=env,
                                           args=QUIET + ["--enable-logging"] + (a.gl_flags.split() if a.gl_flags else SOFTWARE_GL))
        ctx = await browser.new_context(viewport={"width": a.width, "height": a.height}, device_scale_factor=1)
        page = await ctx.new_page()
        await page.add_init_script("if(window===top && location.href===" + json.dumps(url) +
                                   ") window.__JK_BOT_TOKEN=" + json.dumps(token) + ";")
        page.on("console", lambda m: note(m.type, m.text))
        page.on("pageerror", lambda e: note("pageerror", e))
        page.on("crash", lambda: (note("crash", "page crashed"), events.update(crash=True)))
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        recording = False; shots = 0; next_shot = time.monotonic() + 20
        deadline = time.monotonic() + a.max_seconds
        try:
            while time.monotonic() < deadline and not events["crash"]:
                host.hub.pump(); host.expire_capture()
                now = time.monotonic()
                if a.record and not recording and events["start"]:
                    r = await page.evaluate("jkBot.startRecording(700)")
                    note("recording", json.dumps(r)); recording = True
                if now >= next_shot:
                    next_shot = now + a.shot_every
                    with contextlib.suppress(Exception):
                        await page.screenshot(path=str(run / f"shot-{shots:03d}.png"), timeout=5000); shots += 1
                    with contextlib.suppress(Exception):
                        info = await page.evaluate("jkBot.info()"); note("info", json.dumps(info))
                        fps = await page.evaluate("new Promise(r=>{let n=0;const t=performance.now();const f=()=>{n++;if(performance.now()-t<2000)requestAnimationFrame(f);else r(n/((performance.now()-t)/1000));};requestAnimationFrame(f);})")
                        note("fps", f"{fps:.1f}")
                if events["end"] and now - events["end"] >= a.tail:
                    break
                if a.smoke and events["start"] and now - events["start"] >= a.smoke:
                    break
                await asyncio.sleep(0.05)
            if recording:
                with contextlib.suppress(Exception):
                    note("recording", "stop " + json.dumps(await page.evaluate("jkBot.stopRecording()")))
                for _ in range(200):
                    host.hub.pump()
                    if host.capture and host.capture.get("status") != "recording": break
                    await asyncio.sleep(0.1)
                note("capture", json.dumps({k: v for k, v in (host.capture or {}).items() if k not in ("file", "capture_id", "instance")}))
        finally:
            with contextlib.suppress(Exception): await ctx.close()
            with contextlib.suppress(Exception): await browser.close()
            await runner.cleanup(); host.close()
    print(json.dumps({"run": str(run), "events": {k: (round(v - t0, 1) if isinstance(v, float) else v) for k, v in events.items()}}))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True); p.add_argument("--engine-dir", required=True)
    p.add_argument("--p78", required=True); p.add_argument("--skin-gob", required=True)
    p.add_argument("--runtime", required=True); p.add_argument("--record", action="store_true")
    p.add_argument("--max-seconds", type=float, default=700); p.add_argument("--smoke", type=float, default=0)
    p.add_argument("--tail", type=float, default=10); p.add_argument("--shot-every", type=float, default=30)
    p.add_argument("--width", type=int, default=960); p.add_argument("--height", type=int, default=600)
    p.add_argument("--gl-flags", default="", help="Override the Chrome GL flags (default: SwiftShader as PR4).")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--chrome", default=shutil.which("google-chrome") or "/usr/bin/google-chrome")
    asyncio.run(main(p.parse_args()))
