import struct
import unittest
from world import describe_entry
from world import bootstrap_entry, bootstrap_frame


class EntryTests(unittest.TestCase):
    def test_movement_frame_region_envelope(self):
        header=struct.pack('<IIIII',(1<<8)|120,123,30,987,1)
        commands=b'\x02'+bytes(7)
        response,info=bootstrap_frame(header+commands,(1,123),True)
        self.assertEqual(response,header+b'\x80\x08\0'+commands)
        self.assertEqual(info['movement_commands'],1)
        self.assertEqual(info['command'],'movement_lockstep_frame')
        for data in [commands[:-1],b'\x03'+bytes(7),bytes(520)]:
            with self.assertRaises(ValueError):bootstrap_frame(header+data,(1,123),True)
    def test_frame_headers_and_rejected_context(self):
        request = struct.pack('<IIIII',(1<<8)|120,123,30,987,1)
        response, info = bootstrap_frame(request,(1,123),True)
        self.assertEqual(response,request+b'\0')
        self.assertEqual(info['frame_tick'],30)
        for session, entered in [(None,True),((1,124),True),((1,123),False)]:
            with self.assertRaises(ValueError):bootstrap_frame(request,session,entered)
        for request in [request+b'\0',request[:19],struct.pack('<IIIII',(1<<8)|120,123,30,987,2)]:
            with self.assertRaises(ValueError):bootstrap_frame(request,(1,123),True)
    def test_recovered_request_layout_and_redaction(self):
        payload = bytearray(52)
        struct.pack_into('<II', payload, 0, (7 << 8) | 102, 0xdeadbeef)
        payload[8:12] = bytes([19, 0, 0xab, 0xcd])
        struct.pack_into('<iiiii', payload, 12, 1012, -1, -1, 3, -1)
        payload[32] = 5
        payload[33:40] = b'Private'
        info = describe_entry(payload, (7, 0xdeadbeef))
        self.assertTrue(info['session_valid'])
        self.assertEqual(info['entry_counter'], 19)
        self.assertEqual(info['target_id'], 1012)
        self.assertEqual(info['character_slot'], 5)
        self.assertEqual(info['requested_x'], -1)
        self.assertEqual(info['entry_kind'], 3)
        self.assertEqual(info['destination_id'], -1)
        self.assertTrue(info['named_destination'])
        self.assertNotIn('Private', str(info))
        self.assertNotIn(str(0xdeadbeef), str(info))
        self.assertFalse(describe_entry(payload, None)['session_valid'])
        self.assertFalse(describe_entry(payload, (7, 123))['session_valid'])

    def test_wrong_command_or_length(self):
        for payload in [b'f', b'f' + bytes(52), b'd' + bytes(51)]:
            with self.assertRaises(ValueError):
                describe_entry(payload, None)

    def test_bootstrap_layout_and_validation(self):
        import tempfile
        from pathlib import Path
        from login import Accounts
        with tempfile.TemporaryDirectory() as temp:
            accounts = Accounts(Path(temp) / 'accounts.db')
            accounts.db.execute('INSERT INTO characters(player_id,slot,name,race,ship) VALUES (1,0,\'Baz\',0,1)')
            accounts.db.commit()
            request = bytearray(52)
            struct.pack_into('<II', request, 0, (1 << 8) | 102, 123)
            request[8] = 1
            struct.pack_into('<i', request, 12, 52)
            result = bootstrap_entry(request, (1,123), accounts)
            self.assertEqual(result[:4], bytes([102,0,1,0]))
            self.assertEqual(len(result),48)
            self.assertEqual(struct.unpack_from('<I',result,16)[0],3)
            self.assertEqual(result[32:],bytes(16))
            moved = bootstrap_entry(request, (1,123), accounts, spawn=(1234, -567))
            self.assertEqual(struct.unpack_from('<ii', moved, 4), (1234, -567))
            self.assertEqual(moved[:4], result[:4])
            self.assertEqual(moved[12:], result[12:])
            with self.assertRaises(ValueError):
                bootstrap_entry(request, (1,123), accounts, spawn=(2**31, 0))
            with self.assertRaises(ValueError):bootstrap_entry(request,None,accounts)
            request[32]=1
            with self.assertRaises(ValueError):bootstrap_entry(request,(1,123),accounts)
            request[32]=0
            struct.pack_into('<i',request,12,999)
            with self.assertRaises(ValueError):bootstrap_entry(request,(1,123),accounts)
            accounts.close()


if __name__ == '__main__':
    unittest.main()
