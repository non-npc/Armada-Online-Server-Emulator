# Save protocol implementation notes

The original FUN_00493e10 sends opcode 107 with 0x538 bytes: authenticated ID/token at +0/+4, client mode at +9, exit flag at +10, owner ID at +12, and the 0x528-byte character block at +16. FUN_00493f00 sends opcode 108 with 0xf54 bytes, appending the 0xa1c personal-data block. Uninitialized padding is not used for authentication. These blocks are stored byte-for-byte, except that current admin name/race/ship and the existing intro completion sentinel are applied during restore.

The original loop in FUN_00494200 autosaves every 9001 ticks and starts at player index 1. The local bootstrap uses index 0. The backed-up autosave patch changes the verified immediate divisor to 300 and the initial index to 0.

The five active ship powers (+0xed0, five 20-byte records), gameplay resource balance (+0x994), and position vector (+0x30/+0x38) are outside the original character block (+0x99c through +0xec3). The signature-verified .semu section wraps both upload builders and appends 112 bytes: balance uint32, 100 bytes of powers, float32 X/Z. Byte +8 of an extended save identifies extension version 1. Login byte +8 is 0x53 for extension-capable clients. The server only sends the restore trailer to clients that advertised support.

Restore uses the original FUN_00485cc0 command 6 player-join path: tick, 65 participant IDs, local index, integer X/Z, core block and personal-data block. An extension marker 0x7e and 112-byte trailer follow the personal-data block. The patched consumer copies power slots before original stat initialization, advances the command cursor by 113 bytes, then restores the exact resource balance after join bonuses. The trailer is bounded by the region buffer's length. Original clients receive no trailer. The server ignores pre-restore save uploads and replays committed restore frames unchanged.

Before a sector change/logout, verified wrappers capture current hull/shield/energy into the original saved fields and call the existing full save uploader. Original sector-leave status 4 returns to character selection. A ten-second authenticated grace period accepts final snapshots delivered after a logout packet.

Original reliable transport uses 980-byte payload fragments, index in flag bits 8–15, count in bits 16–23, shared group, and consecutive sequence numbers. Reassembly is limited to eight fragments, 64 groups and ten seconds. Invalid counts, duplicate content conflicts, identity mismatches, stale save sequences and invalid/nonfinite positions are rejected. Logs contain save metadata, not snapshot bytes.

Client hashes:
- Original: 2e9d6bd287228342089b2f7ec29917a15ea89b9eae855110465940530639610b
- Autosave-only input: 0e741c3453737f85053c4594f09dd67d3548e8ee4ae7c90df021f1c7452b1776
- Extended final-save output: 5b4a9886a7e5d4cc860f3b719de2a9996e838894f2fb304fe2124eac4e1523f5

Regular tests use the standard library. The optional Server_Emulator/tests/client_hook_analysis.py uses analysis-only Unicorn and pefile from the surrounding project workspace's analysis_tools folder to execute generated x86 hooks against isolated memory. No such libraries are required to run the server or regular tests. Windows client testing remains necessary, especially for visual updates, mission-specific progression, unusual game modes and crash recovery.
