"""Relink private practice engines with Emscripten 6.0.12 and verified bot objects."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BOT = "CMakeFiles/sith_engine.dir/src/AI/jkBot.c.o"
ARCHIVE_SHA = "57b32bd079f6946ddf820c4a08c62f1e017e2a71e9e9a16fc197b1635ae4e15d"
OBJECTS = {
    "control": "79ab7149d0f1ac96e9b9ee5ccaa974d206903e6024df93b56388b0922951a782",
    "candidate": "f26004fc3219085ab96ef9bb035bf00897dc2a598eb0d7ea2ca3d4fe3a3912ba",
}
HOOKS = ["sithUpdate", "sithTime_Advance", "sithThing_Update", "jkBot_Tick"]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(out, candidate=None, archive=None):
    archive = archive or REPO / "web_bots/engine-relink.tar.gz"
    archive_sha = digest(archive)
    lane = "candidate" if candidate else "control"
    if candidate or archive_sha == ARCHIVE_SHA:
        if archive_sha != ARCHIVE_SHA:
            raise ValueError("The historical C3 candidate needs its original release --archive")
        receipt = json.loads((REPO / "qa/c3-door-access-matches.json").read_bytes())
        expected = receipt["candidate_wasm" if candidate else "baseline_wasm"]
        glue = receipt["build_reproduction"]["candidate_js_sha256" if candidate else "stock_js_sha256"]
    else:
        files = json.loads((REPO / "web_bots/BUILD.json").read_bytes())["files"]
        if archive_sha != files["web_bots/engine-relink.tar.gz"]["sha256"]:
            raise ValueError("Relink archive does not match the current build manifest")
        expected = files["bin/bots-jkweb/openjkdf2.wasm"]["sha256"]
        glue = files["bin/bots-jkweb/openjkdf2.js"]["sha256"]
    version = subprocess.check_output(["emcc", "--version"], text=True).splitlines()[0]
    if "6.0.12" not in version:
        raise ValueError("Expected Emscripten 6.0.12")
    if out.exists() or any((p/".git").exists() for p in (out, *out.parents)):
        raise ValueError("Choose an unused external engine directory")
    with TemporaryDirectory() as tmp:
        work = Path(tmp)
        with tarfile.open(archive) as tar:
            tar.extractall(work, filter="data")
        if candidate:
            shutil.copyfile(candidate, work/BOT)
        if archive_sha == ARCHIVE_SHA and digest(work/BOT) != OBJECTS[lane]:
            raise ValueError("Wrong input bot object")
        link = json.loads((work/"link.json").read_bytes())["link"]
        if link[0] != "em++" or link.count(BOT) != 1:
            raise ValueError("Unexpected relink command")
        wasm, js = work/"openjkdf2.wasm", work/"openjkdf2.js"
        subprocess.run(link, cwd=work, check=True, timeout=480)
        if digest(wasm) != expected or digest(js) != glue:
            raise ValueError("Unmodified baseline failed byte-for-byte reproduction")
        source = HERE/"practice_clock.c"
        subprocess.run(["emcc", "-O2", "-Wall", "-Werror", "-c", source, "-o", "practice.o"],
                       cwd=work, check=True, timeout=120)
        subprocess.run([*link, "practice.o", *["-Wl,--wrap="+name for name in HOOKS]],
                       cwd=work, check=True, timeout=480)
        if b"BOT_PRACTICE_CLOCK" not in wasm.read_bytes() or b"adjoinPracticeRate" not in js.read_bytes():
            raise ValueError("Private clock missing from linked engine")
        out.mkdir()
        for artifact in (wasm, js):
            shutil.copyfile(artifact, out/artifact.name)
        info = dict(engine=lane, base_wasm=expected, base_js=glue, archive_sha256=archive_sha,
                    bot_object_sha256=digest(work/BOT), source=digest(source), emcc=version,
                    supported_rates=[1, 2, 4], files={file.name:digest(file) for file in (wasm,js)})
        (out/"practice-clock.json").write_text(json.dumps(info,indent=2)+"\n")
        print(json.dumps(info), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--candidate-object", type=Path)
    p.add_argument("--archive", type=Path, help="Original relink archive for replaying an older C3 trial")
    a = p.parse_args()
    build(a.output.resolve(), a.candidate_object, a.archive)
