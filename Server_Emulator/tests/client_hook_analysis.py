from pathlib import Path
import sys,struct,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent.parent/'analysis_tools'))
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import *
import pefile
CLIENT=ROOT.parent/'Patched_Client/ArmadaOnline_local.exe'
p=pefile.PE(str(CLIENT));new=p.sections[-1];START=0x400000+new.VirtualAddress
BUFFER=START+0x400;WALLET=START+0x1400
STACK=0x2000000;SHIP=0x3000000;WORLD=0x3100000;MANAGER=0x3200000;FRAME=0x3300000
class HookTests(unittest.TestCase):
 def machine(self):
  u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(0x400000,0xda0000)
  for sec in p.sections:u.mem_write(0x400000+sec.VirtualAddress,sec.get_data())
  for addr,size in [(STACK,0x10000),(SHIP,0x4000),(WORLD,0x70000),(MANAGER,0x1000),(FRAME,0x4000)]:u.mem_map(addr,size)
  u.reg_write(UC_X86_REG_EBP,STACK+0x8000);u.reg_write(UC_X86_REG_ESP,STACK+0x6000)
  u.reg_write(UC_X86_REG_EFLAGS,0x202)
  u.mem_write(WORLD+0x6dbac,struct.pack('<I',MANAGER));u.mem_write(MANAGER,struct.pack('<I',SHIP))
  u.mem_write(0x46fb80,bytes.fromhex('8b4424048b0481c20400'))
  return u
 def save_hook(self,hook,corearg,length):
  u=self.machine();ebp=u.reg_read(UC_X86_REG_EBP);esp=u.reg_read(UC_X86_REG_ESP)
  payload=bytes((i*17)%256 for i in range(length));powers=bytes(range(100))
  u.mem_write(FRAME,payload);u.mem_write(ebp+corearg,struct.pack('<I',SHIP+0x99c))
  u.mem_write(SHIP+0x994,struct.pack('<I',1731));u.mem_write(SHIP+0xed0,powers)
  u.mem_write(SHIP+0x30,struct.pack('<fff',1700.25,0,1800.5))
  # At the original CALL site: IP, port, payload pointer, length.
  u.mem_write(esp,struct.pack('<4I',0x520acc,8101,FRAME,length))
  u.reg_write(UC_X86_REG_EBX,0x11223344);u.emu_start(hook,0x4ec8d0,count=20000)
  output=bytes(u.mem_read(BUFFER,length+112));expected=bytearray(payload);expected[8]=1
  self.assertEqual(output,bytes(expected)+struct.pack('<I',1731)+powers+struct.pack('<ff',1700.25,1800.5))
  self.assertEqual(struct.unpack('<I',u.mem_read(esp+8,4))[0],BUFFER)
  self.assertEqual(struct.unpack('<I',u.mem_read(esp+12,4))[0],length+112)
  self.assertEqual(u.reg_read(UC_X86_REG_EBX),0x11223344)
 def test_sector_exit_final_snapshot_hook(self):
  for hook in (0x492081,0x4920b3):
   u=self.machine();ebp=u.reg_read(UC_X86_REG_EBP);esp=u.reg_read(UC_X86_REG_ESP)
   u.mem_write(ebp-0x3c,struct.pack('<I',WORLD));u.mem_write(ebp-0x44,struct.pack('<I',SHIP))
   u.mem_write(0x84e6b4,struct.pack('<I',1));u.mem_write(SHIP+0x19c,struct.pack('<I',700));u.mem_write(SHIP+0x1a8,struct.pack('<I',800));u.mem_write(SHIP+0x1b0,struct.pack('<I',900))
   u.mem_write(esp,struct.pack('<4I',0x52097c,8101,FRAME,52))
   u.mem_write(0x493f00,b'\xc3');calls=[]
   def capture(machine,address,size,_):
    if address==0x493f00:
     args=struct.unpack('<6I',machine.mem_read(machine.reg_read(UC_X86_REG_ESP)+4,24));calls.append(args)
   u.hook_add(UC_HOOK_CODE,capture);u.emu_start(hook,0x4ec8d0,count=1000)
   self.assertEqual(calls,[(WORLD+0x44a78,SHIP+0x99c,0,0,1,1)])
   self.assertEqual(struct.unpack('<3I',u.mem_read(SHIP+0xe20,12)),(700,800,900))
 def test_core_upload_hook(self):self.save_hook(0x493ec9,8,0x538)
 def test_profile_upload_hook(self):self.save_hook(0x493fc9,12,0xf54)
 def test_login_capability_hook(self):
  u=self.machine();esp=u.reg_read(UC_X86_REG_ESP);u.mem_write(FRAME,bytes(44));u.mem_write(esp,struct.pack('<4I',0x51b628,8101,FRAME,44))
  u.emu_start(0x44433e,0x4ec8d0,count=100);self.assertEqual(u.mem_read(FRAME+8,1),b'S')
 def restore(self,extended):
  u=self.machine();ebp=u.reg_read(UC_X86_REG_EBP);offset=4205;powers=bytes(range(100))
  u.mem_write(ebp-0x1284,struct.pack('<I',FRAME));u.mem_write(ebp-8,struct.pack('<I',offset));u.mem_write(ebp-12,struct.pack('<I',WORLD));u.mem_write(ebp-0xa89,b'\0')
  trailer=b'\x7e'+struct.pack('<I',1731)+powers+struct.pack('<ff',1700.,1800.) if extended else b''
  u.mem_write(FRAME+offset,trailer);u.mem_write(FRAME+0x1fa4,struct.pack('<I',offset+len(trailer)))
  u.emu_start(0x48db28,0x48db2f,count=10000)
  self.assertEqual(struct.unpack('<I',u.mem_read(ebp-8,4))[0],offset+len(trailer))
  if extended:self.assertEqual(u.mem_read(SHIP+0xed0,100),powers)
  else:self.assertEqual(u.mem_read(SHIP+0xed0,100),bytes(100))
  u.mem_write(SHIP+0x994,struct.pack('<I',999))
  u.emu_start(0x48ef43,0x48ef48,count=10000)
  self.assertEqual(struct.unpack('<I',u.mem_read(SHIP+0x994,4))[0],1731 if extended else 999)
  self.assertEqual(u.mem_read(WALLET,4),bytes(4))
 def test_extended_restore_hook(self):self.restore(True)
 def test_legacy_restore_hook(self):self.restore(False)
if __name__=='__main__':unittest.main()
