# -*- coding: utf-8 -*-
"""消息模板配置：触发指令 + 各环节回复模板"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

from . import register
from ..widgets import info, warn

try:
    import config_manager as CM
except Exception:
    CM = None

TEMPLATE_LABELS = {
    "search_hint": "搜索用法提示",
    "searching": "搜索中",
    "no_result": "无结果",
    "result_header": "结果头部",
    "result_item": "结果条目",
    "result_footer": "结果尾部",
    "getting": "获取中",
    "success": "获取成功",
    "password_line": "提取码行",
    "transfer_failed": "获取失败",
    "dead_link": "源链接失效提示",
    "dead_link_end": "连续失效结尾",
    "account_invalid": "账号异常提示",
    "transfer_retry": "临时错误重试提示",
    "expired": "结果已过期",
    "invalid_index": "序号无效",
    "no_account": "无可用账号",
    "unlicensed": "未激活提示",
}

TEMPLATE_VARS = {
    "search_hint": "",
    "searching": "{keyword}",
    "no_result": "{keyword}",
    "result_header": "{keyword} {total} {page} {pages}",
    "result_item": "{index} {title} {pan_name} {source}",
    "result_footer": "",
    "getting": "{title} {pan_name} {pan_icon}",
    "success": "{pan_name} {share_url} {password_line}",
    "password_line": "{password}",
    "transfer_failed": "{reason} {origin_url}",
    "dead_link": "{title} {pan_name}",
    "dead_link_end": "{keyword}",
    "account_invalid": "{pan_name} {reason}",
    "transfer_retry": "{reason}",
    "expired": "",
    "invalid_index": "{max}",
    "no_account": "{pan_name}",
    "unlicensed": "",
}

DEFAULT_TRIGGERS = {
    "search_cmd": "搜索",
    "next_page_cmd": "下一页",
    "prev_page_cmd": "上一页",
    "help_cmd": "帮助",
}


@register("nd_template")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("配置用户触发搜索的指令词，以及每个环节机器人回复的文案。"
                 "大括号里的变量会在发送时自动替换。")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    # ---------- 触发指令 ----------
    g1 = QGroupBox("触发指令")
    gl = QGridLayout(g1)
    gl.setContentsMargins(14, 16, 14, 16)
    e_search = QLineEdit("搜索")
    e_next = QLineEdit("下一页")
    e_prev = QLineEdit("上一页")
    e_help = QLineEdit("帮助")
    ck_group = None
    gl.addWidget(QLabel("搜索指令"), 0, 0)
    gl.addWidget(e_search, 0, 1)
    gl.addWidget(QLabel("下一页"), 0, 2)
    gl.addWidget(e_next, 0, 3)
    gl.addWidget(QLabel("上一页"), 1, 0)
    gl.addWidget(e_prev, 1, 1)
    gl.addWidget(QLabel("帮助"), 1, 2)
    gl.addWidget(e_help, 1, 3)
    gl.setColumnStretch(1, 1)
    gl.setColumnStretch(3, 1)
    lay.addWidget(g1)

    # ---------- 群聊多人并发 ----------
    g15 = QGroupBox("群聊多人同时使用")
    g15l = QVBoxLayout(g15)
    g15l.setContentsMargins(14, 16, 14, 16)
    g15l.setSpacing(6)
    ck_at = QCheckBox("群聊回复 @ 发起人（每个人的结果只 @ 他自己，互不干扰）")
    ck_at.setChecked(True)
    tip_at = QLabel("群里多个人同时搜索时，回复会 @ 出发起人，避免分不清哪份结果是自己的。"
                    "Plus 内核用微信原生 @，免费内核自动改成在正文里写 @昵称。")
    tip_at.setObjectName("groupDesc")
    tip_at.setWordWrap(True)
    g15l.addWidget(ck_at)
    g15l.addWidget(tip_at)
    lay.addWidget(g15)

    # ---------- 模板编辑 ----------
    g2 = QGroupBox("回复模板")
    g2l = QVBoxLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)

    split = QSplitter(Qt.Horizontal)
    left = QListWidget()
    left.setFixedWidth(180)
    for k in TEMPLATE_LABELS:
        it = QListWidgetItem(TEMPLATE_LABELS[k])
        it.setData(Qt.UserRole, k)
        left.addItem(it)

    right = QWidget()
    rl = QVBoxLayout(right)
    rl.setContentsMargins(12, 0, 0, 0)
    lab = QLabel()
    lab.setStyleSheet("font-weight:600;")
    hint = QLabel()
    hint.setObjectName("groupDesc")
    hint.setWordWrap(True)
    editor = QTextEdit()
    editor.setMinimumHeight(180)
    # 空字段提示：明确"留空=本条不发送"，默认文案在下方参照框里，避免被误写回配置
    editor.setPlaceholderText("（未自定义：本条留空则不发送；下方「默认模板（参照）」是出厂文案，可直接照抄）")
    rl.addWidget(lab)
    rl.addWidget(hint)
    rl.addWidget(editor, 1)
    ref_lbl = QLabel("默认模板（参照，可直接照抄修改）：")
    ref_lbl.setObjectName("groupDesc")
    ref_lbl.setWordWrap(True)
    default_box = QTextEdit()
    default_box.setReadOnly(True)
    default_box.setMaximumHeight(96)
    default_box.setObjectName("defaultRef")
    rl.addWidget(ref_lbl)
    rl.addWidget(default_box)
    btns = QHBoxLayout()
    b_reset = QPushButton("恢复默认")
    b_reset.clicked.connect(lambda: on_reset())
    btns.addStretch(1)
    btns.addWidget(b_reset)
    rl.addLayout(btns)

    split.addWidget(left)
    split.addWidget(right)
    split.setStretchFactor(1, 1)
    g2l.addWidget(split)
    lay.addWidget(g2, 1)

    templates = {}

    def _show_current():
        it = left.currentItem()
        if not it:
            return
        k = it.data(Qt.UserRole)
        lab.setText(f"{TEMPLATE_LABELS.get(k, k)}（{k}）")
        v = TEMPLATE_VARS.get(k, "")
        hint.setText(f"可用变量：{v}" if v else "无变量")
        # 注意：编辑框只显示【落盘保存的值】，空就是空——绝不把默认文案填进编辑框，
        # 否则切换/保存时会把默认值写回 netdisk.json，造成"每条都被写入内容"。
        # 默认的出厂文案只放在下方"默认模板（参照）"框里供对照/照抄。
        if CM is not None:
            default_val = CM.DEFAULT_CONFIG.get("templates", {}).get(k, "")
        else:
            default_val = ""
        cur = templates.get(k, "")
        editor.blockSignals(True)
        editor.setPlainText(cur)
        editor.blockSignals(False)
        default_box.setPlainText(default_val)

    def _save_current():
        it = left.currentItem()
        if not it:
            return
        key = it.data(Qt.UserRole)
        val = editor.toPlainText()
        if val.strip():
            templates[key] = val
        elif key == "search_hint":
            # search_hint 必须显式持久化为空串：空=不发送。
            # 不能删（否则回落默认 usage 文案会在"搜了没带关键词"时刷屏）
            templates[key] = ""
        else:
            # 其它模板留空 → 不写入配置，运行时回落默认文案，
            # 避免"保存了空模板 → 机器人发空消息/整段消失"
            templates.pop(key, None)

    left.currentItemChanged.connect(lambda *_: (_save_current(), _show_current()))
    editor.textChanged.connect(lambda: _save_current())

    def on_reset():
        if CM is None:
            return
        # 清空即可：运行时会通过深合并回落默认文案（search_hint 默认即空=不发送）。
        # 不再把全部默认文案写回配置，避免"每条都被写入内容"。
        templates.clear()
        _show_current()
        mw.log("模板已恢复默认", "WARN")

    def load(cfg):
        if CM is None:
            return
        c = CM.load_config(True)
        t = c.get("templates", {})
        templates.clear()
        templates.update(t)
        trig = c.get("triggers", DEFAULT_TRIGGERS)
        e_search.setText(str(trig.get("search_cmd", "搜索")))
        e_next.setText(str(trig.get("next_page_cmd", "下一页")))
        e_prev.setText(str(trig.get("prev_page_cmd", "上一页")))
        e_help.setText(str(trig.get("help_cmd", "帮助")))
        left.setCurrentRow(0)
        _show_current()

    def collect():
        if CM is None:
            return {}
        _save_current()
        c = CM.load_config()
        c["templates"] = dict(templates)
        c["triggers"] = {
            "search_cmd": e_search.text().strip() or "搜索",
            "next_page_cmd": e_next.text().strip() or "下一页",
            "prev_page_cmd": e_prev.text().strip() or "上一页",
            "help_cmd": e_help.text().strip() or "帮助",
        }
        c.setdefault("wechat", {})["group_reply_at"] = ck_at.isChecked()
        CM.save_config(c)
        return {}

    w.load = load
    w.collect = collect
    return w
