#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/external/ni_2023_atrial/Single_Cells"
PREFIX="${SUNDIALS_PREFIX:-$ROOT/.local/sundials}"
OUTPUT="$ROOT/model_assets/atrial/ni_2023/ni_single_cell"

test -f "$SOURCE/main_HAM_Signalling_cvode_new.cpp"
test -f "$PREFIX/include/sundials/sundials_config.h"
mkdir -p "$(dirname "$OUTPUT")"

"${CXX:-c++}" -std=c++14 -O2 \
  -include "$ROOT/backend/native/ni_2023/sundials6_compat.hpp" \
  -I"$SOURCE/lib" -I"$PREFIX/include" -L"$PREFIX/lib" \
  "$ROOT/backend/native/ni_2023/driver.cpp" "$SOURCE"/lib/*.cpp \
  -lsundials_cvode -lsundials_nvecserial -lsundials_sunmatrixdense \
  -lsundials_sunlinsoldense -lsundials_generic -lz \
  -Wl,-rpath,"$PREFIX/lib" -o "$OUTPUT"

"$OUTPUT" 1000 0 1 0 0 0 0 "$SOURCE/Restart_ICs/ICs_baseline.bin" >/dev/null
