"""Capture the dedicated engine's private native follow camera for a single local match."""
import asyncio
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import secrets
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib

_thread = None
_completed = None
_stop = threading.Event()
PREPARE_TIMEOUT = 20



def png(path, width, height, rgba):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    stride = width * 4
    scan = b"".join(b"\0" + rgba[i:i + stride] for i in range(0, len(rgba), stride))
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0))
    path.write_bytes(data + chunk(b"IDAT", zlib.compress(scan, 1)) + chunk(b"IEND", b""))


def encode(frames, out, captured, video_name="native-follow.mp4"):
    stamps = [item["received_monotonic"] for item in captured]
    deltas = [b - a for a, b in zip(stamps, stamps[1:])]
    if min(deltas) <= 0:
        raise ValueError("non-monotonic observer data")
    lines = []
    for i, duration in enumerate(deltas):
        lines.extend([f"file f{i:05d}.png", "option framerate 1000", f"duration {duration:.6f}"])
    lines.extend([f"file f{len(captured)-1:05d}.png", "option framerate 1000"])
    ffconcat = frames / "frames.ffconcat"
    ffconcat.write_text("ffconcat version 1.0\n" + "\n".join(lines) + "\n")
    video = out / video_name
    subprocess.run(["ffmpeg","-nostdin","-n","-hide_banner","-loglevel","error","-threads","1",
                    "-safe","0","-f","concat","-i",str(ffconcat),"-an","-threads","2",
                    "-fps_mode","vfr","-c:v","libx264","-bf","0","-preset","veryfast","-crf","20",
                    "-pix_fmt","yuv420p","-movflags","+faststart",str(video)],check=True,timeout=45)
    probe = json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_entries",
                    "stream=codec_name,width,height,nb_frames,duration:packet=pts_time:format=duration",
                    "-of","json",str(video)],timeout=12))
    encoded = probe["streams"][0]
    actual = [float(packet["pts_time"]) for packet in probe["packets"]]
    elapsed = [stamp - stamps[0] for stamp in stamps]
    subprocess.run(["ffmpeg","-nostdin","-v","error","-xerror","-threads","2","-i",str(video),
                    "-an","-f","null","-"],check=True,timeout=30)
    if len(actual) != len(captured) or int(encoded["nb_frames"]) != len(captured):
        raise ValueError("Encoded frame count differs from the number of native frames")
    max_error = max(abs(t - expected) for t, expected in zip(actual, elapsed))
    if max_error > .002:
        raise ValueError("Encoded presentation timestamps differ from native observations")
    for duration in (encoded["duration"], probe["format"]["duration"]):
        if not -.001 <= float(duration) - actual[-1] <= .06:
            raise ValueError("Encoded duration disagrees with final presentation time")
    return {"path":video.name,"sha256":hashlib.sha256(video.read_bytes()).hexdigest(),"stream":encoded,
            "max_pts_error_seconds":max_error, "recorded_span":stamps[-1] - stamps[0],"longest_frame_gap":max(deltas), "decoded_fully":True}


async def rifle_camera(obs, state):
    """Use ordinary observer controls to place a detached camera outside the stock alcove."""
    from manager.spectator import SpectatorError
    goal = (2.40, 1.45, 1.24)
    item = (2.399664, 2.053292, 1.124753)
    epochs = {key: state[key] for key in ("world_epoch", "control_epoch")}
    state = await obs.configure(dict(epochs, mode="free", target=None))
    epochs = {key: state[key] for key in epochs}
    sequence = 0
    begin = time.monotonic()
    while time.monotonic() - begin < 14 and not _stop.is_set():
        obs.frame(**epochs)  # renew the independent observer lease during movement
        pose = state["pose"]
        delta = [dest - pos for dest, pos in zip(goal, pose["position"])]
        settled = math.dist(goal, pose["position"]) < .009
        # A zero yaw and pitch align the forward/right movement axes with +Y/+X.
        if settled:
            dx, dy, dz = [dest - pos for dest, pos in zip(item, pose["position"])]
            yaw, pitch = math.atan2(-dx, dy), math.atan2(dz, math.hypot(dx, dy))
            right = forward = vertical = 0.
        else:
            yaw = pitch = 0.
            right, forward, vertical = [max(-1., min(1., d * 1.8)) for d in delta]
        sequence += 1
        try:
            state = await obs.input(dict(epochs,sequence=sequence,forward=forward,right=right,up=vertical,
                         yaw_delta=math.remainder(yaw-pose["yaw"],math.tau),
                         pitch_delta=math.remainder(pitch-pose["pitch"],math.tau)))
        except SpectatorError as exc:
            if exc.status != 429:
                raise
            await asyncio.sleep(.06)
            continue
        if settled:
            # The input request polls once before applying stop. Read actual settled pose.
            await asyncio.sleep(.12)
            state = await obs.refresh()
            if math.dist(goal,state["pose"]["position"]) < .018 and state["pose"]["sector"] == 41:
                return epochs, {"desired_position":goal,"look_at_stock_thing_29":item,
                                "settled_pose":state["pose"],"flight_seconds":time.monotonic()-begin}
        await asyncio.sleep(.075)
    raise ValueError("Free observer did not reach rifle overlook in sector 41")


