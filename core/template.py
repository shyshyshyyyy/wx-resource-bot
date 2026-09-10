# -*- coding: utf-8 -*-
"""
消息模板渲染。

原则：模板是给非程序员在面板里改的，所以：
- 占位符缺失时不抛异常，原样保留 {xxx}，方便用户看出自己写错了哪个
- 提供每个模板可用的占位符清单，面板直接展示，不用查文档
"""

import re
import logging

log = logging.getLogger("template")

_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# 面板上展示给用户看的占位符说明
PLACEHOLDER_HELP = {
    "search_hint":      [],
    "searching":        ["keyword", "pan_name", "pan_icon"],
    "no_result":        ["keyword", "pan_name"],
    "result_header":    ["keyword", "total", "page", "pages", "pan_name"],
    "result_item":      ["index", "index_emoji", "pan_icon", "title", "pan_name", "source", "size", "datetime", "dead_mark"],
    "result_footer":    ["page", "pages", "total"],
    "getting":          ["title", "pan_name", "pan_icon"],
    "success":          ["title", "share_url", "password_line", "pan_name", "pan_icon", "expire"],
    "password_line":    ["password"],
    "transfer_failed":  ["title", "reason", "origin_url", "pan_name", "pan_icon"],
    "dead_link":        ["title", "pan_name", "pan_icon"],
    "dead_link_end":    ["keyword", "pan_name"],
    "account_invalid":  ["pan_name", "reason", "pan_icon"],
    "transfer_retry":   ["reason", "pan_icon"],
    "expired":          [],
    "invalid_index":    ["max"],
    "no_account":       ["pan_name", "pan_icon"],
    "unlicensed":       [],
}

# 每个网盘类型配一个不同颜色的圆球，放在序号前，一眼区分资源来自哪个网盘。
# key 与 config_manager.ACCOUNT_TEMPLATE.pan / search.default_types 对齐。
PAN_ICON = {
    "quark":   "🟣",   # 夸克
    "baidu":   "🔵",   # 百度
    "aliyun":  "🟠",   # 阿里云
    "uc":      "🟢",   # UC
    "xunlei":  "🟡",   # 迅雷
    "guangya": "🔴",   # 光鸭
    "mobile":  "⚪",   # 移动
}

# 彩色数字标签（1~10 用 emoji 数字，更大的回落普通数字）
_INDEX_EMOJI = {
    1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
    6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟",
}


def pan_icon(pan):
    """返回某网盘类型的彩色圆球 emoji；未知类型给个中性灰球。"""
    return PAN_ICON.get(pan, "⚪")


def index_emoji(i):
    """返回彩色数字标签；超过 10 回落普通数字，避免 KeyError。"""
    try:
        return _INDEX_EMOJI.get(int(i), str(i))
    except (TypeError, ValueError):
        return str(i)

PLACEHOLDER_DESC = {
    "keyword": "用户搜索的关键词",
    "pan_name": "网盘中文名，如「夸克」",
    "total": "结果总条数",
    "page": "当前页码",
    "pages": "总页数",
    "index": "本页内的序号，用户回这个数字",
    "title": "资源标题",
    "source": "来源频道或插件",
    "size": "资源大小，取不到时为空",
    "datetime": "资源发布时间",
    "dead_mark": "已失效标记（仅在该条源链接被检出失效时显示🔴，正常为空）",
    "share_url": "转存后生成的分享链接",
    "password_line": "提取码整行，没有提取码时自动为空",
    "password": "提取码",
    "expire": "分享有效期描述",
    "reason": "失败原因",
    "origin_url": "搜索到的原始链接",
    "max": "当前页最大序号",
}


class SafeDict(dict):
    def __missing__(self, key):
        return "{%s}" % key


def render(template_str, **kwargs):
    if not template_str:
        return ""
    try:
        text = template_str.format_map(SafeDict(**kwargs))
    except Exception as e:
        log.warning("模板渲染失败，返回原文: %s", e)
        return template_str
    # 清掉因为可选字段为空而留下的空行（比如没有提取码时的 password_line）
    lines = [ln.rstrip() for ln in text.split("\n")]
    out, blank = [], False
    for ln in lines:
        if not ln.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    return "\n".join(out).strip()


def validate(name, template_str):
    """检查模板里有没有写错的占位符。返回 (ok, [未知占位符])。"""
    allowed = set(PLACEHOLDER_HELP.get(name, []))
    used = set(_PLACEHOLDER.findall(template_str or ""))
    unknown = sorted(used - allowed)
    return (not unknown), unknown


def help_for(name):
    return [{"key": k, "desc": PLACEHOLDER_DESC.get(k, "")}
            for k in PLACEHOLDER_HELP.get(name, [])]
