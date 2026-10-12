#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/external/ni_2023_atrial/Single_Cells"
BUILD_SOURCE="$ROOT/.build/ni_2023/Single_Cells"
PREFIX="${SUNDIALS_PREFIX:-$ROOT/.local/sundials}"
OUTPUT="$ROOT/model_assets/atrial/ni_2023/ni_single_cell"

test -f "$SOURCE/main_HAM_Signalling_cvode_new.cpp"
test -f "$PREFIX/include/sundials/sundials_config.h"
mkdir -p "$(dirname "$OUTPUT")"
python3 "$ROOT/scripts/prepare_ni_build_source.py"

SUNDIALS_MAJOR="$(awk '$2 == "SUNDIALS_VERSION_MAJOR" { print $3 }' "$PREFIX/include/sundials/sundials_config.h")"
if [[ ! "$SUNDIALS_MAJOR" =~ ^[0-9]+$ ]]; then
  echo "Unable to determine the installed SUNDIALS major version" >&2
  exit 1
fi
if (( SUNDIALS_MAJOR >= 7 )); then
  SUNDIALS_SUPPORT_LIBRARY="-lsundials_core"
else
  SUNDIALS_SUPPORT_LIBRARY="-lsundials_generic"
fi

"${CXX:-c++}" -std=c++14 -O2 \
  -include "$ROOT/backend/native/ni_2023/sundials6_compat.hpp" \
  -I"$BUILD_SOURCE/lib" -I"$PREFIX/include" -L"$PREFIX/lib" \
  "$ROOT/backend/native/ni_2023/driver.cpp" "$BUILD_SOURCE"/lib/*.cpp \
  -lsundials_cvode -lsundials_nvecserial -lsundials_sunmatrixdense \
  -lsundials_sunlinsoldense "$SUNDIALS_SUPPORT_LIBRARY" -lz \
  -Wl,-rpath,"$PREFIX/lib" -o "$OUTPUT"

"$OUTPUT" 1000 0 1 0 0 0 0 "$SOURCE/Restart_ICs/ICs_baseline.bin" >/dev/null
