"""The coach seat: watch one live bot and coach it, or take the seat yourself.

Attach to any bot that exposes the companion API (a JKWeb seat started by
``web_bots.headless`` or ``web_bots.join_room``, or a native bot started by
``bots.run --companion-port``). In ``auto`` the seat runs the UCB1 coach from
``bots.coach``. An operator can jump in at any time: ``preset``, ``set`` and
``strategy`` take the seat over (the coach stops grading and the open window
is dropped, never scored), and ``auto`` hands it back.

Operator input comes from the terminal (``--interactive``) or, for a person or
agent that cannot hold a terminal, from a control directory: append lines to
``DIR/commands.txt`` and read ``DIR/status.json`` / ``DIR/log.jsonl``.

Commands:
    status                         print the latest observation summary
    preset NAME                    apply a tactics preset (with reset) and hold it
    set NAME=VALUE [NAME=VALUE..]  merge tactic values and hold them
    strategy MODE [ttl=S] [weapon=N] [resource=BIN] [range=R] [risk=R]
                                   send an expiring strategy (autonomous|pressure|resource|recover)
    say TEXT                       public chat, only if the run allows companion chat
    auto                           hand the seat to the learning coach
    lilivane                       hand the seat to Lilivane's observation policy
    hold                           stop coaching but keep the lease and current tactics
    release                        give the lease back; the bot plays on its own
    quit                           release and exit

Every effect goes through the engine's ordinary companion commands; nothing
here touches game state directly. Wren (AI collaborator, via Grok Bot).
"""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import queue
import signal
import secrets
import shlex
import sys
import threading
import time

from . import tactics
from .lilivane_policy import Policy as LilivanePolicy
from .coach import Bandit, Coach, build_id, load_brain_memory, load_memory, save_brain_memory, save_memory
from .companion import MODES
from .companion_cli import call, load_private

FENCE = ("run_id", "world_epoch", "life_epoch")


