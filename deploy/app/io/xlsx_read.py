"""Minimal XLSX reader: stdlib zipfile + ElementTree only.

Every cell's <v> element is returned as TEXT, never parsed through float().
That is the whole point of writing this instead of using openpyxl for
import: openpyxl (like most spreadsheet libraries) parses a numeric cell to
a Python float on the way in, which is exactly the failure mode the
integer minor-unit contract exists to prevent. openpyxl remains fine for
XLSX *export*, where no such round trip happens.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col_letters(cell_ref: str) -> str:
    return "".join(ch for ch in cell_ref if ch.isalpha())


class Workbook:
    def __init__(self, zip_file: zipfile.ZipFile, sheet_paths: dict[str, str],
                 shared_strings: list[str]):
        self._zip = zip_file
        self._sheet_paths = sheet_paths
        self._shared_strings = shared_strings

    def sheet_names(self) -> list[str]:
        return list(self._sheet_paths.keys())

    def read_rows(self, sheet_name: str) -> dict[int, dict[str, str]]:
        """{row_number: {column_letters: text_value}}. A shared-string cell
        is resolved by index; every other cell keeps its literal <v> text."""
        path = self._sheet_paths[sheet_name]
        with self._zip.open(path) as fh:
            tree = ET.parse(fh)
        rows: dict[int, dict[str, str]] = {}
        for row_el in tree.getroot().iter(f"{_NS}row"):
            row_num = int(row_el.get("r"))
            cells: dict[str, str] = {}
            for cell_el in row_el.iter(f"{_NS}c"):
                ref = cell_el.get("r")
                if not ref:
                    continue
                col = _col_letters(ref)
                cell_type = cell_el.get("t")
                v_el = cell_el.find(f"{_NS}v")
                text = None
                if cell_type == "s":
                    if v_el is not None and v_el.text is not None:
                        text = self._shared_strings[int(v_el.text)]
                elif cell_type == "str":
                    t_el = cell_el.find(f"{_NS}t")
                    if t_el is not None:
                        text = t_el.text
                    elif v_el is not None:
                        text = v_el.text
                else:
                    if v_el is not None:
                        text = v_el.text
                if text is not None:
                    cells[col] = text
            if cells:
                rows[row_num] = cells
        return rows

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> "Workbook":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    with zf.open("xl/sharedStrings.xml") as fh:
        tree = ET.parse(fh)
    strings = []
    for si_el in tree.getroot().iter(f"{_NS}si"):
        text = "".join(t_el.text or "" for t_el in si_el.iter(f"{_NS}t"))
        strings.append(text)
    return strings


def _read_sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    with zf.open("xl/workbook.xml") as fh:
        wb_tree = ET.parse(fh)
    with zf.open("xl/_rels/workbook.xml.rels") as fh:
        rels_tree = ET.parse(fh)
    rel_targets = {rel_el.get("Id"): rel_el.get("Target") for rel_el in rels_tree.getroot()}
    sheet_paths = {}
    for sheet_el in wb_tree.getroot().iter(f"{_NS}sheet"):
        name = sheet_el.get("name")
        rid = sheet_el.get(f"{_REL_NS}id")
        target = rel_targets[rid]
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        sheet_paths[name] = target
    return sheet_paths


def open_workbook(path: str | Path) -> Workbook:
    zf = zipfile.ZipFile(path)
    return Workbook(zf, _read_sheet_paths(zf), _read_shared_strings(zf))
