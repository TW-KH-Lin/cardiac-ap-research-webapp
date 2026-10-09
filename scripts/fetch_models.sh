#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root. Every Git checkout is fixed to a reviewed SHA.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p external model_assets/ventricular/simone model_assets/atrial model_assets/pacemaker

fetch_git() {
  local url="$1" dest="$2" revision="$3"
  if [[ ! -d "$dest/.git" ]]; then
    git clone "$url" "$dest"
  fi
  git -C "$dest" fetch origin "$revision"
  git -C "$dest" checkout --detach "$revision"
  [[ "$(git -C "$dest" rev-parse HEAD)" == "$revision" ]]
}

fetch_git_sparse() {
  local url="$1" dest="$2" revision="$3" path="$4"
  if [[ ! -d "$dest/.git" ]]; then
    git clone --filter=blob:none --no-checkout "$url" "$dest"
  fi
  git -C "$dest" sparse-checkout init --cone
  git -C "$dest" sparse-checkout set "$path"
  git -C "$dest" fetch --depth 1 origin "$revision"
  git -C "$dest" checkout --detach "$revision"
  [[ "$(git -C "$dest" rev-parse HEAD)" == "$revision" ]]
}

fetch_raw() {
  local url="$1" dest="$2"
  curl --fail --location --retry 3 --connect-timeout 15 --max-time 120 "$url" --output "$dest.tmp"
  test -s "$dest.tmp"
  mv "$dest.tmp" "$dest"
}

fetch_git https://github.com/jtmff/torord.git external/torord 11e463da0f083c276c0057211e476f35cc2fc2c0
fetch_git https://github.com/myokit/models.git external/myokit-models e8ef6dbad6c1bf4446428f1f73dd0a4d164af40d
fetch_git https://github.com/thomgrand/cardiomyocyte_emulator.git external/grandits_emulator 26ba43c619c0acf2fc853326aa4cd0578b786d6a
fetch_git_sparse https://github.com/drgrandilab/Ni-et-al-2023-Human-Atrial-Signaling-Model.git external/ni_2023_atrial 683d1dab564b7a427ec301126924c94e8bf5ecb2 Single_Cells
fetch_git_sparse https://github.com/drgrandilab/Herrera-et-al-2025-Sex-Specific-Human-Atrial-Model.git external/herrera_2025_atrial 77c8e39b5a8ca2ea49b4ff260a63a2e9c8e7b69c "Single Cell"

if [[ "${FETCH_PMR:-1}" == "1" ]]; then
  fetch_raw https://models.cellml.org/workspace/711/rawfile/c8dc3b237a23e43c99a5d4a768313d5c6bc3ce18/BPS2020.cellml model_assets/ventricular/BPS2020.cellml
  fetch_raw https://models.cellml.org/workspace/d92/rawfile/83903a0ad0a326782c7f35c4d51e9cea5dc6e90a/Simone_Trancuccio2025.m model_assets/ventricular/simone/Simone_Trancuccio2025.m
  fetch_raw https://models.cellml.org/workspace/d92/rawfile/83903a0ad0a326782c7f35c4d51e9cea5dc6e90a/Main_Simone_Trancuccio_2025.m model_assets/ventricular/simone/Main_Simone_Trancuccio_2025.m
  mkdir -p model_assets/pacemaker/linder_fabbri_2025_betaAR
  fetch_raw https://models.cellml.org/workspace/c65/rawfile/95db8d627beef8d27783ae6fa2381a2fb47b123a/HumanSAN_Fabbri_Fantini_Wilders_Severi_2017.cellml model_assets/pacemaker/linder_fabbri_2025_betaAR/HumanSAN_Fabbri_Fantini_Wilders_Severi_2017.cellml
  python3 scripts/prepare_linder_cellml.py
  python3 scripts/generate_simone_static.py
fi

if [[ -f "${SUNDIALS_PREFIX:-$ROOT/.local/sundials}/include/sundials/sundials_config.h" ]]; then
  scripts/build_ni_2023.sh
fi

python3 scripts/update_manifest_hashes.py
