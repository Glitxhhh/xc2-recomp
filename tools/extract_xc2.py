r"""Extract Xenoblade Chronicles 2: ExeFS of the base game and the update, the update's merged RomFS, the RomFS of
each add-on content file, and the game's icon from the update's control data.

    .venv-py314\Scripts\python tools\extract_xc2.py --base <base.nsp> --update <update.nsp> --keys <prod.keys>
        [--dlc <dlc.nsp> ...] [--hactool <hactool.exe>] [--work build] [--name upd]

Writes build/extracted/v0/exefs, build/extracted/<name>/{exefs,romfs}, build/extracted/<name>/aoc/<index> (the layout
runtime/fs_host.c mount_aoc reads) and build/extracted/<name>/icon.ico (tools/build_game.py embeds it in xc2.exe in place of
runtime/xc2.ico). Key values are read by the tools from the keys file and never printed.
"""
import argparse
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract  # noqa: E402

APP_ID = 0x0100E95004038000
AOC_BASE = APP_ID + 0x1000
CONTROL = 2    # NCA content type of the control data (NACP and icons)
AOC_DATA = 5   # NCA content type of add-on content (PublicData)
# The icons are 256x256 JPEGs, one per NACP language. XC2 has no American English entry (its English is en-GB, as the NACP's
# language list says); any other one is the same picture.
ICONS = ('icon_AmericanEnglish.dat', 'icon_BritishEnglish.dat')
ICON_SIZES = (16, 24, 32, 48, 64, 256)


def nca_romfs(path, record, tickets, keys_path, hactool, target, log):
    """Unpack the RomFS of the NCA described by record (inside the NSP at path) to target, with the NSP's titlekeys."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='nca-', dir=target.parent) as tmp:
        tmp = Path(tmp)
        nca, title_keys, hactool_keys = tmp / 'content.nca', tmp / 'title.keys', tmp / 'hactool.keys'
        extract.copy_range(path, extract.record_offset(record), record['size'], nca)
        fd = os.open(title_keys, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            for rights, key in tickets.items():
                f.write(f'{rights.hex()} = {key.hex()}\n')
        extract.hactool_prod_keys(keys_path, hactool_keys)
        result = tmp / 'romfs'
        code, text = extract.run_hactool([str(hactool), '-y', '--disablekeywarns', '--suppresskeys', '-k',
                                          str(hactool_keys), f'--romfsdir={result}', str(nca)],
                                         dict(os.environ, MNG_TITLE_KEYS=str(title_keys)))
        log.write_text(text, encoding='utf-8')
        extract.require(code == 0 and result.is_dir(), f'{path.name}: hactool failed; see {log}')
        result.rename(target)


def nsp_records(path, keys_path):
    """The NSP's common-ticket titlekeys and its NCA records."""
    keys = extract.load_keys(keys_path)
    with path.open('rb') as f:
        _, entries = extract.container_entries(f, path.stat().st_size)
        tickets = extract.common_tickets(f, entries)
        records = extract.nca_inventory(f, entries, keys)
    return tickets, [r for r, _ in records]


def extract_dlc(path, keys_path, hactool, out, logs):
    """The add-on index of the NSP at path; its RomFS goes to out/<index>. Titlekeys come from the NSP's own ticket."""
    tickets, records = nsp_records(path, keys_path)
    picked = [r for r in records if r['content_type'] == AOC_DATA and 0 < int(r['title_id'], 16) - AOC_BASE < 2000]
    extract.require(len(picked) == 1, f'{path.name}: expected one add-on content NCA, found {len(picked)}')
    record = picked[0]
    index = int(record['title_id'], 16) - AOC_BASE
    target = out / str(index)
    if target.is_dir():
        extract.say(f'  add-on content {index} already extracted')
        return index
    nca_romfs(path, record, tickets, keys_path, hactool, target, logs / f'dlc-{index}.log')
    extract.say(f'  {path.name} is add-on content {index} ({record["title_id"]})')
    return index


def extract_icon(update, keys_path, hactool, out, logs):
    """The game's icon from the update's control NCA, written to out/icon.ico. Stays under build/: it is game artwork."""
    from PIL import Image   # only this step needs Pillow (tools/requirements-py314.txt)
    ico = out / 'icon.ico'
    if ico.is_file():
        return
    tickets, records = nsp_records(update, keys_path)
    picked = [r for r in records if r['content_type'] == CONTROL]
    extract.require(len(picked) == 1, f'{update.name}: expected one control NCA, found {len(picked)}')
    with tempfile.TemporaryDirectory(prefix='control-', dir=out) as tmp:
        control = Path(tmp) / 'control'
        nca_romfs(update, picked[0], tickets, keys_path, hactool, control, logs / 'control.log')
        found = [control / n for n in ICONS if (control / n).is_file()] or sorted(control.glob('icon_*.dat'))
        extract.require(bool(found), f'{update.name}: the control data has no icon')
        jpeg = found[0]
        image = Image.open(io.BytesIO(jpeg.read_bytes())).convert('RGBA')
    image.save(ico, format='ICO', sizes=[(n, n) for n in ICON_SIZES])
    extract.say(f'  game icon: {image.width}x{image.height} -> {ico.name}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--update', type=Path, required=True)
    ap.add_argument('--keys', type=Path, required=True)
    ap.add_argument('--dlc', type=Path, nargs='*', default=[])
    ap.add_argument('--hactool', type=Path, default=extract.ROOT / 'toolchain' / 'hactool' / 'hactool.exe')
    ap.add_argument('--work', type=Path, default=extract.ROOT / 'build')
    ap.add_argument('--name', default='upd', help='folder under build/extracted for the update (default upd: 3.0.1)')
    args = ap.parse_args()
    work = args.work.resolve()
    out = work / 'extracted' / args.name
    logs = work / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    if not (work / 'extracted' / 'v0' / 'exefs' / 'main').is_file():
        extract.say('ExeFS of the base game')
        extract.extract_exefs(args.base, args.keys, work / 'extracted' / 'v0', logs, update=False)
    if not (out / 'exefs' / 'main').is_file():
        extract.say('ExeFS of the update')
        extract.extract_exefs(args.update, args.keys, out, logs, update=True)
    for path in args.dlc:
        extract_dlc(path, args.keys, args.hactool.resolve(), out / 'aoc', logs)
    extract_icon(args.update, args.keys, args.hactool.resolve(), out, logs)
    if not (out / 'romfs' / 'index.json').is_file():
        extract.say('RomFS: base merged with the update')
        extract.merge_update_romfs(args.base, args.update, args.keys, args.hactool.resolve(), out / 'romfs', logs)
    extract.say(f'done: {out}')


if __name__ == '__main__':
    main()
