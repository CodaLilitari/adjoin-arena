"""Export a self-contained, hot-reloadable Lily policy with immutable weights."""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path

from . import motor_model


def policy_source(model):
    model=motor_model.validate_model(model)
    # Exact inference code travels with the weights; the worker needs no NumPy
    # and no import of this checkout. Revisions are ordinary trusted local code.
    pieces=["\"\"\"Learned movement candidate; use a learned-motor directive with a goal.\"\"\"",
            "import math", "ABI_VERSION = 1", "FEATURES = "+repr(motor_model.FEATURES),
            "OUTPUTS = "+repr(motor_model.OUTPUTS),
            "MODEL_SHA256 = "+repr(motor_model.digest(model)),
            "MODEL = "+repr(model)]
    for name in ("number","vector","unit","dot","features","validate_model","predict"):
        pieces.append(inspect.getsource(getattr(motor_model,name)))
    pieces.append('''
validate_model(MODEL)

def decide(observation, context):
    if context.get("undertaking"):
        return {"action": "wait"}
    directive = context.get("directive") or {}
    if directive.get("goal") != "learned-motor":
        return {"action": "baseline"}
    params = directive.get("parameters") or {}
    goal = {"direction": params["direction"], "distance": params["distance"]}
    duration = params.get("duration_ms", 550)
    if type(duration) is not int or not 1 <= duration <= 600:
        raise ValueError("Motor duration must be 1..600 ms.")
    sense = observation["lily"]["sense"]
    values = predict(MODEL, features(sense, observation["state"], goal))
    buttons = (1 if values[4] >= .5 else 0) | (2 if values[5] >= .5 else 0)
    step = dict(zip(OUTPUTS[:4], values[:4]))
    step.update(duration_ms=duration, buttons=buttons)
    return {"action": "motor", "skill": "learned-motor", "steps": [step], "goal": goal}
''')
    source="\n\n".join(pieces)+"\n"
    compile(source,"lily-learned-motor","exec")
    if len(source.encode())>128*1024:
        raise ValueError("Export exceeds the policy source-size bound; use a smaller hidden layer.")
    return source


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        model=motor_model.load_model(args.model)
        args.output.write_text(policy_source(model),encoding="utf-8")
        print(json.dumps({"model_sha256":motor_model.digest(model),"policy":str(args.output)}))
        return 0
    except (OSError,ValueError) as exc:
        parser.exit(1,"Motor export: "+str(exc)+"\n")


if __name__ == "__main__":
    raise SystemExit(main())
