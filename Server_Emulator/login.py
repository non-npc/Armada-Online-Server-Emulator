"""Development login payload inferred from FUN_00443eb0; no world entry."""
import secrets
import hashlib
import hmac
import re
import sqlite3
import struct
from pathlib import Path
from datetime import datetime, timezone

class Accounts:
    def __init__(self, path):
        path = Path(path)
        self.db = sqlite3.connect(path)
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        charcols = {row[1] for row in self.db.execute('PRAGMA table_info(characters)')}
        accountcols = {row[1] for row in self.db.execute('PRAGMA table_info(accounts)')}
        savecols = {row[1] for row in self.db.execute('PRAGMA table_info(character_saves)')}
        required = {'intro_completed', 'sector', 'position_x', 'position_z', 'last_target_x', 'last_target_z'}
        if tables and (not required <= charcols or not {'salt', 'password_hash'} <= accountcols or 'extra' not in savecols):
            backups = path.parent / 'backups'
            backups.mkdir(exist_ok=True)
            backup = backups / (path.stem + '_migration_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.sqlite3')
            dest = sqlite3.connect(backup)
            try:
                self.db.backup(dest)
            finally:
                dest.close()
        self.db.execute('CREATE TABLE IF NOT EXISTS accounts (name TEXT PRIMARY KEY, player_id INTEGER UNIQUE NOT NULL)')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(accounts)')}
        for column in ['salt', 'password_hash']:
            if column not in columns:
                self.db.execute(f'ALTER TABLE accounts ADD COLUMN {column} BLOB')
        row = self.db.execute("SELECT player_id FROM accounts WHERE name='player'").fetchone()
        if row is None and 'accounts' not in tables:
            salt = secrets.token_bytes(16)
            digest = hashlib.pbkdf2_hmac('sha256', b'player', salt, 200000)
            player_id = self.db.execute('SELECT COALESCE(MAX(player_id),0)+1 FROM accounts').fetchone()[0]
            self.db.execute('INSERT INTO accounts(name,player_id,salt,password_hash) VALUES (?,?,?,?)',
                            ('player', player_id, salt, digest))
        self.db.execute('CREATE TABLE IF NOT EXISTS characters (player_id INTEGER, slot INTEGER, name TEXT UNIQUE COLLATE NOCASE, race INTEGER, ship INTEGER, PRIMARY KEY(player_id,slot))')
        charcols = {row[1] for row in self.db.execute('PRAGMA table_info(characters)')}
        if 'intro_completed' not in charcols:
            self.db.execute('ALTER TABLE characters ADD COLUMN intro_completed INTEGER NOT NULL DEFAULT 0')
        for column in ['sector', 'position_x', 'position_z', 'last_target_x', 'last_target_z']:
            if column not in charcols:
                self.db.execute(f'ALTER TABLE characters ADD COLUMN {column} INTEGER')
        self.db.execute("CREATE TABLE IF NOT EXISTS character_saves (player_id INTEGER NOT NULL, slot INTEGER NOT NULL, core BLOB NOT NULL, profile BLOB, saved_at TEXT NOT NULL, PRIMARY KEY(player_id,slot))")
        if 'extra' not in savecols:
            self.db.execute('ALTER TABLE character_saves ADD COLUMN extra BLOB')
        self.db.commit()

    def save_snapshot(self, payload, session, slot):
        from persistence import parse_save
        name, race, ship, core, profile, extra = parse_save(payload, session)
        row = self.db.execute('SELECT name FROM characters WHERE player_id=? AND slot=?', (session[0],slot)).fetchone()
        if row is None or name.lower()!=row[0].lower():
            raise ValueError('Snapshot does not match selected character')
        if race>=6 or ship>=64:
            raise ValueError('Invalid snapshot race or ship')
        # Preserve opaque fields byte-for-byte, including ones not yet decoded.
        self.db.execute("INSERT INTO character_saves(player_id,slot,core,profile,saved_at,extra) VALUES (?,?,?,?,?,?) ON CONFLICT(player_id,slot) DO UPDATE SET core=excluded.core,profile=COALESCE(excluded.profile,character_saves.profile),saved_at=excluded.saved_at,extra=COALESCE(excluded.extra,character_saves.extra)", (session[0],slot,core,profile,datetime.now(timezone.utc).isoformat(),extra))
        self.db.execute('UPDATE characters SET race=?,ship=? WHERE player_id=? AND slot=?', (race,ship,session[0],slot))
        if extra:
            x,z=struct.unpack_from('<ff',extra,104)
            self.db.execute('UPDATE characters SET position_x=?,position_z=? WHERE player_id=? AND slot=?',(round(x),round(z),session[0],slot))
        self.db.commit()
        return len(core),len(profile or b''),len(extra or b'')

    def snapshot(self, player_id, slot):
        row=self.db.execute('SELECT core,profile FROM character_saves WHERE player_id=? AND slot=?',(player_id,slot)).fetchone()
        if row is None: return None
        core=bytearray(row[0])
        metadata=self.db.execute('SELECT name,race,ship,intro_completed FROM characters WHERE player_id=? AND slot=?',(player_id,slot)).fetchone()
        if metadata is None: return None
        name,race,ship,intro=metadata
        core[:16]=name.encode('ascii').ljust(16,b'\0')
        flags=struct.unpack_from('<I',core,16)[0]
        struct.pack_into('<I',core,16,(flags&~0x3fe)|1|(race<<7)|(ship<<1))
        if intro and struct.unpack_from('<I',core,0x524)[0]==0: struct.pack_into('<I',core,0x524,1)
        return bytes(core),row[1]

    def snapshot_extra(self, player_id, slot):
        row=self.db.execute('SELECT extra FROM character_saves WHERE player_id=? AND slot=?',(player_id,slot)).fetchone()
        return row[0] if row else None

    def location(self, player_id, slot):
        return self.db.execute('SELECT sector,position_x,position_z FROM characters WHERE player_id=? AND slot=?', (player_id, slot)).fetchone()

    def save_location(self, player_id, slot, sector, x, z):
        if sector not in {1,2,3,4,5,50,51,52} or not all(isinstance(v,int) and -(2**31) <= v < 2**31 for v in (x,z)):
            raise ValueError('Invalid verified sector or location')
        self.db.execute('UPDATE characters SET sector=?,position_x=?,position_z=? WHERE player_id=? AND slot=?', (sector,x,z,player_id,slot))
        self.db.commit()

    def save_target(self, player_id, slot, x, z):
        # A destination is not the current position. Keep it in separate fields.
        self.db.execute('UPDATE characters SET last_target_x=?,last_target_z=? WHERE player_id=? AND slot=?', (x,z,player_id,slot))
        self.db.commit()

    def mark_intro_completed(self, player_id, slot):
        self.db.execute('UPDATE characters SET intro_completed=1 WHERE player_id=? AND slot=?', (player_id, slot))
        self.db.commit()

    def login(self, payload):
        if len(payload) != 44 or payload[0] != 100:
            raise ValueError('Expected a 44-byte login payload')
        # Exported request builder: version at +4, a byte at +8, username at +9.
        name = payload[9:25].split(b'\0', 1)[0].decode('ascii', 'replace').strip()
        if not name:
            raise ValueError('Empty test username')
        password = payload[25:41].split(b'\0', 1)[0]
        row = self.db.execute('SELECT player_id,salt,password_hash FROM accounts WHERE name=?', (name,)).fetchone()
        if row is None or row[1] is None or row[2] is None:
            raise PermissionError('Invalid test account credentials')
        digest = hashlib.pbkdf2_hmac('sha256', password, row[1], 200000)
        if not hmac.compare_digest(digest, row[2]):
            raise PermissionError('Invalid test account credentials')
        player_id = row[0]
        token = secrets.randbits(32) or 1
        response = bytearray(180)
        # Client reads opcode+24-bit ID, token, status at +8 and six slot records.
        struct.pack_into('<II', response, 0, (player_id << 8) | 100, token)
        response[8] = 0
        for slot, character_name, race, ship, intro_completed in self.db.execute(
                'SELECT slot,name,race,ship,intro_completed FROM characters WHERE player_id=?', (player_id,)):
            base = 12 + slot * 28
            response[base] = 1
            name_bytes = character_name.encode('ascii')[:15]
            response[base+1:base+1+len(name_bytes)] = name_bytes
            response[base+17] = race
            response[base+18] = ship
            snapshot = self.snapshot(player_id,slot)
            response[base+19] = (struct.unpack_from('<I',snapshot[0],0x20)[0] & 0x7f) if snapshot else 1
            if snapshot:
                response[base+21:base+23] = snapshot[0][0x493:0x495]
            # FUN_00443eb0 copies +36 (slot-relative +24) to character +0x524.
            # FUN_0042e5f0 checks that field for zero before loading map 2000.
            # Use 1 as the completion sentinel; this emulator does not award XP yet.
            struct.pack_into('<I', response, base+24, struct.unpack_from('<I',snapshot[0],0x524)[0] if snapshot else int(bool(intro_completed)))
        # Other character fields stay at zero until their semantics are recovered.
        return bytes(response), player_id

    def create_character(self, payload, session):
        if len(payload) != 28 or payload[0] != 104 or session is None:
            return b'h\x03'
        word, token = struct.unpack_from('<II', payload)
        if (word >> 8, token) != session:
            return b'h\x03'
        name = payload[8:24].split(b'\0', 1)[0].decode('ascii', 'replace').strip()
        slot, race, ship = payload[24:27]
        if slot >= 6 or race >= 6 or ship >= 64 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9]+)?', name) or not 2 <= len(name) <= 15:
            return b'h\x03'
        existing = self.db.execute('SELECT name,race,ship FROM characters WHERE player_id=? AND slot=?', (session[0],slot)).fetchone()
        if existing:
            return b'h\x00' if existing == (name,race,ship) else b'h\x03'
        try:
            self.db.execute('INSERT INTO characters(player_id,slot,name,race,ship) VALUES (?,?,?,?,?)', (session[0],slot,name,race,ship))
            self.db.commit()
        except sqlite3.IntegrityError:
            self.db.rollback()
            return b'h\x02'
        return b'h\x00'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.db.close()
