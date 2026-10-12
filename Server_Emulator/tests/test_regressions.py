from contextlib import closing
import json
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import shutil
from pathlib import Path
from login import Accounts
from world import bootstrap_entry, bootstrap_frame, movement_target, parse_commands, MAPS
from protocol import decode, encode


def login_request():
    req=bytearray(44); req[0]=100; req[9:15]=b'player'; req[25:31]=b'player'
    return req


def entry(session, sector=52, slot=0, counter=1):
    req=bytearray(52)
    struct.pack_into('<II', req, 0, (session[0]<<8)|102, session[1])
    req[8]=counter
    struct.pack_into('<iiiii',req,12,sector,0,0,session[0],-1)
    req[32]=slot
    return req


def move(x,z):
    return (2|((x&0xfffff)<<24)|((z&0xfffff)<<44)).to_bytes(8,'little')


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'accounts.sqlite3'
        self.a=Accounts(self.path)
        self.a.db.execute("INSERT INTO characters(player_id,slot,name,race,ship) VALUES(1,0,'Pilot',0,1)")
        self.a.db.commit()
    def tearDown(self):
        self.a.close(); self.temp.cleanup()
    def test_mixed_attack_move_commands_keep_order(self):
        cmds=b'\x01\0\x2a\0'+move(1550,1588)+b'\x03\0\x2a\0'
        header=struct.pack('<IIIII',376,123,30,0,1)
        reply,info=bootstrap_frame(header+cmds,(1,123),True)
        self.assertEqual(reply[20:],b'\x80'+struct.pack('<H',len(cmds))+cmds)
        self.assertEqual(info['command_ids'],[1,2,3])
        self.assertEqual(info['movement_commands'],1)
    def test_relinquish_each_of_five_power_slots(self):
        header=struct.pack('<IIIII',376,123,30,0,1)
        for slot in range(5):
            record=bytes([20,100+slot])
            reply,info=bootstrap_frame(header+record,(1,123),True)
            self.assertEqual(reply[20:],b'\x80\x02\0'+record)
            self.assertEqual(info['command_ids'],[20])
    def test_relinquish_purchase_and_movement_order(self):
        cmds=bytes([20,104,21,0xab,42,0,0,0xcd])+move(1700,1800)
        header=struct.pack('<IIIII',376,123,30,0,1)
        reply,info=bootstrap_frame(header+cmds,(1,123),True)
        self.assertEqual(reply[23:],cmds)
        self.assertEqual(info['command_ids'],[20,21,2])
        with self.assertRaisesRegex(ValueError,'Truncated command 20'):
            parse_commands(b'\x14')
    def test_station_purchase_six_bytes_and_mixed_batch(self):
        purchase=bytes([21,0xab,42,0,0,0xcd])
        commands=purchase+move(1550,1588)+bytes([1,0,42,0])
        header=struct.pack('<IIIII',376,123,30,0,1)
        reply,info=bootstrap_frame(header+commands,(1,123),True)
        self.assertEqual(info['command_ids'],[21,2,1])
        self.assertEqual(reply[23:],commands)
        self.assertEqual(parse_commands(purchase),[purchase])
    def test_truncated_station_purchase_rejected(self):
        for length in range(1,6):
            with self.assertRaisesRegex(ValueError,'Truncated command 21'):
                parse_commands(bytes([21,0,42,0,0,0])[:length])
    def test_four_byte_target_and_twelve_byte_batch(self):
        for cmds in [b'\x01\0\x2a\0',b'\x01\0\x2a\0'+move(42,81)]:
            reply,info=bootstrap_frame(struct.pack('<IIIII',376,123,0,0,1)+cmds,(1,123),True)
            self.assertEqual(reply[23:],cmds)
    def test_truncated_record_is_not_reinterpreted_or_carried_to_next_tick(self):
        with self.assertRaisesRegex(ValueError,'Truncated command 2'):
            parse_commands(move(42,81)[:-1])
        self.assertEqual(parse_commands(move(12,91)),[move(12,91)])
        with self.assertRaisesRegex(ValueError,'Unsupported gameplay command'):
            parse_commands(b'\xff')
    def test_signed_movement_coordinate_layout(self):
        for point in [(1550,1588),(-1,-524288),(524287,0)]:
            self.assertEqual(movement_target(move(*point)),point)
    def test_starter_sector_and_original_resource_manifest(self):
        reply=bootstrap_entry(entry((1,123)),(1,123),self.a)
        self.assertEqual(struct.unpack_from('<I',reply,16)[0],3)
        self.assertEqual(struct.unpack_from('<ii',reply,4),(1550,1588))
        self.assertEqual(MAPS['3']['unit_spawn_rows'],124)
        self.assertEqual(MAPS['52']['unit_spawn_rows'],0)
        self.assertEqual(MAPS['52']['npc_shop_rows'],9)
    def test_portal_entry_honors_target_and_nonzero_entry_coordinate(self):
        self.a.save_location(1,0,3,1550,1588)
        req=entry((1,123),sector=52)
        struct.pack_into('<ii',req,16,2000,2100)
        result=bootstrap_entry(req,(1,123),self.a,restore=False)
        self.assertEqual(struct.unpack_from('<I',result,16)[0],52)
        self.assertEqual(struct.unpack_from('<ii',result,4),(2000,2100))
        self.assertEqual(self.a.location(1,0),(3,1550,1588))
    def test_invalid_saved_sector_fails_without_overwriting_records(self):
        self.a.db.execute('UPDATE characters SET sector=999 WHERE player_id=1')
        self.a.db.commit()
        with self.assertRaisesRegex(ValueError,'Saved sector'):
            bootstrap_entry(entry((1,123)),(1,123),self.a)
        self.assertEqual(self.a.location(1,0),(999,None,None))
    def test_two_controlled_spawns_change_wire_coordinates(self):
        a=bootstrap_entry(entry((1,123)),(1,123),self.a,spawn=(100,100))
        b=bootstrap_entry(entry((1,123)),(1,123),self.a,spawn=(1700,1800))
        self.assertNotEqual(a[4:12],b[4:12])
        self.assertEqual(a[12:],b[12:])
    def test_saved_sector_and_position_survive_reopen(self):
        self.a.save_location(1,0,1,580,2620)
        self.a.close(); self.a=Accounts(self.path)
        reply=bootstrap_entry(entry((1,123)),(1,123),self.a)
        self.assertEqual(struct.unpack_from('<I',reply,16)[0],1)
        self.assertEqual(struct.unpack_from('<ii',reply,4),(580,2620))
    def test_movement_destination_does_not_overwrite_position(self):
        self.a.save_location(1,0,3,1550,1588)
        self.a.save_target(1,0,2500,2800)
        self.assertEqual(self.a.location(1,0),(3,1550,1588))
    def test_intro_flag_per_character_and_persistent_credentials(self):
        before=self.a.db.execute('SELECT name,player_id,salt,password_hash FROM accounts').fetchall()
        self.a.db.execute("INSERT INTO characters(player_id,slot,name,race,ship) VALUES(1,1,'Second',0,1)")
        self.a.db.commit()
        self.assertEqual(struct.unpack_from('<I',self.a.login(login_request())[0],36)[0],0)
        self.a.mark_intro_completed(1,0)
        self.a.close(); self.a=Accounts(self.path)
        reply,_=self.a.login(login_request())
        self.assertEqual(struct.unpack_from('<I',reply,36)[0],1)
        self.assertEqual(struct.unpack_from('<I',reply,64)[0],0)
        self.assertEqual(before,self.a.db.execute('SELECT name,player_id,salt,password_hash FROM accounts').fetchall())
    def test_schema_matches_runtime(self):
        fresh=sqlite3.connect(':memory:')
        try:
            fresh.executescript((Path(__file__).resolve().parents[1]/'data/schema.sql').read_text())
            for table in ['accounts','characters','character_saves']:
                actual=[(r[1],r[2],r[3],r[4],r[5]) for r in self.a.db.execute('PRAGMA table_info('+table+')')]
                expected=[(r[1],r[2],r[3],r[4],r[5]) for r in fresh.execute('PRAGMA table_info('+table+')')]
                self.assertEqual(actual,expected)
        finally: fresh.close()


