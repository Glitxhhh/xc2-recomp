"""recomp/patches.py on small patch files, without game files: `include` and `@host:` words.

Run: .venv/Scripts/python tests/patches_test.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recomp'))

import patches  # noqa: E402

MODS = [('main', 0x7000000000, 0x15ed000), ('sdk', 0x7001e00000, 0x900000)]
PAGE = 0x70015ed000


class PatchFiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def write(self, name, text):
        (self.root / name).write_text(text)
        return self.root / name

    def test_include_and_host_call(self):
        self.write('fixes.txt', 'set wind XC2_WIND_GUARD 1\nsite wind main 1abcd8 97fffeba @host:fd0\n')
        t = patches.load(self.write('top.txt', 'set a XC2_A 0\nsite a sdk 525f4 940ddbb9 9400cf82\ninclude fixes.txt\n'), MODS)
        self.assertEqual([s[0] for s in t.sets], ['a', 'wind'])
        self.assertEqual(t.page, PAGE)
        (k, words), = t.for_module('main', 0x7000000000).values()
        self.assertEqual(k, 1)
        site = 0x70001abcd8
        self.assertEqual(words, [0x94000000 | ((PAGE + 0xfd0 - site) >> 2)])
        self.assertEqual(t.for_module('sdk', 0x7001e00000)[0x7001e525f4], (0, [0x9400cf82]))

    def test_include_loop_stops(self):
        self.write('a.txt', 'include b.txt\n')
        self.write('b.txt', 'include a.txt\n')
        with self.assertRaises(patches.PatchError):
            patches.load(self.root / 'a.txt', MODS)

    def test_host_offset_outside_page_stops(self):
        with self.assertRaises(patches.PatchError):
            patches.load(self.write('p.txt', 'set w X 1\nsite w main 10 d503201f @host:1000\n'), MODS)


if __name__ == '__main__':
    unittest.main()
