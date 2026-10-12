"""Signature-verified extension for this exact local Armada alpha executable.
Adds a versioned save trailer: local balance, five temporary powers, X/Z.
Original installation files are never modified. No external Python libraries.
"""
from pathlib import Path
import hashlib, struct, shutil
OUTPUT_HASH='5b4a9886a7e5d4cc860f3b719de2a9996e838894f2fb304fe2124eac4e1523f5'
INPUT_HASH='0e741c3453737f85053c4594f09dd67d3548e8ee4ae7c90df021f1c7452b1776'
BASE=0x400000
class Code:
 def __init__(self,va): self.va=va;self.b=bytearray();self.labels={};self.fix=[]
 def emit(self,h):self.b.extend(bytes.fromhex(h))
 def word(self,n):self.b.extend(struct.pack('<I',n))
 def label(self,n):self.labels[n]=len(self.b)
 def branch(self,op,target):
  self.emit(op);pos=len(self.b);self.b.extend(bytes(4));self.fix.append((pos,target))
 def finish(self):
  for pos,target in self.fix:
   address=self.va+self.labels[target] if isinstance(target,str) else target
   struct.pack_into('<i',self.b,pos,address-(self.va+pos+4))
  return bytes(self.b)
def align(n,a):return (n+a-1)//a*a

