# TEMP: write a GOB from a source GOB, dropping named entries (byte-exact copies of the rest).
import struct,sys
src,dst=sys.argv[1],sys.argv[2]; drop={d.lower() for d in sys.argv[3:]}
f=open(src,'rb').read(); idx=struct.unpack_from('<I',f,8)[0]; n=struct.unpack_from('<I',f,idx)[0]
ents=[]
for i in range(n):
    o,s,name=struct.unpack_from('<II128s',f,idx+4+i*136)
    nm=name.split(b'\0')[0]
    if nm.decode().replace('\\','/').lower() in drop: continue
    ents.append((nm,f[o:o+s]))
hdr=12; parts=[]; offs=[]; pos=hdr
for nm,d in ents: offs.append(pos); parts.append(d); pos+=len(d)
body=b''.join(parts); index_off=pos
idxb=[struct.pack('<I',len(ents))]+[struct.pack('<II128s',o,len(d),nm) for (nm,d),o in zip(ents,offs)]
with open(dst,'wb') as w:
    w.write(b'GOB '+struct.pack('<II',0x14,index_off)); w.write(body); w.write(b''.join(idxb)); print(len(ents),'entries')
