"""Bounded, literal-only HR03 CSV/XLSX reader; no ORM or uploaded code execution.

The import sheet contains real records only. Instructions and example sheets are
never imported. Text identifiers are mandatory in XLSX to avoid Excel rounding.
"""
from __future__ import annotations

import csv
import io
import posixpath
import re
from datetime import datetime, timedelta
from zipfile import BadZipFile, ZipFile
from defusedxml.ElementTree import fromstring

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_EXPANDED = 30 * 1024 * 1024
SHEET_NAME = "教职工导入"
COLUMNS = {
    "staff_no": "工号", "legal_name": "姓名", "gender_code": "性别",
    "birth_date": "出生日期", "document_number": "证件号码",
    "staff_category_code": "人员类别", "relationship_type": "聘用关系",
    "effective_from": "入职日期", "department_name": "所属部门",
    "legacy_department_id": "部门编号",
}
ALIASES = {**{k: k for k in COLUMNS}, **{v: k for k, v in COLUMNS.items()}}
N = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class TabularError(ValueError):
    """Safe error: never embeds uploaded person/identity values."""


def _headers(values):
    names = [ALIASES.get(str(v or "").strip()) for v in values]
    if not names or any(name is None for name in names):
        raise TabularError("表头为空或包含不支持的列，请使用本系统模板")
    if len(names) != len(set(names)):
        raise TabularError("表头存在重复列（中文和英文同义列也不能重复）")
    if "legal_name" not in names:
        raise TabularError("必须包含“姓名”列")
    return names


def _text(value, row_no):
    text = str(value or "").strip()
    if len(text) > 1000 or any(ord(c) < 32 and c not in "\t\n\r" for c in text):
        raise TabularError(f"第 {row_no} 行包含过长内容或非法控制字符")
    return text


def _rows(matrix):
    try:
        _, values, _ = next(matrix)
    except StopIteration:
        raise TabularError("文件为空")
    headers = _headers(values)
    result = []
    for row_no, values, kinds in matrix:
        if not any(str(v or "").strip() for v in values):
            continue
        if len(values) > len(headers):
            raise TabularError(f"第 {row_no} 行列数超过表头，请检查多余单元格")
        values = values + [""] * (len(headers) - len(values))
        row = {}
        for col, (key, value) in enumerate(zip(headers, values)):
            kind = kinds.get(col, "text")
            if key in ("staff_no", "document_number") and value != "" and kind == "number":
                raise TabularError(f"第 {row_no} 行{COLUMNS[key]}必须设为文本，避免长号码或前导零丢失")
            if key in ("birth_date", "effective_from") and value != "" and kind.startswith("date:"):
                value = _excel_date(value, kind == "date:1904", row_no)
            row[key] = _text(value, row_no)
        row["_source_row_no"] = row_no
        result.append(row)
        if len(result) > MAX_ROWS:
            raise TabularError(f"单次最多导入 {MAX_ROWS} 行，请分批上传")
    if not result:
        raise TabularError("模板只有表头或空白行，请先填写真实教职工资料")
    return result


def _excel_date(value, use_1904, row_no):
    try:
        serial = float(value)
        if not serial.is_integer() or serial < 0 or serial > 2958465 or (not use_1904 and serial == 60):
            raise ValueError
        days = serial if use_1904 or serial < 60 else serial - 1
        base = datetime(1904, 1, 1) if use_1904 else datetime(1899, 12, 31)
        value = base + timedelta(days=days)
        if value.year < 1900:
            raise ValueError
        return value.date().isoformat()
    except (ValueError, OverflowError):
        raise TabularError(f"第 {row_no} 行日期不是有效的日期值") from None


