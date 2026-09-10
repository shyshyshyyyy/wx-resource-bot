# -*- coding: utf-8 -*-
"""
面板页面声明式定义（Schema）

设计原则：
1. 每个字段的 key 与 wxbot_core.WXBotConfig 使用的 config.json 键名**完全一致**，
   渲染器直接读写 config 字典，杜绝"面板有控件但配置没落地 / 配置有字段但面板没入口"的漏项。
2. kind="form"   -> 由通用渲染器根据 Field 自动生成控件
   kind="custom" -> 由 pages/ 下专门的 QWidget 实现（复杂表格、文件管理、状态面板等）
3. 来源：底座 SiverWXbot_plus dashboard.html 18 个页面 + wxbot_core.WXBotConfig 全字段。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass
class F:
    """单个配置字段定义"""
    key: str                       # config.json 中的键名
    label: str                     # 界面显示名
    type: str = "text"             # text|int|switch|select|area|list|dict|time
    default: Any = None
    tip: str = ""
    options: Optional[List[str]] = None
    placeholder: str = ""
    min_value: int = 0
    max_value: int = 10 ** 9
    rows: int = 4                  # area 类型行数
    secret: bool = False           # 密码框
    span: int = 1                  # 栅格占用列数（1=半行，2=整行）


@dataclass
class Group:
    """页面内的一个分组卡片"""
    title: str
    fields: List[F] = field(default_factory=list)
    desc: str = ""


@dataclass
class Page:
    """侧边栏的一个功能页"""
    id: str
    title: str
    section: str = ""              # 侧边栏分组名
    kind: str = "form"             # form | custom
    groups: List[Group] = field(default_factory=list)
    desc: str = ""


# ============================================================
# 页面清单（顺序 = 侧边栏顺序）
# ============================================================

PAGES: List[Page] = [

    # ---------------- 运行 ----------------
    Page(id="status", title="状态面板", section="运行", kind="custom",
         desc="机器人运行状态、微信内核、监听统计"),
    Page(id="license", title="授权激活", section="运行", kind="custom",
         desc="软件授权码激活与机器码"),
    Page(id="siver_panel", title="远程访问服务", section="运行", kind="form", desc="",
         groups=[
             Group("远程面板", [
                 F("siver_panel_enabled", "启用远程访问服务", "switch", False,
                   tip="开启后可通过 SiverPanel 远程管理本机机器人"),
                 F("siver_panel_activation_code", "远程服务激活码", "text", "",
                   secret=True, span=2, tip="面板激活码"),
                 F("siver_panel_base_url", "服务地址", "text", "https://panel.siver.top",
                   span=2),
                 F("siver_panel_ws_url", "WebSocket 地址", "text",
                   "wss://panel.siver.top/relay/ws", span=2),
             ]),
         ]),

    # ---------------- AI ----------------
    Page(id="api", title="模型配置", section="AI 能力", kind="custom",
         desc="多 AI 接口配置（OpenAI 兼容 / Dify / Coze / Dus）"),
    Page(id="prompt", title="Prompt", section="AI 能力", kind="custom",
         desc="多提示词文件管理"),
    Page(id="admin", title="管理员", section="AI 能力", kind="form", groups=[
        Group("管理员账号", [
            F("admin", "管理员微信昵称", "text", "文件传输助手", span=2,
              tip="接收管理命令的微信账号（如：文件传输助手）"),
        ], desc="该账号发送的命令会被识别为管理指令"),
    ]),

    # ---------------- 监听 ----------------
    Page(id="listen", title="私聊监听", section="监听范围", kind="custom",
         desc="监听模式、白/黑名单、按人绑定 Prompt 与接口"),
    Page(id="group", title="群组管理", section="监听范围", kind="custom",
         desc="监听群列表、群回复规则、群专属接口与 Prompt"),
    Page(id="friend", title="好友管理", section="监听范围", kind="form", groups=[
        Group("新好友自动处理", [
            F("new_friend_switch", "自动通过新好友", "switch", False),
            F("new_friend_reply_switch", "通过后自动打招呼", "switch", False),
            F("new_friend_check_min", "检查间隔最小（秒）", "int", 60, min_value=60, max_value=3600),
            F("new_friend_check_max", "检查间隔最大（秒）", "int", 300, min_value=60, max_value=3600),
        ]),
        Group("打招呼消息", [
            F("new_friend_msg", "消息列表（随机一条）", "list", [], span=2,
              tip="通过好友后随机发送其中一条"),
        ]),
        Group("自动备注", [
            F("new_friend_remark_use_nickname", "使用昵称作为备注", "switch", True),
            F("new_friend_remark_prefix", "备注前缀", "text", ""),
            F("new_friend_remark_suffix", "备注后缀", "text", "_机器人备注"),
            F("new_friend_remark_prefix_timestamp", "前缀加时间戳", "switch", False),
            F("new_friend_remark_suffix_timestamp", "后缀加时间戳", "switch", False),
            F("new_friend_tags", "自动打标签", "list", [], span=2),
        ]),
    ]),

    # ---------------- 自动回复 ----------------
    Page(id="keyword", title="关键词回复", section="自动回复", kind="custom",
         desc="私聊/群聊关键词匹配回复规则"),
    Page(id="forward", title="自定义转发", section="自动回复", kind="custom",
         desc="把指定会话的消息转发到目标会话"),
    Page(id="schedule", title="定时消息", section="自动回复", kind="custom",
         desc="定时/随机 群发消息任务"),
    Page(id="moments", title="朋友圈", section="自动回复", kind="custom",
         desc="定时发朋友圈、随机朋友圈、随机点赞"),
    Page(id="startstop", title="定时启停", section="自动回复", kind="form", groups=[
        Group("每日自动启停", [
            F("everyday_start_stop_bot_switch", "启用定时启停", "switch", False),
            F("everyday_start_bot_time", "每日启动时间", "time", "08:00"),
            F("everyday_stop_bot_time", "每日停止时间", "time", "23:00"),
        ], desc="到点自动启动 / 停止机器人"),
    ]),

    # ---------------- 数据 ----------------
    Page(id="memory", title="记忆管理", section="数据", kind="custom",
         desc="对话记忆浏览与清理"),
    Page(id="backup", title="数据备份", section="数据", kind="custom",
         desc="配置与记忆数据备份恢复"),

    # ---------------- 网盘资源搜索（新增） ----------------
    Page(id="nd_search", title="盘搜接口", section="网盘资源搜索", kind="custom",
         desc="搜索数据源接口与启用的网盘类型"),
    Page(id="nd_account", title="网盘账号", section="网盘资源搜索", kind="custom",
         desc="7 种网盘账号 Cookie 与转存目录管理"),
    Page(id="nd_template", title="消息模板", section="网盘资源搜索", kind="custom",
         desc="触发指令与各环节回复模板"),
    Page(id="nd_convert", title="分享转链", section="网盘资源搜索", kind="custom",
         desc="分享文案转存为自己的链接并群发"),

    # ---------------- 系统 ----------------
    Page(id="other", title="其他配置", section="系统", kind="form", groups=[
        Group("对话记忆", [
            F("memory_switch", "启用对话记忆", "switch", True),
            F("memory_max_count", "单窗口最多存储条数", "int", 3000, min_value=1, max_value=5000),
            F("memory_context_count", "AI 请求带入条数", "int", 1000, min_value=1, max_value=5000),
        ], desc="记忆数据保存在 data/memory/，可在「记忆管理」中查看与清理"),
        Group("发送行为", [
            F("reply_delay_switch", "模拟人工延迟", "switch", True),
            F("reply_delay_min", "最小延迟（秒）", "int", 1, min_value=1, max_value=600),
            F("reply_delay_max", "最大延迟（秒）", "int", 5, min_value=1, max_value=600),
            F("clean_ai_reply_switch", "清洗 AI 回复格式", "switch", True),
        ]),
        Group("接口异常兜底", [
            F("api_error_reply", "接口失败时的回复", "text", "在忙，我稍后回复您", span=2),
            F("api_error_reply_once", "每个会话只回复一次", "switch", False),
        ]),
        Group("图片识别", [
            F("chat_image_recognition_switch", "私聊图片识别", "switch", False),
            F("chat_image_recognition_api", "私聊识图接口序号", "int", 0, min_value=0, max_value=99),
            F("group_image_recognition_switch", "群聊图片识别", "switch", False),
            F("group_image_recognition_api", "群聊识图接口序号", "int", 0, min_value=0, max_value=99),
        ], desc="需要接口模型支持视觉能力"),
        Group("回复轮数限制", [
            F("chat_max_round_switch", "启用轮数限制", "switch", False),
            F("chat_max_round_default", "默认最大轮数", "int", 99, min_value=1, max_value=99999),
            F("chat_max_round_reset_days", "重置周期（天，0=不重置）", "int", 0, min_value=0, max_value=365),
            F("chat_max_round_reply", "超限时的回复", "text", "", span=2),
            F("chat_max_round_reply_once", "超限只回复一次", "switch", False),
        ]),
        Group("长消息拆分", [
            F("chat_split_reply_switch", "私聊拆分多条发送", "switch", False),
            F("chat_split_max_chars", "私聊单条字数", "int", 100, min_value=1, max_value=2000),
            F("chat_split_max_count", "私聊最多条数", "int", 4, min_value=1, max_value=20),
            F("group_split_reply_switch", "群聊拆分多条发送", "switch", False),
            F("group_split_max_chars", "群聊单条字数", "int", 100, min_value=1, max_value=2000),
            F("group_split_max_count", "群聊最多条数", "int", 4, min_value=1, max_value=20),
        ]),
    ]),
    Page(id="account", title="账号密码", section="系统", kind="custom",
         desc="面板登录账号与密码"),
    Page(id="email", title="报错邮箱", section="系统", kind="form", groups=[
        Group("SMTP 配置", [
            F("email_sender", "发件邮箱", "text", "", span=2),
            F("email_password", "授权码 / 密码", "text", "", secret=True, span=2),
            F("email_smtp_host", "SMTP 服务器", "text", "smtp.qq.com"),
            F("email_smtp_port", "SMTP 端口", "int", 465, min_value=1, max_value=65535),
            F("email_receiver", "收件邮箱", "text", "", span=2),
            F("email_enable", "启用邮件报错", "switch", False),
        ], desc="机器人运行异常时发送邮件通知"),
    ]),
    Page(id="webhook", title="Webhook 通知", section="系统", kind="form", groups=[
        Group("Webhook", [
            F("webhook_url", "回调地址", "text", "", span=2,
              placeholder="https://your.server/hook"),
            F("webhook_enable", "启用 Webhook", "switch", False),
        ], desc="机器人异常 / 事件时推送到指定地址"),
    ]),
    Page(id="about", title="关于", section="系统", kind="custom",
         desc="版本、内核、数据位置与诊断信息"),
]


def pages_by_section():
    """按 section 分组返回，保持定义顺序"""
    out: Dict[str, List[Page]] = {}
    for p in PAGES:
        out.setdefault(p.section or "其他", []).append(p)
    return out


def get_page(pid: str) -> Optional[Page]:
    for p in PAGES:
        if p.id == pid:
            return p
    return None


def all_form_fields() -> List[F]:
    """收集所有 form 页面用到的字段（用于自检与默认值填充）"""
    fields: List[F] = []
    for p in PAGES:
        for g in p.groups:
            fields.extend(g.fields)
    return fields
