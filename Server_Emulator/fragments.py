"""Bounded original transport fragment reassembly (980-byte payload pieces)."""
from protocol import Packet, decode, encode
CHUNK=0x3d4
class Reassembler:
 def __init__(self): self.pending={}
 def feed(self,packet,peer,session,now):
  self.pending={k:v for k,v in self.pending.items() if now-v[0]<10}
  count=packet.fragments
  if count<=1: return packet
  index=(packet.flags>>8)&255
  if session is None: raise ValueError('Fragmented payload requires a login session')
  if not 2<=count<=8 or index>=count or not 0<len(packet.payload)<=CHUNK: raise ValueError('Invalid fragment bounds')
  if index<count-1 and len(packet.payload)!=CHUNK: raise ValueError('Short non-final fragment')
  key=(peer,session,packet.channel,packet.group)
  if key not in self.pending:
   if len(self.pending)>=64: raise ValueError('Fragment queue full')
   self.pending[key]=(now,count,{})
  _,expected,parts=self.pending[key]
  if expected!=count: raise ValueError('Conflicting fragment count')
  if index in parts and parts[index].payload!=packet.payload: raise ValueError('Conflicting duplicate fragment')
  parts[index]=packet
  if len(parts)<count: return None
  del self.pending[key]
  first=parts[0]
  for i in range(count):
   if parts[i].sequence!=(first.sequence+i)&0xffffffff: raise ValueError('Noncontiguous fragment sequence')
  payload=b''.join(parts[i].payload for i in range(count))
  return Packet((first.flags&0xff0000ff)|0x10000,first.sequence,first.group,payload,first.encrypted)

def split_wire(wire):
 packet=decode(wire)
 if len(packet.payload)<=CHUNK: return [wire]
 count=(len(packet.payload)+CHUNK-1)//CHUNK
 if count>8: raise ValueError('Outgoing payload too large')
 return [encode(packet.payload[i*CHUNK:(i+1)*CHUNK], flags=(packet.channel<<24)|(count<<16)|(i<<8)|0x10,sequence=(packet.sequence+i)&0xffffffff,group=packet.sequence,encrypted=packet.encrypted) for i in range(count)]
