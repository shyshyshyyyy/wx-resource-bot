# -*- coding: utf-8 -*-
"""网盘账号管理：7 种网盘的 Cookie / 转存目录 / 限额"""

import time
import os
import uuid

from PySide6.QtCore import Qt
from PySide6 import QtGui
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QCheckBox, QPlainTextEdit,
)

from . import register
from ..widgets import info, warn

try:
    import config_manager as CM
except Exception:
    CM = None

PAN_NAMES = {
    "quark": "夸克", "baidu": "百度", "uc": "UC", "aliyun": "阿里云",
    "xunlei": "迅雷", "guangya": "光鸭", "mobile": "移动",
}
PAN_KEYS = list(PAN_NAMES.keys())

# 各网盘根目录 ID（与 transfer/adapters.py 的 _list_dir 对齐）
ROOT_IDS = {
    "quark": "0", "uc": "0", "xunlei": "", "aliyun": "root",
    "baidu": "/", "guangya": "", "mobile": "root",
}

# 每种网盘的「凭据」语义不一致，是用户最常踩的坑：
#   cookie 类        ：夸克 / 百度 / UC / 天翼 —— 真·浏览器 Cookie
#   refresh_token 类 ：光鸭 / 迅雷 / 阿里     —— 不是 Cookie，是 refresh_token
#   Basic 令牌类     ：移动                  —— Authorization 的 Basic 令牌或 Cookie
CRED_LABEL = {
    "quark": "Cookie", "baidu": "Cookie", "uc": "Cookie", "tianyi": "Cookie",
    "aliyun": "refresh_token", "xunlei": "refresh_token / Cookie",
    "guangya": "refresh_token", "mobile": "Authorization 令牌 / Cookie",
}
CRED_TIP = {
    "quark": "夸克网盘 Cookie：登录 pan.quark.cn → F12 → Application → 复制 Cookie 整串。",
    "baidu": "百度网盘 Cookie：需含 BDUSS（登录 pan.baidu.com 后复制）。",
    "uc": "UC 网盘 Cookie：登录 drive.uc.cn → F12 → 复制 Cookie 整串。",
    "tianyi": "天翼云盘 Cookie：登录 cloud.189.cn → F12 → 复制 Cookie 整串。",
    "aliyun": "阿里云盘 refresh_token（⚠️ 不是 Cookie）：取 refresh_token 长串粘贴。",
    "xunlei": "迅雷云盘 refresh_token（XLUserToken，也可贴 Cookie）：登录 pan.xunlei.com 后取 refresh_token。",
    "guangya": "光鸭 refresh_token（⚠️ 不是 Cookie、也不是 eyJ 开头的 access_token！）：可点「手机验证码登录」用手机号+短信登录自动获取，或登录 guangyapan.com 后从 devtools 复制 refresh_token（gy. 开头）。若提示 token does not match，填一下「设备ID」与官网一致。",
    "mobile": "移动云盘：Authorization 的 Basic 令牌（可带 Basic 前缀，会自动去掉），也可直接贴 Cookie。",
}
COOKIE_TIP = CRED_TIP  # 兼容旧引用


