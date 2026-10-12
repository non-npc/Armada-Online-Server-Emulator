"""Verified original character save uploads and player-join restore layout."""
import struct
import math
CORE_SIZE=0x528
PROFILE_SIZE=0xa1c
SAVE_LENGTHS={107:0x538,108:0xf54}

def parse_save(payload,session):
    base=SAVE_LENGTHS.get(payload[0]) if payload else None
    if base is None or len(payload) not in (base,base+112): raise ValueError('Invalid character snapshot length or opcode')
    extra=payload[base:] or None
    if extra:
        if payload[8]!=1: raise ValueError('Invalid save extension version')
        x,z=struct.unpack_from('<ff',extra,104)
        if not all(math.isfinite(v) and -(2**31)<=v<2**31 for v in (x,z)): raise ValueError('Invalid saved position')
    word,token=struct.unpack_from('<II',payload)
    if session is None or (word>>8,token)!=session: raise ValueError('Character snapshot requires authenticated session')
    if payload[9]!=0 or payload[10] not in (0,1): raise ValueError('Unsupported snapshot mode or exit flag')
    owner=struct.unpack_from('<I',payload,12)[0]
    if owner!=session[0]: raise ValueError('Character snapshot owner mismatch')
    core=payload[16:16+CORE_SIZE]
    try: name=core[:16].split(b'\0',1)[0].decode('ascii')
    except UnicodeDecodeError: raise ValueError('Invalid snapshot character name') from None
    if not name: raise ValueError('Empty snapshot character name')
    flags=struct.unpack_from('<I',core,16)[0]
    return name,(flags>>7)&7,(flags>>1)&63,core,payload[16+CORE_SIZE:base] or None,extra

def restore_command(player_id,core,profile=None,x=-1,z=-1,extra=None):
    if len(core)!=CORE_SIZE or (profile is not None and len(profile)!=PROFILE_SIZE): raise ValueError('Invalid stored snapshot size')
    # FUN_00485cc0 case 6: tick, 65 participant IDs, player index, X/Z,
    # character block and personal profile. Player index 0 is the local ship.
    if extra is not None and len(extra)!=112: raise ValueError('Invalid saved extension size')
    participants=[player_id]+[0xffffffff]*64
    return b'\x06'+struct.pack('<I',0)+struct.pack('<65I',*participants)+struct.pack('<Bii',0,x,z)+core+(profile if profile is not None else bytes(PROFILE_SIZE))+(b'\x7e'+extra if extra is not None else b'')

def prepend_restore(frame,command):
    if len(frame)<21 or frame[0]!=120: raise ValueError('Invalid restore frame')
    if frame[20]==0: existing=b''
    elif frame[20]==0x80:
        count=struct.unpack_from('<H',frame,21)[0]
        existing=frame[23:]
        if count!=len(existing): raise ValueError('Invalid frame command length')
    else: raise ValueError('Unsupported restore region')
    commands=command+existing
    if len(commands)>7980: raise ValueError('Restore exceeds client region buffer')
    return frame[:20]+b'\x80'+struct.pack('<H',len(commands))+commands
