#!/usr/bin/env python3
"""Prepare a Myokit-readable copy of the pinned Linder-Fabbri CellML source.

The published CellML omits several parent-side private-interface declarations
that are required by CellML 1.0 section 3.4.6.4. This script adds only the
missing declarations implied by the existing child-side public interfaces.
Equations, constants, initial values, and connection mappings are unchanged.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "model_assets/pacemaker/linder_fabbri_2025_betaAR/HumanSAN_Fabbri_Fantini_Wilders_Severi_2017.cellml"
OUTPUT = ROOT / "model_assets/pacemaker/linder_fabbri_2025_betaAR/HumanSAN_Fabbri_Fantini_Wilders_Severi_2017.myokit.cellml"
CELLML = "http://www.cellml.org/cellml/1.0#"
NS = {"c": CELLML}


def main() -> None:
    tree = ET.parse(SOURCE)
    root = tree.getroot()
    unit_names = {item.attrib["name"] for item in root.findall("c:units", NS)}
    units_added: list[str] = []
    if "per_nanomolar" not in unit_names:
        units = ET.Element(f"{{{CELLML}}}units", {"name": "per_nanomolar"})
        units.append(ET.Element(f"{{{CELLML}}}unit", {"exponent": "-1", "units": "nanomolar"}))
        first_component = root.find("c:component", NS)
        root.insert(list(root).index(first_component) if first_component is not None else 0, units)
        units_added.append("per_nanomolar = nanomolar^-1")
    if "nonomolar" not in unit_names:
        units = ET.Element(f"{{{CELLML}}}units", {"name": "nonomolar"})
        units.append(ET.Element(f"{{{CELLML}}}unit", {"units": "nanomolar"}))
        first_component = root.find("c:component", NS)
        root.insert(list(root).index(first_component) if first_component is not None else 0, units)
        units_added.append("nonomolar = nanomolar (published spelling alias)")
    components = {item.attrib["name"]: item for item in root.findall("c:component", NS)}
    parents: dict[str, str] = {}
    for group in root.findall("c:group", NS):
        relationship = group.find("c:relationship_ref", NS)
        if relationship is None or relationship.get("relationship") != "encapsulation":
            continue

        def walk(ref: ET.Element, parent: str | None = None) -> None:
            name = ref.attrib["component"]
            if parent is not None:
                parents[name] = parent
            for child in ref.findall("c:component_ref", NS):
                walk(child, name)

        for ref in group.findall("c:component_ref", NS):
            walk(ref)

    merged_connections: list[str] = []
    seen_connections: dict[tuple[str, str], tuple[ET.Element, str, str]] = {}
    for connection in list(root.findall("c:connection", NS)):
        mapping = connection.find("c:map_components", NS)
        if mapping is None:
            continue
        first, second = mapping.attrib["component_1"], mapping.attrib["component_2"]
        key = tuple(sorted((first, second)))
        if key not in seen_connections:
            seen_connections[key] = (connection, first, second)
            continue
        target, target_first, target_second = seen_connections[key]
        existing = {(item.attrib["variable_1"], item.attrib["variable_2"]) for item in target.findall("c:map_variables", NS)}
        reversed_order = first == target_second and second == target_first
        for variable_mapping in connection.findall("c:map_variables", NS):
            variable_1 = variable_mapping.attrib["variable_2"] if reversed_order else variable_mapping.attrib["variable_1"]
            variable_2 = variable_mapping.attrib["variable_1"] if reversed_order else variable_mapping.attrib["variable_2"]
            if (variable_1, variable_2) not in existing:
                target.append(ET.Element(f"{{{CELLML}}}map_variables", {"variable_1": variable_1, "variable_2": variable_2}))
                existing.add((variable_1, variable_2))
        root.remove(connection)
        merged_connections.append(f"{first}<->{second}")

    changed: list[str] = []
    for connection in root.findall("c:connection", NS):
        mapping = connection.find("c:map_components", NS)
        if mapping is None:
            continue
        first, second = mapping.attrib["component_1"], mapping.attrib["component_2"]
        if parents.get(second) == first:
            parent_name, child_name, parent_key, child_key = first, second, "variable_1", "variable_2"
        elif parents.get(first) == second:
            parent_name, child_name, parent_key, child_key = second, first, "variable_2", "variable_1"
        else:
            first_variables = {item.attrib["name"]: item for item in components[first].findall("c:variable", NS)}
            second_variables = {item.attrib["name"]: item for item in components[second].findall("c:variable", NS)}
            for variable_mapping in connection.findall("c:map_variables", NS):
                first_variable = first_variables[variable_mapping.attrib["variable_1"]]
                second_variable = second_variables[variable_mapping.attrib["variable_2"]]
                first_interface = first_variable.get("public_interface", "none")
                second_interface = second_variable.get("public_interface", "none")
                if first_interface in {"in", "out"} and second_interface == "none":
                    required = "out" if first_interface == "in" else "in"
                    second_variable.set("public_interface", required)
                    changed.append(f"{second}.{second_variable.attrib['name']} public_interface={required}")
                elif second_interface in {"in", "out"} and first_interface == "none":
                    required = "out" if second_interface == "in" else "in"
                    first_variable.set("public_interface", required)
                    changed.append(f"{first}.{first_variable.attrib['name']} public_interface={required}")
                elif first_interface in {"in", "out"} and first_interface == second_interface:
                    raise ValueError(f"Conflicting interfaces for {first}.{first_variable.attrib['name']} and {second}.{second_variable.attrib['name']}")
            continue
        parent_variables = {item.attrib["name"]: item for item in components[parent_name].findall("c:variable", NS)}
        child_variables = {item.attrib["name"]: item for item in components[child_name].findall("c:variable", NS)}
        for variable_mapping in connection.findall("c:map_variables", NS):
            parent_variable = parent_variables[variable_mapping.attrib[parent_key]]
            child_variable = child_variables[variable_mapping.attrib[child_key]]
            child_interface = child_variable.get("public_interface", "none")
            parent_interface = parent_variable.get("private_interface", "none")
            if child_interface in {"in", "out"} and parent_interface == "none":
                required = "out" if child_interface == "in" else "in"
                parent_variable.set("private_interface", required)
                changed.append(f"{parent_name}.{parent_variable.attrib['name']} private_interface={required}")
            elif parent_interface in {"in", "out"} and child_interface == "none":
                required = "out" if parent_interface == "in" else "in"
                child_variable.set("public_interface", required)
                changed.append(f"{child_name}.{child_variable.attrib['name']} public_interface={required}")
            elif child_interface in {"in", "out"} and parent_interface in {"in", "out"}:
                if child_interface == parent_interface:
                    raise ValueError(f"Conflicting interfaces for {parent_name}.{parent_variable.attrib['name']} and {child_name}.{child_variable.attrib['name']}")

    ET.register_namespace("cellml", CELLML)
    ET.register_namespace("cmeta", "http://www.cellml.org/metadata/1.0#")
    tree.write(OUTPUT, encoding="UTF-8", xml_declaration=True)
    print(f"source_sha256={hashlib.sha256(SOURCE.read_bytes()).hexdigest()}")
    print(f"runtime_sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")
    print(f"missing_unit_definitions_added={len(units_added)}")
    for item in units_added:
        print(item)
    print(f"duplicate_connections_merged={len(merged_connections)}")
    for item in merged_connections:
        print(item)
    print(f"interface_declarations_added={len(changed)}")
    for item in changed:
        print(item)


if __name__ == "__main__":
    main()