class FolderPickDialog(QDialog):
    """网盘目录选择器（对齐 xinyue-search 后台交互）。

    每行：radio 单选 + 文件夹名 + 「›」进入子级；顶部显示当前路径。
    选中圆圈 = 选定该文件夹；「›」/双击 = 进入浏览；「上级」返回。
    list_dir 返回统一结构 [{id, name, is_dir}]。
    """

    def __init__(self, parent, adapter, root_id="0", root_name="根目录",
                 cur_id="", cur_name=""):
        super().__init__(parent)
        self.setWindowTitle("选择转存目录")
        self.resize(480, 560)
        self.adapter = adapter
        self.stack = [(root_id, root_name)]   # (id, name) 路径栈
        self.result_id = ""
        self.result_name = ""
        # 打开时默认勾选账号已保存的目录
        self.picked = {"id": str(cur_id or ""), "name": str(cur_name or "")}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        tip = QLabel("点名称前的圆圈选中该文件夹；点右侧 › 进入下一级。")
        tip.setObjectName("groupDesc")
        lay.addWidget(tip)

        row = QHBoxLayout()
        self.lab_path = QLabel()
        self.lab_path.setStyleSheet("color:#4E5969;font-weight:600;")
        b_up = QPushButton("上级")
        b_up.setFixedWidth(70)
        b_up.clicked.connect(self.go_up)
        row.addWidget(self.lab_path, 1)
        row.addWidget(b_up)
        lay.addLayout(row)

        self.listw = QListWidget()
        self.listw.itemDoubleClicked.connect(self.enter)
        lay.addWidget(self.listw, 1)

        self.lab_state = QLabel("")
        self.lab_state.setObjectName("groupDesc")
        lay.addWidget(self.lab_state)

        btns = QHBoxLayout()
        b_new = QPushButton("新建文件夹")
        b_new.clicked.connect(self.new_folder)
        b_ok = QPushButton("确定")
        b_ok.setObjectName("btnPrimary")
        b_cancel = QPushButton("取消")
        b_ok.clicked.connect(self.pick)
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_new)
        btns.addStretch(1)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        lay.addLayout(btns)

        self.load()

    # ---------------- 数据 ----------------
    def _current(self):
        return self.stack[-1]

    def load(self):
        pid, pname = self._current()
        self.lab_path.setText(" / ".join(n for _, n in self.stack))
        self.listw.clear()
        self.lab_state.setText("正在读取文件夹列表…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            items = self.adapter.list_dir(pid)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.lab_state.setText(f"读取失败：{e}")
            return
        QApplication.restoreOverrideCursor()
        dirs = [it for it in items if it.get("is_dir", True)]
        if not dirs:
            self.lab_state.setText("（该目录下没有子文件夹）")
            return
        for it in dirs:
            iid, nm = str(it.get("id", "")), str(it.get("name", ""))
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 4, 10, 4)
            h.setSpacing(8)
            rb = QRadioButton(nm)
            rb.setCursor(Qt.PointingHandCursor)
            if iid and iid == self.picked.get("id"):
                rb.setChecked(True)
            rb.toggled.connect(
                lambda on, i=iid, n=nm: on and self._pick_radio(i, n))
            b_in = QPushButton("›")
            b_in.setFixedWidth(32)
            b_in.setToolTip("进入该文件夹")
            b_in.clicked.connect(lambda _=None, i=iid, n=nm: self.enter_id(i, n))
            h.addWidget(rb, 1)
            h.addWidget(b_in)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self.listw.addItem(item)
            self.listw.setItemWidget(item, row)
        self.lab_state.setText(f"共 {len(dirs)} 个子文件夹")

    def _pick_radio(self, iid, name):
        self.picked = {"id": iid, "name": name}
        self.lab_state.setText(f"已选中：{name}")

    def enter_id(self, iid, name):
        self.stack.append((iid, name))
        self.load()

    def enter(self, item):
        w = self.listw.itemWidget(item)
        if w:
            rb = w.findChild(QRadioButton)
            if rb:
                # 双击 = 先勾选再进入，保证路径栈和选中项一致
                self._pick_radio(self.picked.get("id", ""), rb.text())
                self.enter_id(self.picked.get("id", ""), rb.text())
                return
        self.load()

    def go_up(self):
        if len(self.stack) > 1:
            self.stack.pop()
            self.load()

    def new_folder(self):
        """在当前目录下新建子文件夹（同名自动复用，不重复建）"""
        name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名称：")
        name = (name or "").strip()
        if not ok or not name:
            return
        pid, _ = self._current()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.adapter.create_dir(pid, name)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.lab_state.setText(f"新建失败：{e}")
            return
        QApplication.restoreOverrideCursor()
        self.lab_state.setText(f"已创建「{name}」")
        self.load()

    def pick(self):
        if self.picked.get("id"):
            self.result_id = self.picked["id"]
            self.result_name = self.picked["name"]
            self.accept()
            return
        pid, pname = self._current()
        if len(self.stack) > 1:
            # 没勾选就落在当前浏览的这一层
            self.result_id = str(pid)
            self.result_name = str(pname)
            self.accept()
            return
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "提示", "请先点文件夹名前的圆圈选中一个文件夹")


