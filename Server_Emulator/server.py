"""Loopback-only UDP diagnostic server for Armada Online."""
import argparse
import hashlib
import json
import socket
import time
import struct
from datetime import datetime, timezone
from pathlib import Path
from protocol import decode, encode, replies
from version import __version__
from login import Accounts
from fragments import Reassembler, split_wire, CHUNK
from persistence import restore_command, prepend_restore
from world import describe_entry, bootstrap_entry, bootstrap_frame, parse_commands, movement_target


def serve(port=8101, spawn=None):
    directory = Path(__file__).resolve().parent / 'logs'
    directory.mkdir(exist_ok=True)
    path = directory / datetime.now().strftime('session_%Y%m%d_%H%M%S_%f.jsonl')
    sequence = 1
    data = Path(__file__).resolve().parent / 'data'
    data.mkdir(exist_ok=True)
    accounts = Accounts(data / 'accounts.sqlite3')
    pending = {}
    cached = {}
    sessions = {}
    extended_clients = {}
    entered = set()
    selected = {}
    intro_pending = set()
    target_updates = {}
    last_sync = {}
    reassembler = Reassembler()
    save_sequences = {}
    save_grace = {}
    restore_pending = {}
    restore_guard = set()
    with accounts, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, path.open('x', encoding='utf-8') as log:
        sock.bind(('127.0.0.1', port))
        print(f'Armada SEMU {__version__} listening on 127.0.0.1:{port}', flush=True)
        sock.settimeout(0.2)
        print('Original level-one starter sector 3; client-local resources.', flush=True)
        print(f'Spawn response coordinates (world coordinates; live-client verification required): {spawn if spawn is not None else "original map starting point"}', flush=True)
        print('Manage login accounts in the browser admin page. Local command relay enabled; authoritative physics and progression pending. Ctrl+C stops.', flush=True)
        print(f'Log: {path}', flush=True)
        while True:
            now = time.monotonic()
            for key, (wire, deadline, remaining) in list(pending.items()):
                if now >= deadline:
                    if remaining <= 0:
                        del pending[key]
                    else:
                        sock.sendto(wire, key[0])
                        pending[key] = (wire, now + 0.5, remaining - 1)
            cached = {key: value for key, value in cached.items() if now - value[0] < 30}
            try:
                raw, address = sock.recvfrom(65535)
            except socket.timeout:
                continue
            received_ns = time.perf_counter_ns()
            record = {'time': datetime.now(timezone.utc).isoformat(), 'peer': list(address), 'bytes': len(raw)}
            try:
                packet = decode(raw)
                opcode = packet.payload[0] if packet.payload else None
                record.update(flags=hex(packet.flags), sequence=packet.sequence, group=packet.group,
                              fragments=packet.fragments, channel=packet.channel, opcode=opcode,
                              encrypted=packet.encrypted)
                output = replies(packet, sequence)
                if packet.fragments > 1:
                    assembled = reassembler.feed(packet,address,sessions.get(address),now)
                    if assembled is None:
                        for response in output: sock.sendto(response,address)
                        record['note']='Snapshot fragment buffered; awaiting complete payload'
                        log.write(json.dumps(record)+'\n'); log.flush()
                        continue
                    packet=assembled
                    opcode=packet.payload[0] if packet.payload else None
                    record['assembled_opcode']=opcode
                    record['assembled_bytes']=len(packet.payload)
                if packet.flags & 15 == 15:
                    pending.pop((address, packet.sequence, packet.channel), None)
                elif packet.fragments <= 1 and opcode == 100:
                    # Replace milestone-1 diagnostic reply; preserve its acknowledgment.
                    output = output[:1] if (packet.flags >> 4) & 15 == 1 else []
                    key = (address, packet.sequence, packet.group, packet.channel, hashlib.sha256(packet.payload).digest())
                    if key in cached:
                        response = cached[key][1]
                        record['duplicate'] = True
                    else:
                        try:
                            payload, player_id = accounts.login(packet.payload)
                        except PermissionError:
                            payload, player_id = b'p\x01', None
                        if player_id is not None:
                            if len(sessions) >= 256:
                                sessions.pop(next(iter(sessions)))
                            sessions[address] = (player_id, struct.unpack_from('<I', payload, 4)[0])
                            extended_clients[address] = packet.payload[8] == 0x53
                            entered.discard(address)
                            selected.pop(address, None)
                            save_sequences.pop(address,None)
                            save_grace.pop(address,None)
                            restore_pending.pop(address,None)
                            restore_guard.discard(address)
                            intro_pending.discard(address)
                            last_sync.pop(address, None)
                            cached = {k:v for k,v in cached.items() if k[0] != address or k == key}
                        response = encode(payload, flags=(packet.channel << 24) | 0x10010,
                                          sequence=sequence)
                        if len(cached) >= 256:
                            cached.pop(next(iter(cached)))
                        cached[key] = (now, response)
                        if len(pending) >= 256:
                            pending.pop(next(iter(pending)))
                        pending[(address, sequence, packet.channel)] = (response, now + 0.5, 8)
                        sequence = (sequence + 1) & 0xffffffff
                        record['player_id'] = player_id
                    output.append(response)
                elif packet.fragments <= 1 and opcode == 104:
                    payload = accounts.create_character(packet.payload, sessions.get(address))
                    response = encode(payload, flags=(packet.channel << 24) | 0x10010, sequence=sequence)
                    if len(pending) >= 256:
                        pending.pop(next(iter(pending)))
                    pending[(address, sequence, packet.channel)] = (response, now + 0.5, 8)
                    sequence = (sequence + 1) & 0xffffffff
                    output.append(response)
                    record['creation_status'] = payload[1]
                    record['note'] = 'Character creation response sent'

                if packet.flags & 15 != 15 and opcode in (107,108):
                    grace=save_grace.get(address)
                    if address in entered and address in selected:
                        save_slot=selected[address]
                    elif grace is not None and now<grace[0]:
                        save_slot=grace[1]
                    else:
                        raise ValueError('Snapshot requires an active selected character or recent logout')
                    previous=save_sequences.get(address)
                    newer=previous is None or 0 < ((packet.sequence-previous)&0xffffffff) < 0x80000000
                    if not newer:
                        record['note']='Duplicate or stale snapshot ignored'
                    elif address in restore_pending or address in restore_guard:
                        record['note']='Pre-restore snapshot ignored to preserve saved progress'
                    else:
                        if len(packet.payload) not in (0x538,0xf54) and not extended_clients.get(address):
                            raise ValueError('Extended snapshot requires updated client login')
                        core_size,profile_size,extra_size=accounts.save_snapshot(packet.payload,sessions.get(address),save_slot)
                        save_sequences[address]=packet.sequence
                        record['saved_character_slot']=save_slot
                        record['saved_core_bytes']=core_size
                        record['saved_profile_bytes']=profile_size
                        record['saved_extension_bytes']=extra_size
                        record['note']='Character snapshot committed to SQLite'

                leaving = opcode == 102 and len(packet.payload)==52 and struct.unpack_from('<i',packet.payload,12)[0]==-1
                if packet.flags & 15 != 15 and leaving:
                    info=describe_entry(packet.payload,sessions.get(address))
                    if not info['session_valid'] or address not in entered:
                        raise ValueError('Leaving sector requires an active authenticated character')
                    record.update(info)
                    # Original FUN_00492660 status 4 returns to character selection.
                    response=encode(bytes([102,4,info['entry_counter'],0]),flags=(packet.channel<<24)|0x10010,sequence=sequence)
                    pending[(address,sequence,packet.channel)]=(response,now+0.5,8)
                    sequence=(sequence+1)&0xffffffff;output.append(response)
                    record['note']='Sector leave acknowledged; final snapshot remains accepted'
                if packet.flags & 15 != 15 and packet.fragments <= 1 and opcode == 102 and not leaving:
                    record.update(describe_entry(packet.payload, sessions.get(address)))
                    try:
                        payload = bootstrap_entry(packet.payload, sessions.get(address), accounts, spawn=spawn, restore=address not in entered)
                    except ValueError as exc:
                        record['note'] = str(exc)
                    else:
                        key = (address, 'entry', hashlib.sha256(packet.payload).digest())
                        if key in cached:
                            response = cached[key][1]
                            payload = decode(response).payload
                            record['duplicate'] = True
                        else:
                            response = encode(payload, flags=(packet.channel << 24) | 0x10010,
                                              sequence=sequence)
                            if len(cached) >= 256:
                                cached.pop(next(iter(cached)))
                            cached[key] = (now, response)
                            if len(pending) >= 256:
                                pending.pop(next(iter(pending)))
                            pending[(address, sequence, packet.channel)] = (response, now + 0.5, 8)
                            sequence = (sequence + 1) & 0xffffffff
                        output.append(response)
                        entered.add(address)
                        intro_pending.add(address)
                        selected[address] = record['character_slot']
                        if not record.get('duplicate'):
                            saved_state=accounts.snapshot(sessions[address][0],selected[address])
                            if saved_state: restore_pending[address]=saved_state
                            else: restore_pending.pop(address,None)
                        sector = struct.unpack_from('<I', payload, 16)[0]
                        record['loaded_sector'] = sector
                        record['spawn_x'], record['spawn_z'] = struct.unpack_from('<ii', payload, 4)
                        # Commit on the first authenticated sync, when the client has
                        # actually progressed past entry. Do not mark failed loads.
                        record['intro_completed_saved'] = False
                        if not record.get('duplicate'):
                            cached = {k:v for k,v in cached.items() if not (k[0] == address and len(k)>1 and k[1]=='frame')}
                            last_sync.pop(address, None)
                            accounts.save_location(sessions[address][0], selected[address], sector, record['spawn_x'], record['spawn_z'])
                        record['entry_status'] = 0
                        record['note'] = 'Original local map bootstrap sent; command relay available'
                    print(f"Sector entry: slot={record['character_slot']} target={record['target_id']} "
                          f"counter={record['entry_counter']} session_valid={record['session_valid']}", flush=True)
                if packet.flags & 15 != 15 and packet.fragments <= 1 and opcode == 120:
                    try:
                        frame_request = packet.payload
                        if 20 <= len(frame_request) <= 532:
                            candidate = (address, 'frame', sessions.get(address), struct.unpack_from('<I', frame_request, 8)[0])
                            if candidate in cached:
                                # Validate original retry context before using cached bytes.
                                bootstrap_frame(frame_request[:20], sessions.get(address), address in entered)
                                committed = decode(cached[candidate][1]).payload
                                frame_request = frame_request[:20]
                        payload, info = bootstrap_frame(frame_request, sessions.get(address), address in entered)
                    except ValueError as exc:
                        record['note'] = str(exc)
                    else:
                        record.update(info)
                        if address in intro_pending:
                            accounts.mark_intro_completed(sessions[address][0], selected[address])
                            intro_pending.discard(address)
                            record['intro_completed_saved'] = True
                        prev = last_sync.get(address)
                        if prev is not None:
                            record['sync_interval_ms'] = round((now - prev) * 1000, 2)
                        last_sync[address] = now
                        key = (address, 'frame', sessions[address], info['frame_tick'])
                        if key in cached:
                            response = cached[key][1]
                            record['duplicate'] = True
                            record['note'] = 'Previously committed frame replayed; new commands for this tick ignored'
                        else:
                            if address in restore_pending:
                                core,profile=restore_pending.pop(address)
                                location=accounts.location(sessions[address][0],selected[address])
                                x,z=location[1:] if location and None not in location[1:] else (-1,-1)
                                extra=accounts.snapshot_extra(sessions[address][0],selected[address]) if extended_clients.get(address) else None
                                payload=prepend_restore(payload,restore_command(sessions[address][0],core,profile,x,z,extra=extra))
                                restore_guard.add(address)
                                record['restored_core_bytes']=len(core)
                                record['restored_profile_bytes']=len(profile or b'')
                                record['restored_extension_bytes']=len(extra or b'')
                            else:
                                restore_guard.discard(address)
                            response = encode(payload, flags=packet.channel << 24, sequence=sequence)
                            if len(cached) >= 256:
                                cached.pop(next(iter(cached)))
                            cached[key] = (now, response)
                            sequence = (sequence + max(1,(len(payload)+CHUNK-1)//CHUNK)) & 0xffffffff
                            for command in parse_commands(packet.payload[20:]):
                                if command[0] == 2:
                                    target_updates[address] = movement_target(command)
                        output.append(response)
                if packet.flags & 15 != 15 and packet.fragments <= 1 and opcode == 106:
                    word, token = struct.unpack_from('<II', packet.payload) if len(packet.payload)==8 else (0,0)
                    if sessions.get(address) != (word >> 8, token):
                        raise ValueError('Logout requires a valid login session')
                    output.append(encode(b'j', flags=(packet.channel << 24) | 0x10000, sequence=sequence))
                    sequence = (sequence + 1) & 0xffffffff
                    entered.discard(address)
                    restore_pending.pop(address,None)
                    restore_guard.discard(address)
                    last_sync.pop(address, None)
                    slot=selected.pop(address,None)
                    if slot is not None: save_grace[address]=(now+10,slot)
                    intro_pending.discard(address)
                record['parse_enqueue_ms'] = round((time.perf_counter_ns() - received_ns) / 1e6, 3)
                for response in output:
                    pieces=split_wire(response)
                    for piece in pieces:
                        sock.sendto(piece,address)
                        if len(pieces)>1:
                            fragment=decode(piece)
                            pending[(address,fragment.sequence,fragment.channel)]=(piece,now+0.5,8)
                record['receive_to_send_ms'] = round((time.perf_counter_ns() - received_ns) / 1e6, 3)
                record['replies'] = len(output)
                if address in target_updates:
                    accounts.save_target(sessions[address][0], selected[address], *target_updates.pop(address))
                if 'assembled_opcode' in record:
                    record['fragment_reassembled']=True
                if packet.fragments <= 1 and opcode == 100:
                    record['note'] = 'Login response sent; see player_id for accepted account'
                print(f"RX {len(raw)} bytes opcode={opcode} seq={packet.sequence} replies={len(output)}", flush=True)
            except ValueError as exc:
                record['error'] = str(exc)
                print(f'Rejected: {exc}', flush=True)
            # Metadata only: passwords and packet payloads are deliberately omitted.
            log.write(json.dumps(record) + '\n'); log.flush()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8101)
    parser.add_argument('--version', action='version', version='Armada SEMU '+__version__)
    parser.add_argument('--spawn-x', type=int, default=None)
    parser.add_argument('--spawn-z', type=int, default=None)
    parser.add_argument('--admin-port', type=int, default=8102)
    parser.add_argument('--no-admin', action='store_true')
    args = parser.parse_args()
    if (args.spawn_x is None) != (args.spawn_z is None):
        parser.error('--spawn-x and --spawn-z must be supplied together')
    spawn = None if args.spawn_x is None else (args.spawn_x, args.spawn_z)
    if spawn is not None and not all(-(2**31) <= n < 2**31 for n in spawn):
        parser.error('spawn coordinates must fit signed 32-bit integers')
    admin = None
    try:
        if not args.no_admin:
            from admin import start_admin
            admin = start_admin(Path(__file__).resolve().parent / 'data/accounts.sqlite3', args.admin_port)
        serve(args.port, spawn=spawn)
    except KeyboardInterrupt:
        print('\nStopped.')
    except OSError as exc:
        print(f'Server error: {exc}'); raise SystemExit(1)

    finally:
        if admin is not None:
            admin.shutdown()
            admin.server_close()
