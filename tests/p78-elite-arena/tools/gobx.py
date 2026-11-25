import struct,sys,os
f=open(sys.argv[1],'rb').read(); out=sys.argv[2]
assert f[:4]==b'GOB '
idx=struct.unpack_from('<I',f,8)[0]; n=struct.unpack_from('<I',f,idx)[0]
for i in range(n):
    o,s,name=struct.unpack_from('<II128s',f,idx+4+i*136)
    name=name.split(b'\0')[0].decode().replace('\\','/')
    p=os.path.join(out,name); os.makedirs(os.path.dirname(p),exist_ok=True)
    open(p,'wb').write(f[o:o+s])
print(n)
