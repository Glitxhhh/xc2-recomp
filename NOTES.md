# XC2 Recomp: bring-up notes

Fork of the XC3 bring-up (`xc3` remote: the uncommitted XC3 work on top of XCX master 1025eac; `xcx` remote: XCX Recomp).
Game data stays out of the repository.

## Inputs

| File | Title id | Notes |
|---|---|---|
| base | `0100E95004038000` | v0 NSP |
| update 3.0.1 (v1114112) | `0100E95004038800` | RomFS through BKTR; the supported version (`tools/data/expected-xc2-3.0.1.json`) |
| add-on content 1-6, 99 | `0100E95004039001`-`6`, `...9063` | 1 Torna, 2 New Quests, 3 Rare Blades, 4 Challenge Mode, 5 Helpful Items, 6 My Nintendo bonus, 99 Japanese voices; mounted from `build/extracted/upd/aoc/<index>` |
| update 2.1.0 (v983040) | `0100E95004038800` | `tools/data/expected-xc2-2.1.0.json`; `extract_xc2.py --name v210`, `build_game.py --version v210`. Boots and plays the new-game script (title to Argentum) with no unimplemented call; no add-on content extracted for it yet |
| XCI | `0100E95004038000` | base + v2.1.0 update + 7 DLC in one cartridge image; the 2.1.0 build uses the NSP update instead |

## Survey

- Older NintendoSDK (2017). Modules `main`, `sdk`, `subsdk0`, `rtld`. Init arrays: main 200, subsdk0 46, sdk 103.
- Start-up is `nn::init::Start(ulong, ulong, void (*)(), void (*)())`: two callbacks, no finalizer (`boot.c guest_main`).
- First `nvnBootstrapLoader` returns to main+0x708b44 (2.1.0: +0x7082c4; `boot.c nvn_rets`, keyed by `rt_game_name`).
- 2.1.0 and 3.0.1 bind the same 59 overrides (`--probe-services`); the same SDK symbols, so no older-SDK gap shows for 2.1.0.
- Lifted: 76,639 functions (main 35,908), 277 MB of C, 0 unsupported instructions, 21 s.
- Audio goes through AudioRenderer at revision 3 (`audren.c`), not AudioOut as in XCX and XC3.
- NVN pool and texture setup lends the virtual core (`kernel.c kern_core_lend`, `nvn_api.h NVN_BLOCKING`): taking it back
  counts one priority step better. Without that, XC2's main thread (p44, polling the clock with no SVC) kept the core the
  render thread (p44) gave up in `nvnMemoryPoolInitialize`, and presents stopped on the first loading screen.
- Older SDK names the runtime now also answers: `account::OpenPreselectedUser` (Result), `fs::CommitSaveData`,
  `vi::SetLayerScalingMode`, `oe::Enable/DisableScreenShot`. `fs::QueryMountRomCacheSize` answers one page: XC2 mallocs it and
  asserts on null.

## Build and run

```powershell
.venv-py314\Scripts\python tools\extract_xc2.py --base game\base.nsp --update game\update-3.0.1.nsp --keys <prod.keys> --dlc (ls game\dlc-*.nsp) --hactool toolchain\hactool\hactool.exe
.venv\Scripts\python recomp\gen.py --exefs build\extracted\upd\exefs --out generated\upd
tools\build_xc2.ps1
build\upd\xc2.exe
```

`build\xlate\xc2_xlate.exe` is XC3's translator build copied over (same sources) with `tools\build_xlate.py --id-only`.

Test runs: `XC2_ASSUME_FOCUS=1 XC2_BACKGROUND_WINDOW=1`, `--boot`, `XC2_INPUT_SCRIPT=<file>`, `--seconds N --shot x.png`,
`XC2_SHOTS=<from>-<to>:<step>`, `XC2_DUMP=<frame>`.

## Known gaps

- Transform feedback is not replayed (`nvn_api_cmd.c xfb_skipped`).
- No patch table: the game runs at its own frame rate and resolution. Comments that say XC2 in `frame_rate.c`,
  `resolution.c` and the `UI_*` sites of `nvn_api_cmd.c` describe XCX addresses (the rename went XCX -> XC3 -> XC2); those
  paths are inert until the sites are found in XC2's `main`: neither 3.0.1 nor 2.1.0 holds the `{1920, 1080, 1280, 720}`
  table, and the `xc360` set that gates every XCX address write in `frame_rate.c` does not exist for XC2.
- XC2 builds its window with present interval 1 and never changes it (`XC2_TRACE=gfx`: `nvnWindowSetPresentInterval` is
  not called through the new-game script). Its 30 fps cap is the game's own vsync waits, so 60 fps needs a patch at that
  site, not at the NVN interval.
- `docs/` and `tests/` still describe XC3 2.2.1 / XCX behaviour under the renamed names; the installer and release text say
  XC2 3.0.1.
- The toolchain's deps directory has no `bin/`, so `build_game.py --deps` copies no DLLs; a new build directory takes them
  from `build\upd`.
