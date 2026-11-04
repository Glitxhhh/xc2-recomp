"""Write libnx-sharp.bin, the game's monolib/shader/lib_nx.ini with its own anti-aliasing and dynamic resolution off.

XC2 3.0.1's bf2.ard holds lib_nx.ini, the post-processing settings, as one xbc1 block (a 0x30-byte header, then a zlib
stream) at bf2.ard+0x28205d430: 1566 bytes compressed, 4460 unpacked. The edits (found in Aegis, aegis-xc2
runtime/services/romfs_virtual.c xc2_patch_libnx, MIT): AntiAliasing=off (the game's FXAA-style pass), red_Auto=off
(dynamic resolution), and red_sclX/Y, red_hdsclX/Y (0.75 shipped), red_AtMinX/Y (0.7 shipped) at 1.0. The edited text
is padded to the old size with spaces and recompressed into the same 1566 bytes (zlib level 9: 1558), so the block
keeps its place and size and nothing else in the archive moves. runtime/romfs.c serves these bytes over the original's
when XC2_GAME_SHARP=1.

Output, in the build directory next to romfs-index.bin (derived from the player's game files, never in the repo):
libnx-sharp.bin, the whole replacement block (0x30 + 1566 bytes). Without a matching block (another game version, or
a RomFS without bf2.ard) no file is written and an old one is removed.

    .venv\\Scripts\\python tools\\libnx_sharp.py --romfs build\\extracted\\upd\\romfs --out build\\upd

Standard library only.
"""
import argparse
import json
import struct
import zlib
from pathlib import Path

ARCHIVE = 'bf2.ard'
BLOCK = 0x28205d430           # in bf2.ard
HEADER = 0x30
PACKED, UNPACKED = 1566, 4460
NAME = b'lib_nx.ini'
EDITS = {'AntiAliasing': 'off', 'red_Auto': 'off', 'red_sclX': '1.0', 'red_sclY': '1.0', 'red_hdsclX': '1.0',
         'red_hdsclY': '1.0', 'red_AtMinX': '1.0', 'red_AtMinY': '1.0'}
OUT_NAME = 'libnx-sharp.bin'


def edit_block(block):
    """The replacement for one xbc1 block (header and PACKED bytes), or None with the reason it does not apply."""
    if len(block) != HEADER + PACKED or block[:4] != b'xbc1':
        return None, 'no xbc1 block there'
    kind, unpacked, packed = struct.unpack_from('<III', block, 4)
    if (kind, unpacked, packed) != (1, UNPACKED, PACKED) or block[0x14:0x14 + len(NAME) + 1] != NAME + b'\0':
        return None, f'the block there is not lib_nx.ini ({kind}, {unpacked}, {packed})'
    text = zlib.decompress(block[HEADER:])
    lines, done = text.split(b'\n'), set()
    for i, line in enumerate(lines):
        key = line.split(b'=', 1)[0].decode('latin1')
        if key in EDITS and b'=' in line:
            lines[i] = f'{key}={EDITS[key]}'.encode() + (b'\r' if line.endswith(b'\r') else b'')
            done.add(key)
    if done != set(EDITS):
        return None, f'lib_nx.ini lacks {", ".join(sorted(set(EDITS) - done))}'
    out = b'\n'.join(lines)
    if len(out) > UNPACKED:
        return None, 'the edited lib_nx.ini is longer than the original'
    packed_out = zlib.compress(out.ljust(UNPACKED, b' '), 9)
    if len(packed_out) > PACKED:
        return None, f'the edited lib_nx.ini packs to {len(packed_out)} bytes, more than {PACKED}'
    return block[:HEADER] + packed_out.ljust(PACKED, b'\0'), None


def write(romfs, out):
    """Writes out/libnx-sharp.bin from romfs (romfs.bin and index.json); returns the reason when it does not."""
    target = out / OUT_NAME
    manifest = json.loads((romfs / 'index.json').read_text())
    entry = next((f for f in manifest['files'] if f['path'] == ARCHIVE), None)
    why = None
    if not entry or entry['size'] < BLOCK + HEADER + PACKED:
        why = f'no {ARCHIVE} large enough'
    else:
        with open(romfs / 'romfs.bin', 'rb') as f:
            f.seek(entry['offset'] + BLOCK)
            data, why = edit_block(f.read(HEADER + PACKED))
    if why:
        target.unlink(missing_ok=True)
        return why
    if not target.is_file() or target.read_bytes() != data:
        target.write_bytes(data)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--romfs', type=Path, required=True, help='directory with romfs.bin and index.json')
    ap.add_argument('--out', type=Path, required=True, help='build directory')
    args = ap.parse_args()
    why = write(args.romfs.resolve(), args.out.resolve())
    print(f'lib_nx.ini: {why}; no {OUT_NAME}' if why else f'lib_nx.ini: {OUT_NAME} written')


if __name__ == '__main__':
    main()
