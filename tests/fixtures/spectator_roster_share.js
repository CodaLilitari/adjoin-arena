// Exercise the shipping JKWeb packer and unmodified retail range planner.
const assert = require('node:assert/strict');
const crypto = require('node:crypto').webcrypto;
const fs = require('node:fs');
const vm = require('node:vm');

async function main() {
  const engine = fs.readFileSync(process.argv[2], 'utf8');
  const Module = {};
  const loaded = Symbol();
  let mods;
  // Stop before starting WASM. jkMaps and jkMods are JS modules installed first.
  Object.defineProperty(Module, 'jkMods', {
    get: () => mods,
    set(value) { mods = value; throw loaded; }
  });
  try {
    vm.runInNewContext(engine, {Module, crypto, console, TextEncoder, TextDecoder});
  } catch (e) {
    if (e !== loaded) throw e;
  }
  const maps = Module.jkMaps;
  const pack = (files) => mods.lib.packFiles(files.map(([rel, bytes]) => ({rel, bytes, size: bytes.length})), f => f.bytes);
  const original = Buffer.from('this synthetic data comes from the player install');
  const custom = Buffer.from('new model texture bytes');
  const gob = pack([['other_name.wav', original], ['my_texture.mat', custom]]);
  const outer = pack([['lilitari.gob', gob.bytes]]);
  const fp = await maps.lib.sha256(outer.bytes);
  const retail = [{entries: [{offset: 0, size: original.length, name: 'stock.wav'}],
    read: (offset, count) => original.subarray(offset, offset + count)}];
  mods.current = () => ({name: 'Companion', fp, path: 'jkmods/companion'});
  mods.lib.pack = dir => { assert.equal(dir, '/jk1/jkmods/companion'); return outer; };
  maps.core.gameRoot = () => '/jk1';
  maps.core.retailSources = (root, ext) => { assert.equal(root, '/jk1'); assert.equal(ext, 'gob'); return retail; };
  const prepare = vm.runInNewContext('(' + fs.readFileSync(0, 'utf8') + ')', {window: {Module}});
  const {stream, info} = await prepare(fp);
  const payload = Buffer.from(stream.bytes());
  assert.equal(payload.includes(original), false);
  assert.equal(payload.includes(custom), true);
  assert.equal(info.refsBytes, 44);  // count plus one SHA-256 range descriptor
  assert.equal((await maps.lib.rebuild(info, payload, [], false)).reason, 'missing-retail');
  assert.deepEqual(Buffer.from((await maps.lib.rebuild(info, payload, retail, false)).bytes), Buffer.from(outer.bytes));
  await assert.rejects(prepare('0'.repeat(64)), /no longer mounted/);
}
main().catch(e => { console.error(e); process.exitCode = 1; });