class MigrationTests(unittest.TestCase):
    def test_old_database_backup_and_records_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'accounts.sqlite3'
            old=sqlite3.connect(path)
            old.executescript("CREATE TABLE accounts(name TEXT PRIMARY KEY,player_id INTEGER UNIQUE NOT NULL,salt BLOB,password_hash BLOB);CREATE TABLE characters(player_id INTEGER,slot INTEGER,name TEXT UNIQUE COLLATE NOCASE,race INTEGER,ship INTEGER,PRIMARY KEY(player_id,slot));")
            old.execute("INSERT INTO accounts VALUES('private',77,?,?)",(b'originalsalt',b'originalhash'))
            old.execute("INSERT INTO characters VALUES(77,2,'Survivor',4,20)")
            old.commit(); old.close()
            accounts=Accounts(path)
            try:
                self.assertEqual(accounts.db.execute("SELECT salt,password_hash FROM accounts WHERE name='private'").fetchone(),(b'originalsalt',b'originalhash'))
                self.assertEqual(accounts.db.execute('SELECT player_id,slot,name,race,ship FROM characters').fetchone(),(77,2,'Survivor',4,20))
                backups=list((path.parent/'backups').glob('*.sqlite3'))
                self.assertEqual(len(backups),1)
                with closing(sqlite3.connect(backups[0])) as saved:
                    self.assertEqual(saved.execute('SELECT name FROM characters').fetchone(),('Survivor',))
                self.assertEqual(accounts.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally: accounts.close()


class UDPIntegrationTests(unittest.TestCase):
    def test_real_server_login_entry_frame_replay_logout_relogin(self):
        # Isolated copy: integration traffic cannot modify the user's DB.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'data').mkdir()
            for name in ['server.py', 'version.py', 'admin.py', 'fragments.py', 'persistence.py','world.py','protocol.py','login.py']:
                shutil.copyfile(Path(__file__).resolve().parents[1]/name,root/name)
            shutil.copyfile(Path(__file__).resolve().parents[1]/'data/maps.json',root/'data/maps.json')
            accounts=Accounts(root/'data/accounts.sqlite3')
            accounts.db.execute("INSERT INTO characters(player_id,slot,name,race,ship) VALUES(1,0,'Pilot',0,1)")
            accounts.db.commit(); accounts.close()
            probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); probe.bind(('127.0.0.1',0))
            port=probe.getsockname()[1]; probe.close()
            process=subprocess.Popen([sys.executable,str(root/'server.py'),'--port',str(port)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
                    client.settimeout(.3); peer=('127.0.0.1',port)
                    from fragments import Reassembler,split_wire
                    from tests.test_persistence import sample
                    incoming=Reassembler(); session=None
                    seq=1
                    def exchange(payload,opcode):
                        nonlocal seq
                        client.sendto(encode(payload,flags=0x10010,sequence=seq),peer); seq+=1
                        end=time.monotonic()+3
                        while time.monotonic()<end:
                            try: packet=decode(client.recv(65535))
                            except (socket.timeout, ConnectionResetError): continue
                            if packet.flags&15==15: continue
                            if (packet.flags>>4)&15==1:
                                client.sendto(encode(flags=15,sequence=packet.sequence),peer)
                            if packet.fragments>1:
                                packet=incoming.feed(packet,peer,session,time.monotonic())
                                if packet is None: continue
                            if packet.payload and packet.payload[0]==opcode: return packet.payload
                        raise AssertionError('Missing response for opcode '+str(opcode))
                    # Retry startup login without depending on a fixed sleep.
                    end=time.monotonic()+5
                    while True:
                        try:
                            request=bytearray(login_request());request[8]=0x53
                            login=exchange(bytes(request),100); break
                        except AssertionError:
                            if time.monotonic()>end: raise
                    word,token=struct.unpack_from('<II',login); session=(word>>8,token)
                    self.assertEqual(struct.unpack_from('<I',login,36)[0],0)
                    result=exchange(entry(session),102)
                    self.assertEqual(struct.unpack_from('<I',result,16)[0],3)
                    header=struct.pack('<IIIII',(session[0]<<8)|120,session[1],0,0,1)
                    commands=bytes([20,100,21,0xab,42,0,0,0xcd])+b'\x01\0\x2a\0'+move(1700,1800)
                    first=exchange(header+commands,120)
                    second=exchange(header+b'\xff',120)
                    self.assertEqual(first,second)
                    self.assertEqual(first[23:],commands)
                    snapshot=bytearray(sample(session)); snapshot[8]=1
                    trailer=struct.pack('<I',1731)+bytes(range(100))+struct.pack('<ff',1700.,1800.)
                    snapshot=bytes(snapshot)+trailer
                    pieces=split_wire(encode(snapshot,flags=0x10010,sequence=seq)); seq+=len(pieces)
                    for piece in reversed(pieces): client.sendto(piece,peer)
                    deadline=time.monotonic()+3
                    while True:
                        with closing(sqlite3.connect(root/'data/accounts.sqlite3')) as saved:
                            row=saved.execute('SELECT core,profile FROM character_saves').fetchone()
                        if row is not None: break
                        if time.monotonic()>deadline: self.fail('Snapshot was not committed')
                        time.sleep(.02)
                    self.assertEqual(row,(snapshot[16:16+0x528],snapshot[16+0x528:0xf54]))
                    leave=bytearray(entry(session));struct.pack_into('<i',leave,12,-1)
                    self.assertEqual(exchange(bytes(leave),102)[1],4)
                    logout=struct.pack('<II',(session[0]<<8)|106,session[1])
                    self.assertEqual(exchange(logout,106),b'j')
                    trailer=struct.pack('<I',2000)+bytes(range(100))+struct.pack('<ff',1700.,1800.)
                    snapshot=snapshot[:0xf54]+trailer
                    pieces=split_wire(encode(snapshot,flags=0x10010,sequence=seq));seq+=len(pieces)
                    for piece in pieces:client.sendto(piece,peer)
                    deadline=time.monotonic()+3
                    while True:
                        with closing(sqlite3.connect(root/'data/accounts.sqlite3')) as saved:
                            extra=saved.execute('SELECT extra FROM character_saves').fetchone()[0]
                        if extra==trailer:break
                        if time.monotonic()>deadline:self.fail('Late final save was not committed')
                        time.sleep(.02)
                    request=bytearray(login_request());request[8]=0x53
                    login=exchange(bytes(request),100)
                    self.assertEqual(struct.unpack_from('<I',login,36)[0],struct.unpack_from('<I',snapshot,16+0x524)[0])
                    word,token=struct.unpack_from('<II',login);session=(word>>8,token)
                    exchange(entry(session),102)
                    header=struct.pack('<IIIII',(session[0]<<8)|120,session[1],0,0,1)
                    restored=exchange(header,120)
                    self.assertEqual(restored[23],6)
                    self.assertEqual(restored[23+274:23+274+0x528],snapshot[16:16+0x528])
                    self.assertEqual(restored[-113:],b'\x7e'+trailer)
                    self.assertEqual(exchange(header+b'\xff',120),restored)
                    with closing(sqlite3.connect(root/'data/accounts.sqlite3')) as saved:
                        self.assertEqual(saved.execute('SELECT sector,position_x,position_z,last_target_x,last_target_z FROM characters').fetchone(),(3,1700,1800,1700,1800))
            finally:
                process.terminate(); process.wait(timeout=5)
                errors=process.stderr.read().decode(); process.stderr.close()
                self.assertNotIn('Traceback',errors)
            logs=list((root/'logs').glob('*.jsonl'))
            rows=[json.loads(line) for line in logs[0].read_text().splitlines()]
            frames=[r for r in rows if r.get('opcode')==120]
            self.assertEqual(len(frames),4)
            self.assertTrue(frames[1]['duplicate'])
            self.assertTrue(all('receive_to_send_ms' in r for r in frames))
            self.assertTrue(all('token' not in r for r in rows))

if __name__=='__main__': unittest.main()
