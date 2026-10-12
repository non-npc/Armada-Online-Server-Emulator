from pathlib import Path
import hashlib,struct,tempfile,unittest
from patch_save_extension import INPUT_HASH,OUTPUT_HASH,patched,apply
ROOT=Path(__file__).resolve().parents[1]
class ClientPatchTests(unittest.TestCase):
 def test_supplied_client_has_verified_extension_and_autosave(self):
  data=(ROOT.parent/'Patched_Client/ArmadaOnline_local.exe').read_bytes()
  self.assertEqual(hashlib.sha256(data).hexdigest(),OUTPUT_HASH)
  self.assertEqual(data[0x9361a:0x9361f],bytes.fromhex('b92c010000'))
  self.assertEqual(data[0x93636:0x9363d],bytes.fromhex('c745f800000000'))
  pe=struct.unpack_from('<I',data,0x3c)[0];opt=pe+24;size=struct.unpack_from('<H',data,pe+20)[0];count=struct.unpack_from('<H',data,pe+6)[0]
  header=opt+size+(count-1)*40
  self.assertEqual(data[header:header+8],b'.semu\0\0\0')
 def test_patch_is_reproducible(self):
  source=ROOT.parent/'Patched_Client/backups'/('ArmadaOnline_local.exe.'+INPUT_HASH[:16]+'.bak')
  if not source.exists(): self.skipTest('Original patch input backup unavailable')
  self.assertEqual(hashlib.sha256(patched(source.read_bytes())).hexdigest(),OUTPUT_HASH)
 def test_unknown_build_is_rejected_without_writing(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'game.exe';p.write_bytes(b'unsupported build')
   with self.assertRaises(ValueError):apply(p)
   self.assertEqual(p.read_bytes(),b'unsupported build');self.assertFalse((p.parent/'backups').exists())
if __name__=='__main__':unittest.main()
