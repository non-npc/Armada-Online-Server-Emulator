"""Apply verified local autosave fixes to the exact supported patched client."""
from pathlib import Path
import hashlib, shutil, struct
ORIGINAL_HASH='2e9d6bd287228342089b2f7ec29917a15ea89b9eae855110465940530639610b'
OLD=b'64.62.227.98';NEW=b'127.0.0.1'+b'\0'*(len(OLD)-len(b'127.0.0.1'))
# Verified VAs 0x49421a / 0x494236, .text raw mapping RVA-0xc00.
PATCHES=[(0x9361a,b'\xb9\x29\x23\0\0',b'\xb9\x2c\x01\0\0'),(0x93636,b'\xc7\x45\xf8\x01\0\0\0',b'\xc7\x45\xf8\0\0\0\0')]
def apply(path):
 path=Path(path); data=path.read_bytes()
 reconstructed=data.replace(NEW,OLD)
 # Reconstruct exactly the known original bytes before accepting this build.
 for offset,before,after in PATCHES:
  if reconstructed[offset:offset+len(after)]==after:
   reconstructed=reconstructed[:offset]+before+reconstructed[offset+len(after):]
 if hashlib.sha256(reconstructed).hexdigest()!=ORIGINAL_HASH: raise ValueError('Unsupported client build; no files changed')
 result=bytearray(data)
 for offset,before,after in PATCHES:
  if bytes(result[offset:offset+len(before)]) not in (before,after): raise ValueError('Patch signature mismatch')
  result[offset:offset+len(after)]=after
 if bytes(result)==data: return False
 backups=path.parent/'backups';backups.mkdir(exist_ok=True)
 backup=backups/(path.name+'.'+hashlib.sha256(data).hexdigest()[:16]+'.bak')
 if not backup.exists(): shutil.copy2(path,backup)
 path.write_bytes(result)
 return True
if __name__=='__main__':
 target=Path(__file__).resolve().parent.parent/'Patched_Client/ArmadaOnline_local.exe'
 print('Updated local autosave client' if apply(target) else 'Autosave patches already applied')
 print('Copy Patched_Client/ArmadaOnline_local.exe into your game install folder again.')

