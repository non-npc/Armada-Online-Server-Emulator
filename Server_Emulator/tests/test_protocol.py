import binascii
import socket
import struct
import unittest
from protocol import checksum, decode, encode, replies

class TransportTests(unittest.TestCase):
    def test_crc_independent_reference(self):
        for body in [b'', b'123456789', bytes(range(256))]:
            expected = binascii.crc32(body, 0xffffffff) ^ 0xffffffff
            self.assertEqual(checksum(body), expected)

    def test_xor_and_plain_receive(self):
        for encrypted in [True, False]:
            body = struct.pack('<III', 0x10010, 7, 0) + b'd' + bytes(43)
            key = struct.pack('<I', binascii.crc32(body, 0xffffffff) ^ 0xffffffff)
            raw = key + (bytes(b ^ key[i % 4] for i, b in enumerate(body)) if encrypted else body)
            packet = decode(raw)
            self.assertEqual(packet.sequence, 7)
            self.assertEqual(packet.payload, b'd' + bytes(43))
            self.assertEqual(packet.encrypted, encrypted)

    def test_invalid_packet_rejected(self):
        with self.assertRaises(ValueError): decode(b'bad')
        raw = bytearray(encode(b'payload')); raw[-1] ^= 1
        with self.assertRaises(ValueError): decode(raw)

    def test_ack_and_login_response_over_udp(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            server.bind(('127.0.0.1', 0)); server.settimeout(1); client.settimeout(1)
            client.sendto(encode(b'd' + bytes(43), flags=0x3010010, sequence=91), server.getsockname())
            raw, address = server.recvfrom(4096)
            output = replies(decode(raw), 5); self.assertEqual(len(output), 2)
            for response in output: server.sendto(response, address)
            ack = decode(client.recv(4096)); reply = decode(client.recv(4096))
            self.assertEqual(ack.flags & 15, 15); self.assertEqual(ack.sequence, 91)
            self.assertEqual(reply.payload, b'p\x05'); self.assertEqual(reply.channel, 3)
            self.assertEqual(replies(ack, 6), [])

    def test_fragment_does_not_trigger_login(self):
        packet = decode(encode(b'd', flags=0x20010))
        self.assertEqual(len(replies(packet, 5)), 1)


class LoginTests(unittest.TestCase):
    def test_success_parser_layout_and_persistence(self):
        import tempfile
        from pathlib import Path
        from login import Accounts
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'accounts.db'
            accounts = Accounts(path)
            request = bytearray(44); request[0] = 100; request[9:15] = b'player'; request[25:31] = b'player'
            payload, player_id = accounts.login(request)
            self.assertEqual(len(payload), 180)
            word, token = struct.unpack_from('<II', payload)
            self.assertEqual(word & 255, 100); self.assertEqual(word >> 8, player_id)
            self.assertNotEqual(token, 0); self.assertEqual(payload[8:], bytes(172))
            accounts.close(); accounts = Accounts(path)
            self.assertEqual(accounts.login(request)[1], player_id)
            with self.assertRaises(ValueError): accounts.login(b'd')
            request[25:31] = b'wrong!'
            with self.assertRaises(PermissionError): accounts.login(request)
            accounts.close()

class CreationTests(unittest.TestCase):
    def test_creation_persistence_and_statuses(self):
        import tempfile
        from pathlib import Path
        from login import Accounts
        with tempfile.TemporaryDirectory() as temp:
            accounts = Accounts(Path(temp)/'accounts.db')
            login = bytearray(44); login[0]=100; login[9:15]=b'player';login[25:31]=b'player'
            success, player_id = accounts.login(login)
            token = struct.unpack_from('<I',success,4)[0]
            session = (player_id,token)
            request = bytearray(28);struct.pack_into('<II',request,0,(player_id<<8)|104,token)
            request[8:11]=b'Baz';request[24:27]=bytes([0,0,1])
            self.assertEqual(accounts.create_character(request,None),b'h\x03')
            self.assertEqual(accounts.create_character(request,session),b'h\x00')
            self.assertEqual(accounts.create_character(request,session),b'h\x00')
            request[24]=1
            self.assertEqual(accounts.create_character(request,session),b'h\x02')
            restored,_=accounts.login(login)
            self.assertEqual(restored[12],1);self.assertEqual(restored[13:16],b'Baz')
            self.assertEqual(restored[29:32],bytes([0,1,1]))
            accounts.close()

if __name__ == '__main__': unittest.main()
