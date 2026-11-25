"""Compile the production neural loader on Linux and exercise its signed integer ABI."""
import hashlib
from pathlib import Path
import random
import subprocess
import tempfile
import unittest


class NativeRedPolicy(unittest.TestCase):
    def test_cross_language_scores_and_rejected_files(self):
        source=Path(__file__).resolve().parents[1]
        rng=random.Random(51519)
        center=[0,100,-10,1060,15,-25,1,0,10]
        scale=[3,400,1001,300,12,20,1,2,3]
        w1=[[rng.randint(-16384,16384) for _ in range(9)] for _ in range(8)]
        b1=[rng.randint(-33554432,33554432) for _ in range(8)]
        w2=[rng.randint(-16384,16384) for _ in range(8)]
        b2=-97
        rows=[[9,8],center,scale,*[[b,*row] for b,row in zip(b1,w1)],[b2,*w2]]
        data=("RED_NEURAL_V1 "+"\n".join(" ".join(map(str,row)) for row in rows)+"\n").encode()
        def trunc(a,b):
            return -(abs(a)//b) if a<0 else a//b
        def score(x):
            z=[max(-2048,min(2048,trunc((v-c)*1024,s))) for v,c,s in zip(x,center,scale)]
            h=[max(0,min(32768,trunc(b+sum(p*q for p,q in zip(w,z)),1024))) for b,w in zip(b1,w1)]
            return b2+sum(p*q for p,q in zip(w2,h))
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            c=tmp/"test.c"; exe=tmp/"test"; path=tmp/"weights"
            c.write_text('#define RED_POLICY_TEST\n#include "red_policy.inc"\n'
                         'int main(int argc,char **argv){RedNet net;char digest[65];int x[9];'
                         'if(argc!=3||!Red_Load(argv[1],argv[2],&net,digest))return 2;'
                         'while(scanf("%d",&x[0])==1){for(int i=1;i<9;++i)if(scanf("%d",&x[i])!=1)return 3;'
                         'printf("%" PRId64 "\\n",Red_Score(&net,x));} return 0;}\n')
            subprocess.run(["cc","-std=gnu11","-Wall","-Wextra","-Werror","-I",source,c,
                            "-lcrypto","-o",exe],check=True)
            path.write_bytes(data)
            digest=hashlib.sha256(data).hexdigest()
            observations=[[0]*9,center,[2147483647]*9,[-2147483648]*9]+[
                [rng.randint(-1050,5000) for _ in range(9)] for _ in range(350)]
            answer=subprocess.run([exe,path,digest],input="".join(" ".join(map(str,x))+"\n" for x in observations),
                                  text=True,capture_output=True,check=True)
            self.assertEqual([score(x) for x in observations],list(map(int,answer.stdout.split())))
            self.assertEqual(subprocess.run([exe,path,"0"*64]).returncode,2)
            for bad in [data+b" 0",data+b"\0",data[:-8],data.replace(b"3 400",b"0 400"),
                        data.replace(b"9 8",b"8 8",1),b"x"*8193]:
                path.write_bytes(bad)
                self.assertEqual(subprocess.run([exe,path,hashlib.sha256(bad).hexdigest()]).returncode,2)


if __name__=="__main__":
    unittest.main()
