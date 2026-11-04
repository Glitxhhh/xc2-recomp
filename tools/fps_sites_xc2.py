r"""Find the 60 fps sites in XC2's main and print them as the xc360 set of a patch table (recomp/patches.py).

    .venv\Scripts\python tools\fps_sites_xc2.py build\extracted\upd\exefs\main > recomp\patches-upd.txt

XC2 steps its logic by a fixed 1/30 s each frame and paces frames itself (NOTES.md, "60 fps"). The set has three parts:
  - every load of the 1/30 constant (`ldr s<t>, [x<n>, #lo]` after `adrp x<n>, <its page>`) reads patch page +0x50, the
    frame step runtime/frame_rate.c stores; x<n> is pointed back at the constant's page afterwards, so code after the
    site sees the registers it had;
  - the frame wait's target (the spin in the frame loop, `fmul s0, s0, s10` = period * interval * 0.997) reads +0x48,
    the frame time of the limit;
  - the frame-time getter (period * interval) returns +0x50.
The interval itself (1 instead of 2) and the step most logic advances by (two floats of a game object) are data writes
in runtime/frame_rate.c (xc2_interval_store, xc2_delta_store). The two single sites are found by their
instruction words near a known address, and the script stops when the code there is not what it expects.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'recomp'))
from nso import Nso  # noqa: E402

STEP = 1.0 / 30
PAGE_STEP, PAGE_WAIT = 0x50, 0x48


def adrp(pc, target, rd):
    imm = (target >> 12) - (pc >> 12)
    imm &= 0x1FFFFF
    return 0x90000000 | (imm & 3) << 29 | (imm >> 2) << 5 | rd


def ldr_s(rt, rn, off):
    return 0xBD400000 | (off // 4) << 10 | rn << 5 | rt


def adrp_target(pc, w):
    imm = ((w >> 29) & 3) | (((w >> 5) & 0x7FFFF) << 2)
    if imm & (1 << 20):
        imm -= 1 << 21
    return ((pc >> 12) + imm) << 12


def writes_reg(w, rd):
    """A conservative test: an instruction whose low five bits name rd and that is not a store or a compare."""
    if (w & 31) != rd:
        return False
    store = (w & 0x3B400000) == 0x39000000 or (w & 0x3A400000) == 0x28000000   # STR (imm) / STP
    compare = (w & 0x7F20001F) == 0x6B00001F or (w & 0x7F00001F) == 0x7100001F
    return not store and not compare


def step_sites(img, text_end, const_at):
    page, lo = const_at & ~0xFFF, const_at & 0xFFF
    sites = []
    for a in range(0, text_end, 4):
        w = struct.unpack_from('<I', img, a)[0]
        if (w & 0xFFC00000) != 0xBD400000 or ((w >> 10) & 0xFFF) * 4 != lo:
            continue
        rn, rt = (w >> 5) & 31, w & 31
        for b in range(a - 4, max(a - 0x400, 0), -4):
            v = struct.unpack_from('<I', img, b)[0]
            if (v & 0x9F000000) == 0x90000000 and (v & 31) == rn:
                if adrp_target(b, v) == page:
                    sites.append((a, w, [('page', rn), ldr_s(rt, rn, PAGE_STEP), adrp(a, page, rn)]))
                break
            if writes_reg(v, rn):
                break
    return sites


def expect(img, a, words, what):
    have = struct.unpack_from(f'<{len(words)}I', img, a)
    if list(have) != words:
        sys.exit(f'fps_sites_xc2: {what} at main+{a:#x} is not the expected code; another game version?')


def main():
    n = Nso(sys.argv[1])
    img, text_end = n.image, n.text[0] + n.text[1]
    hits = [i for i in range(n.rodata[0], n.rodata[0] + n.rodata[1], 4) if struct.unpack_from('<f', img, i)[0] ==
            struct.unpack('<f', struct.pack('<f', STEP))[0]]
    sites = []
    for c in hits:
        sites += step_sites(img, text_end, c)
    if not sites:
        sys.exit('fps_sites_xc2: no loads of 1/30')
    # The frame wait, 3.0.1 main+0x6ab168: fmul s0, s0, s10 ; fcmp s0, s8 ; b.pl (the loop); x8 is dead there
    wait = 0x6ab168
    expect(img, wait, [0x1E2A0800, 0x1E282000], 'the frame wait')
    # The frame-time getter, 3.0.1 main+0x6a3710: ldp x29, x30, [sp, #0x10] ; ldp x20, x19, [sp], #0x20 ; ret
    getter = 0x6a3710
    expect(img, getter, [0xA9417BFD, 0xA8C24FF4, 0xD65F03C0], 'the frame-time getter')
    print('# XC2 3.0.1 60 fps (tools/fps_sites_xc2.py; NOTES.md "60 fps"). Generated from the game\'s main.')
    print('set xc360 XC2_FPS60 1')
    for a, w, repl in sites:
        words = ' '.join(f'@page:x{r[1]}' if isinstance(r, tuple) else f'{r:08x}' for r in repl)
        print(f'site xc360 main {a:x} {w:08x} {words}')
    print(f'site xc360 main {wait:x} 1e2a0800 @page:x8 {ldr_s(0, 8, PAGE_WAIT):08x}')
    print(f'site xc360 main {getter:x} a9417bfd @page:x8 {ldr_s(0, 8, PAGE_STEP):08x} a9417bfd')
    print('include fixes-upd.txt   # the game fixes, kept by hand')
    print(f'# {len(sites)} step loads', file=sys.stderr)


if __name__ == '__main__':
    main()
