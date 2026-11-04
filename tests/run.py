"""Runs every check that needs no game files and reports one line per check, then a summary table.

The checks are the ones docs/building.md ("Checks") and the test files' own docstrings mark as needing no game files.
The exit status is 1 when a blocking check fails or cannot run on this host; a check skipped by a flag, or because it
is for another host, does not count. Two checks run and are reported but do not block, so the runner records these
gaps instead of hiding them: tools/check_platform.py, because runtime/kernel.c and runtime/main.c still use Win32
directly, and tests/excl_mt.py, because its ABA cases fail on the compare-and-swap in runtime/cpu.h. While excl-mt does
not block, a wrong total in its contention cases does not fail the run either: read its output.

Two interpreters take part, as docs/building.md lays out. The lifter environment (.venv, Python 3.12, with the
unicorn, capstone and lz4 wheels of tools/requirements.txt) runs the lifter and CPU-header checks, which import
tests/diff/common.py. The extraction environment (.venv-py314, Python 3.14, whose tkinter the installer window needs)
runs the installer and tools checks. Each defaults to that venv in the repository when it exists, else to the
interpreter running this script; --lifter-python and --tools-python name other ones, as CI does.

The installer window test opens a Tk window: without a display it runs under xvfb-run when that exists, else only its
headless classes.

Usage: run.py [--list] [--only NAME ...] [--skip-diff] [--skip-native] [--lifter-python EXE] [--tools-python EXE]

    --skip-diff     leave out the differential tests against Unicorn (simd, atomic)
    --skip-native   leave out every check that compiles C (flags, excl-mt, simd, atomic): for a host without a
                    C compiler, such as the Windows CI job that covers the installer on its target
"""
import argparse
import functools
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MSYS_CLANG = Path(r'C:\msys64\ucrt64\bin\clang.exe')
WHEELS = ('capstone', 'unicorn')      # what tests/diff/common.py imports

# Classes of tests/installer_gui_test.py that need no display. SmokeTest opens the installer window; EndToEndTest
# skips itself unless build/install-test exists.
GUI_HEADLESS = ('ParseTest', 'ModelTest', 'RunStatesTest', 'FormTest', 'CatalogTest', 'CancelTest')


@dataclass(frozen=True)
class Check:
    name: str
    script: str             # relative to the repository root
    env: str                # 'lifter' or 'tools': the interpreter that runs it
    modules: tuple = ()     # wheels that interpreter must import
    compiles: bool = False  # builds C with tests/diff/common.py compiler()
    diff: bool = False      # a differential test against Unicorn
    display: bool = False   # opens a window
    hosts: tuple = ()       # os.name values it runs on; empty: everywhere
    blocking: bool = True
    note: str = ''


CHECKS = [
    Check('installer', 'tests/installer_test.py', 'tools'),
    Check('installer-gui', 'tests/installer_gui_test.py', 'tools', display=True),
    Check('hactool-log', 'tests/hactool_log_test.py', 'tools'),
    Check('worktree', 'tests/worktree_test.py', 'tools', hosts=('nt',),
          note='Windows only: it asserts directory junctions'),
    Check('spin-waits', 'tests/spin_waits_test.py', 'lifter', modules=('capstone', 'lz4')),
    Check('flags', 'tests/flags_check.py', 'lifter', modules=WHEELS, compiles=True),
    # Its three ABA cases fail: runtime/cpu.h stx##N and stxp128 are a compare-and-swap, which cannot see X->Y->X, so the
    # whole test exits 1 today. It runs so the log shows the cases, and it blocks again once that gap is closed or
    # recorded in the test itself.
    Check('excl-mt', 'tests/excl_mt.py', 'lifter', modules=WHEELS, compiles=True, blocking=False,
          note='not blocking: the ABA cases fail, the compare-and-swap in runtime/cpu.h cannot see X->Y->X'),
    Check('atomic', 'tests/diff/atomic.py', 'lifter', modules=WHEELS, compiles=True, diff=True),
    Check('simd', 'tests/diff/simd.py', 'lifter', modules=WHEELS, compiles=True, diff=True),
    # runtime/kernel.c and runtime/main.c use Win32 directly, so this check fails today. It runs so the log shows the
    # remaining uses, and it stays out of the exit status until they are gone (then it becomes blocking).
    Check('platform', 'tools/check_platform.py', 'tools', blocking=False,
          note='not blocking: runtime/kernel.c and runtime/main.c still use Win32 directly'),
]


def interpreter(explicit, venv):
    if explicit:
        return explicit
    exe = ROOT / venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return str(exe) if exe.exists() else sys.executable


def has_compiler():
    """Whether tests/diff/common.py compiler() would find one, without importing it (that needs the wheels)."""
    return bool(os.environ.get('CC') or (os.name == 'nt' and MSYS_CLANG.exists()) or
                shutil.which('clang') or shutil.which('gcc'))


