# -*- coding: utf-8 -*-
"""配置读写。config.json 放在 exe 同级的 data/ 目录，升级时保留。"""

import os
import sys
import json
import copy
import threading

_lock = threading.RLock()
_cache = None

DEFAULT_CONFIG = {
    "license": "",

    "panel": {
        "host": "127.0.0.1",
        "port": 8765,
        "username": "admin",
        "password": "admin123",          # 首次登录后强制修改
        "auto_open_browser": True,
    },

    "wechat": {
        "core": "auto",                   # auto | free | plus
        "nickname": "",                   # 多开时指定实例，仅 plus 版有效
        "listen_private": True,
        "listen_groups": [],              # 要监听的群名
        "whitelist": [],                  # 私聊白名单，空=全部
        "blacklist": [],
        "reply_interval_ms": 1200,        # 两条消息之间的最小间隔，防封
        # 群聊多人同时搜索时，回复要不要 @ 发起人（Plus 内核是真 @，
        # 免费内核自动降级为正文里写 @昵称）
        "group_reply_at": True,
    },

    "search": {
        # pansou 官方没有发布 Windows 二进制，所以默认走远程接口，开箱即用。
        # 想用本地盘搜，见 README 的「本地盘搜」一节，编译出 bin/pansou.exe 后
        # 把 mode 改成 local 或 both 即可。
        "mode": "remote",                 # local | remote | both
        "local": {
            "enabled": False,
            "exe": "bin/pansou.exe",
            "port": 8888,
            "channels": "tgsearchers3",
            "extra_env": {},
            "autostart": True,
        },
        "remote": {
            "enabled": True,
            # 默认填的是 pansou 作者的公开演示站，能直接用但不稳定也不该长期蹭。
            # 换成你自己那台 pansou 的地址。
            "base_url": "http://38.92.9.77:8888",
            "token": "",
            "timeout": 20,
        },
        "page_size": 10,
        "max_results": 60,
        # 广告词：搜索结果里「标题」含这些词的资源会被剔除（去广告/引流）。
        # 面板里多行填写，逗号或换行分隔；为空表示不过滤。
        "ad_words": "",
        "session_ttl": 300,               # 选号上下文超时（秒）
        # 用户选定的 7 种网盘。与盘搜接口 cloud_types 对齐；
        # 转存引擎有对应适配器才能真正转存，否则回落原链（见 transfer.fallback_original_link）
        "default_types": ["quark", "baidu", "uc", "aliyun", "xunlei", "guangya", "mobile"],
        # 指令必须带网盘类型：开启后，「搜索 关键词」不带类型会提示先选类型，
        # 而不是返回混合结果（含未启用的类型）。默认关，保留旧行为。
        "require_pan_type": False,
    },

    "transfer": {
        "enabled": True,
        "retry": 2,
        "fallback_original_link": True,   # 转存失败时回落到原始链接
        "share_expire_days": 0,           # 0 = 永久
        # 选号取链时发现源链接已失效（死链）时，是否自动跳到下一条未失效资源。
        # 关掉则只提示"该条已失效"，由用户自己翻页/重选。默认开启，体验更顺。
        "auto_skip_dead": True,
        "accounts": [],                   # 见下方 ACCOUNT_TEMPLATE
        # 定时清理转存到自己网盘的资源文件（移植自网盘搜索站的 delete_search）。
        # 只删「机器人本次运行以来转存记录」里的文件；保留期与时刻均可自定义。
        "cleanup": {
            "enabled": False,             # 默认关，用户在面板开启
            "time": "03:00",               # 每天执行时刻 HH:MM
            "older_than_days": 7,          # 保留天数，超过即删
        },
    },

    # 本地表格导入的资源（面板导入 xlsx/csv 后写入 data/imported.json）。
    "imported": {
        "enabled": True,
        "path": "",                       # 最近一次导入的表格路径（仅展示用）
    },

    "templates": {
        # search_hint 默认留空=不发送。仅在用户主动填入用法说明时才展示，
        # 避免"搜索没带关键词"时刷一长串用法（之前就是被这条默认的文案坑了）。
        "search_hint": "",
        "searching": "🔍 正在为您搜索「{keyword}」…",
        "no_result": "没有找到「{keyword}」相关的资源，换个关键词试试～",
        # 开启「指令必须指定网盘类型」后，未带类型的搜索指令会收到这条提示
        "require_pan_hint": "请先指定网盘类型再搜索，例如：\n搜索 {keyword} 夸克\n搜索 {keyword} 百度",
        "result_header": "🔍 为您找到 {total} 条「{keyword}」资源（第 {page}/{pages} 页）",
        # 彩球(pan_icon) + 彩色序号(index_emoji) + 标题；不再展示 pansou 插件(source)
        "result_item": "{pan_icon} {index_emoji}. {dead_mark}{title} 〔{pan_name}〕",
        "result_footer": "━━━━━━━━━━\n回复序号即可获取，例如：1\n回复「下一页」查看更多",
        # 面向终端用户：用"获取资源/保存到您的网盘"替代"转存"
        "getting": "{pan_icon} ⏳ 正在为您获取「{title}」…",
        # 取链成功：明确告诉用户这是「他的」资源链接、要尽快转存（5 分钟失效）
        "success": "已为您获取到【{pan_name}】资源链接\n{share_url}\n{password_line}\n请及时转存，5分钟失效。",
        "password_line": "🔑 提取码：{password}",
        "transfer_failed": "⚠️ 资源获取失败（{reason}），以下是原始链接：\n{origin_url}",
        # 资源链接失效检测：源链接死了（被取消/封禁/清空），与买家自己的账号无关
        "dead_link": "⚠️「{title}」（{pan_name}）的源链接已失效（分享被取消或封禁），属上游资源问题，与您的网盘账号无关。",
        "dead_link_end": "已连续尝试多条资源均提示源链接失效，建议换个关键词，或回复「下一页」查看更多。",
        # 买家自己的账号出问题（Cookie / refresh_token 失效），明确指引去面板更新
        "account_invalid": "⚠️ 您的「{pan_name}」账号状态异常：{reason}。请在面板更新该网盘的 Cookie / refresh_token 后重试。",
        # 临时网络/风控错误，稍后重试即可
        "transfer_retry": "⚠️ 资源获取失败（临时错误：{reason}），请稍后重试或换其他资源。",
        "expired": "上次的搜索结果已过期，请重新搜索。",
        "invalid_index": "序号超出范围，请回复 1-{max} 之间的数字。",
        "no_account": "「{pan_name}」尚未配置可用账号，请联系管理员。",
        "unlicensed": "程序未激活，请联系管理员。",
        # 本地导入表里标记为「自己的资源」的项：获取时跳过转存，直接给原链
        "own_resource": "✅「{title}」是你的自有资源，无需转存，原链接如下：\n{url}",
    },

    "advanced": {
        "log_level": "INFO",
        "log_keep_days": 7,
    },
}

