# design-02 П6б: склейка полос y0..y1 нескольких снимков бок о бок (обзор для владельца).
# crop.py out.png y0 y1 in1.png in2.png ... — side-by-side crops of rows y0..y1
import sys, struct, zlib
sys.path.insert(0,'/home/pakar/igor/remlab/tools/design/figma/link')
from importlib import import_module
rp=import_module('compare-shots').read_png
out,y0,y1=sys.argv[1],int(sys.argv[2]),int(sys.argv[3])
imgs=[rp(p) for p in sys.argv[4:]]
rows=[b''.join(r[y]+b'\x60\x60\x60\xff'*4 for w,h,r in imgs) for y in range(y0,y1)]
W=len(rows[0])//4
def ch(t,b): return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b)&0xffffffff)
open(out,'wb').write(b'\x89PNG\r\n\x1a\n'+ch(b'IHDR',struct.pack('>IIBBBBB',W,y1-y0,8,6,0,0,0))+ch(b'IDAT',zlib.compress(b''.join(b'\x00'+r for r in rows),6))+ch(b'IEND',b''))
