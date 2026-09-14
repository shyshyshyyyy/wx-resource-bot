# -*- coding: utf-8 -*-
"""
本地表格导入资源。

顾客需求：
  1. 资源要支持本地表格（xlsx/csv）导入；
  2. 导入时每行可标「是否是自己的资源」；
  3. 标「是」→ 用户获取时跳过转存，直接给原链接；
     标「否」→ 走正常转存分享引擎。

本模块负责：解析表格 -> 写入 data/imported.json -> 供搜索命令合并查询。

标准模板（列名不区分大小写 / 支持中英文 / 允许额外列）：
  名称        ：资源标题（必填）
  链接        ：分享链接（必填）
  提取码      ：提取码 / 密码（可选）
  网盘类型    ：夸克/百度/UC/阿里云/迅雷/光鸭/移动（可选，留空按链接域名自动识别）
  是否自己的  ：是 / 否 / 1 / 0 / true / false / y（可选，默认「否」= 走转存）
"""

import os
import csv
import json
import logging
import threading

log = logging.getLogger("imported")

from core import paths
from core.session import normalize_pan
from search.pansou_client import Result, _sniff_type

# ---------- 列名识别 ----------
# 每个字段对应一组「命中即算该列」的关键字（小写子串匹配）。
_COLUMN_HINTS = {
    "title": ("名称", "标题", "名字", "资源名", "name", "title", "资源"),
    "url":   ("链接", "地址", "分享", "url", "link", "分享链接"),
    "password": ("提取码", "密码", "提取", "pwd", "password", "码"),
    "pan":   ("网盘", "类型", "盘", "pan", "type"),
    "own":   ("自己", "是否", "自有", "私有", "own"),
}

# 「是自己的资源」的真值集合（小写）
_OWN_TRUE = {"是", "y", "yes", "true", "1", "自己的", "自有", "own",
             "是自己的", "我的", "1.0"}


def _match_header(header, field):
    """判断某个表头属于哪个字段（返回字段名或 None）。"""
    h = (header or "").strip().lower()
    if not h:
        return None
    for key, hints in _COLUMN_HINTS.items():
        for hint in hints:
            if hint in h:
                return key
    return None


def _norm_pan(declared, url):
    """把用户写的网盘类型归一化成内部键；留空或认不出则按链接域名嗅探。"""
    d = (declared or "").strip()
    if d:
        key = normalize_pan(d)
        if key:
            return key
    return _sniff_type(url, d)


def _is_own(raw):
    return str((raw or "")).strip().lower() in _OWN_TRUE


def _read_rows(path):
    """读取表格为 [(header_list, [row_dict_by_header, ...])]。
    支持 .xlsx（openpyxl）与 .csv（utf-8 / gbk）。"""
    ext = os.path.splitext(path)[1].lower()
    headers, rows = [], []
    if ext == ".xlsx":
        try:
            import openpyxl
        except Exception as e:
            raise RuntimeError("缺少 openpyxl，无法解析 xlsx：%s" % e)
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        data = list(ws.iter_rows(values_only=True))
        if not data:
            return [], []
        # 第一行是表头；可能出现整行 None（空行），过滤掉
        headers = [("" if c is None else str(c)) for c in data[0]]
        for r in data[1:]:
            if r is None or all(c is None or str(c).strip() == ""
                               for c in r):
                continue
            row = [("" if c is None else str(c)) for c in r]
            # 按表头位置映射，避免「数据列比表头多」时丢失末尾列
            rows.append({h: (row[i] if i < len(row) else "")
                         for i, h in enumerate(headers)})
    else:
        # csv：自动探测编码
        raw = None
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with open(path, "r", encoding=enc, newline="") as f:
                    raw = f.read()
                break
            except Exception:
                continue
        if raw is None:
            raise RuntimeError("无法读取表格文件（编码识别失败）")
        reader = csv.reader(raw.splitlines())
        lines = [ln for ln in reader if ln and any(
            c.strip() for c in ln)]
        if not lines:
            return [], []
        headers = [c.strip() for c in lines[0]]
        for ln in lines[1:]:
            # 按表头位置映射（数据列多于表头时不会丢失末列；少于时补空）
            rows.append({h: (ln[i] if i < len(ln) else "")
                         for i, h in enumerate(headers)})
    return headers, rows


def _json_path():
    return os.path.join(paths.data_dir(), "imported.json")


def load_imported():
    p = _json_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def clear_imported():
    p = _json_path()
    try:
        if os.path.exists(p):
            os.remove(p)
        return True
    except Exception as e:
        log.warning("清空导入失败: %s", e)
        return False


def count_imported():
    return len(load_imported())


def import_table(path):
    """解析表格并写入 data/imported.json（覆盖式：重新导入即替换旧数据）。

    返回 (count, errors)。
      count  ：成功导入的条数（含 own 与 非 own）
      errors ：每条解析失败的说明（行号 + 原因）
    """
    headers, rows = _read_rows(path)
    if not headers:
        return 0, ["表格为空或无法解析表头"]

    # 建立 字段 -> 列下标 的映射
    col = {}
    for idx, h in enumerate(headers):
        fld = _match_header(h, None)
        if fld and fld not in col:
            col[fld] = idx
    # 用 header 名直接做字典的话上面 _read_rows 已经 zip 成 dict，
    # 这里改用 dict 行 + 列名匹配更稳妥：
    def _cell(row, fld):
        # row 是 header->value 的字典；再按 hint 找具体 key
        for h, v in row.items():
            if _match_header(h, None) == fld and (v or "").strip():
                return v
        return ""

    out, errors = [], []
    for i, row in enumerate(rows, start=2):  # 行号从 2 起（1=表头）
        title = _cell(row, "title").strip()
        url = _cell(row, "url").strip()
        if not title or not url:
            errors.append("第 %d 行：缺少「名称」或「链接」，已跳过" % i)
            continue
        pan = _norm_pan(_cell(row, "pan"), url)
        own = _is_own(_cell(row, "own"))
        out.append(Result({
            "title": title,
            "url": url,
            "password": _cell(row, "password").strip(),
            "pan": pan,
            "own": own,
            "source": "本地导入",
            "datetime": "",
            "size": "",
            "origin": "imported",
        }))

    # 覆盖写入
    p = _json_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([dict(r) for r in out], f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    log.info("导入本地资源：%d 条（own=%d），来自 %s",
             len(out), sum(1 for r in out if r.get("own")), path)
    return len(out), errors


def search_imported(keyword, pan=None):
    """按关键词 + 网盘类型过滤导入表，返回带 own 标志的 Result 列表。

    用于并入「搜索」命令结果。匹配：标题或链接包含关键词（不区分大小写）。"""
    kw = (keyword or "").strip().lower()
    items = load_imported()
    out = []
    for it in items:
        if pan and it.get("pan") != pan:
            continue
        if kw:
            title = (it.get("title") or "").lower()
            url = (it.get("url") or "").lower()
            if kw not in title and kw not in url:
                continue
        out.append(Result(dict(it)))
    return out