ACCOUNT_TEMPLATE = {
    "id": "",
    "pan": "quark",          # quark | baidu | uc | aliyun | xunlei | guangya | mobile
    "name": "账号1",
    "enabled": True,
    "cookie": "",           # 夸克/UC/百度填 Cookie；迅雷/阿里填 refresh_token
                            # 移动云盘填 Authorization Basic 令牌或 Cookie
    "phone": "",            # 仅移动云盘需要，可留空
    "banned_words": "",     # 广告关键词，逗号分隔，转存后命中即删
    "save_dir_id": "",       # 转存目标文件夹 ID
    "save_dir_name": "",     # 显示用
    "temp_dir_id": "",       # 临时转存文件夹 ID（用完即清）
    "temp_dir_name": "",
    "status": "unknown",     # ok | invalid | unknown
    "last_check": 0,
}

# 配置格式版本。v2：去掉每日转存上限，并修复被"未 load 就 collect"写坏的数值
CONFIG_VERSION = 2


def app_dir():
    """程序所在目录。统一走 core.paths，保证打包后与面板一致。"""
    try:
        from core import paths
        return paths.app_dir()
    except Exception:
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))
        return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    try:
        from core import paths
        return paths.data_dir()
    except Exception:
        d = os.path.join(app_dir(), "data")
        os.makedirs(d, exist_ok=True)
        return d


