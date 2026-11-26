/* Exercise browser boot/clock adaptation with synthetic exports; no game assets. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const crypto = require("node:crypto");
const delay = ms => new Promise(resolve => setTimeout(resolve,ms));

async function check(mode, adaptive, olderEngine=false, entry=false) {
  const nodes = new Map();
  const el = id => {
    if (!nodes.has(id)) nodes.set(id,{});
    return nodes.get(id);
  };
  const dirs = [], files = [], delivered = [];
  const heap = new Uint8Array(2048);
  let sent = false, payloadReceived = false, inited = false, reportedRules;
  const configuredEntry = [];
  let wasmNow = 100;
  const navigation = mode === "nf-guns";
  const batches = [];
  let flush;
  const clockCmd = new Uint8Array(20+28);
  clockCmd.set(Buffer.from("JKCP")); clockCmd[4]=1; clockCmd[5]=16;
  const view = new DataView(clockCmd.buffer);
  view.setUint16(6,28,true); view.setFloat64(20,5002,true);
  const command = (kind, deadline) => {
    const bytes = clockCmd.slice(), v = new DataView(bytes.buffer);
    bytes[5] = kind; v.setFloat64(20,deadline,true);
    v.setUint32(28,73,true);
    return Buffer.from(bytes).toString("base64");
  };
  const forwardedKinds = new Set();
  const roomTicket = "c".repeat(32), rosterHash = "a".repeat(64), rosterRequests = [];
  const ctx = { crypto:crypto.webcrypto, Uint8Array, DataView, TextDecoder, Blob, console, btoa, atob,
    location:{pathname:"/bot/lily",host:"127.0.0.1:3912",origin:"http://127.0.0.1:3912"},
    document:{querySelector:el,createElement:()=>({}),head:{append(script) {
      const m=ctx.Module;
      m.FS={mkdirTree:x=>dirs.push(x),writeFile:(p,b)=>files.push([p,b.length])};
      m.HEAPU8=heap; m.ENV={};
      m._jkBotWebNow=()=>wasmNow;
      if (mode === "ff-sabers" && !olderEngine) m._jkBotWebHitRules=()=>1;
      if (!olderEngine) m._jkBotWebSetNfSaberEntry=value=>{ configuredEntry.push(value); return value; };
      m._jkBotWebInbox=()=>160;
      m._jkBotWebReceive=n=>delivered.push(heap.slice(160,160+n));
      m._jkBotWebViewFlags=()=>0;
      m._jkBotWebRenderedModel=()=>0;
      if (mode === "nf-sabers") {
        ctx.adjoinPublishZoneRoster = async (...args) => { rosterRequests.push(args); };
        m.jkMods = {current:()=>({fp:rosterHash}), feedUp:()=>"engine publisher"};
      }
      m.preRun[0](); m.onRuntimeInitialized(); script.onload();
      for (const kind of [1,5,7]) {
        const frame = new Uint8Array(24); frame[5] = kind; m.onJkBotEvent(frame);
      }
      inited=true;
    }}},
    setTimeout:(fn,ms)=>setTimeout(fn,Math.min(3,ms)).unref(),
    AbortSignal, setInterval:fn => { flush = fn; },
    __JK_BOT_TOKEN:"synthetic-key",
    fetch:async (url, opts)=>{
      assert.equal(opts.headers.Authorization,"Bearer synthetic-key");
      if(url.endsWith("/navigation")) {
        const request = JSON.parse(opts.body);
        assert.ok(opts.signal instanceof AbortSignal);
        batches.push(request);
        if (batches.length === 1) throw Error("simulated lost acknowledgement");
        return {ok:true,json:async()=>({next:request.first+request.lines.length,discarded:1})};
      }
      if(url.endsWith("/boot")) return {ok:true,json:async()=>({mod:true,navigation,assets:[{path:"/jk1/resource/Res2.gob"}],
        env:{JK_BOT_LILY:adaptive ? "1" : "0",JK_BOT_WEB_NAME:"Darth_Lilitari",JK_BOT_WEB_MODEL:"dlil.3do",JK_BOT_WEB_SOUND:"dlil.snd",
             JK_BOT_WEB_NF_SABER_ENTRY:entry ? "1" : undefined,
             JK_BOT_WEB_HIT_RULES:mode === "ff-sabers" ? "hit-what-you-see" : undefined,
             JK_BOT_WEB_MODE:mode,JK_BOT_WEB_ROOM:"Canyon",JK_BOT_WEB_ROLE:"host",JK_BOT_FORCE_SIDE:"dark",JK_BOT_FORCE_STYLE:"competitive",JK_BOT_WEB_THIRD_PERSON:"1"}})};
      if(url.endsWith("/assets/0"))return {ok:true,arrayBuffer:async()=>new ArrayBuffer(17)};
      assert.ok(url.endsWith("/frames"));
      const msg=JSON.parse(opts.body);
      if (msg.hit_rules) reportedRules=msg.hit_rules;
      assert.ok(!("token" in msg));
      if(msg.frames.length)payloadReceived=true;
      for (const data of msg.frames) forwardedKinds.add(Buffer.from(data,"base64")[5]);
      const send=inited && !sent;
      if (send) {
        sent=true;
        wasmNow+=0.75; // The POST began at 100; the response arrives at 100.75.
      }
      return {ok:true,json:async()=>({frames:send?[command(16,5002),command(19,5001),command(20,5002),command(20,4999),command(20,5000.5),command(16,5000.5)]:[],server_mono:5000})};
    }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../web_bots/client.js"),"utf8"),ctx);
  if (olderEngine) {
    for (let i=0;ctx.jkBot.info().stage!=="failed" && i<50;i++) await delay(5);
    assert.equal(ctx.jkBot.info().stage,"failed");
    assert.match(el("#error").textContent,entry ? /cannot enable predictive NF saber entry/ : /cannot host Hit what you see/);
    assert.equal(inited,false);
    return;
  }
  for(let i=0;!delivered.length && i<50;i++)await delay(5);
  assert.equal(ctx.__JK_BOT_TOKEN,undefined);
  assert.ok(dirs.includes("/jk1/player") && dirs.includes("/mots/persist"));
  assert.deepEqual(files,[["/jk1/resource/Res2.gob",17]]);
  assert.equal(ctx.Module.jkSavesMounted,true);
  assert.equal(ctx.Module.jkBotConfig.mode,mode);
  assert.deepEqual(configuredEntry, entry ? [1] : []);
  assert.equal(reportedRules, mode === "ff-sabers" ? "hit-what-you-see" : undefined);
  assert.equal(ctx.Module.jkBotConfig.hitRules,reportedRules);
  if (mode === "nf-sabers") {
    const publish = ctx.Module.jkMods.feedUp;
    const feed = "https://jediknight.zone/feed/7?up=" + roomTicket;
    assert.equal(publish(feed, rosterHash, ()=>true), true);
    assert.equal(publish(feed, rosterHash, ()=>false), true);
    assert.equal(publish(feed, "b".repeat(64), ()=>true), "engine publisher");
    assert.equal(publish("http://127.0.0.1/feed/7", rosterHash, ()=>true), "engine publisher");
    assert.deepEqual(rosterRequests, [[7, roomTicket, rosterHash]]);
  }
  if (navigation) {
    for (let i=0; i<258; i++) ctx.Module.printErr("BOT_EDGE_ATTEMPT "+i);
    assert.equal(ctx.jkBot.info().navigationDiscarded,2);
    await flush(); await flush(); await flush();
    assert.deepEqual(batches[0],batches[1]);
    assert.equal(batches[2].first,33);
    assert.equal(batches[2].lines[0],"BOT_EDGE_ATTEMPT 32");
    assert.equal(ctx.jkBot.info().navigationDiscarded,4);
  }
  assert.equal(ctx.Module.ENV.JK_BOT_WEB_MODE,mode);
  assert.equal(ctx.Module.jkBotConfig.elite,true);
  assert.equal(ctx.Module.jkBotConfig.sound,"dlil.snd");
  assert.equal(ctx.Module.jkRelayUrl,"ws://127.0.0.1:3912/relay");
  assert.equal(payloadReceived,true);
  assert.deepEqual(Array.from(forwardedKinds), adaptive ? [1,5,7] : [1]);
  assert.equal(ctx.Module.jkBotConfig.lily,adaptive);
  assert.deepEqual(delivered.map(frame=>frame[5]), adaptive ? [16,19,20] : [16]);
  for (const frame of delivered) {
    const v = new DataView(frame.buffer);
    assert.equal(v.getFloat64(20,true), frame[5] === 19 ? 101 : 102);
    assert.equal(v.getUint32(28,true),73);
  }
  assert.equal(new DataView(delivered[0].buffer).getFloat64(20,true),102);
  console.log("Browser client boot, scoped MEMFS, frame transfer and monotonic TTL mapping passed.");
}
Promise.all([...["ff-guns","ff-sabers","nf-guns","nf-sabers"].map((mode,i)=>check(mode,i%2===1)),
             check("ff-sabers",false,true),check("nf-sabers",false,false,true),check("nf-sabers",false,true,true)]).catch(e=>{console.error(e);process.exitCode=1;});
