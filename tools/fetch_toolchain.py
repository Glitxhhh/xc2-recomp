"""Fetch the toolchain tools\\build_xc2.ps1 builds with into the ignored toolchain\\ (the dev-mode layout installer/layout.py
and tools/build_game.py read):

    .venv\\Scripts\\python tools\\fetch_toolchain.py [--dest DIR] [--force]

    toolchain\\llvm-mingw-<clang>\\llvm-mingw-<clang>\\   llvm-mingw, x86_64 only: what clang and lld need for xc2.exe
    toolchain\\deps-mingw\\include, lib\\              headers and import libraries of SDL3, Opus, libvpx, Vulkan (headers
                                                   and loader), zstd and VMA (build_game.py DEFAULT_DEPS)
    toolchain\\deps-mingw\\bin\\                       SDL3.dll and libopus-0.dll

The downloads are tools/make_release.py's PINS, the same files and versions the Windows release ships, cached in
toolchain/release-dl/ and checked against their sha256; a mismatch stops the script. The .zst packages of MSYS2 unpack
with the stdlib on Python 3.14 and with zstandard (tools/requirements.txt) before, so the build's .venv runs it.

A folder that is already there is left alone; --force rebuilds it. Each folder is assembled next to its place and
renamed into it at the end, so an interrupted run leaves nothing half-filled. Ninja is not fetched: build_xc2.ps1 uses
MSYS2 UCRT64's.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_release as mr  # noqa: E402

CLANG_VERSION = '23.1.4'   # the clang of llvm-mingw release mr.LLVM_VERSION; names the folder build_xc2.ps1 picks
DLLS = ['SDL3.dll', 'libopus-0.dll']


def build_llvm(dst):
    mr.copy_tree(mr.unpack('llvm-mingw') / f'llvm-mingw-{mr.LLVM_VERSION}-ucrt-x86_64', dst, mr.llvm_skip)
    out = subprocess.run([str(dst / 'bin' / 'clang.exe'), '--version'], capture_output=True, text=True).stdout
    if f'clang version {CLANG_VERSION} ' not in out:
        sys.exit(f'{dst}: llvm-mingw {mr.LLVM_VERSION} is not clang {CLANG_VERSION}:\n{out}')


def build_deps(dst):
    mr.fill_deps(dst)
    (dst / 'bin').mkdir()
    dll = mr.unpack('sdl3-dll') / 'SDL3.dll'
    if mr.sha256_file(dll) != mr.SDL3_DLL_SHA256:
        sys.exit(f'{dll}: not the pinned SDL3.dll')
    shutil.copy2(dll, dst / 'bin' / 'SDL3.dll')
    shutil.copy2(mr.unpack('opus') / 'ucrt64' / 'bin' / 'libopus-0.dll', dst / 'bin' / 'libopus-0.dll')


def place(dst, build, force):
    """Run build(tmp) on an empty sibling of dst and rename it to dst, unless dst is there and force is not set."""
    if dst.exists() and not force:
        print(f'{dst}: there, left alone (--force rebuilds it)')
        return
    tmp = dst.with_name(dst.name + '.partial')
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    build(tmp)
    shutil.rmtree(dst, ignore_errors=True)
    tmp.rename(dst)
    print(f'{dst}: {mr.mib(mr.dir_size(dst))}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dest', type=Path, default=mr.MAIN_ROOT / 'toolchain', help='toolchain directory (default %(default)s)')
    ap.add_argument('--force', action='store_true', help='rebuild folders that are already there')
    args = ap.parse_args()
    name = f'llvm-mingw-{CLANG_VERSION}'
    place(args.dest / name / name, build_llvm, args.force)
    place(args.dest / 'deps-mingw', build_deps, args.force)


if __name__ == '__main__':
    main()