def _xml(zf, name):
    try:
        return fromstring(zf.read(name), forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception as exc:
        raise TabularError("Excel 结构无效或含不安全的 XML 内容，请另存为标准 .xlsx") from exc


def _xlsx_matrix(raw):
    try:
        zf = ZipFile(io.BytesIO(raw))
    except BadZipFile as exc:
        raise TabularError("文件不是有效的 .xlsx 工作簿") from exc
    with zf:
        entries = zf.infolist()
        names = [info.filename for info in entries]
        if len(entries) > 200 or len(names) != len(set(names)):
            raise TabularError("Excel 压缩结构异常")
        if sum(info.file_size for info in entries) > MAX_EXPANDED:
            raise TabularError("Excel 解压内容过大，请删除无用工作表后重试")
        for info in entries:
            name = info.filename
            if (name.startswith("/") or "\\" in name or ".." in name.split("/") or info.flag_bits & 1
                    or info.file_size > MAX_EXPANDED or info.file_size > max(4096, info.compress_size) * 200):
                raise TabularError("Excel 压缩结构不安全或解压比例过高")
            if any(s in name.lower() for s in ("vbaproject", "externallinks/", "embeddings/")):
                raise TabularError("不支持宏、外部链接或嵌入文件，请使用纯数据模板")
        for name in names:
            if name.endswith(".rels"):
                rels = _xml(zf, name)
                if any(r.attrib.get("TargetMode", "").lower() == "external" for r in rels):
                    raise TabularError("不支持含外部链接的 Excel")
        workbook = _xml(zf, "xl/workbook.xml")
        date1904 = workbook.find("m:workbookPr", N)
        date1904 = date1904 is not None and date1904.attrib.get("date1904") in ("1", "true")
        sheets = workbook.findall("m:sheets/m:sheet", N)
        target = next((s for s in sheets if s.attrib.get("name") == SHEET_NAME), None)
        if target is None or target.attrib.get("state", "visible") != "visible":
            raise TabularError(f"缺少可见的“{SHEET_NAME}”工作表，请使用本系统模板")
        rid = target.attrib.get(f"{{{R}}}id")
        rels = _xml(zf, "xl/_rels/workbook.xml.rels")
        relation = next((r for r in rels if r.attrib.get("Id") == rid), None)
        if relation is None:
            raise TabularError("Excel 工作表引用无效")
        path = relation.attrib.get("Target", "")
        path = path.lstrip("/") if path.startswith("/") else posixpath.normpath("xl/" + path)
        if not path.startswith("xl/worksheets/") or path not in names:
            raise TabularError("Excel 工作表路径无效")
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in _xml(zf, "xl/sharedStrings.xml").findall("m:si", N):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{N['m']}}}t")))
                if len(shared) > 100000:
                    raise TabularError("Excel 文本项过多，请分批导入")
        date_styles = set()
        if "xl/styles.xml" in names:
            styles = _xml(zf, "xl/styles.xml")
            custom = {}
            for fmt in styles.findall("m:numFmts/m:numFmt", N):
                custom[int(fmt.attrib["numFmtId"])] = fmt.attrib.get("formatCode", "")
            for idx, xf in enumerate(styles.findall("m:cellXfs/m:xf", N)):
                fmt_id = int(xf.attrib.get("numFmtId", 0))
                fmt = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", custom.get(fmt_id, "")).lower()
                if fmt_id in range(14, 23) or ("y" in fmt and "d" in fmt):
                    date_styles.add(idx)
        document = _xml(zf, path)
        previous = 0
        for node in document.findall("m:sheetData/m:row", N):
            try:
                row_no = int(node.attrib.get("r", 0))
                if row_no <= previous or row_no > MAX_ROWS + 1000:
                    raise ValueError
                previous = row_no
                values, kinds, seen = [], {}, set()
                for cell in node.findall("m:c", N):
                    reference = cell.attrib.get("r", "")
                    match = re.fullmatch(r"([A-Z]{1,2})([1-9][0-9]*)", reference)
                    if not match or int(match[2]) != row_no:
                        raise ValueError
                    col = 0
                    for letter in match[1]:
                        col = col * 26 + ord(letter) - 64
                    col -= 1
                    if col >= len(COLUMNS) or col in seen:
                        raise ValueError
                    seen.add(col)
                    if cell.find("m:f", N) is not None:
                        raise TabularError(f"第 {row_no} 行含公式，请粘贴为数值或文本后再上传")
                    typ = cell.attrib.get("t", "n")
                    value = cell.findtext("m:v", "", N)
                    kind = "text"
                    if typ == "s":
                        i = int(value)
                        if i < 0 or i >= len(shared):
                            raise ValueError
                        value = shared[i]
                    elif typ == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall("m:is//m:t", N))
                    elif typ == "n" and value:
                        kind = "date:1904" if date1904 else "date:1900"
                        if int(cell.attrib.get("s", 0)) not in date_styles:
                            kind = "number"
                    elif typ not in ("n", "str", "d"):
                        raise TabularError(f"第 {row_no} 行含错误值或布尔值，请改为文本")
                    while len(values) <= col:
                        values.append("")
                    values[col] = value
                    kinds[col] = kind
                # Formatting-only trailing cells must not add data columns.
                while values and values[-1] == "":
                    values.pop()
                if values:
                    yield row_no, values, kinds
            except (ValueError, KeyError, TypeError, IndexError):
                raise TabularError("Excel 行号、列号或单元格引用无效") from None


def read_import_rows(raw: bytes, filename: str) -> list[dict]:
    if len(raw) > MAX_BYTES:
        raise TabularError("上传文件不能超过 5 MB")
    if filename.lower().endswith(".xlsx"):
        try:
            return _rows(iter(_xlsx_matrix(raw)))
        except TabularError:
            raise
        except (ValueError, KeyError, IndexError, BadZipFile, RuntimeError) as exc:
            raise TabularError("Excel 结构或格式损坏，请使用本系统模板另存后重试") from exc
    if not filename.lower().endswith(".csv"):
        raise TabularError("请上传 .xlsx 或 UTF-8 编码的 .csv 文件")
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        def matrix():
            prior_line = 0
            for row in reader:
                start = prior_line + 1
                prior_line = reader.line_num
                yield start, row, {}
        return _rows(iter(matrix()))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise TabularError("CSV 编码或格式不正确，请另存为 UTF-8 CSV") from exc
