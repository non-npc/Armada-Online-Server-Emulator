import unittest, tempfile, struct
from pathlib import Path
from login import Accounts
from persistence import *
from fragments import Reassembler,split_wire
from protocol import encode,decode

def sample(session=(1,123),opcode=108,name='Pilot'):
 core=bytearray((i*17)%256 for i in range(CORE_SIZE)); core[:16]=name.encode().ljust(16,b'\0')
 struct.pack_into('<I',core,16,1|(1<<1))
 struct.pack_into('<I',core,0x20,7)
 profile=bytes((i*13)%256 for i in range(PROFILE_SIZE)) if opcode==108 else b''
 return struct.pack('<II4BI',(session[0]<<8)|opcode,session[1],0,0,1,0,session[0])+core+profile

class SnapshotTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'accounts.sqlite3';self.a=Accounts(self.path)
  self.a.db.execute("INSERT INTO characters(player_id,slot,name,race,ship) VALUES(1,0,'Pilot',0,1)");self.a.db.commit()
 def tearDown(self): self.a.close();self.temp.cleanup()
 def test_roundtrip_all_opaque_bytes_and_reopen(self):
  payload=sample();self.a.save_snapshot(payload,(1,123),0)
  self.a.close();self.a=Accounts(self.path)
  self.assertEqual(self.a.snapshot(1,0),(payload[16:16+CORE_SIZE],payload[16+CORE_SIZE:]))
  self.assertEqual(self.a.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
 def test_core_only_preserves_extended_profile(self):
  self.a.save_snapshot(sample(),(1,123),0);self.a.save_snapshot(sample(opcode=107),(1,123),0)
  self.assertEqual(len(self.a.snapshot(1,0)[1]),PROFILE_SIZE)
 def test_extended_balance_powers_and_position(self):
  base=bytearray(sample());base[8]=1
  powers=bytes((i*3)%256 for i in range(100))
  trailer=struct.pack('<I',1731)+powers+struct.pack('<ff',1700.25,1800.5)
  self.a.save_snapshot(bytes(base)+trailer,(1,123),0)
  self.a.close();self.a=Accounts(self.path)
  self.assertEqual(self.a.snapshot_extra(1,0),trailer)
  self.assertEqual(self.a.location(1,0)[1:],(1700,1800))
  core,profile=self.a.snapshot(1,0)
  command=restore_command(1,core,profile,1700,1800,extra=trailer)
  self.assertEqual(command[-113:],b'\x7e'+trailer)
 def test_invalid_extended_position_rejected(self):
  base=bytearray(sample());base[8]=1
  with self.assertRaises(ValueError):self.a.save_snapshot(bytes(base)+bytes(104)+struct.pack('<ff',float('nan'),0),(1,123),0)
  self.assertIsNone(self.a.snapshot(1,0))
 def test_wrong_session_character_and_truncation_are_rejected(self):
  for payload,session,slot in [(sample(),(1,999),0),(sample(name='Other'),(1,123),0),(sample()[:-1],(1,123),0),(sample(),(1,123),1)]:
   with self.assertRaises(ValueError):self.a.save_snapshot(payload,session,slot)
  self.assertIsNone(self.a.snapshot(1,0))
 def test_admin_metadata_overrides_snapshot_without_losing_inventory(self):
  payload=sample();self.a.save_snapshot(payload,(1,123),0)
  self.a.db.execute("UPDATE characters SET name='Renamed',race=2,ship=4,intro_completed=1");self.a.db.commit()
  core,_=self.a.snapshot(1,0);self.assertEqual(core[:16],b'Renamed'.ljust(16,b'\0'))
  self.assertEqual(core[0x198:0x3c8],payload[16+0x198:16+0x3c8])
  self.assertEqual((struct.unpack_from('<I',core,16)[0]>>7)&7,2)
 def test_restore_layout_and_frame_replay_payload(self):
  payload=sample();core,profile=payload[16:16+CORE_SIZE],payload[16+CORE_SIZE:]
  command=restore_command(1,core,profile,1550,1588)
  self.assertEqual(command[0],6);self.assertEqual(struct.unpack_from('<65I',command,5),(1,)+(0xffffffff,)*64)
  self.assertEqual(struct.unpack_from('<Bii',command,265),(0,1550,1588))
  self.assertEqual(command[274:274+CORE_SIZE],core);self.assertEqual(command[274+CORE_SIZE:],profile)
  frame=struct.pack('<IIIII',120,0,15,0,1)+b'\0'
  result=prepend_restore(frame,command);self.assertEqual(result[23:],command)
  self.assertEqual(struct.unpack_from('<H',result,21)[0],len(command))

class FragmentTests(unittest.TestCase):
 def test_out_of_order_reassembly_and_duplicate(self):
  payload=sample();packets=[decode(w) for w in split_wire(encode(payload,sequence=100))];r=Reassembler()
  self.assertIsNone(r.feed(packets[-1],'peer',(1,123),0))
  self.assertIsNone(r.feed(packets[-1],'peer',(1,123),1))
  result=None
  for packet in packets[:-1]: result=r.feed(packet,'peer',(1,123),2)
  self.assertEqual(result.payload,payload)
 def test_restore_five_fragments(self):
  payload=sample();command=restore_command(1,payload[16:16+CORE_SIZE],payload[16+CORE_SIZE:])
  frame=prepend_restore(struct.pack('<IIIII',120,0,15,0,1)+b'\0',command)
  pieces=split_wire(encode(frame,sequence=1000));self.assertEqual(len(pieces),5)
  r=Reassembler();result=None
  for wire in reversed(pieces):result=r.feed(decode(wire),'peer',(1,123),0)
  self.assertEqual(result.payload,frame)
 def test_unauthenticated_and_conflicting_fragments(self):
  packet=decode(split_wire(encode(sample(),sequence=100))[0]);r=Reassembler()
  with self.assertRaises(ValueError): r.feed(packet,'peer',None,0)
  r.feed(packet,'peer',(1,123),0)
  altered=decode(encode(b'x'*980,flags=packet.flags,sequence=100,group=packet.group))
  with self.assertRaises(ValueError):r.feed(altered,'peer',(1,123),1)
 def test_expired_fragment_cannot_complete_old_upload(self):
  packets=[decode(w) for w in split_wire(encode(sample(),sequence=100))];r=Reassembler()
  self.assertIsNone(r.feed(packets[0],'peer',(1,123),0));self.assertIsNone(r.feed(packets[1],'peer',(1,123),11))
if __name__=='__main__':unittest.main()
