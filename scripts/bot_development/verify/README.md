# Browser package verification

`web_candidate.py` preserves the independent source/relink check used for the
refinement builds. It does not change tracked QA receipts or the source checkout.
Use Python 3.11+ with tar extraction filters, Git and a local engine repository
containing the base commit pinned in `web_bots/BUILD.json`.

```bash
python scripts/bot_development/verify/web_candidate.py \
  --repo /path/to/adjoin-arena --engine /path/to/OpenJKDF2 \
  --source-only --receipt /path/to/new-source-check.json
```

This verifies all packaged file sizes and hashes, exports the affected files from the pinned base with
`git archive`, checks and applies the packaged patches in their recorded order, and compares every changed
source hash. It retains a temporary staging directory and prints its location.
`--work-dir` chooses the parent directory. No retail game data is needed.

For the full independent relink, initialize the Emscripten version pinned by the
manifest in your shell and omit `--source-only`:

```bash
python scripts/bot_development/verify/web_candidate.py \
  --repo /path/to/adjoin-arena --engine /path/to/OpenJKDF2 \
  --compiler /path/to/emsdk/upstream/emscripten/em++ \
  --receipt /path/to/new-relink-check.json
```

The verifier first links the archived object files with the pinned SDK. For the
room-join package it then recompiles all three bundled libsmacker objects and
links again. It compares the rebuilt object hashes and requires both links to
produce the published JavaScript and WebAssembly byte-for-byte. With
`--source-only`, the receipt records `independent_direct_relink` as null.
