"""Apply the ordered JKWeb overlays only from a known complete source state."""
import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile


BASE = "7a6f95c9a3399e59acbf019dc6b25f9981d29dff"
PATCHES = ("engine.patch", "external-room.patch", "bot-tactics-web.patch")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run_git(directory, *args):
    command = ["git", "--no-optional-locks", "-C", str(directory), *map(str, args)]
    return subprocess.check_output(command, timeout=45)


def patch_paths(patches):
    names = set()
    for patch in patches:
        for line in patch.read_text().splitlines():
            if line.startswith(("--- a/", "+++ b/")):
                name = line[6:].split("\t")[0]
                if Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
                    raise ValueError("Invalid source path in " + patch.name)
                names.add(name)
    return sorted(names)


def staged_source(source, base_repo, *, apply=False):
    if run_git(base_repo, "rev-parse", "HEAD").decode().strip() != BASE:
        raise ValueError("The Git source checkout must point to " + BASE)
    patches = [Path(__file__).resolve().parent / name for name in PATCHES]
    paths = patch_paths(patches)

    def state(tree):
        return {name: file_hash(tree / name) for name in paths}

    # The second overlay modifies a hunk introduced by the first. Derive the
    # complete bytes at each patch boundary, including originally absent files.
    with tempfile.TemporaryDirectory(prefix="jkweb-overlay-") as temp:
        reference = Path(temp)
        tracked = run_git(base_repo, "ls-tree", "-r", "--name-only", BASE, "--", *paths).decode().splitlines()
        exported = run_git(base_repo, "archive", BASE, "--", *tracked)
        with tarfile.open(fileobj=io.BytesIO(exported)) as stream:
            stream.extractall(reference, filter="data")
        states = [state(reference)]
        for patch in patches:
            run_git(reference, "apply", "--whitespace=nowarn", patch)
            states.append(state(reference))

    current = state(source)
    if current not in states:
        raise ValueError("Engine overlay inputs contain unknown local changes")
    index = states.index(current)
    if not apply and index != len(patches):
        raise ValueError("The complete engine patch stack is required")
    for index in range(index, len(patches)):
        run_git(source, "apply", "--whitespace=nowarn", patches[index])
        if state(source) != states[index + 1]:
            raise ValueError("Applied source differs at " + patches[index].name)
    return states[-1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    staged_source(args.source.resolve(), args.source.resolve(), apply=True)
