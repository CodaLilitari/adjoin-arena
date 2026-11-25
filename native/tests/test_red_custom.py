"""Compile the actual custom admission and world gates with two independent episode identities."""
import hashlib
import os
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest


class CustomEpisodes(unittest.TestCase):
    def test_explicit_pairs_only(self):
        native=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"episode").mkdir()
            probe=root/"probe.c"; exe=root/"probe"
            probe.write_text('#include "red_custom.h"\nint main(int n,char**v){if(n!=8)return 9;'
                'int a=Custom_Admission(v[1],v[2],v[3],atoi(v[4]),atoi(v[5]));'
                'if(a<0)return 6;if(!a)return 4;return Custom_World(v[3],v[6],v[7])?0:7;}\n')
            subprocess.run(["cc","-std=gnu11","-Wall","-Wextra","-Werror","-I",native,probe,"-lcrypto","-o",exe],check=True)
            base={k:v for k,v in os.environ.items() if not k.startswith("ADJOIN_CUSTOM_")}
            def check(env,args,code):
                p=subprocess.run([exe,*args],env=env,cwd=root,capture_output=True,text=True)
                self.assertEqual(code,p.returncode,p.stderr)
                return p.stderr
            for name,mapname,mode,teams,skins in [("Arena_A","alpha.jkl","ffa","0","0"),
                                                  ("Field_B","zulu.jkl","ctf","1","0"),
                                                  ("Court-C","beta.jkl","tdm","1","1")]:
                # Valid GOB layout and independently declared level identities.
                # The map payload is an admission fixture; live geometry is tested by the arena.
                level=("# local test world "+mapname+"\nSECTION: HEADER\nVersion 1\n").encode()
                episode=(f'"{name}"\nTYPE {10 if mode=="ctf" else 2}\nSEQ 1\n1: 1 1 LEVEL {mapname} 0 0 -1 -1\nend\n').encode()
                payload=bytearray(); table=bytearray()
                for member,body in (("episode.jk",episode),("jkl/"+mapname,level)):
                    table+=struct.pack("<II128s",12+len(payload),len(body),member.encode());payload+=body
                data=struct.pack("<4sII",b"GOB ",20,12+len(payload))+payload+struct.pack("<I",2)+table
                (root/"episode"/(name.lower()+".gob")).write_bytes(data)
                jkl=hashlib.sha256(level).hexdigest()
                env=dict(base,ADJOIN_CUSTOM_EPISODE=name,ADJOIN_CUSTOM_MAP=mapname,
                         ADJOIN_CUSTOM_GOB_SHA256=hashlib.sha256(data).hexdigest(),
                         ADJOIN_CUSTOM_MAP_SHA256=jkl,ADJOIN_CUSTOM_MODE=mode)
                argv=["127.0.0.1:6000",name,mapname,teams,skins,jkl,mode]
                good=check(env,argv,0)
                self.assertIn("phase=admission status=accepted",good); self.assertIn("phase=world status=accepted",good)
                check(base,argv,4)
                for key in tuple(k for k in env if k.startswith("ADJOIN_CUSTOM_")):
                    partial=env.copy(); del partial[key]; check(partial,argv,6)
                check(dict(env,ADJOIN_CUSTOM_GOB_SHA256="0"*64),argv,6)
                check(dict(env,ADJOIN_CUSTOM_EPISODE="../escape"),argv,6)
                for i,value,code in ((0,"192.0.2.1:6000",6),(1,"Other",6),(2,"other.jkl",6),
                                     (5,"0"*64,7),(6,"unsupported",7)):
                    wrong=argv.copy();wrong[i]=value;check(env,wrong,code)
                teamswap=argv.copy();teamswap[3]="0" if teams=="1" else "1";check(env,teamswap,6)
                if mode=="tdm":
                    wrong=argv.copy();wrong[4]="0";check(env,wrong,6)


if __name__=="__main__":
    unittest.main()