def get_config_path():
    """网盘侧配置：data/config/netdisk.json
    （与底座 config.json 分开，避免 data/config.json 与 data/config/ 混淆）"""
    from core import paths
    return os.path.join(paths.config_dir(), "netdisk.json")


def _deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _repair(cfg):
    """一次性修复历史遗留问题（只在配置版本低于 CONFIG_VERSION 时跑一次）。

    背景：早期版本里，面板的自定义页面（盘搜接口 / 网盘账号…）在启动时
    没有调用 load()，控件停在出厂默认值（SpinBox=最小值、CheckBox=未勾选）。
    用户一按「保存配置」或「启动机器人」，collect() 就把这些默认值写回磁盘，
    把真配置冲掉 —— 表现为"盘搜接口重启后就没了"。

    判断依据：被冲掉的文件里，所有数值恰好都等于控件的最小值
    （port=1 / page_size=1 / timeout=3 / default_types=[] 等）。
    """
    if int(cfg.get("_v", 1) or 1) >= CONFIG_VERSION:
        return cfg, False

    changed = False
    d = DEFAULT_CONFIG
    s = cfg.setdefault("search", {})

    if not s.get("default_types"):
        s["default_types"] = list(d["search"]["default_types"])
        changed = True
    for key, floor, dflt in (("page_size", 1, 10),
                             ("max_results", 10, 60),
                             ("session_ttl", 30, 300)):
        try:
            val = int(s.get(key, dflt))
        except Exception:
            val = dflt
        if val <= floor:
            s[key] = dflt
            changed = True

    loc = s.setdefault("local", {})
    if not (loc.get("exe") or "").strip():
        loc["exe"] = d["search"]["local"]["exe"]
        changed = True
    if int(loc.get("port", 0) or 0) <= 1:
        loc["port"] = d["search"]["local"]["port"]
        changed = True
    if not (loc.get("channels") or "").strip():
        loc["channels"] = d["search"]["local"]["channels"]
        changed = True

    rem = s.setdefault("remote", {})
    if int(rem.get("timeout", 0) or 0) <= 3:
        rem["timeout"] = d["search"]["remote"]["timeout"]
        changed = True

    # 自动转存开关：控件默认未勾选，同样会被写成 False
    t = cfg.setdefault("transfer", {})
    if t.get("enabled") is False:
        t["enabled"] = True
        changed = True

    # 去掉每日转存上限
    for acc in t.get("accounts", []) or []:
        for k in ("daily_limit", "used_today", "last_reset"):
            if k in acc:
                acc.pop(k, None)
                changed = True
        if acc.get("status") == "limited":
            acc["status"] = "unknown"
            changed = True

    cfg["_v"] = CONFIG_VERSION
    return cfg, True