class ControlFile:
    """Tail DIR/commands.txt; write DIR/status.json and DIR/log.jsonl."""
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.commands = self.dir / "commands.txt"
        self.commands.touch()
        self.offset = self.commands.stat().st_size  # only lines written after start

    def read(self):
        size = self.commands.stat().st_size
        if size < self.offset:
            self.offset = 0
        if size == self.offset:
            return []
        with self.commands.open("r", encoding="utf-8") as f:
            f.seek(self.offset)
            data = f.read()
        complete = data.rfind("\n") + 1
        self.offset += len(data[:complete].encode("utf-8"))
        return [line.strip() for line in data[:complete].splitlines() if line.strip()]

    def status(self, value: dict):
        temporary = self.dir / "status.json.tmp"
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.dir / "status.json")

    def log(self, value: dict):
        with (self.dir / "log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(value, sort_keys=True) + "\n")


class CoachSeat:
    def __init__(self, cred, coach: Coach, *, memory=None, label="default", build=None,
                 request=call, clock=time.monotonic, log=print, control: ControlFile | None = None,
                 start="auto", controller="coach", save_record=None, weapons="guns"):
        self.cred, self.coach, self.memory, self.label, self.build = cred, coach, memory, label, build
        self.save_record = save_record
        self.request, self.clock, self.out, self.control = request, clock, log, control
        self.mode = start
        self.lilivane = LilivanePolicy(weapons=weapons)
        self.controller_epoch = 0
        self.lease = None
        self.queued = []
        self.pending = None          # (kind, label, request_id, coach_preset or None)
        self.last = {}
        self.manual = None           # description of what the operator applied
        self.controller = controller
        self.history = []

    # -- helpers ---------------------------------------------------------
    def say(self, kind, **fields):
        entry = dict(t=round(self.clock(), 2), kind=kind, **fields)
        self.history.append(entry)
        self.history = self.history[-50:]
        if self.control:
            self.control.log(entry)
        self.out("seat: " + kind + " " + json.dumps(fields, sort_keys=True))

    def send(self, route, body, label, coach_preset=None):
        key = secrets.token_hex(12)
        result = self.request(self.cred, route, dict(self.lease, request_id=key, **body))
        self.pending = (route, label, key, coach_preset, self.mode, self.controller_epoch)
        self.say("sent", route=route, what=label, status=result.get("status") if isinstance(result, dict) else None)

    def summary(self):
        state = (self.last.get("state") or {}) if self.last else {}
        return {"mode": self.mode, "leased": self.lease is not None, "coach_preset": self.coach.current,
                "lilivane_preset": self.lilivane.current, "manual": self.manual, "pending": self.pending[1] if self.pending else None,
                "native_active": self.last.get("native_active"), "build": self.build, "label": self.label,
                "bandit": self.coach.bandit.export(),
                "state": {k: state.get(k) for k in ("kills", "deaths", "health", "shields", "mana", "weapon",
                                                     "mode", "sector", "position") if k in state},
                "recent": self.history[-8:]}

    # -- operator commands -----------------------------------------------
    def command(self, line: str) -> bool:
        """Apply one operator line. Returns False when the seat should exit."""
        try:
            words = shlex.split(line)
        except ValueError as error:
            self.say("error", line=line, error=str(error)); return True
        if not words:
            return True
        op, args = words[0].lower(), words[1:]
        try:
            if op == "status":
                self.out(json.dumps(self.summary(), indent=2, sort_keys=True))
            elif op == "quit":
                return False
            elif op in ("auto", "lilivane"):
                self.controller_epoch += 1
                self.lilivane.reset()
                self.mode, self.manual = op, None
                self.coach.current = None   # the coach picks and applies its next preset
                self.say("handback")
            elif op == "hold":
                self.mode = "hold"; self.coach.current = None; self.say("hold")
            elif op == "release":
                self.release(); self.mode = "released"; self.coach.current = None
            elif op == "preset":
                if len(args) != 1 or args[0] not in tactics.PRESETS:
                    raise ValueError("preset NAME, one of " + ", ".join(sorted(tactics.PRESETS)))
                self.takeover(("tactics", {"preset": args[0], "reset": True}, "preset " + args[0]))
            elif op == "set":
                values = tactics.parse_assignments(args)
                tactics.validate(values)
                self.takeover(("tactics", {"values": values}, "set " + " ".join(args)))
            elif op == "strategy":
                if not args or args[0] not in MODES:
                    raise ValueError("strategy MODE, one of " + ", ".join(MODES))
                body = {"mode": args[0]}
                names = {"ttl": "ttl_seconds", "weapon": "weapon", "resource": "resource", "range": "range", "risk": "risk"}
                for item in args[1:]:
                    key, _, value = item.partition("=")
                    if key not in names or not value:
                        raise ValueError("strategy options: ttl= weapon= resource= range= risk=")
                    body[names[key]] = float(value) if key in ("ttl", "range", "risk") else int(value)
                self.takeover(("strategy", body, "strategy " + " ".join(args)))
            elif op == "say":
                if not args:
                    raise ValueError("say TEXT")
                self.takeover(("say", {"text": " ".join(args)}, "say"), keep_mode=True)
            else:
                raise ValueError("unknown command " + op)
        except ValueError as error:
            self.say("error", line=line, error=str(error))
        return True

    def takeover(self, action, keep_mode=False):
        if not keep_mode:
            self.controller_epoch += 1
            if self.mode == "auto" and self.coach.current is not None:
                self.say("takeover", dropped_window_of=self.coach.current)
            self.mode = "manual"
            self.coach.current = None  # the open window is dropped, never graded
        self.queued.append(action)  # FIFO: commands arriving together are all sent, in order

    # -- lease and coaching ----------------------------------------------
    def release(self):
        if self.lease:
            try:
                self.request(self.cred, "release", dict(self.lease, request_id=secrets.token_hex(12)))
            except (OSError, ValueError, KeyError, http.client.HTTPException):
                pass
            self.say("released")
        self.lease = self.pending = None

    waiting = False

    def refused(self, error):
        """The hub refused a request. A bot whose state is briefly stale (dead,
        loading, a slow page) answers 'Waiting for native state' while our lease
        is still valid: keep it and renew it next pass. Dropping it here made the
        seat lock itself out ('A controller holds this bot') until the hub's 30 s
        expiry. A moved fence or a lost lease starts the next pass clean."""
        text = str(error)
        if "Waiting for native state" in text and self.lease:
            if not self.waiting:
                self.say("hub", error=text, kept_lease=True)
            self.waiting = True
            return
        self.waiting = False
        self.say("hub", error=text)
        self.lease = self.pending = None

    def tick(self):
        observed = self.request(self.cred, "observation")
        self.last = observed
        fence = {key: observed[key] for key in FENCE}
        if self.mode == "released" and not self.queued:
            return
        if self.lease is None or any(self.lease[key] != fence[key] for key in FENCE):
            self.lease = self.pending = None
            self.lilivane.reset()
            if observed["native_active"]:
                ticket = self.request(self.cred, "attach", dict(fence, controller=self.controller))
                self.lease = dict(fence, lease_id=ticket["lease_id"])
                if self.mode == "released":
                    self.mode = "manual"
        else:
            self.request(self.cred, "renew", self.lease)
        if not self.lease:
            return
        now = self.clock()
        game_time = observed["state"].get("game_time", now)
        if self.pending:
            route, label, key, coach_preset, owner, epoch = self.pending
            result = self.request(self.cred, "commands/" + key)
            status = result.get("status")
            if status != "pending":
                self.pending = None
                self.say("result", what=label, status=status, reason=result.get("reason"))
                if status == "applied":
                    if coach_preset and owner == self.mode and epoch == self.controller_epoch:
                        if owner == "lilivane":
                            self.lilivane.applied(game_time, coach_preset)
                        elif owner == "auto":
                            self.coach.begin(coach_preset, observed["state"], now)
                    elif not coach_preset:
                        self.manual = label
            return
        if self.queued:
            route, body, label = self.queued.pop(0)
            self.send(route, body, label)
            return
        if self.mode == "lilivane":
            preset = self.lilivane.choose(game_time, observed["state"])
            if preset:
                self.send("tactics", {"preset": preset, "reset": True}, "Lilivane preset " + preset, preset)
        elif self.mode == "auto":
            before = dict(self.coach.bandit.plays)
            preset = self.coach.step(observed["state"], now)
            if self.coach.bandit.plays != before:
                if self.save_record is not None:
                    self.save_record(self.label, self.coach.bandit.export(), self.build)
                else:
                    save_memory(self.memory, self.label, self.coach.bandit.export(), self.build)
                self.say("graded", bandit=self.coach.bandit.export())
            if preset:
                self.send("tactics", {"preset": preset, "reset": True}, "coach preset " + preset, coach_preset=preset)


def run(seat: CoachSeat, *, seconds=0.0, poll=1.0, sleep=time.sleep, inputs=None):
    started = seat.clock()
    try:
        while not seconds or seat.clock() - started < seconds:
            lines = []
            if seat.control:
                lines += seat.control.read()
            while inputs is not None:
                try:
                    lines.append(inputs.get_nowait())
                except queue.Empty:
                    break
            for line in lines:
                seat.say("operator", line=line)
                if not seat.command(line):
                    return
            try:
                seat.tick()
                seat.waiting = False
            except ValueError as error:
                seat.refused(error)
            except (OSError, http.client.HTTPException) as error:
                seat.say("unreachable", error=str(error))
            if seat.control:
                seat.control.status(seat.summary())
            sleep(poll)
    finally:
        seat.release()
        if seat.control:
            seat.control.status(dict(seat.summary(), stopped=True))


def stdin_lines():
    lines = queue.Queue()
    def reader():
        for line in sys.stdin:
            lines.put(line.strip())
        lines.put("quit")
    threading.Thread(target=reader, daemon=True).start()
    return lines


def resolve_credentials(args):
    if args.credentials:
        return args.credentials
    manifest = json.loads(Path(args.run).read_text(encoding="utf-8"))
    seats = manifest.get("seats") or {}
    if args.seat not in seats:
        raise ValueError("Seat not in this headless run: " + args.seat)
    return Path(seats[args.seat]["companion_credential"])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--credentials", type=Path, help="Private companion BOT.json of the seat to coach.")
    who.add_argument("--run", type=Path, help="headless.json written by web_bots.headless (use with --seat).")
    p.add_argument("--seat", help="Seat name inside --run.")
    p.add_argument("--presets", default="default,arsenal,hunter,standoff,dry")
    p.add_argument("--dwell-seconds", type=float, default=90.0)
    p.add_argument("--memory", type=Path)
    p.add_argument("--brain-root", type=Path,
                   help="BrainStore root to persist coach stats (instead of --memory).")
    p.add_argument("--brain-profile", default="coach",
                   help="BrainStore profile that owns the coach record.")
    p.add_argument("--label", default="default")
    p.add_argument("--engine", type=Path, help="Engine file the bot runs (hashed into the memory record).")
    p.add_argument("--build-id")
    p.add_argument("--seconds", type=float, default=0.0)
    p.add_argument("--poll", type=float, default=1.0)
    p.add_argument("--start", choices=("auto", "lilivane", "manual", "hold"), default="auto")
    p.add_argument("--weapons", choices=("guns", "sabers"), default="guns", help="Match weapon rules for Lilivane.")
    p.add_argument("--interactive", action="store_true", help="Read operator commands from the terminal.")
    p.add_argument("--control", type=Path, help="Control directory (commands.txt in, status.json/log.jsonl out).")
    args = p.parse_args(argv)
    if args.memory is not None and args.brain_root is not None:
        p.error("choose either --memory or --brain-root, not both")
    if args.run and not args.seat:
        p.error("--run needs --seat")
    def stop(signum, frame):  # SIGTERM releases the lease (run()'s finally) instead of holding it 30 s
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        arms = [name for name in args.presets.split(",") if name]
        unknown = [name for name in arms if name not in tactics.PRESETS]
        if unknown:
            raise ValueError("Unknown presets: " + ", ".join(unknown))
        build = args.build_id or build_id(args.engine)
        store = save_record = None
        if args.brain_root is not None:
            from .brain import BrainStore
            store = BrainStore(args.brain_root, args.brain_profile)
            record = load_brain_memory(store, args.label, build)
            save_record = lambda label, snapshot, saved_build: save_brain_memory(
                store, label, snapshot, saved_build)
        else:
            record = load_memory(args.memory, args.label, build)
        coach = Coach(Bandit(arms, record=record), args.dwell_seconds)
        seat = CoachSeat(load_private(resolve_credentials(args)), coach, memory=args.memory, label=args.label,
                         build=build, control=ControlFile(args.control) if args.control else None, start=args.start,
                         save_record=save_record, weapons=args.weapons)
        try:
            run(seat, seconds=args.seconds, poll=args.poll, inputs=stdin_lines() if args.interactive else None)
        finally:
            if store is not None:
                store.close()
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as error:
        print(f"Coach seat: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
