"""Record or check the code-generation baseline of a game version: counts about the lifted modules, never their content.

A baseline is the set of numbers that recomp/gen.py's manifests (generated/<ver>/<module>/manifest.json) and the
report of tests/jumptables_check.py give for one version of the game: functions lifted and chunks per module, bytes of
generated C, all-label fallback functions (a `br` whose table the resolver could not bound), the census of unsupported
instructions (mnemonic or decoder group -> count), the lifter's timings, and the jump-table counts (disagreements with
the oracle, sites only the resolver or only the oracle resolves, computed sites left unresolved). Every value is a
count, a size or a time, so tools/data/codegen-baseline-<name>.json may be committed; tools/check_content.py accepts it.

  python tools/codegen_baseline.py --generated generated/v210 --name xc2-2.1.0 \\
      [--jumptables build/logs/jumptables-check.log] [--wall-seconds S] --write
  python tools/codegen_baseline.py --generated generated/v210 --name xc2-2.1.0 [--jumptables ...] [--tolerance 2]
  python tools/codegen_baseline.py --selftest

--write records the numbers. Without it the current numbers are compared with the recorded ones, every one is printed
with its change, and the exit code is 1 when a module is missing, the functions lifted fall or the generated C grows by
more than --tolerance percent (default 2), an all-label fallback or an unsupported instruction is added (any growth,
in total or per census entry), or, when --jumptables is given and the baseline holds jump-table counts, a disagreement,
an unverified hoisted base, a computed site left unresolved or a computed PLT stub appears. Chunks, instructions,
timings and the other jump-table counts are informational. Standard library only.
"""
import argparse
import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'tools' / 'data'
# The lifter's load order (recomp/layout.py ORDER); modules outside it follow alphabetically.
ORDER = ['main'] + [f'subsdk{i}' for i in range(10)] + ['sdk']

# Per-module numbers taken from the manifest's stats, by the rule the comparison applies to them.
STRICT = ('all_label_fallbacks', 'unsupported')         # never grow
SIZED = ('c_bytes',)                                      # grow by --tolerance percent at most
FLOORED = ('functions',)                                  # fall by --tolerance percent at most
INFO = ('chunks', 'instructions', 'jump_tables', 'jump_table_targets', 'br_dispatch', 'traps', 'external_branches',
        'external_calls')
TIMINGS = ('discover_s', 'emit_wall_s', 'emit_worker_s', 'table_s')
# Counts of tests/jumptables_check.py per module, by rule; the keys are the report's own labels.
JT_STRICT = ('disagree', 'base not verified', 'computed, unresolved', 'PLT stubs computed or resolved')
JT_INFO = ('functions', 'br', 'computed', 'resolved', 'entries', 'oracle resolved', 'agree', 'oracle wrong',
           'only resolver', 'only oracle', 'only oracle, oracle wrong', 'resolved, not computed',
           'targets outside function', 'base local', 'base verified', 'PLT stubs')


def module_order(names):
    return sorted(names, key=lambda n: (ORDER.index(n) if n in ORDER else len(ORDER), n))


def read_generated(generated):
    """{module: numbers} from every <module>/manifest.json under generated, in load order. The manifest's marker,
    addresses and chunk names stay behind: the baseline holds counts only."""
    modules = {}
    for path in generated.glob('*/manifest.json'):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        stats = manifest.get('stats', {})
        entry = {'functions': int(manifest['function_count']), 'chunks': len(manifest.get('chunks', []))}
        for key in STRICT + SIZED + INFO:
            if key != 'chunks':
                entry[key] = int(stats.get(key, 0))
        entry['unsupported_census'] = {str(k): int(v) for k, v in manifest.get('unsupported_census', {}).items()}
        timings = manifest.get('timings', {})
        entry['timings'] = {k: float(timings[k]) for k in TIMINGS if k in timings}
        modules[str(manifest['module'])] = entry
    if not modules:
        raise SystemExit(f'{generated}: no <module>/manifest.json (the output of recomp/gen.py)')
    return {name: modules[name] for name in module_order(modules)}


