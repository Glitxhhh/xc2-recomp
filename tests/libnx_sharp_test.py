"""tools/libnx_sharp.py on a made-up lib_nx.ini block, without game files.

Run: .venv/Scripts/python tests/libnx_sharp_test.py
"""
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import libnx_sharp as ls  # noqa: E402

TEXT = (b'tonemap=on\r\nAntiAliasing=on\r\nred_sclX=1.0\r\nred_sclY=1.0\r\nred_hdsclX=0.75\r\nred_hdsclY=0.75\r\n'
        b'red_Auto=on\r\nred_AtMinX=0.7\r\nred_AtMinY=0.7\r\nblur=off\r\n')


def block(text, packed=ls.PACKED):
    """An xbc1 block of lib_nx.ini holding text padded to UNPACKED bytes, its stream zero-padded to PACKED."""
    z = zlib.compress(text.ljust(ls.UNPACKED, b' '), 1)
    head = b'xbc1' + struct.pack('<IIII', 1, ls.UNPACKED, packed, 0) + ls.NAME
    return head.ljust(ls.HEADER, b'\0') + z.ljust(ls.PACKED, b'\0')


class LibNx(unittest.TestCase):
    def test_edits(self):
        out, why = ls.edit_block(block(TEXT))
        self.assertIsNone(why)
        self.assertEqual(len(out), ls.HEADER + ls.PACKED)
        self.assertEqual(out[:ls.HEADER], block(TEXT)[:ls.HEADER])
        text = zlib.decompressobj().decompress(out[ls.HEADER:])
        self.assertEqual(len(text), ls.UNPACKED)
        lines = text.rstrip(b' ').split(b'\r\n')
        for want in (b'AntiAliasing=off', b'red_Auto=off', b'red_hdsclX=1.0', b'red_AtMinY=1.0', b'tonemap=on',
                     b'blur=off'):
            self.assertIn(want, lines)

    def test_other_block(self):
        self.assertIsNotNone(ls.edit_block(block(TEXT, packed=1000))[1])
        self.assertIsNotNone(ls.edit_block(b'\0' * (ls.HEADER + ls.PACKED))[1])

    def test_missing_key(self):
        _, why = ls.edit_block(block(TEXT.replace(b'red_Auto=on\r\n', b'')))
        self.assertIn('red_Auto', why)


if __name__ == '__main__':
    unittest.main()
