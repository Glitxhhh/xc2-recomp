# Build build\upd\xc2.exe for XC2 3.0.1 with llvm-mingw, then copy the DLLs and the shader translator
# (tools/build_xlate.py) next to it. Run from the repository root.
# The toolchain is the repository's own, in the ignored toolchain\ (the dev-mode layout of installer/layout.py):
# toolchain\llvm-mingw-*\llvm-mingw-*\ (the last by name), toolchain\deps-mingw with include\, lib\ and bin\ (SDL3.dll,
# libopus-0.dll), and MSYS2 UCRT64 ninja. -Setup takes all of it from an unpacked TotK or XC2 Recomp release folder
# instead (llvm\, runtime\deps\, bin\).
param([string]$Setup = '',
      [string]$Xlate = "$PSScriptRoot\..\build\xlate")
$ErrorActionPreference = 'Stop'
if ($Setup) {
    $Setup = (Resolve-Path $Setup).Path
    $llvm, $deps, $ninja = "$Setup\llvm", "$Setup\runtime\deps", "$Setup\bin\ninja.exe"
    $dlls = "$Setup\bin\SDL3.dll", "$Setup\bin\libopus-0.dll"
} else {
    $tc = (Resolve-Path "$PSScriptRoot\..\toolchain").Path
    $clang = Get-ChildItem "$tc\llvm-mingw-*\llvm-mingw-*\bin\clang.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName | Select-Object -Last 1
    if (-not $clang) { throw "no $tc\llvm-mingw-*\llvm-mingw-*\bin\clang.exe: unpack llvm-mingw there, or pass -Setup <release folder>" }
    $llvm, $deps, $ninja = $clang.Directory.Parent.FullName, "$tc\deps-mingw", 'C:\msys64\ucrt64\bin\ninja.exe'
    $dlls = (Get-ChildItem "$deps\bin\*.dll").FullName
}
& "$PSScriptRoot\..\.venv\Scripts\python.exe" "$PSScriptRoot\build_game.py" --version upd `
    --expected "$PSScriptRoot\data\expected-xc2-3.0.1.json" --toolchain $llvm --deps $deps `
    --ninja $ninja 2>&1 | Select-String -NotMatch 'warning|note:|^\s+\||^\s*\d+ \||^E:/Game|^\s*\^|_Nonnull|_Nullable|^\[\d+/\d+\] CC'
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$out = "$PSScriptRoot\..\build\upd"
Copy-Item $dlls $out -Force
Copy-Item "$Xlate\xc2_xlate.exe", "$Xlate\xc2_xlate.id" $out -Force
Copy-Item "$llvm\bin\libc++.dll", "$llvm\bin\libunwind.dll", "$llvm\bin\libwinpthread-1.dll" $out -Force