def read_jumptables(path):
    """{module: counts} from the log tests/jumptables_check.py writes (build/logs/jumptables-check.log or its
    standard output), or from a JSON file: a baseline written here, or a bare {module: counts}."""
    text = path.read_text(encoding='utf-8')
    if path.suffix.lower() == '.json':
        data = json.loads(text)
        data = data.get('jumptables', data) if isinstance(data, dict) else data
        if not isinstance(data, dict) or not data:
            raise SystemExit(f'{path}: no jump-table counts')
        return {str(m): {str(k): int(v) for k, v in counts.items()} for m, counts in data.items()}
    report, counts = {}, None
    for line in text.splitlines():
        head = re.match(r'== (\w+): (\d+) functions$', line)
        if head:
            counts = report.setdefault(head.group(1), {})
            counts['functions'] = int(head.group(2))
            continue
        if line.startswith('-- '):      # the samples that follow a module's counts, with disassembly
            counts = None
            continue
        row = re.match(r'  (\S.*?)\s+(-?\d+)\s*$', line)
        if row and counts is not None:
            counts[row.group(1)] = int(row.group(2))
    if not report:
        raise SystemExit(f'{path}: no "== <module>: N functions" report of tests/jumptables_check.py')
    return report


def snapshot(generated, name, jumptables=None, wall_seconds=None):
    """The baseline document for the generated directory: per-module numbers, totals, the merged unsupported census,
    the lifter's wall time when the caller measured it, and the jump-table counts when a report is given."""
    modules = read_generated(generated)
    totals = {key: sum(m[key] for m in modules.values()) for key in FLOORED + SIZED + STRICT + INFO}
    census = {}
    for m in modules.values():
        for key, n in m.pop('unsupported_census').items():
            census[key] = census.get(key, 0) + n
    return {
        'name': name,
        'generated': generated.name,
        'modules': modules,
        'totals': totals,
        'unsupported_census': dict(sorted(census.items(), key=lambda kv: (-kv[1], kv[0]))),
        'lifter_wall_s': None if wall_seconds is None else round(float(wall_seconds), 1),
        'jumptables': read_jumptables(jumptables) if jumptables else None,
    }


def counts_only(doc):
    """The document without its timings and the recording commit: what a comparison looks at. Timings vary from run to
    run, so a --write that changes nothing else leaves the file as it is instead of churning the diff."""
    out = {k: v for k, v in doc.items() if k not in ('lifter_wall_s', 'recorded')}
    out['modules'] = {name: {k: v for k, v in m.items() if k != 'timings'} for name, m in doc.get('modules', {}).items()}
    return out


def git_head():
    """The short commit the numbers were recorded at, or None outside a git checkout."""
    try:
        done = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def compare(old, new, tolerance):
    """(failures, lines): every recorded number against the current one, one line each, with FAIL where the rule of
    STRICT, SIZED, FLOORED or JT_STRICT is broken."""
    lines, failed = [], 0

    def check(label, before, after, rule):
        nonlocal failed
        verdict = ''
        if rule == 'strict' and after > before:
            verdict = 'FAIL: grew'
        elif rule == 'sized' and after > before * (1 + tolerance / 100):
            verdict = f'FAIL: grew by more than {tolerance:g}%'
        elif rule == 'floored' and after < before * (1 - tolerance / 100):
            verdict = f'FAIL: fell by more than {tolerance:g}%'
        failed += bool(verdict)
        lines.append(f'{label:44} {before:>13,} -> {after:>13,} ({after - before:+,}){"  " + verdict if verdict else ""}')

    def check_group(prefix, before, after):
        for key in FLOORED:
            check(f'{prefix} {key}', before[key], after[key], 'floored')
        for key in SIZED:
            check(f'{prefix} {key}', before[key], after[key], 'sized')
        for key in STRICT:
            check(f'{prefix} {key}', before[key], after[key], 'strict')
        for key in INFO:
            check(f'{prefix} {key}', before.get(key, 0), after.get(key, 0), 'info')

    for name, before in old['modules'].items():
        after = new['modules'].get(name)
        if after is None:
            lines.append(f'FAIL: module {name} is in the baseline but not in the generated directory')
            failed += 1
            continue
        check_group(name, before, after)
    for name in module_order(set(new['modules']) - set(old['modules'])):
        lines.append(f'module {name} is new (not in the baseline)')
    check_group('total', old['totals'], new['totals'])

    before, after = old.get('unsupported_census', {}), new.get('unsupported_census', {})
    for key in sorted(set(before) | set(after)):
        check(f'unsupported {key!r}', before.get(key, 0), after.get(key, 0), 'strict')

    old_jt, new_jt = old.get('jumptables'), new.get('jumptables')
    if old_jt and new_jt:
        for name, counts in old_jt.items():
            current = new_jt.get(name)
            if current is None:
                lines.append(f'FAIL: jump tables of {name} are in the baseline but not in the report')
                failed += 1
                continue
            for key in JT_STRICT:
                check(f'{name} jump tables {key!r}', counts.get(key, 0), current.get(key, 0), 'strict')
            for key in JT_INFO:
                if key in counts or key in current:
                    check(f'{name} jump tables {key!r}', counts.get(key, 0), current.get(key, 0), 'info')
    elif old_jt:
        lines.append('jump tables: the baseline holds counts but no --jumptables report was given; not checked')
    elif new_jt:
        lines.append('jump tables: the report was read but the baseline holds no counts; not checked')
    return failed, lines


