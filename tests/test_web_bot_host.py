import base64
import json
import struct
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from web_bots import serve
from bots import companion as cp


class HostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for filename in serve.ASSETS:
            f = self.root / "game" / filename
            f.parent.mkdir(exist_ok=True,parents=True)
            f.write_bytes(b"fixture")
        engine = self.root/"engine"
        engine.mkdir()
        (engine/"openjkdf2.js").write_text("")
        (engine/"openjkdf2.wasm").write_bytes(b"x")
        self.host = serve.Host(self.root/"game", engine, self.root/"run", "My_Room", None, False)
        self.server = TestServer(self.host.app(), host="127.0.0.1")
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.host.set_port(self.server.port)
        self.addAsyncCleanup(self.client.close)
        self.addCleanup(self.host.close)
        self.auth = {"Authorization":"Bearer "+self.host.tokens["lily"]}

    async def test_scoped_asset_and_boot(self):
        url = "/engine/lily/boot"
        body = {"instance":"a"*32}
        self.assertEqual((await self.client.post(url,json=body)).status,401)
        res = await self.client.post(url,json=body,headers=self.auth)
        self.assertEqual(res.status,200)
        data = await res.json()
        self.assertEqual(data["env"]["JK_BOT_WEB_ROLE"],"host")
        self.assertNotIn(self.host.tokens["lily"],json.dumps(data))
        self.assertEqual((await self.client.post("/engine/yun/boot",json=body,headers=self.auth)).status,401)
        self.assertEqual((await self.client.get("/engine/lily/assets/0",headers=self.auth)).status,200)
        self.assertEqual((await self.client.get("/engine/lily/assets/0")).status,401)
        self.assertEqual((await self.client.get("/engine/lily/assets/999",headers=self.auth)).status,404)
        self.assertEqual((await self.client.get("/status",headers={"Origin":"https://invalid.test"})).status,403)

    async def boot(self):
        result=await self.client.post("/engine/lily/boot",json={"instance":"a"*32},headers=self.auth)
        self.assertEqual(result.status,200)
        return await result.json()

    async def exchange(self, datagrams, **extra):
        body=dict(instance="a"*32,frames=[base64.b64encode(raw).decode() for raw in datagrams],**extra)
        return await self.client.post("/engine/lily/frames",json=body,headers=self.auth)

    async def test_model_and_engine_credential_never_served_as_public_files(self):
        conf=await self.boot()
        self.assertFalse(conf["mod"])
        self.assertEqual([f["path"] for f in conf["assets"]],["/jk1/"+f for f in serve.ASSETS])
        for route in ("/engines/lily.json","/wasm/other","/bot/unknown"):
            self.assertEqual((await self.client.get(route)).status,404)
        self.assertEqual((await self.client.get("/status",headers={"Host":"someone-else.example"})).status,403)
        result=await self.client.get("/relay")
        self.assertIn(result.status,(403,503))

    async def test_datagram_http_round_trip_and_epoch_fencing(self):
        await self.boot()
        state=bytearray(144)
        struct.pack_into("<4I",state,0,1,42,88,13)
        struct.pack_into("<iII",state,60,-1,4,0xffffffff)
        res=await self.exchange([cp.frame(cp.STATE,1,1,1,state)],view={"flags":7,"model":"dlil.3do"})
        self.assertEqual(res.status,200)
        status=await (await self.client.get("/status")).json()
        self.assertEqual(status["joined_count"],1)
        self.assertEqual(status["seats"]["lily"]["view"],{"flags":7,"model":"dlil.3do"})
        hub=self.host.hub
        token=hub.bots["lily"].token
        fence={"run_id":hub.run_id,"world_epoch":1,"life_epoch":1}
        _,lease=hub.request("POST","lily","attach","",token,dict(fence,controller="Coda"))
        _,pending=hub.request("POST","lily","strategy","",token,
                             dict(fence,lease_id=lease["lease_id"],request_id="web",mode="recover"))
        self.assertEqual(pending["status"],"pending")
        response=await (await self.exchange([])).json()
        raw=base64.b64decode(response["frames"][0]); _,_,kind,_,world,life,seq=cp.HEADER.unpack_from(raw)
        self.assertEqual((kind,world,life),(16,1,1))
        self.assertLessEqual(struct.unpack_from("<d",raw,20)[0]-response["server_mono"],10)
        await self.exchange([cp.frame(cp.ACK,1,1,seq,struct.pack("<BBH",0,kind,0))])
        self.assertEqual(hub.request("GET","lily","commands/web","",token,None)[1]["status"],"applied")
        self.assertEqual((await self.exchange([b"bad"])).status,400)
        self.assertEqual((await self.client.post("/engine/lily/boot",json={"instance":"b"*32},headers=self.auth)).status,409)
        self.host.seats["lily"]["poll"]-=9
        await self.client.post("/engine/lily/boot",json={"instance":"b"*32},headers=self.auth)
        self.assertEqual((await self.exchange([])).status,409)
        data={"instance":"b"*32,"frames":[base64.b64encode(cp.frame(cp.STATE,1,1,1,state)).decode()]}
        self.assertEqual((await self.client.post("/engine/lily/frames",json=data,headers=self.auth)).status,200)
        self.assertEqual(hub.bots["lily"].world,2)
        self.assertIsNone(hub.bots["lily"].lease)

    async def test_ordered_and_bounded_private_video_file(self):
        await self.boot()
        prefix="/engine/lily/capture/"
        hdr={**self.auth,"X-Engine-Instance":"a"*32}
        meta={"mime":"video/webm","audio_tracks":1,"width":640,"height":360}
        cap=await (await self.client.post(prefix+"start",json=meta,headers=hdr)).json()
        hdr["X-Capture-ID"]=cap["capture_id"]
        raw=bytes.fromhex("1a45dfa3")+b"fixture"
        self.assertEqual((await self.client.post(prefix+"chunk",data=raw,headers={**hdr,"X-Chunk-Index":"1"})).status,409)
        self.assertEqual((await self.client.post(prefix+"chunk",data=raw,headers={**hdr,"X-Chunk-Index":"0"})).status,200)
        self.assertEqual((await self.client.post(prefix+"finish",json={"chunks":1,"duration_seconds":2.1},headers=hdr)).status,200)
        status=await (await self.client.get("/status")).json()
        self.assertNotIn("capture_id",status["capture"])
        self.assertEqual((self.host.runtime/status["capture"]["filename"]).read_bytes(),raw)
