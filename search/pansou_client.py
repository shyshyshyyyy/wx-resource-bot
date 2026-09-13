# -*- coding: utf-8 -*-
"""
pansou 搜索客户端。支持本地实例、远程接口，或两者合并去重。

pansou 的 /api/search 返回 merged_by_type：按网盘类型分组的链接列表。
这里统一归一化成扁平的 Result 列表，方便分页和选号。
"""

import re
import logging
import hashlib
import concurrent.futures as futures

import requests

log = logging.getLogger("pansou")

# pansou 类型键 → 我们内部使用的键（基本一致，个别做映射）
TYPE_MAP = {
    "quark": "quark", "uc": "uc", "xunlei": "xunlei", "baidu": "baidu",
    "aliyun": "aliyun", "tianyi": "tianyi", "mobile": "mobile",
    "115": "115", "123": "123", "pikpak": "pikpak",
    "magnet": "magnet", "ed2k": "ed2k", "others": "others",
    # 光鸭云盘上线较晚，pansou 可能还没有独立类型，
    # 先按链接域名从 others 里捞出来（见 _sniff_type）
    "guangya": "guangya", "guangyapan": "guangya",
}

_DOMAIN_HINTS = [
    (r"guangyapan\.com|gyp\.cn", "guangya"),
    (r"pan\.quark\.cn", "quark"),
    (r"drive\.uc\.cn", "uc"),
    (r"pan\.xunlei\.com", "xunlei"),
    (r"pan\.baidu\.com|yun\.baidu\.com", "baidu"),
    (r"aliyundrive\.com|alipan\.com", "aliyun"),
    (r"cloud\.189\.cn", "tianyi"),
    (r"caiyun\.139\.com", "mobile"),
    (r"115\.com", "115"),
    (r"123pan\.com|123684\.com", "123"),
    (r"mypikpak\.com", "pikpak"),
]

# 永不展示的网盘类型：磁力(magnet)/电驴(ed2k) 含大量不健康内容，
# 且不属于网盘，无论是否显式勾选都应从搜索结果中剔除（双层保险：
# 即使误配进 default_types，这里也拦下）。
BLOCKED_PAN_TYPES = frozenset({"magnet", "ed2k"})


def _sniff_type(url, declared=""):
    """优先看链接域名，取不到再用 pansou 声明的类型。"""
    u = (url or "").lower()
    for pattern, t in _DOMAIN_HINTS:
        if re.search(pattern, u):
            return t
    return TYPE_MAP.get((declared or "").lower(), declared or "others")


class Result(dict):
    """一条资源。用 dict 便于直接丢进模板渲染。"""

    @property
    def uid(self):
        raw = "%s|%s" % (self.get("url", ""), self.get("password", ""))
        return hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()


def _normalize(payload, origin):
    """把 pansou 的响应拍平成 Result 列表。"""
    out = []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}

    merged = data.get("merged_by_type") or {}
    if isinstance(merged, dict):
        for ptype, links in merged.items():
            if not isinstance(links, list):
                continue
            for it in links:
                if not isinstance(it, dict):
                    continue
                url = it.get("url") or it.get("link") or ""
                if not url:
                    continue
                out.append(Result({
                    "title": (it.get("note") or it.get("title") or "").strip() or "未命名资源",
                    "url": url,
                    "password": (it.get("password") or it.get("pwd") or "").strip(),
                    "pan": _sniff_type(url, ptype),
                    "source": it.get("source") or it.get("channel") or origin,
                    "datetime": it.get("datetime") or it.get("time") or "",
                    "size": it.get("size") or "",
                    "origin": origin,
                }))

    # 有些版本只返回 results
    results = data.get("results")
    if isinstance(results, list):
        for it in results:
            if not isinstance(it, dict):
                continue
            for link in (it.get("links") or []):
                url = link.get("url") or ""
                if not url:
                    continue
                out.append(Result({
                    "title": (it.get("title") or it.get("content") or "").strip()[:80] or "未命名资源",
                    "url": url,
                    "password": (link.get("password") or "").strip(),
                    "pan": _sniff_type(url, link.get("type") or ""),
                    "source": it.get("channel") or origin,
                    "datetime": it.get("datetime") or "",
                    "size": "",
                    "origin": origin,
                }))
    return out