def describe(doc):
    totals = doc['totals']
    yield (f'{doc["name"]}: {len(doc["modules"])} modules ({", ".join(doc["modules"])}), '
           f'{totals["functions"]:,} functions, {totals["chunks"]:,} chunks, {totals["c_bytes"] / 1e6:,.0f} MB of C, '
           f'{totals["all_label_fallbacks"]:,} all-label fallbacks, {totals["unsupported"]:,} unsupported')
    if doc.get('lifter_wall_s') is not None:
        yield f'  lifter wall time {doc["lifter_wall_s"]:.1f} s'
    if doc.get('jumptables'):
        for name, counts in doc['jumptables'].items():
            yield (f'  {name} jump tables: {counts.get("br", 0)} br, {counts.get("resolved", 0)} resolved, '
                   f'{counts.get("disagree", 0)} disagree, {counts.get("only resolver", 0)} only resolver, '
                   f'{counts.get("computed, unresolved", 0)} computed unresolved')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--generated', type=Path, help='output directory of recomp/gen.py (generated/<ver>)')
    ap.add_argument('--name', help='baseline name, for example xc2-2.1.0 (default: the name of --generated)')
    ap.add_argument('--baseline', type=Path, help='baseline file (default tools/data/codegen-baseline-<name>.json)')
    ap.add_argument('--jumptables', type=Path, help='report of tests/jumptables_check.py (log or JSON)')
    ap.add_argument('--wall-seconds', type=float, help='wall time of the recomp/gen.py run, as measured by the caller')
    ap.add_argument('--tolerance', type=float, default=2.0,
                    help='percent the generated C may grow and the functions lifted may fall (default 2)')
    ap.add_argument('--write', action='store_true', help='record the numbers instead of comparing')
    ap.add_argument('--selftest', action='store_true', help='check this script on synthetic manifests and exit')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.generated:
        ap.error('--generated is required')
    name = args.name or args.generated.resolve().name
    baseline = args.baseline or DATA / f'codegen-baseline-{name}.json'
    current = snapshot(args.generated, name, args.jumptables, args.wall_seconds)

    if args.write:
        current['recorded'] = {'commit': git_head()}
        existed = baseline.is_file()
        if existed and counts_only(json.loads(baseline.read_text(encoding='utf-8'))) == counts_only(current):
            print(f'{baseline} unchanged: only timings differ, and they are not rewritten')
            return 0
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps(current, indent=2) + '\n', encoding='utf-8')
        print(f'{"updated" if existed else "wrote"} {baseline}')
        for line in describe(current):
            print(line)
        return 0

    if not baseline.is_file():
        print(f'{baseline}: no baseline recorded; run with --write first')
        return 2
    recorded = json.loads(baseline.read_text(encoding='utf-8'))
    failed, lines = compare(recorded, current, args.tolerance)
    print(f'{baseline.name} ({recorded.get("recorded", {}).get("commit") or "unknown commit"}) '
          f'against {args.generated}:')
    for line in lines:
        print('  ' + line)
    print(f'{failed} failing checks' if failed else 'baseline holds')
    return 1 if failed else 0


# ---- self-test on synthetic manifests -------------------------------------------------------------------------------