async def session(command, env, output, port, prepared, launched, recording_dir, camera):
    from web_gateway.ipc import NativeIPC
    from manager.spectator import SpectatorController
    token = secrets.token_urlsafe(32)
    ipc = NativeIPC(port, token)
    env = dict(env, OPENJKDF2_GATEWAY_PORT=str(port), OPENJKDF2_GATEWAY_TOKEN=token,
               OPENJKDF2_REQUIRE_DP_POOL="0")
    out = Path(recording_dir).resolve() if recording_dir else Path(output).resolve() / "spectator"
    if any((parent / ".git").exists() for parent in (out, *out.parents)):
        raise ValueError("Choose a recording directory outside a Git checkout")
    out.mkdir(exist_ok=False, parents=True)
    def flag(name):
        return command[command.index(name) + 1] if name in command else None
    with Path(command[0]).open("rb") as engine:
        engine_sha256 = hashlib.file_digest(engine, "sha256").hexdigest()
    receipt = {"source":"native dedicated host spectator RGBA", "match_directory":Path(output).name,
               "output_directory":out.name,"audio":False,"time_base":"monotonic frame receipt times",
               "clip_limit_seconds":45, "pose_source":"last polled observer status; not sampled synchronously with the pixels",
               "status":"starting","captured":[]}
    receipt["camera"] = camera
    receipt["match"] = {"episode":flag("-episode"), "map":flag("-map"), "engine_sha256":engine_sha256,
                        "started_utc":datetime.now(timezone.utc).isoformat(), "ipc_port":port}
    obs = SpectatorController(ipc, True, lambda: bool(ipc.connected and ipc.session))
    closed = False
    try:
        fds = obs.prepare_launch(env)
        prepared.set_result((env, fds))
        child = await asyncio.wrap_future(launched)
        obs.spawned()
        receipt["match"]["host_pid"] = child.pid
        await ipc.start()
        await ipc.wait_ready(timeout=35)
        await ipc.info()
        obs.start()
        first = time.monotonic()
        seq = 0
        target = None
        station = False
        capped = False
        with tempfile.TemporaryDirectory(prefix="adjoin-follow-") as tmp:
            frames = Path(tmp)
            while not _stop.is_set() and child.poll() is None and time.monotonic() - first < 150:
                s = obs.status()
                receipt["last_state"] = {k:s[k] for k in ("available","state","reason","mode","world_epoch","control_epoch","players")}
                if len(s["players"]) >= 2 and "joined_roster" not in receipt:
                    receipt["joined_roster"] = s["players"]
                    receipt["roster_monotonic"] = time.monotonic()
                if camera == "rifle-overlook":
                    if not station and s["available"]:
                        epochs, station = await rifle_camera(obs, s)
                        receipt["epochs"] = epochs
                        receipt["overlook"] = station
                        s = obs.status()
                    active = bool(station and s["mode"] == "free")
                else:
                    if not target and s["available"] and len(s["players"]) >= 2:
                        chosen = sorted(s["players"], key=lambda x:x["slot"])[0]
                        target = {k:chosen[k] for k in ("peer_id","generation")}
                        receipt["followed"]=chosen
                        new = await obs.configure(dict(world_epoch=s["world_epoch"],control_epoch=s["control_epoch"],
                                                       mode="follow",target=target))
                        receipt["epochs"] = {k:new[k] for k in ("world_epoch","control_epoch")}
                    active = bool(target and s["mode"]=="follow" and s["target"] == target)
                if active:
                    value = obs.frame(after=seq,**receipt["epochs"])
                    if value:
                        seq = value["sequence"]
                        data = value["pixels"]
                        here = len(receipt["captured"])
                        png(frames/f"f{here:05d}.png",value["width"],value["height"],data)
                        receipt["captured"].append({"sequence":seq,"received_monotonic":value["received"],
                            "image_sha256":hashlib.sha256(data).hexdigest(),"pose":s["pose"]})
                        if value["received"] - receipt["captured"][0]["received_monotonic"] >= 45 or here >= 224:
                            capped = True
                            break
                elif target and receipt["captured"] and s["mode"] != "follow":
                    break
                await asyncio.sleep(.075)
            receipt["clip_limit_reached"]=capped
            await obs.close()
            await ipc.close()
            closed = True
            records = receipt["captured"]
            if "joined_roster" in receipt and len(records)>=3 and len(set(v["image_sha256"] for v in records))>=2:
                video_name = "native-follow.mp4" if camera == "follow" else "native-rifle-overlook.mp4"
                receipt["video"]=encode(frames,out,records,video_name)
                receipt["status"]="recorded"
            else:
                receipt["status"]="insufficient_live_frames"
    except Exception as exc:
        if not prepared.done():
            prepared.set_exception(exc)
        receipt["status"]="error"
        receipt["error"]=f"{type(exc).__name__}: {str(exc).replace(token,'[redacted]')}"
    finally:
        if not closed:
            await obs.close()
            await ipc.close()
        receipt_file = out / "observer-receipt.json"
        with receipt_file.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, allow_nan=False)
            stream.write("\n")
    return {"status":receipt["status"], "receipt":str(receipt_file), "error":receipt.get("error"),
            "receipt_sha256":hashlib.sha256(receipt_file.read_bytes()).hexdigest()}