class GuangyaLoginDialog(QDialog):
    """光鸭手机验证码登录向导。

    光鸭的短信登录在 API 层被滑块人机验证挡住，所以提供两条路：
      A) 完整 API 流程：填手机号 -> 发送验证码 -> 填验证码 -> 换令牌
         （仅在滑块未强制拦截的环境可用，被拦会引导走 B）。
      B) 浏览器辅助（兜底，99% 可用）：打开官网登录页过滑块+短信，
         登录后把页面里的 refresh_token 复制回来。
    最终都收敛成一个 refresh_token，填回账号后由适配器自动续期。
    """

    def __init__(self, parent, device_id=""):
        super().__init__(parent)
        self.setWindowTitle("光鸭 · 手机验证码登录")
        self.resize(470, 400)
        self.device_id = device_id or os.urandom(16).hex()
        self.captcha_token = ""
        self.verification_id = ""
        self.result = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        tip = QLabel("方式一：填手机号发验证码（部分环境需先在浏览器过滑块）。\n"
                     "方式二（兜底）：点「打开官网登录」过滑块+短信登录后，"
                     "复制页面 refresh_token 粘到下方。")
        tip.setObjectName("groupDesc")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        f = QFormLayout()
        f.setSpacing(8)
        self.e_phone = QLineEdit()
        self.e_phone.setPlaceholderText("11 位手机号，如 13800000000")
        f.addRow("手机号", self.e_phone)
        self.e_code = QLineEdit()
        self.e_code.setPlaceholderText("6 位短信验证码")
        f.addRow("验证码", self.e_code)
        lay.addLayout(f)

        row = QHBoxLayout()
        b_send = QPushButton("发送验证码")
        b_send.clicked.connect(self.send_code)
        b_open = QPushButton("打开官网登录")
        b_open.clicked.connect(self.open_site)
        row.addWidget(b_send)
        row.addWidget(b_open)
        lay.addLayout(row)

        self.lab_state = QLabel("")
        self.lab_state.setObjectName("groupDesc")
        self.lab_state.setWordWrap(True)
        lay.addWidget(self.lab_state)

        f2 = QFormLayout()
        f2.setSpacing(8)
        self.e_rt = QPlainTextEdit()
        self.e_rt.setMinimumHeight(70)
        self.e_rt.setPlaceholderText("在此粘贴官网登录后的 refresh_token（gy. 开头）")
        f2.addRow("refresh_token", self.e_rt)
        lay.addLayout(f2)

        btns = QHBoxLayout()
        b_ok = QPushButton("登录并保存")
        b_ok.setObjectName("btnPrimary")
        b_ok.clicked.connect(self.do_login)
        b_cancel = QPushButton("取消")
        b_cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        lay.addLayout(btns)

    def send_code(self):
        from transfer import guangya_auth as GYA
        phone = self.e_phone.text().strip()
        if not phone:
            self.lab_state.setText("请先填手机号")
            return
        self.lab_state.setText("正在获取验证码…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.captcha_token = GYA.captcha_init(self.device_id, phone)
            GYA.send_sms(self.device_id, phone, self.captcha_token)
            self.lab_state.setText("验证码已发送，请查收短信并填入。")
        except GYA.CaptchaRequired as e:
            GYA.open_browser_login()
            self.lab_state.setText("接口被滑块拦截，已打开官网登录页：请过滑块+短信登录，"
                                   "然后复制页面 refresh_token 粘到下方框。\n（%s）" % e)
        except Exception as e:
            self.lab_state.setText("发送失败：%s" % e)
        finally:
            QApplication.restoreOverrideCursor()

    def open_site(self):
        from transfer import guangya_auth as GYA
        GYA.open_browser_login()
        self.lab_state.setText("已打开官网登录页，登录后复制 refresh_token 粘到下方框。")

    def do_login(self):
        from transfer import guangya_auth as GYA
        rt = self.e_rt.toPlainText().strip()
        if rt:
            self.result = {"refresh_token": rt, "device_id": self.device_id}
            self.accept()
            return
        phone = self.e_phone.text().strip()
        code = self.e_code.text().strip()
        if not (phone and code):
            self.lab_state.setText("请填验证码，或在下方粘贴 refresh_token。")
            return
        self.lab_state.setText("正在换取令牌…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if not self.captcha_token:
                self.captcha_token = GYA.captcha_init(self.device_id, phone)
                GYA.send_sms(self.device_id, phone, self.captcha_token)
            tok = GYA.exchange(self.device_id, phone, code,
                               self.captcha_token, self.verification_id)
            self.result = {"refresh_token": tok["refresh_token"],
                           "device_id": self.device_id}
            self.accept()
        except GYA.CaptchaRequired as e:
            GYA.open_browser_login()
            self.lab_state.setText("接口被滑块拦截，已打开官网登录页：请登录后复制"
                                   "refresh_token 粘到下方框。\n（%s）" % e)
        except Exception as e:
            self.lab_state.setText("登录失败：%s" % e)
        finally:
            QApplication.restoreOverrideCursor()


class AccountDialog(QDialog):
    def __init__(self, parent=None, data=None, pan_locked=None):
        super().__init__(parent)
        self.setWindowTitle("网盘账号")
        self.resize(560, 520)
        d = data or {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        form = QFormLayout()
        form.setSpacing(10)

        self.cb_pan = QComboBox()
        self.cb_pan.addItems([f"{PAN_NAMES[k]}（{k}）" for k in PAN_KEYS])
        if d.get("pan") in PAN_KEYS:
            self.cb_pan.setCurrentIndex(PAN_KEYS.index(d["pan"]))
        self.cb_pan.setEnabled(pan_locked is None)
        self.cb_pan.currentIndexChanged.connect(self._on_pan_change)

        self.e_name = QLineEdit(d.get("name", "账号1"))
        self.ck_on = QCheckBox("启用")
        self.ck_on.setChecked(bool(d.get("enabled", True)))

        self.e_cookie = QPlainTextEdit(d.get("cookie", ""))
        self.e_cookie.setMinimumHeight(120)
        self.lab_cred = QLabel("凭据 / Cookie")
        self.e_phone = QLineEdit(d.get("phone", ""))
        self.e_device = QLineEdit(d.get("device_id", ""))
        self.e_device.setPlaceholderText("光鸭可选：refresh_token 绑定设备时填，需与官网一致")

        # 转存目录：对齐网站后台 ——「请选择」按钮弹出文件列表单选，
        # 不再让用户手填目录 ID
        self.dir_id = str(d.get("save_dir_id", "") or "")
        self.dir_name = str(d.get("save_dir_name", "") or "")
        self.temp_id = str(d.get("temp_dir_id", "") or "")
        self.temp_name = str(d.get("temp_dir_name", "") or "")

        def _dir_row(which):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            b = QPushButton("请选择")
            b.setFixedWidth(80)
            b.clicked.connect(lambda _=None, k=which: self.pick_dir(k))
            lab = QLabel()
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            b_clear = QPushButton("清除")
            b_clear.setFixedWidth(56)
            b_clear.clicked.connect(lambda _=None, k=which: self.clear_dir(k))
            h.addWidget(b)
            h.addWidget(lab, 1)
            h.addWidget(b_clear)
            setattr(self, "lab_dir_" + which, lab)
            return w

        self.e_banned = QLineEdit(d.get("banned_words", ""))

        form.addRow("网盘类型", self.cb_pan)
        form.addRow("备注名", self.e_name)
        form.addRow("", self.ck_on)
        form.addRow(self.lab_cred, self.e_cookie)
        form.addRow("设备ID（光鸭可选）", self.e_device)
        form.addRow("手机号（仅移动云盘）", self.e_phone)
        form.addRow("默认转存目录", _dir_row("save"))
        form.addRow("临时资源目录", _dir_row("temp"))
        form.addRow("广告关键词", self.e_banned)
        lay.addLayout(form)
        self._refresh_dir_labels()

        self.lab_tip = QLabel()
        self.lab_tip.setObjectName("groupDesc")
        self.lab_tip.setWordWrap(True)
        lay.addWidget(self.lab_tip)
        self._on_pan_change()

        btns = QHBoxLayout()
        b_verify = QPushButton("校验凭据")
        b_verify.clicked.connect(self.verify)
        b_ok = QPushButton("保存")
        b_ok.setObjectName("btnPrimary")
        b_cancel = QPushButton("取消")
        b_ok.clicked.connect(self.accept)
        b_cancel.clicked.connect(self.reject)
        self.b_gy_login = QPushButton("手机验证码登录")
        self.b_gy_login.clicked.connect(self.guangya_login)
        btns.addWidget(self.b_gy_login)
        btns.addWidget(b_verify)
        btns.addStretch(1)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        lay.addLayout(btns)

        self.lab_verify = QLabel("")
        self.lab_verify.setObjectName("groupDesc")
        self.lab_verify.setWordWrap(True)
        lay.addWidget(self.lab_verify)

    def _pan_key(self):
        return PAN_KEYS[self.cb_pan.currentIndex()]

    def _norm_cred(self):
        """去掉用户可能多贴的协议前缀（Basic / Bearer），统一存裸值。"""
        c = self.e_cookie.toPlainText().strip()
        low = c.lower()
        if low.startswith("basic "):
            c = c[6:].strip()
        elif low.startswith("bearer "):
            c = c[7:].strip()
        return c

    def _on_pan_change(self):
        pk = self._pan_key()
        self.lab_cred.setText(CRED_LABEL.get(pk, "凭据 / Cookie"))
        self.lab_tip.setText(CRED_TIP.get(pk, ""))
        if hasattr(self, "b_gy_login"):
            self.b_gy_login.setVisible(pk == "guangya")
        if hasattr(self, "lab_verify"):
            self.lab_verify.setText("")

    def verify(self):
        """用当前表单里的凭据试连一次，立刻告诉用户能不能用"""
        from PySide6.QtWidgets import QMessageBox
        from transfer import base as TB
        pan = self._pan_key()
        cookie = self._norm_cred()
        if not cookie:
            QMessageBox.warning(self, "提示", "请先填写凭据 / Cookie")
            return
        cls = TB.get_adapter(pan)
        if cls is None:
            QMessageBox.warning(self, "提示", f"暂不支持 {pan}")
            return
        acc = self.data()
        self.lab_verify.setText("正在校验…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            adapter = cls(acc)
            ok, msg = adapter.check()
            # 迅雷 refresh_token 会轮转，把最新值回填到凭据框，避免下次用旧令牌
            if acc.get("pan") == "xunlei" and adapter.account.get("cookie"):
                self.e_cookie.setPlainText(adapter.account["cookie"])
        except Exception as e:
            ok, msg = False, str(e)
        QApplication.restoreOverrideCursor()
        color = "#00B42A" if ok else "#F53F3F"
        self.lab_verify.setText(
            f'<span style="color:{color};font-weight:600">'
            f'{"校验通过" if ok else "校验失败"}：{msg}</span>')

    def guangya_login(self):
        """光鸭：打开手机验证码登录向导，成功后把 refresh_token 填回凭据框。"""
        from PySide6.QtWidgets import QMessageBox
        dlg = GuangyaLoginDialog(self, self.e_device.text().strip())
        if dlg.exec() == QDialog.Accepted and dlg.result:
            res = dlg.result
            idx = PAN_KEYS.index("guangya")
            self.cb_pan.setCurrentIndex(idx)
            self.e_cookie.setPlainText(res.get("refresh_token", ""))
            if res.get("device_id"):
                self.e_device.setText(res["device_id"])
            QMessageBox.information(self, "登录成功",
                                    "已将 refresh_token 填入凭据框，点「保存」即可。"
                                    "后续由程序自动续期，无需重复登录。")

    def _make_adapter(self):
        """用表单里现填的凭据建适配器（不用先保存）"""
        from transfer import base as TB
        pan = self._pan_key()
        cls = TB.get_adapter(pan)
        if cls is None:
            return None, f"暂不支持 {pan}"
        acc = {"pan": pan, "cookie": self._norm_cred(),
               "phone": self.e_phone.text().strip()}
        return cls(acc), None

    def _refresh_dir_labels(self):
        for which, iid, nm in (("save", self.dir_id, self.dir_name),
                               ("temp", self.temp_id, self.temp_name)):
            lab = getattr(self, "lab_dir_" + which)
            if iid:
                short = iid if len(iid) <= 18 else iid[:16] + "…"
                lab.setText(f"<b>{nm or '已选择'}</b>&nbsp;&nbsp;"
                            f"<span style='color:#86909C'>{short}</span>")
            else:
                lab.setText("<span style='color:#86909C'>未选择"
                            "（留空 = 网盘根目录）</span>")

    def pick_dir(self, which):
        """网站后台同款：弹出文件列表，radio 单选 + › 进入子级"""
        from PySide6.QtWidgets import QMessageBox
        if not self.e_cookie.toPlainText().strip():
            QMessageBox.warning(self, "提示", "请先填写凭据 / Cookie，再选择目录")
            return
        pan = self._pan_key()
        adapter, err = self._make_adapter()
        if err:
            QMessageBox.warning(self, "提示", err)
            return
        cur_id = self.dir_id if which == "save" else self.temp_id
        cur_nm = self.dir_name if which == "save" else self.temp_name
        try:
            dlg = FolderPickDialog(self, adapter,
                                   root_id=ROOT_IDS.get(pan, "0"),
                                   root_name="根目录",
                                   cur_id=cur_id, cur_name=cur_nm)
            if dlg.exec() == QDialog.Accepted:
                if which == "save":
                    self.dir_id, self.dir_name = dlg.result_id, dlg.result_name
                else:
                    self.temp_id, self.temp_name = dlg.result_id, dlg.result_name
                self._refresh_dir_labels()
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e)[:400])

    def clear_dir(self, which):
        if which == "save":
            self.dir_id = self.dir_name = ""
        else:
            self.temp_id = self.temp_name = ""
        self._refresh_dir_labels()

    def data(self):
        return {
            "pan": self._pan_key(),
            "name": self.e_name.text().strip() or "账号1",
            "enabled": self.ck_on.isChecked(),
            "cookie": self._norm_cred(),
            "phone": self.e_phone.text().strip(),
            "device_id": self.e_device.text().strip(),
            "banned_words": self.e_banned.text().strip(),
            "save_dir_id": self.dir_id,
            "save_dir_name": self.dir_name,
            "temp_dir_id": self.temp_id,
            "temp_dir_name": self.temp_name,
        }


@register("nd_account")
def build(page, mw):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(18, 14, 18, 14)
    lay.setSpacing(12)

    tip = QLabel("为每种网盘配置至少一个可用账号，机器人才能把搜索到的资源转存成你自己的分享链接。"
                 "同一网盘可配多个账号，超过日限额会自动切换。")
    tip.setObjectName("pageDesc")
    tip.setWordWrap(True)
    lay.addWidget(tip)

    g = QGroupBox("账号列表")
    gl = QVBoxLayout(g)
    gl.setContentsMargins(14, 16, 14, 16)

    table = QTableWidget(0, 7)
    table.setHorizontalHeaderLabels(
        ["启用", "网盘", "备注名", "凭据", "转存目录", "今日 / 上限", "状态"])
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
    table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
    table.setMinimumHeight(300)
    gl.addWidget(table)

    btns = QHBoxLayout()
    b_add = QPushButton("新增账号")
    b_edit = QPushButton("编辑")
    b_del = QPushButton("删除")
    b_check = QPushButton("检测选中")
    b_add.clicked.connect(lambda: on_add())
    b_edit.clicked.connect(lambda: on_edit())
    b_del.clicked.connect(lambda: on_del())
    b_check.clicked.connect(lambda: on_check())
    for b in (b_add, b_edit, b_del, b_check):
        btns.addWidget(b)
    btns.addStretch(1)
    gl.addLayout(btns)
    lay.addWidget(g)

    # ---------- 转存策略 ----------
    g2 = QGroupBox("转存策略")
    g2l = QGridLayout(g2)
    g2l.setContentsMargins(14, 16, 14, 16)
    ck_on = QCheckBox("启用自动转存")
    sp_retry = QSpinBox()
    sp_retry.setRange(0, 10)
    ck_fb = QCheckBox("转存失败时回落原始链接")
    sp_exp = QSpinBox()
    sp_exp.setRange(0, 365)
    ck_cleanup = QCheckBox("分享后删除网盘里的源文件（默认关：删了文件，发出去的链接立刻失效）")
    g2l.addWidget(ck_on, 0, 0)
    g2l.addWidget(QLabel("失败重试次数"), 0, 1)
    g2l.addWidget(sp_retry, 0, 2)
    g2l.addWidget(ck_fb, 1, 0)
    g2l.addWidget(QLabel("分享有效期（天，0=永久）"), 1, 1)
    g2l.addWidget(sp_exp, 1, 2)
    g2l.addWidget(ck_cleanup, 2, 0, 1, 3)
    g2l.setColumnStretch(3, 1)
    lay.addWidget(g2)

    lay.addStretch(1)

    def _row(acc):
        r = table.rowCount()
        table.insertRow(r)
        ck = QCheckBox()
        ck.setChecked(bool(acc.get("enabled", True)))
        ck.setEnabled(False)
        cell = QWidget()
        h = QHBoxLayout(cell)
        h.setContentsMargins(0, 0, 0, 0)
        h.setAlignment(Qt.AlignCenter)
        h.addWidget(ck)
        table.setCellWidget(r, 0, cell)

        table.setItem(r, 1, QTableWidgetItem(PAN_NAMES.get(acc.get("pan", ""), acc.get("pan", ""))))
        table.setItem(r, 2, QTableWidgetItem(str(acc.get("name", ""))))
        cookie = str(acc.get("cookie", ""))
        masked = (cookie[:12] + "…（已隐藏 " + str(len(cookie)) + " 字符）") if cookie else "未填写"
        table.setItem(r, 3, QTableWidgetItem(masked))
        table.setItem(r, 4, QTableWidgetItem(str(acc.get("save_dir_name", "") or acc.get("save_dir_id", ""))))
        st = {"ok": "正常", "invalid": "失效", "unknown": "未检测"}.get(
            acc.get("status", "unknown"), acc.get("status", "未检测"))
        it_st = QTableWidgetItem(st)
        it_st.setForeground(
            QtGui.QColor("#00B42A" if st == "正常" else
                         ("#F53F3F" if st == "失效" else "#86909C")))
        table.setItem(r, 5, it_st)
        table.item(r, 1).setData(Qt.UserRole, acc.get("id", ""))

    def refresh():
        table.setRowCount(0)
        if CM is None:
            return
        for acc in CM.load_config(True).get("transfer", {}).get("accounts", []):
            _row(acc)

    def on_add():
        dlg = AccountDialog(mw)
        if dlg.exec() != QDialog.Accepted:
            return
        data = dlg.data()
        data["id"] = uuid.uuid4().hex[:10]
        data.update({"status": "unknown", "last_check": 0})
        if CM:
            c = CM.load_config()
            c.setdefault("transfer", {}).setdefault("accounts", []).append(data)
            CM.save_config(c)
            if data.get("cookie"):
                ok, msg = _verify_account(c, data)
                mw.log(f"[{data['pan']}] {data['name']} 凭据校验"
                       f"{'通过' if ok else '失败'}：{msg}",
                       "SUCCESS" if ok else "ERROR")
        refresh()
        mw.log(f"已新增网盘账号：{data['pan']} / {data['name']}", "SUCCESS")

    def _verify_account(c, acc):
        """保存后立刻试连一次，把结果写进 status，用户不用手动点检测"""
        try:
            from transfer import base as TB
            cls = TB.get_adapter(acc.get("pan"))
            if cls is None:
                return False, "暂不支持该网盘"
            # 带 cfg/save_fn：校验时换发的轮转令牌写回配置（对齐网站"换发即写库"）
            ok, msg = cls(acc, cfg=c, save_fn=CM.save_config).check()
        except Exception as e:
            ok, msg = False, str(e)
        acc["status"] = "ok" if ok else "invalid"
        acc["last_check"] = int(time.time())
        try:
            CM.save_config(c)
        except Exception:
            pass
        return ok, msg

    def _current_id():
        r = table.currentRow()
        if r < 0:
            return None
        it = table.item(r, 1)
        return it.data(Qt.UserRole) if it else None

    def on_edit():
        aid = _current_id()
        if not aid:
            warn(mw, "提示", "请先选中一个账号")
            return
        c = CM.load_config()
        acc = next((a for a in c["transfer"]["accounts"] if a.get("id") == aid), None)
        if not acc:
            return
        old_cookie = acc.get("cookie")
        dlg = AccountDialog(mw, acc)
        if dlg.exec() != QDialog.Accepted:
            return
        acc.update(dlg.data())
        # 用户改了凭据 → 作废旧令牌缓存，避免新填/重填的令牌被旧缓存遮蔽
        if acc.get("cookie") != old_cookie:
            try:
                from transfer.adapters import _token_clear
                _token_clear(aid)
            except Exception:
                pass
        CM.save_config(c)
        if acc.get("cookie"):
            ok, msg = _verify_account(c, acc)
            mw.log(f"[{acc['pan']}] {acc['name']} 凭据校验"
                   f"{'通过' if ok else '失败'}：{msg}",
                   "SUCCESS" if ok else "ERROR")
        refresh()
        mw.log("账号已更新", "SUCCESS")

    def on_del():
        aid = _current_id()
        if not aid:
            warn(mw, "提示", "请先选中一个账号")
            return
        c = CM.load_config()
        c["transfer"]["accounts"] = [
            a for a in c["transfer"]["accounts"] if a.get("id") != aid]
        try:
            from transfer.adapters import _token_clear
            _token_clear(aid)
        except Exception:
            pass
        CM.save_config(c)
        refresh()
        mw.log("账号已删除", "WARN")

    def on_check():
        aid = _current_id()
        if not aid:
            warn(mw, "提示", "请先选中一个账号")
            return
        c = CM.load_config()
        acc = next((a for a in c["transfer"]["accounts"] if a.get("id") == aid), None)
        if not acc:
            return
        try:
            from transfer import base as TB
            # 带 cfg/save_fn：检测（check）内部换发令牌后会把轮转后的 refresh_token
            # 写回配置（对齐网站"换发即写库"），否则重启后配置仍是已作废的旧令牌。
            adapter = TB.get_adapter(acc.get("pan"))(acc, cfg=c, save_fn=CM.save_config)
            ok, msg = adapter.check()
            acc["status"] = "ok" if ok else "invalid"
            if ok:
                mw.log(f"[{acc.get('pan')}] {acc.get('name')} 检测通过：{msg}",
                       "SUCCESS")
            else:
                mw.log(f"[{acc.get('pan')}] {acc.get('name')} 检测失败：{msg}",
                       "ERROR")
        except Exception as e:
            acc["status"] = "invalid"
            msg = f"检测失败：{e}"
            mw.log(f"[{acc.get('pan')}] {acc.get('name')} 检测失败：{e}", "ERROR")
        CM.save_config(c)
        refresh()
        info(mw, "检测结果", msg[:400])

    def load(cfg):
        refresh()
        if CM:
            t = CM.load_config().get("transfer", {})
            ck_on.setChecked(bool(t.get("enabled", True)))
            sp_retry.setValue(int(t.get("retry", 2) or 2))
            ck_fb.setChecked(bool(t.get("fallback_original_link", True)))
            sp_exp.setValue(int(t.get("share_expire_days", 0) or 0))
            ck_cleanup.setChecked(bool(t.get("cleanup_after_share", False)))

    def collect():
        if CM is None:
            return {}
        c = CM.load_config()
        c["transfer"]["enabled"] = ck_on.isChecked()
        c["transfer"]["retry"] = sp_retry.value()
        c["transfer"]["fallback_original_link"] = ck_fb.isChecked()
        c["transfer"]["share_expire_days"] = sp_exp.value()
        c["transfer"]["cleanup_after_share"] = ck_cleanup.isChecked()
        CM.save_config(c)
        return {}

    refresh()
    w.load = load
    w.collect = collect
    return w
