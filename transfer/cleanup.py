# -*- coding: utf-8 -*-
"""
定时清理「转存到自己网盘的资源文件」（移植自网盘搜索站的 delete_search）。

网盘搜索站的逻辑：资源带 is_time=1 且超过保留期后，删 DB 记录 + 调各网盘
的 deletepdirFid($type, $filelist) 真删云盘文件。

机器人侧对应实现：
  - 每次转存成功（见 transfer/base.py:TransferService.run）都把
    {pan, account_id, file_ids, ts} 追加进 data/transfer_log.json；
  - 定时（schedule，每天指定时刻）或手动「立即清理」时，扫描日志里
    超过保留期的记录，用对应账号重建适配器，调 adapter.cleanup(file_ids)
    真删文件，成功后从日志移除。

只删「机器人本次运行以来转存记录」里的文件 —— 旧分享链接会因文件被删而失效，
与搜索站行为一致；不会碰用户网盘里其他自有文件。
"""

import os
import time
import json
import logging
import threading

log = logging.getLogger("cleanup")

_lock = threading.RLock()


def _log_path():
    from core import paths
    return os.path.join(paths.data_dir(), "transfer_log.json")


def load_log():
    p = _log_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_log(entries):
    p = _log_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except Exception as e:
        log.warning("保存转存记录失败: %s", e)


def record_transfer(pan, account_id, file_ids, title="", url=""):
    """追加一条转存记录。file_ids 为空则不记（没东西可清）。"""
    if not file_ids:
        return
    entry = {
        "pan": pan,
        "account_id": account_id,
        "file_ids": list(file_ids),
        "title": title or "",
        "url": url or "",
        "ts": int(time.time()),
        "cleaned": False,
        "last_error": "",
    }
    with _lock:
        entries = load_log()
        entries.append(entry)
        save_log(entries)
    log.info("记录转存：%s / 账号=%s / %d 个文件", pan, account_id, len(file_ids))


def cleanup_due(cfg, pool=None, save_fn=None, now=None):
    """删除超过保留期的转存文件。返回 (cleaned_count, summary_text)。

    cfg      ：完整配置（读 transfer.cleanup 节）
    pool     ：AccountPool（提供 save_fn）；与 save_fn 二选一
    save_fn  ：写回配置的回调（面板「立即清理」时用 CM.save_config）
    """
    tcfg = (cfg or {}).get("transfer", {}).get("cleanup", {})
    if not tcfg.get("enabled", False):
        return 0, "定时清理未启用（在「网盘账号 → 定时清理」里开启）"
    older = int(tcfg.get("older_than_days", 7) or 7)
    if older <= 0:                       # 0 或非法值回落默认，避免「永不过期」
        older = 7
    now = now if now is not None else int(time.time())
    cutoff = now - older * 86400

    entries = load_log()
    done, kept = 0, []
    for e in entries:
        if e.get("cleaned"):
            continue                        # 已清，丢弃
        if e.get("ts", 0) > cutoff:
            kept.append(e)                  # 未到期，保留
            continue
        ok = _delete_once(e, cfg, save_fn or (pool.save_fn if pool else None))
        if ok:
            done += 1                        # 已清，不进 kept（丢弃）
        else:
            kept.append(e)                   # 失败，保留待下次重试
    with _lock:
        save_log(kept)
    msg = "已清理 %d 个转存批次，剩余待清理/未到期 %d 条" % (done, len(kept))
    return done, msg


def _delete_once(entry, cfg, save_fn):
    pan = entry.get("pan")
    acc_id = entry.get("account_id")
    file_ids = entry.get("file_ids") or []
    if not pan or not file_ids:
        return True                         # 无内容可删，视为已清
    from transfer import base as TB
    cls = TB.get_adapter(pan)
    if cls is None:
        log.warning("清理：%s 无适配器，跳过", pan)
        return False
    acc = None
    for a in (cfg or {}).get("transfer", {}).get("accounts", []):
        if a.get("id") == acc_id:
            acc = a
            break
    if acc is None:
        log.warning("清理：账号 %s 不存在（可能已删除），无法清理 %s 文件",
                    acc_id, pan)
        return False
    try:
        adapter = cls(acc, cfg=cfg, save_fn=save_fn)
        adapter.cleanup(file_ids)
        log.info("清理：已删除 %s 的 %d 个文件", pan, len(file_ids))
        return True
    except Exception as ex:
        entry["last_error"] = str(ex)[:200]
        log.warning("清理失败 %s: %s", pan, ex)
        return False
