"""Audit override bindings and guest-call dependencies against an extracted ExeFS.

Run with .venv/bin/python tests/override_symbols_check.py --exefs build/extracted/upd/exefs.
Reads NSOs without writing game-derived files; output is symbol names, addresses and counts.
This checks symbol availability, not the validity of arguments at every runtime call.
"""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recomp"))
from layout import ORDER
from nso import Nso


def source(path):
    text = path.read_text()
    text = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r'"\s+"', '', text)


def audit(exefs, patches):
    modules = {name: Nso(exefs / name) for name in ORDER if (exefs / name).is_file()}
    assert {"main", "subsdk0", "sdk"} <= modules.keys()
    definitions = {}
    bindings = set()
    for name, module in modules.items():
        for symbol in module.exports():
            definitions.setdefault(symbol[0], (name, symbol))
        bindings.update(module.syms[index][0] for _, kind, index, _ in module.relocs
                        if index and kind in (257, 1025, 1026))
    sources = {p.name: source(p) for p in sorted((ROOT / "runtime").glob("ov_*.c"))}
    registrations = {}
    failures = []
    checked = set()

    def require(name, function=True):
        checked.add(name)
        definition = definitions.get(name)
        if not definition:
            failures.append(name)
            return
        module, symbol = definition
        start, size = modules[module].text
        if function and (symbol[1] & 15 != 2 or not start <= symbol[3] < start + size):
            failures.append(name)

    for filename, text in sources.items():
        regs = re.findall(r'HOST_(OVERRIDE|OBSERVER)\("([^"]+)",\s*(\w+)\)', text)
        registrations[filename] = regs
        bound = sum(name in bindings for _, name, _ in regs)
        print(f"{filename}: registrations {len(regs)}, bound {bound}, unbound {len(regs) - bound}")
        for kind, name, _ in regs:
            if kind == "OBSERVER" and name in bindings:
                require(name)

    movie = sources["ov_movie.c"]
    entries = re.search(r'movie_symbols\[MOVIE_ENTRIES\]\s*=\s*\{(.*?)\};', movie, re.S)[1]
    for name in re.findall(r'"([^"]+)"', entries):
        # Each module set exports only one constructor ABI. Every shared vtable method is required.
        if "DecoderC1" not in name or name in bindings:
            require(name)
    for name in re.findall(r'need\("([^"]+)"', movie):
        require(name, function=not name.startswith("_ZTV"))
    movie_overrides = {name for _, name, _ in registrations["ov_movie.c"]}
    constructors = {name for name in bindings if name.startswith("_ZN5movie7DecoderC")}
    for name in constructors:
        require(name)
        if name not in movie_overrides:
            failures.append(name)
    print(f"movie constructor bindings: {len(constructors)}, overridden {len(constructors & movie_overrides)}")

    # This helper belongs only to ov_claim_benefit. SDKs with neither the public wrapper nor a relocation to it
    # cannot enter that override; requiring its private helper unconditionally would reject XC2 3.0.1.
    system = sources["ov_system.c"]
    claim_bound = any(name in bindings for _, name, fn in registrations["ov_system.c"] if fn == "ov_claim_benefit")
    for name in re.findall(r'ldr_symbol\("([^"]+)"', system):
        if claim_bound:
            require(name)
        else:
            print(f"{name}: entry bindings {int(claim_bound)}, definitions {int(name in definitions)}")

    probe = sources["ov_probe.c"]
    for name in re.findall(r'sdk\("([^"]+)"', probe):
        require(name)
    for name in re.findall(r'#define\s+TRY_WAIT_SYSTEM_EVENT\s+"([^"]+)"', probe):
        require(name)

    # ov_zstd.c's two fixed original addresses belong to the 1.4.3 patch set, not the 3.0.1 program.
    patch_text = patches.read_text()
    zstd_sites = len(re.findall(r'^site\s+zstd\s', patch_text, re.M))
    print(f"zstd patch sites: {zstd_sites}")
    if zstd_sites:
        raise ValueError("This audit only supports a patch set without the 1.4.3 zstd trampolines")
    for name in sorted(set(failures)):
        print(f"{name}: failures {failures.count(name)}")
    print(f"guest dependencies checked: {len(checked)}, failures: {len(failures)}")
    return bool(failures)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exefs", type=Path, default=ROOT / "build/extracted/upd/exefs")
    parser.add_argument("--patches", type=Path, default=ROOT / "recomp/patches-upd.txt")
    args = parser.parse_args()
    sys.exit(audit(args.exefs, args.patches))