# ---------------------------------------------------------------------------
# 模板自动升级：把落盘配置里残留的旧版模板升级为当前默认，
# 但保留用户已经自定义过的模板（不误删用户改动）。
#
# 背景：模板在 DEFAULT_CONFIG 里，但用户一旦在面板保存过配置，模板就被持久化
# 到 netdisk.json。之后 bot 读的是落盘旧模板，改 DEFAULT_CONFIG 不生效——
# 这就是"明明改了模板、跑出来还是旧措辞/没彩色"的根因。
# ---------------------------------------------------------------------------
# 上一版（含"转存"黑话、无彩色占位符）的模板默认串快照。
# 升级判定：落盘模板 == 这些旧值（或含"转存"）即视为"用户没改过、只是过期"，
# 回落新默认；否则视为用户已自定义，保留。这样既不误删用户改动，又能把陈旧
# 模板刷成新版。若未来再改模板，只需把 CURRENT_TPL_VER +1 并在下方补快照。
_OLD_TEMPLATE_DEFAULTS = {
    "searching": "正在搜索「{keyword}」，稍等…",
    "no_result": "没有找到「{keyword}」的资源，换个关键词试试。",
    "result_header": "「{keyword}」找到 {total} 条（第 {page}/{pages} 页）",
    "result_item": "{index}. {title}\n   {pan_name} · {source}",
    "result_footer": "回复数字获取资源\n回复「下一页」翻页",
    "getting": "正在为你转存「{title}」…",
    "success": "{title}\n{share_url}\n{password_line}",
    "password_line": "提取码：{password}",
    "transfer_failed": "转存失败（{reason}），这是原始链接：\n{origin_url}",
    "expired": "上次的搜索结果已过期，请重新搜索。",
    "invalid_index": "序号超出范围，请回复 1-{max} 之间的数字。",
    "no_account": "「{pan_name}」还没有配置可用账号，请联系管理员。",
    "unlicensed": "程序未激活，请联系管理员。",
}
_OLD_TEMPLATE_VALUES = set(_OLD_TEMPLATE_DEFAULTS.values()) | {
    # v2 时期曾用过的 success 措辞，同样视为"旧版可升级"，让落盘配置自动刷成新版
    "✅ 已为您保存到{pan_name}：\n{share_url}\n{password_line}",
}
CURRENT_TPL_VER = 3


def _upgrade_templates(cfg):
    """把 cfg["templates"] 里残留的旧版模板升级为当前默认。
    返回被升级的键列表（含哨兵 "_tpl_ver" 表示仅版本号变更）；空 = 无需升级。"""
    tpls = cfg.get("templates")
    if not isinstance(tpls, dict):
        tpls = cfg["templates"] = {}
    defaults = DEFAULT_CONFIG.get("templates", {})
    prev_ver = int(cfg.get("_tpl_ver", 0) or 0)
    if prev_ver >= CURRENT_TPL_VER:
        return []
    upgraded = []
    for key, new_val in defaults.items():
        old_val = tpls.get(key)
        if old_val is None or old_val in _OLD_TEMPLATE_VALUES or ("转存" in str(old_val)):
            tpls[key] = new_val
            upgraded.append(key)
    cfg["_tpl_ver"] = CURRENT_TPL_VER
    # 即便模板无变化，也要把版本号落盘，避免每次启动都重跑这段
    if not upgraded:
        upgraded = ["_tpl_ver"]
    return upgraded


def load_config(force=False):
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        raw = {}
        path = get_config_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                # 配置损坏时备份一份再用默认值，别让程序起不来
                try:
                    os.replace(path, path + ".broken")
                except Exception:
                    pass
                raw = {}
        cfg = _deep_merge(DEFAULT_CONFIG, raw)
        cfg, fixed = _repair(cfg)
        upg = _upgrade_templates(cfg)   # 落盘旧模板自动升级为新版（保留用户已自定义的新版）
        _cache = cfg
        if fixed or upg:
            save_config(cfg)      # 修完立刻落盘，避免每次启动重复判定
        return _cache


def save_config(config=None):
    global _cache
    with _lock:
        cfg = config if config is not None else _cache
        if cfg is None:
            return False
        _cache = cfg
        path = get_config_path()
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return True
        except Exception:
            return False


def update(section, values):
    """局部更新：update("search", {...})"""
    cfg = load_config()
    if section:
        cfg[section] = _deep_merge(cfg.get(section, {}), values)
    else:
        cfg.update(values)
    save_config(cfg)
    return cfg
