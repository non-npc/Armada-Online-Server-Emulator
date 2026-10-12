"""Local-asset world entry and bounded command relay for the original client."""
import struct
import json
from pathlib import Path

MAPS = json.loads((Path(__file__).resolve().parent / "data/maps.json").read_text())

# Verified consumer lengths in FUN_00485cc0, not a fixed eight-byte stride.
# Command 20: two-byte relinquish/remove record, power slots encoded 100..104.
# FUN_004472c0 builds it; FUN_00485cc0 clears the original active-power flag.
# Command 21: shop target uint16 at +2, offer slot byte at +4; preserve padding.
# FUN_00446bf0 builds 6 bytes; the original client performs purchase checks.
COMMAND_LENGTHS = {1:4, 2:8, 3:4, 4:4, 12:3, 15:4, 20:2, 21:6}

def parse_commands(data):
    records = []
    offset = 0
    while offset < len(data):
        command = data[offset]
        size = COMMAND_LENGTHS.get(command)
        if size is None:
            raise ValueError(f"Unsupported gameplay command {command} at command offset {offset}")
        if offset + size > len(data):
            raise ValueError(f"Truncated command {command} at command offset {offset}: expected {size} bytes")
        records.append(bytes(data[offset:offset+size]))
        offset += size
    return records

def movement_target(record):
    if len(record) != 8 or record[0] != 2:
        raise ValueError("Expected command-2 movement record")
    packed = int.from_bytes(record, "little")
    def signed20(v):
        return v - 0x100000 if v & 0x80000 else v
    # Verified in executable FUN_00494cc0: 20-bit X at bit24, Z at bit44.
    return signed20((packed >> 24) & 0xfffff), signed20((packed >> 44) & 0xfffff)



def bootstrap_frame(payload, session, entered):
    """Return a region-0 frame with zero or more movement commands.

    FUN_004918b0 requires length >20 and consumes region indexes after
    the 20-byte header. A high bit marks uint16 length and command bytes.
    FUN_004917a0 compares header +8 against the outstanding simulation tick.
    FUN_00485cc0 case 2 consumes eight-byte move-to records. Coordinates
    remain packed by the original client; no server simulation is claimed.
    """
    if not 20 <= len(payload) <= 532 or payload[0] != 120:
        raise ValueError('Invalid synchronization request length or opcode')
    word, token, tick, state_hash, sync_word = struct.unpack_from('<IIIII', payload)
    if session is None or (word >> 8, token) != session:
        raise ValueError('Synchronization requires a valid login session')
    if not entered or sync_word & 0xffffff != 1 or sync_word >> 24 != 0:
        raise ValueError('Synchronization requires the active local bootstrap world')
    commands = payload[20:]
    records = parse_commands(commands)
    response = (payload[:20] + b'\x80' + struct.pack('<H', len(commands)) + commands
                if commands else payload + b'\x00')
    return response, {
        'command': 'movement_lockstep_frame' if commands else 'empty_lockstep_frame', 'frame_tick': tick,
        'movement_commands': sum(r[0] == 2 for r in records),
        'command_ids': [r[0] for r in records], 'command_bytes': len(commands),
        'client_state_hash': state_hash, 'synchronization_id': sync_word & 0xffffff,
        'note': 'Experimental local region-0 frame; server-authoritative simulation unavailable',
    }


def bootstrap_entry(payload, session, accounts, spawn=None, restore=True):
    """Local-asset response using original sector definitions and saved entry position.

    Zero block lengths select client CSV loading in FUN_004c1a70. This
    initializes entry only; it does not supply subsequent authoritative ticks.
    """
    info = describe_entry(payload, session)
    if not info['session_valid']:
        raise ValueError('Sector entry requires a valid login session')
    if info['client_mode'] != 0 or info['target_id'] not in {1,2,3,4,5,50,51,52} or info['named_destination']:
        raise ValueError('Unsupported local sector or named destination')
    slot = info['character_slot']
    if slot >= 6 or accounts.db.execute(
            'SELECT 1 FROM characters WHERE player_id=? AND slot=?',
            (session[0], slot)).fetchone() is None:
        raise ValueError('Sector entry requires a saved character in the selected slot')
    response = bytearray(48)
    response[:4] = bytes([102, 0, info['entry_counter'], 0])
    # Initial character selection requests 3 or 52. Until progression is saved,
    # characters created by this emulator have level 1 and belong in sector 3.
    saved = accounts.location(session[0], slot)
    sector = info['target_id']
    if restore and saved and saved[0] is not None and sector in {3,52}:
        sector = saved[0]
    elif restore and (not saved or saved[0] is None) and sector in {3,52}:
        sector = 3
    if str(sector) not in MAPS:
        raise ValueError('Saved sector has no recovered resource definition')
    if spawn is not None:
        x, z = spawn
    elif not restore and (info['requested_x'],info['requested_z']) not in {(0,0),(-1,-1)}:
        x,z=info['requested_x'],info['requested_z']
    elif saved and saved[0] == sector and saved[1] is not None and saved[2] is not None:
        x, z = saved[1:]
    else:
        x, z = MAPS[str(sector)]['spawn']
    if not all(isinstance(v, int) and -(2**31) <= v < 2**31 for v in (x, z)):
        raise ValueError("Spawn coordinates must be signed 32-bit integers")
    struct.pack_into('<iiIIII', response, 4, x, z, 0, sector, 0, 1)
    # +28/+29 and all four length-prefixed blocks remain zero. In particular,
    # do not overwrite the state area at +0x6db94, which contains pointers.
    return bytes(response)


def describe_entry(payload, session):
    # FUN_00491f80 builds a 0x34-byte payload. Never return the session token,
    # destination name, raw bytes, or the two uninitialized padding bytes.
    if len(payload) != 52 or payload[0] != 102:
        raise ValueError('Expected a 52-byte sector-entry payload')
    word, token = struct.unpack_from('<II', payload)
    target, x, z, entry_kind, destination = struct.unpack_from('<iiiii', payload, 12)
    return {
        'command': 'sector_entry',
        'session_valid': session is not None and (word >> 8, token) == session,
        'entry_counter': payload[8],
        'client_mode': payload[9],
        'target_id': target,
        'requested_x': x,
        'requested_z': z,
        'entry_kind': entry_kind,
        'destination_id': destination,
        'character_slot': payload[32],
        'named_destination': bool(payload[33]),
        'note': 'Authenticated local-asset sector entry',
    }
