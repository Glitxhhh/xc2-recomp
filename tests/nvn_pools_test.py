"""Standalone runtime regression checks; no SDL, Vulkan driver, guest code or game files.

Windows: python tests/nvn_pools_test.py --cc C:/msys64/ucrt64/bin/clang.exe
Linux:   python3 tests/nvn_pools_test.py --sanitize --scratch /path/to/scratch

Unused runtime functions are discarded by the linker. This does not replace the Windows runtime probes.
Under ptrace, set ASAN_OPTIONS=detect_leaks=0 because LeakSanitizer cannot run there.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--scratch', type=Path, help='Parent directory for temporary binaries')
    parser.add_argument('--sanitize', action='store_true', help='Enable AddressSanitizer and UndefinedBehaviorSanitizer')
    args = parser.parse_args()
    common = [args.cc, '-std=gnu11', '-Wno-macro-redefined', '-Iruntime']
    syntax = ['runtime/nvn_api_obj.c']
    subprocess.run(common + ['-fsyntax-only'] + syntax, cwd=ROOT, check=True)
    cases = [
        ('pools', ['tests/nvn_pools_test.c', 'runtime/nvn_tex.c'], []),
    ]
    flags = ['-O1', '-g', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections']
    if os.name == 'nt':
        # GNU ld and lld for PE keep unreferenced functions that --gc-sections drops on ELF; those call runtime parts the test leaves out.
        flags += ['-fuse-ld=lld', '-Wl,-Xlink=-force:unresolved']
    if args.sanitize:
        flags += ['-fsanitize=address,undefined']
    with tempfile.TemporaryDirectory(prefix='xc2-runtime-review-', dir=args.scratch) as tmp:
        for name, sources, defines in cases:
            exe = Path(tmp) / (name + ('.exe' if os.name == 'nt' else ''))
            subprocess.run(common + flags + defines + sources + ['-lm', '-o', str(exe)], cwd=ROOT, check=True)
            subprocess.run([str(exe)], cwd=ROOT, check=True)
    print('Descriptor pool checks passed.', flush=True)


if __name__ == '__main__':
    main()