def boot_server(command, directory, env, log, repo, output, *, ipc_port=58471, recording_dir=None, camera="follow", line_buffered=False):
    global _thread, _completed
    if camera not in {"follow", "rifle-overlook"}:
        raise ValueError("Unsupported native observer camera")
    if camera == "rifle-overlook" and ("-map" not in command or command[command.index("-map") + 1].lower() != "m10.jkl"):
        raise ValueError("Stock rifle overlook is specific to Canyon Oasis")
    if _thread:
        raise ValueError("one match per recorder process")
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(Path(repo).resolve()))
    _stop.clear()
    prepared = concurrent.futures.Future()
    launched = concurrent.futures.Future()
    _completed=concurrent.futures.Future()
    def record():
        try:
            outcome = asyncio.run(session(command, env, output, ipc_port, prepared, launched, recording_dir, camera))
            _completed.set_result(outcome)
        except BaseException as exc:
            if not prepared.done():
                prepared.set_exception(exc)
            _completed.set_exception(exc)
    _thread=threading.Thread(target=record,name="arena-native-observer",daemon=True)
    _thread.start()
    # Only the caller spawns the host, after the observer has prepared its pipes.
    # A late observer can finish cleanup after a timeout but cannot create a child.
    try:
        host_env, fds = prepared.result(timeout=PREPARE_TIMEOUT)
        launch_command = ["stdbuf", "-oL", *command] if line_buffered else command
        child = subprocess.Popen(launch_command, cwd=directory, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, env=host_env, pass_fds=fds,
                                 start_new_session=True)
    except BaseException as exc:
        launched.set_exception(exc)
        raise
    launched.set_result(child)
    return child


def finish():
    global _thread
    _stop.set()
    if _thread:
        _thread.join(timeout=100)
        if _thread.is_alive():
            raise TimeoutError("observer did not flush the clip")
        _thread = None
        result = _completed.result()
        if result["status"] != "recorded":
            raise RuntimeError(f"Unverified spectator capture ({result['status']}): {result['receipt']}")
        return result