def patched(data):
 if hashlib.sha256(data).hexdigest()!=INPUT_HASH: raise ValueError('Unsupported input hash; no executable changed')
 pe=struct.unpack_from('<I',data,0x3c)[0]; opt=pe+24
 count=struct.unpack_from('<H',data,pe+6)[0]; opts=struct.unpack_from('<H',data,pe+20)[0]; table=opt+opts
 section_align,file_align=struct.unpack_from('<II',data,opt+32)
 if struct.unpack_from('<H',data,opt+70)[0]&0x40: raise ValueError('Unexpected ASLR build')
 last=table+(count-1)*40;vsize,rva,rawsize,raw=struct.unpack_from('<4I',data,last+8)
 newrva=align(rva+vsize,section_align);newraw=align(len(data),file_align);va=BASE+newrva
 if any(data[table+count*40:table+(count+1)*40]): raise ValueError('No empty section-header space')
 buffer=va+0x400;wallet_pointer=va+0x1400
 stubs=bytearray(); hooks=[]
 def add(code):
  address=va+len(stubs);stubs.extend(code.finish());return address
 # Save upload wrappers retain the original argument stack and inet_addr call.
 for hook,core_arg in [(0x493ec9,8),(0x493fc9,12)]:
  c=Code(va+len(stubs));c.emit('60 8b 74 24 2c 8b 4c 24 30 bf');c.word(buffer);c.emit('f3 a4')
  c.emit('8b 75 '+format(core_arg,'02x')+' 8b 46 f8 ab 81 c6 34 05 00 00 b9 19 00 00 00 f3 a5')
  # param core pointer minus 0x96c is the ship position vector's X.
  c.emit('8b 75 '+format(core_arg,'02x')+' 8b 86 94 f6 ff ff ab 8b 86 9c f6 ff ff ab')
  c.emit('c7 44 24 2c');c.word(buffer);c.emit('81 44 24 30 70 00 00 00 c6 05');c.word(buffer+8);c.emit('01 61');c.branch('e9',0x4ec8d0)
  hooks.append((hook,bytes.fromhex('e8')+struct.pack('<i',0x4ec8d0-hook-5),add(c),True))
 # Capture the complete local character immediately before a sector change or logout.
 for hook in (0x492081,0x4920b3):
  c=Code(va+len(stubs));c.emit('60 8b 5d c4 83 7b 10 00');c.branch('0f85','done')
  c.emit('83 7b 1c 00');c.branch('0f85','done')
  c.emit('8b 75 bc 85 f6');c.branch('0f84','done')
  c.emit('8b 86 a8 01 00 00 89 86 24 0e 00 00 8b 86 9c 01 00 00 89 86 20 0e 00 00 8b 86 b0 01 00 00 89 86 28 0e 00 00')
  c.emit('6a 01 ff 35');c.word(0x84e6b4);c.emit('6a 00 6a 00 8d 86 9c 09 00 00 50 8d 83 78 4a 04 00 50');c.branch('e8',0x493f00)
  c.emit('83 c4 18');c.label('done');c.emit('61');c.branch('e9',0x4ec8d0)
  hooks.append((hook,b'\xe8'+struct.pack('<i',0x4ec8d0-hook-5),add(c),True))
 # Login byte +8 announces SEMU extension support. Original login parsing ignores it.
 c=Code(va+len(stubs));c.emit('60 8b 44 24 2c c6 40 08 53 61');c.branch('e9',0x4ec8d0)
 hooks.append((0x44433e,bytes.fromhex('e88d850a00'),add(c),True))
 # After the original core/profile copy, consume the optional extension trailer.
 c=Code(va+len(stubs));c.emit('9c 60 c7 05');c.word(wallet_pointer);c.word(0)
 c.emit('8b b5 7c ed ff ff 8b 55 f8 8b 86 a4 1f 00 00 29 d0 3d 71 00 00 00');c.branch('0f82','done')
 c.emit('01 d6 80 3e 7e');c.branch('0f85','done');c.emit('83 c6 01 89 35');c.word(wallet_pointer)
 c.emit('0f b6 85 77 f5 ff ff 50 8b 4d f4 8b 89 ac db 06 00');c.branch('e8',0x46fb80)
 c.emit('8d b8 d0 0e 00 00 83 c6 04 b9 19 00 00 00 f3 a5 81 45 f8 71 00 00 00')
 c.label('done');c.emit('61 9d 0f b6 85 77 f5 ff ff');c.branch('e9',0x48db2f)
 hooks.append((0x48db28,bytes.fromhex('0fb68577f5ffff'),add(c),False))
 # Finish restoring the exact balance after original join bonuses/stat initialization.
 c=Code(va+len(stubs));c.emit('9c 60 8b 35');c.word(wallet_pointer);c.emit('85 f6');c.branch('0f84','done')
 c.emit('0f b6 85 77 f5 ff ff 50 8b 4d f4 8b 89 ac db 06 00');c.branch('e8',0x46fb80)
 c.emit('8b 16 89 90 94 09 00 00 c7 05');c.word(wallet_pointer);c.word(0)
 c.label('done');c.emit('61 9d b8 01 00 00 00');c.branch('e9',0x48ef48)
 hooks.append((0x48ef43,bytes.fromhex('b801000000'),add(c),False))
 if len(stubs)>0x400: raise ValueError('Stub overlaps snapshot buffer')
 result=bytearray(data)
 for hook,before,destination,call in hooks:
  offset=hook-BASE-0xc00
  if result[offset:offset+len(before)]!=before: raise ValueError('Hook signature mismatch at '+hex(hook))
  result[offset:offset+len(before)]=(b'\xe8' if call else b'\xe9')+struct.pack('<i',destination-hook-5)+b'\x90'*(len(before)-5)
 section=stubs.ljust(0x1600,b'\0');result.extend(bytes(newraw-len(result)));result.extend(section)
 struct.pack_into('<H',result,pe+6,count+1)
 struct.pack_into('<I',result,opt+56,align(newrva+len(section),section_align));struct.pack_into('<I',result,opt+64,0)
 struct.pack_into('<I',result,opt+4,struct.unpack_from('<I',result,opt+4)[0]+len(section))
 struct.pack_into('<8sIIIIIIHHI',result,table+count*40,b'.semu\0\0\0',len(section),newrva,len(section),newraw,0,0,0,0,0xe0000060)
 return bytes(result)
def apply(path):
 path=Path(path);data=path.read_bytes()
 if hashlib.sha256(data).hexdigest()==OUTPUT_HASH:return OUTPUT_HASH
 result=patched(data)
 backups=path.parent/'backups';backups.mkdir(exist_ok=True)
 backup=backups/(path.name+'.'+INPUT_HASH[:16]+'.bak')
 if not backup.exists():shutil.copy2(path,backup)
 path.write_bytes(result);return hashlib.sha256(result).hexdigest()
if __name__=='__main__':
 path=Path(__file__).resolve().parent.parent/'Patched_Client/ArmadaOnline_local.exe'
 print('Extended client SHA256:',apply(path))
 print('Copy the updated patched client into the game installation folder before playing.')
