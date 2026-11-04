"""Run the synthetic renderer checks without SDL, game data or the full runtime.

Usage: python3 tests/audren_check.py [--sanitize] [--cc /path/to/clang]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default=r'C:\msys64\ucrt64\bin\clang.exe' if os.name == 'nt' else 'clang')
    parser.add_argument('--sanitize', action='store_true', help='Enable AddressSanitizer and UBSan')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='xc2-audren-check-') as work:
        exe = Path(work) / ('audren_check.exe' if os.name == 'nt' else 'audren_check')
        flags = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer'] if args.sanitize else []
        for opt in ('-O0', '-O2'):
            subprocess.run([args.cc, '-std=gnu11', opt, '-g', '-ffunction-sections', '-fdata-sections',
                            *flags, str(ROOT / 'tests' / 'audren_check.c'), '-Wl,--gc-sections', '-lm',
                            '-o', str(exe)], check=True)
            print(opt, flush=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
