"""The vendored MacNativeGames extract_exefs.py, retargeted at Xenoblade Chronicles 2.

The vendored script checks the title IDs of the game it was written for (Xenoblade Chronicles X: Definitive Edition).
tools/vendor stays byte-identical to upstream, so install() builds the module from its source with those IDs and the
game name swapped for XC2's, plaintext ExeFS sections accepted, and registers it as extract_exefs, which every later import then gets (tools/extract.py,
tools/package_select.py). Run as a script, it runs that module's main() with the same arguments
(tools/extract.py extract_exefs).
"""
import sys
import types
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / 'vendor' / 'macnativegames'
SWAPS = (
    ('0100453019AA8000', '0100E95004038000'),   # base and update program
    ('0100453019AA8800', '0100E95004038800'),   # update meta
    ('Xenoblade Chronicles X: Definitive Edition', 'Xenoblade Chronicles 2'),
    # Some dumps carry plaintext NCAs (section encryption type 1): the ExeFS is read as stored, still checked against
    # its hash table. The RomFS goes through hactool, which reads them as they are. Any other type is named.
    ("require(fs[4] == 3, 'Only AES-CTR ExeFS is supported')",
     "require(fs[4] in (1, 3), f'Only AES-CTR or plaintext ExeFS is supported, not encryption type {fs[4]}')"),
    ('return decrypt(ctr_key, modes.CTR(iv), data)[absolute - aligned:]',
     'return (data if fs[4] == 1 else decrypt(ctr_key, modes.CTR(iv), data))[absolute - aligned:]'),
)


def install():
    if getattr(sys.modules.get('extract_exefs'), 'XC2_RETARGETED', False):
        return sys.modules['extract_exefs']
    path = VENDOR / 'extract_exefs.py'
    source = path.read_text(encoding='utf-8')
    for old, new in SWAPS:
        if old not in source:
            sys.exit(f'exefs_xc2: {old!r} is not in {path}; the vendored script changed')
        source = source.replace(old, new)
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    mod = types.ModuleType('extract_exefs')
    mod.__file__ = str(path)
    mod.XC2_RETARGETED = True
    sys.modules['extract_exefs'] = mod
    exec(compile(source, str(path), 'exec'), mod.__dict__)
    return mod


if __name__ == '__main__':
    sys.argv[0] = str(VENDOR / 'extract_exefs.py')
    install().main()
