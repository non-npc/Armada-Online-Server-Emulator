"""Recovered single-datagram transport; no gameplay or fragmentation assembly yet."""
import struct
import binascii
from dataclasses import dataclass


def checksum(data):
    return (binascii.crc32(data, 0xffffffff) ^ 0xffffffff) & 0xffffffff



def xor(data, key):
    return bytes(byte ^ key[i % 4] for i, byte in enumerate(data))


@dataclass
class Packet:
    flags: int
    sequence: int
    group: int
    payload: bytes
    encrypted: bool

    @property
    def channel(self):
        return self.flags >> 24

    @property
    def fragments(self):
        return (self.flags >> 16) & 255


def decode(raw):
    if not 16 <= len(raw) <= 65507:
        raise ValueError('Invalid datagram length')
    key = raw[:4]
    expected = struct.unpack('<I', key)[0]
    body = raw[4:]
    encrypted = False
    if checksum(body) != expected:
        body = xor(body, key)
        encrypted = True
        if checksum(body) != expected:
            raise ValueError('Checksum mismatch')
    flags, sequence, group = struct.unpack('<III', body[:12])
    return Packet(flags, sequence, group, body[12:], encrypted)


def encode(payload=b'', flags=0x10000, sequence=1, group=0, encrypted=True):
    body = struct.pack('<III', flags, sequence, group) + payload
    key = struct.pack('<I', checksum(body))
    return key + (xor(body, key) if encrypted else body)


def replies(packet, sequence):
    result = []
    if packet.flags & 15 == 15:  # acknowledgment; never acknowledge an acknowledgment
        return result
    if (packet.flags >> 4) & 15 == 1:
        result.append(encode(flags=(packet.channel << 24) | 15, sequence=packet.sequence))
    if packet.fragments <= 1 and packet.payload[:1] == b'd':
        # Login UI recognizes p/5 as server version mismatch. Deliberate diagnostic only.
        result.append(encode(b'p\x05', flags=(packet.channel << 24) | 0x10000, sequence=sequence))
    return result