def _dedup(items):
    seen, out = set(), []
    for it in items:
        k = it.uid
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def norm_base(url: str) -> str:
    """把用户填的地址归一化成"根地址"，去掉已经带上的 /api/search。

    面板里有人习惯直接填完整接口 `http://ip:8888/api/search`，
    而 _query 自己还会再拼一次，结果变成 `/api/search/api/search`。
    这里统一剥掉，两边怎么填都能跑。
    """
    u = (url or "").strip().rstrip("/")
    low = u.lower()
    for suf in ("/api/search", "/search"):
        if low.endswith(suf):
            u = u[: -len(suf)].rstrip("/")
            break
    return u


class PansouClient:
    def __init__(self, config, local_manager=None):
        self.cfg = config
        self.local = local_manager

    # ---------- 单个来源 ----------
    def _query(self, base_url, keyword, token="", timeout=20, refresh=False):
        if not base_url:
            return []
        root = norm_base(base_url)
        if not root:
            return []
        url = root + "/api/search"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer %s" % token
        body = {"kw": keyword, "res": "merge", "src": "all"}
        if refresh:
            body["refresh"] = True
        try:
            r = requests.post(url, json=body, headers=headers, timeout=timeout)
            if r.status_code == 405:  # 个别部署只开了 GET
                r = requests.get(url, params={"kw": keyword, "res": "merge"},
                                 headers=headers, timeout=timeout)
            r.raise_for_status()
            return _normalize(r.json(), root)
        except Exception as e:
            log.warning("搜索失败 %s: %s", base_url, e)
            return []

    # ---------- 对外 ----------
    def search(self, keyword, pan=None, refresh=False):
        """
        返回 (results, errors)。

        - pan 不为空：只保留该类型（尊重用户的显式指定）；
        - pan 为空（指令没带网盘类型）：只保留「面板启用的网盘类型」
          (search.default_types)，并强制剔除 magnet / ed2k 等非网盘类型。
          这样就保证「面板只勾了夸克/百度」时，结果里绝不会冒出磁力链接——
          之前这里只排序不裁剪，未启用的类型（尤其磁力）会被一并返回。
        """
        s = self.cfg.get("search", {})
        mode = s.get("mode", "local")
        jobs, errors = [], []

        if mode in ("local", "both") and s.get("local", {}).get("enabled"):
            if self.local and self.local.running():
                jobs.append(("本地", self.local.base_url, "", 20))
            else:
                errors.append("本地盘搜未运行")

        if mode in ("remote", "both") and s.get("remote", {}).get("enabled"):
            rc = s["remote"]
            if rc.get("base_url"):
                jobs.append(("远程", rc["base_url"], rc.get("token", ""),
                             int(rc.get("timeout", 20))))
            else:
                errors.append("远程盘搜未配置地址")

        if not jobs:
            return [], errors or ["没有可用的搜索来源"]

        items = []
        with futures.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futs = {ex.submit(self._query, url, keyword, token, timeout, refresh): name
                    for name, url, token, timeout in jobs}
            for fu in futures.as_completed(futs):
                try:
                    items.extend(fu.result())
                except Exception as e:
                    errors.append("%s：%s" % (futs[fu], e))

        items = _dedup(items)

        if pan:
            items = [i for i in items if i.get("pan") == pan]
        else:
            # 指令未带网盘类型：只保留面板启用的类型，剔除磁力/电驴等。
            enabled = set(s.get("default_types") or [])
            blocked = BLOCKED_PAN_TYPES
            if enabled:
                items = [i for i in items
                         if i.get("pan") in enabled and i.get("pan") not in blocked]
            else:
                # default_types 为空（异常/防御）：至少剔除明确不要的非网盘类型
                items = [i for i in items if i.get("pan") not in blocked]
            # 按启用顺序排序（未命中的已在上一步过滤掉）
            order = s.get("default_types") or []
            rank = {t: i for i, t in enumerate(order)}
            items.sort(key=lambda i: rank.get(i.get("pan"), 99))

        limit = int(s.get("max_results", 60))
        return items[:limit], errors

    def test(self, base_url, token=""):
        """面板「测试连接」用。"""
        items = self._query(base_url, "测试", token, timeout=12)
        return {"ok": True, "count": len(items)} if items is not None else {"ok": False}
