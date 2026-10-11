#!/usr/bin/env python3
"""Prepare a compiler-safe Ni 2023 build copy without editing the pinned checkout."""
from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "external/ni_2023_atrial/Single_Cells"
DESTINATION = ROOT / ".build/ni_2023/Single_Cells"


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = DESTINATION / relative_path
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one reviewed compatibility site in {relative_path}")
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    if not (SOURCE / "lib/CaMKII.hpp").is_file():
        raise RuntimeError("Pinned Ni 2023 source is missing")
    shutil.rmtree(DESTINATION, ignore_errors=True)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE, DESTINATION)

    # These upstream functions update object state and every caller discards
    # their return value. Falling off a non-void function is undefined C++ and
    # GCC 14 can optimize the continuation into a trap. Explicit returns make
    # the reviewed state-update behavior portable without changing equations.
    replace_once(
        "lib/CaMKII.hpp",
        "\t\tydot[5] = dLCC_CKslp * 1e-3;\n\n\t}",
        "\t\tydot[5] = dLCC_CKslp * 1e-3;\n\n\t\treturn 0;\n\t}",
    )
    replace_once(
        "lib/Herg.hpp",
        "\t\tIKr =  (1 + para.dGkr_PKA) * GKr * O * (Vm - Ek);\n\n\n\t}",
        "\t\tIKr =  (1 + para.dGkr_PKA) * GKr * O * (Vm - Ek);\n\n\n\t\treturn IKr;\n\t}",
    )
    for relative_path in ("lib/v9.cpp", "lib/v9_mode_2.cpp"):
        replace_once(
            relative_path,
            "\tI_K_junc_m1 = Fjunc_CaL * (ibark_jm1 * Po_LCCj_m1) ;\n}",
            "\tI_K_junc_m1 = Fjunc_CaL * (ibark_jm1 * Po_LCCj_m1) ;\n\treturn 0.0;\n}",
        )

    print(f"Prepared compiler-safe Ni build source at {DESTINATION}")


if __name__ == "__main__":
    main()
