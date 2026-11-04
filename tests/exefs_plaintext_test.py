"""tools/extract.py extract_exefs on synthetic NSPs: an AES-CTR and a plaintext Program NCA give the same ExeFS, and
any other section encryption type is named in the error. The NSPs, their NCA and the keys file are made up here with
random keys; no game files, no tools.

Run under .venv-py314: python tests/exefs_plaintext_test.py
"""
import hashlib
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import extract  # noqa: E402

TITLE = 0x0100E95004038000
FILES = [('main.npdm', b'META' + bytes(60)), ('main', os.urandom(3000))]
BLOCK = 0x1000


def encrypt(key, mode, data):
    ctx = Cipher(algorithms.AES(key), mode).encryptor()
    return ctx.update(data) + ctx.finalize()


def pfs0(files):
    strings = b''.join(name.encode() + b'\0' for name, _ in files)
    table, offset, name_at = b'', 0, 0
    for name, data in files:
        table += struct.pack('<QQII', offset, len(data), name_at, 0)
        offset, name_at = offset + len(data), name_at + len(name) + 1
    return b'PFS0' + struct.pack('<III', len(files), len(strings), 0) + table + strings + b''.join(d for _, d in files)


def nca(keys, crypt):
    """A Program NCA of XC2's title with one hashed PFS0 section (the ExeFS) at 0xc00 encrypted as crypt says."""
    pfs = pfs0(FILES)
    hashes = b''.join(hashlib.sha256(pfs[i:i + BLOCK]).digest() for i in range(0, len(pfs), BLOCK))
    pfs_at = 0x200
    section = (hashes.ljust(pfs_at, b'\0') + pfs).ljust(-(-(pfs_at + len(pfs)) // 512) * 512, b'\0')
    start = 0xc00
    ctr = os.urandom(8)
    if crypt == 3:
        iv = ctr[::-1] + (start // 16).to_bytes(8, 'big')
        section = encrypt(keys['content'], modes.CTR(iv), section)
    fs = bytearray(512)
    fs[0:5] = bytes([2, 0, 1, 2, crypt])
    fs[8:40] = hashlib.sha256(hashes).digest()
    struct.pack_into('<II', fs, 0x28, BLOCK, 2)
    struct.pack_into('<QQQQ', fs, 0x30, 0, len(hashes), pfs_at, len(pfs))
    fs[0x140:0x148] = ctr
    hdr = bytearray(0xc00)
    size = start + len(section)
    hdr[0x200:0x204] = b'NCA3'
    struct.pack_into('<Q', hdr, 0x208, size)
    struct.pack_into('<Q', hdr, 0x210, TITLE)
    struct.pack_into('<II', hdr, 0x240, start // 512, size // 512)
    hdr[0x280:0x2a0] = hashlib.sha256(fs).digest()
    hdr[0x300:0x340] = encrypt(keys['key_area_key_application_00'], modes.ECB(),
                               bytes(32) + keys['content'] + bytes(16))
    hdr[0x400:0x600] = fs
    header = b''.join(encrypt(keys['header_key'], modes.XTS(i.to_bytes(16, 'big')), bytes(hdr[i * 512:(i + 1) * 512]))
                      for i in range(6))
    return header + section


class PlaintextExefs(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='exefs-test-'))
        self.keys = {'header_key': os.urandom(32), 'key_area_key_application_00': os.urandom(16),
                     'content': os.urandom(16)}
        self.keys_path = self.dir / 'test.keys'
        self.keys_path.write_text(''.join(f'{k} = {v.hex()}\n' for k, v in self.keys.items() if k != 'content'))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_on(self, crypt):
        game = self.dir / f'game-{crypt}.nsp'
        game.write_bytes(pfs0([('program.nca', nca(self.keys, crypt))]))
        out = self.dir / f'out-{crypt}'
        return extract.extract_exefs(game, self.keys_path, out, self.dir, update=False), out.name

    def test_ctr_and_plaintext_give_the_same_files(self):
        for crypt in (3, 1):
            exefs, _ = self.run_on(crypt)
            for name, data in FILES:
                self.assertEqual((exefs / name).read_bytes(), data, f'{name}, encryption type {crypt}')

    def test_other_types_are_named(self):
        with self.assertRaises(ValueError):
            self.run_on(2)
        log = (self.dir / 'extract_exefs-out-2.log').read_text(encoding='utf-8')
        self.assertIn('not encryption type 2', log)


if __name__ == '__main__':
    unittest.main()