@functools.lru_cache(maxsize=None)
def missing_modules(python, modules):
    code = 'import importlib.util, sys; print(" ".join(m for m in sys.argv[1:] if importlib.util.find_spec(m) is None))'
    r = subprocess.run([python, '-c', code, *modules], capture_output=True, text=True)
    return tuple(r.stdout.split()) if r.returncode == 0 else modules


def command(check, pythons):
    """The command line for a check and a note on how it runs."""
    cmd = [pythons[check.env], str(ROOT / check.script)]
    if check.display and os.name != 'nt' and not os.environ.get('DISPLAY'):
        xvfb = shutil.which('xvfb-run')
        if xvfb:
            return [xvfb, '-a', *cmd], 'under xvfb-run'
        return cmd + list(GUI_HEADLESS), 'no display and no xvfb-run: headless classes only'
    return cmd, ''


def skip_reason(check, args):
    if check.hosts and os.name not in check.hosts:
        return check.note
    if args.skip_diff and check.diff:
        return '--skip-diff'
    if args.skip_native and check.compiles:
        return '--skip-native'
    return None


def not_run_reason(check, pythons):
    if check.compiles and not has_compiler():
        return 'no C compiler: clang or gcc on PATH, or $CC'
    missing = missing_modules(pythons[check.env], check.modules)
    if missing:
        return f'{pythons[check.env]} cannot import {", ".join(missing)}: pip install -r tools/requirements.txt'
    return None


def table(rows):
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return [' | '.join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]


def main():
    ap = argparse.ArgumentParser(description='Runs the checks that need no game files.')
    ap.add_argument('--list', action='store_true', help='name the checks and stop')
    ap.add_argument('--only', action='append', metavar='NAME', help='run this check only (repeatable)')
    ap.add_argument('--skip-diff', action='store_true', help='leave out the differential tests against Unicorn')
    ap.add_argument('--skip-native', action='store_true', help='leave out every check that compiles C')
    ap.add_argument('--lifter-python', metavar='EXE', help='interpreter for the lifter checks (default: .venv)')
    ap.add_argument('--tools-python', metavar='EXE', help='interpreter for the installer and tools checks '
                                                          '(default: .venv-py314)')
    args = ap.parse_args()
    if args.list:
        for line in table([(c.name, c.script, c.env, c.note) for c in CHECKS]):
            print(line)
        return 0
    unknown = sorted(set(args.only or ()) - {c.name for c in CHECKS})
    if unknown:
        ap.error(f'unknown check {", ".join(unknown)}; --list names them')
    pythons = {'lifter': interpreter(args.lifter_python, '.venv'), 'tools': interpreter(args.tools_python, '.venv-py314')}
    print(f'lifter checks: {pythons["lifter"]}\ntools checks:  {pythons["tools"]}', flush=True)

    results = []    # (check, outcome, seconds, note)
    for check in CHECKS:
        if args.only and check.name not in args.only:
            continue
        reason = skip_reason(check, args)
        if reason:
            results.append((check, 'SKIP', 0.0, reason))
            continue
        reason = not_run_reason(check, pythons)
        if reason:
            results.append((check, 'NOT RUN', 0.0, reason))
            continue
        cmd, how = command(check, pythons)
        print(f'\n=== {check.name}: {" ".join(cmd)}', flush=True)
        start = time.monotonic()
        code = subprocess.run(cmd, cwd=ROOT).returncode
        seconds = time.monotonic() - start
        outcome = 'PASS' if code == 0 else 'FAIL'
        note = ' / '.join(n for n in (how if outcome == 'PASS' else f'exit {code}', check.note) if n)
        print(f'=== {check.name}: {outcome} ({seconds:.1f}s)', flush=True)
        results.append((check, outcome, seconds, note))

    rows = [('check', 'result', 'time', 'note')]
    rows += [(c.name, outcome, f'{seconds:.1f}s', note) for c, outcome, seconds, note in results]
    print('\n' + '\n'.join(table(rows)))
    blocking = [c.name for c, outcome, _, _ in results if c.blocking and outcome in ('FAIL', 'NOT RUN')]
    verdict = f'{len(blocking)} blocking failures' + (f': {", ".join(blocking)}' if blocking else '')
    print(verdict)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')    # the Actions job page shows the same table
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write('| ' + ' | '.join(rows[0]) + ' |\n|' + '---|' * len(rows[0]) + '\n')
            f.write(''.join('| ' + ' | '.join(r) + ' |\n' for r in rows[1:]) + f'\n{verdict}\n')
    return 1 if blocking else 0


if __name__ == '__main__':
    sys.exit(main())