def _fake_generated(root, modules, marker):
    """Manifests shaped like recomp/gen.py's, with a marker, addresses and chunk names the baseline must leave out."""
    for name, (functions, chunks, c_bytes, fallbacks, census) in modules.items():
        moddir = root / name
        moddir.mkdir(parents=True, exist_ok=True)
        files = [f'{name}_{i:04d}.c' for i in range(chunks)]
        manifest = {
            'module': name, 'marker': marker, 'base': '0x7000000000', 'text': ['0x7000000000', '0x7000100000'],
            'function_count': functions, 'chunks': files, 'table': f'{name}_table.c',
            'chunk_info': [{'file': f, 'functions': functions // chunks, 'bytes': c_bytes // chunks, 'seconds': 0.5}
                           for f in files],
            'stats': {'functions': functions, 'seeds': functions // 2, 'rounds': 3, 'emitted_functions': functions,
                      'instructions': functions * 40, 'jump_tables': 7, 'jump_table_targets': 90,
                      'all_label_fallbacks': fallbacks, 'br_dispatch': 3, 'traps': 1,
                      'unsupported': sum(census.values()), 'external_branches': 12, 'external_calls': 100,
                      'c_bytes': c_bytes, 'largest_chunk_bytes': c_bytes // chunks},
            'unsupported_census': census,
            'timings': {'discover_s': 0.3, 'emit_wall_s': 2.5, 'emit_worker_s': 9.1, 'table_s': 0.1},
        }
        (moddir / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')


def _fake_report(path, modules):
    """A report in the format of tests/jumptables_check.py, with a sample block and a disassembly window after the
    counts of the first module, as the real log has after a disagreement."""
    out = []
    for i, (name, counts) in enumerate(modules.items()):
        out.append(f'== {name}: {counts["functions"]} functions')
        for key, value in counts.items():
            if key != 'functions':
                out.append(f'  {key:32s} {value}')
        out.append(f'  {"resolver time":32s} 0.52 s')
        out.append(f'  {"oracle time":32s} 12.40 s')
        if i == 0:
            out += ['-- only resolver: br 1a2b3c in [1a2b00, 1a2c00)', '   resolver 12 [1a2b40 1a2b44]', '   oracle   None',
                    '  1a2b30: cmp w8, #11', '  1a2b34: b.hi 1a2b60', '  1a2b38: adrp x9, 100000']
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')


def selftest():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import check_content   # the marker the generator writes, and the check CI runs on the baseline file
    marker = check_content.GENERATED_MARKER
    problems = []

    def expect(condition, what):
        if not condition:
            problems.append(what)
            print(f'FAIL {what}')

    def run(*argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(list(argv))
        return code, out.getvalue()

    with tempfile.TemporaryDirectory(prefix='codegen-baseline-') as tmp:
        tmp = Path(tmp)
        gen, baseline, report = tmp / 'v999', tmp / 'codegen-baseline-selftest.json', tmp / 'jumptables-check.log'
        modules = {'main': (1000, 4, 4_000_000, 2, {}), 'sdk': (300, 2, 900_000, 0, {'mrs s3_0_c4_c2_2': 1}),
                   'subsdk0': (50, 1, 120_000, 0, {})}
        _fake_generated(gen, modules, marker)
        jt = {'main': {'functions': 1000, 'br': 40, 'computed': 9, 'resolved': 8, 'entries': 90, 'oracle resolved': 7,
                       'agree': 7, 'disagree': 0, 'only resolver': 1, 'only oracle': 0, 'computed, unresolved': 1,
                       'base local': 6, 'base verified': 2, 'base not verified': 0, 'PLT stubs': 30,
                       'PLT stubs computed or resolved': 0},
              'sdk': {'functions': 300, 'br': 12, 'computed': 2, 'resolved': 2, 'entries': 20, 'oracle resolved': 2,
                      'agree': 2, 'disagree': 0, 'only resolver': 0, 'computed, unresolved': 0, 'base not verified': 0,
                      'PLT stubs': 10, 'PLT stubs computed or resolved': 0}}
        _fake_report(report, jt)
        base = ['--generated', str(gen), '--name', 'selftest', '--baseline', str(baseline), '--jumptables', str(report)]

        code, text = run(*base)
        expect(code == 2 and 'no baseline recorded' in text, 'compare without a baseline exits 2')

        code, text = run(*base, '--wall-seconds', '21.4', '--write')
        expect(code == 0 and baseline.is_file(), '--write records the baseline')
        doc = json.loads(baseline.read_text(encoding='utf-8'))
        expect(list(doc['modules']) == ['main', 'subsdk0', 'sdk'], 'modules are in load order')
        expect(doc['totals']['functions'] == 1350 and doc['totals']['chunks'] == 7
               and doc['totals']['c_bytes'] == 5_020_000 and doc['totals']['all_label_fallbacks'] == 2
               and doc['totals']['unsupported'] == 1, 'totals are the sums of the modules')
        expect(doc['unsupported_census'] == {'mrs s3_0_c4_c2_2': 1}, 'the census is merged over the modules')
        expect(doc['lifter_wall_s'] == 21.4, 'the wall time is recorded')
        expect(doc['jumptables']['main']['only resolver'] == 1 and doc['jumptables']['main']['functions'] == 1000
               and doc['jumptables']['sdk']['PLT stubs'] == 10 and 'resolver time' not in doc['jumptables']['main']
               and '1a2b30: cmp w8, #11' not in json.dumps(doc), 'the report parser reads counts and skips samples')
        text = baseline.read_text(encoding='utf-8')
        expect(marker not in text and '_table.c' not in text and '0x7000000000' not in text,
               'marker, chunk names and addresses stay out of the baseline')
        expect(not check_content.problems_for(baseline), 'tools/check_content.py accepts the baseline file')

        code, text = run(*base)
        expect(code == 0 and 'baseline holds' in text and 'FAIL' not in text, 'unchanged numbers pass')

        code, text = run(*base, '--jumptables', str(baseline))
        expect(code == 0, 'a baseline JSON serves as the jump-table report too')

        code, text = run('--generated', str(gen), '--name', 'selftest', '--baseline', str(baseline))
        expect(code == 0 and 'not checked' in text, 'a missing report leaves the jump tables unchecked')

        def perturb(main=None, sdk=None):
            changed = dict(modules)
            if main:
                changed['main'] = main
            if sdk:
                changed['sdk'] = sdk
            _fake_generated(gen, changed, marker)

        perturb(main=(1000, 4, 4_000_000, 3, {}))
        code, text = run(*base)
        expect(code == 1 and 'main all_label_fallbacks' in text and 'FAIL: grew' in text, 'one more fallback fails')

        perturb(main=(1000, 4, 4_120_000, 2, {}))
        code, text = run(*base)
        expect(code == 1 and 'c_bytes' in text and 'more than 2%' in text, '3% more C fails at the default tolerance')
        code, text = run(*base, '--tolerance', '5')
        expect(code == 0, '3% more C passes at 5% tolerance')

        perturb(main=(1000, 4, 4_040_000, 2, {}))
        code, text = run(*base)
        expect(code == 0, '1% more C passes')

        perturb(main=(940, 4, 4_000_000, 2, {}))
        code, text = run(*base)
        expect(code == 1 and 'fell by more than' in text, '6% fewer functions fails')

        perturb(sdk=(300, 2, 900_000, 0, {'mrs s3_0_c4_c2_2': 1, 'ldst reg pac': 1}))
        code, text = run(*base)
        expect(code == 1 and "unsupported 'ldst reg pac'" in text and 'sdk unsupported' in text,
               'a new unsupported encoding fails, in total and in the census')

        perturb(sdk=(300, 2, 900_000, 0, {}))
        code, text = run(*base)
        expect(code == 0 and "unsupported 'mrs s3_0_c4_c2_2'" in text and '(-1)' in text,
               'a fixed encoding passes and is reported')

        perturb()
        broken = dict(jt, main=dict(jt['main'], disagree=1, agree=6))
        _fake_report(report, broken)
        code, text = run(*base)
        expect(code == 1 and "main jump tables 'disagree'" in text, 'a jump-table disagreement fails')
        _fake_report(report, dict(jt, main=dict(jt['main'], **{'only resolver': 2})))
        code, text = run(*base)
        expect(code == 0 and "'only resolver'" in text and '(+1)' in text, 'one more only-resolver site is informational')
        _fake_report(report, jt)

        import shutil
        shutil.rmtree(gen / 'subsdk0')
        code, text = run(*base)
        expect(code == 1 and 'module subsdk0 is in the baseline' in text, 'a missing module fails')

    if problems:
        print(f'selftest: {len(problems)} failures')
        return 1
    print('selftest: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
