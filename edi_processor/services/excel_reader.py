from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


class ExcelReader:
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    def read_rows(self, path: Path) -> list[list[str]]:
        with zipfile.ZipFile(path) as archive:
            strings = self._read_shared_strings(archive)
            sheet_name = self._first_sheet_name(archive)
            root = ET.fromstring(archive.read(sheet_name))

        rows: list[list[str]] = []
        for row in root.findall(".//a:row", self.namespace):
            row_number = int(row.attrib["r"])
            while len(rows) < row_number:
                rows.append([])

            values: list[str] = []
            for cell in row.findall("a:c", self.namespace):
                column_index = self._column_index(cell.attrib.get("r", "A1"))
                while len(values) < column_index:
                    values.append("")

                value = self._cell_value(cell, strings)
                values[column_index - 1] = value

            rows[row_number - 1] = values

        return rows

    def sheet_names(self, path: Path) -> list[str]:
        with zipfile.ZipFile(path) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))

        return [
            sheet.attrib.get("name", "")
            for sheet in workbook.findall(".//a:sheet", self.namespace)
            if sheet.attrib.get("name")
        ]

    def _read_shared_strings(self, archive: zipfile.ZipFile) -> list[str]:
        try:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        except KeyError:
            return []

        values: list[str] = []
        for item in root.findall("a:si", self.namespace):
            parts = [node.text or "" for node in item.findall(".//a:t", self.namespace)]
            values.append("".join(parts))
        return values

    def _first_sheet_name(self, archive: zipfile.ZipFile) -> str:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        namespace = {
            "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }
        first_sheet = workbook.find(".//a:sheet", namespace)
        if first_sheet is None:
            raise ValueError("Workbook does not contain any sheets.")

        relationship_id = first_sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_namespace = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
        for relationship in relationships.findall("r:Relationship", rel_namespace):
            if relationship.attrib["Id"] == relationship_id:
                return f"xl/{relationship.attrib['Target']}"

        raise ValueError("Could not resolve first worksheet relationship.")

    def _cell_value(self, cell: ET.Element, strings: list[str]) -> str:
        value_node = cell.find("a:v", self.namespace)
        if value_node is None:
            return ""

        value = value_node.text or ""
        if cell.attrib.get("t") == "s" and value:
            return strings[int(value)]

        return value

    def _column_index(self, cell_ref: str) -> int:
        letters = "".join(character for character in cell_ref if character.isalpha())
        index = 0
        for character in letters:
            index = index * 26 + (ord(character.upper()) - ord("A") + 1)
        return index
