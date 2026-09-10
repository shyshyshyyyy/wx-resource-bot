# -*- coding: utf-8 -*-
"""页面工厂：form 页自动渲染，custom 页由各模块实现"""

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

from .. import schema as S
from ..widgets import FormPage

CUSTOM_BUILDERS = {}


def register(pid):
    def deco(fn):
        CUSTOM_BUILDERS[pid] = fn
        return fn
    return deco


class PlaceholderPage(QWidget):
    """尚未实现的页面占位，明确提示避免"功能消失"被忽略"""

    def __init__(self, page: "S.Page"):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 60, 40, 60)
        t = QLabel(f"{page.title} — 建设中")
        t.setStyleSheet("font-size:16px;font-weight:600;color:#4E5969;")
        d = QLabel(page.desc or "")
        d.setStyleSheet("color:#86909C;")
        d.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(d)
        lay.addStretch(1)

    def load(self, config):
        pass

    def collect(self):
        return {}


def _load_into(w, cfg, mw, pid):
    """把配置灌进页面，并打上 _loaded 标记。

    **关键**：之前只有 form 页会 load，custom 页（盘搜接口 / 网盘账号 /
    私聊监听 / 群组管理…）全都不 load。结果控件停在"出厂默认值"
    （SpinBox 是最小值、CheckBox 是未勾选、LineEdit 是空），用户一按
    「保存配置」或「启动机器人」，collect() 就把这些默认值写回磁盘，
    真配置被冲掉 —— 表现就是"我设置的盘搜接口重启后没了"。

    所以这里必须对**所有**页面统一 load；load 失败的页标记为未加载，
    保存时会被跳过，绝不拿默认值覆盖磁盘。
    """
    if not hasattr(w, "load"):
        return
    try:
        w.load(cfg)
        w._loaded = True
    except Exception as e:
        w._loaded = False
        import traceback
        mw.log(f"[{pid}] 载入配置失败（保存时将跳过该页）: {e}\n"
               f"{traceback.format_exc()}", "ERROR")


def build_page(page: "S.Page", mw) -> QWidget:
    if page.kind == "form":
        w = FormPage(page)
        _load_into(w, mw.config, mw, page.id)
        return w
    fn = CUSTOM_BUILDERS.get(page.id)
    if fn:
        try:
            w = fn(page, mw)
        except Exception as e:
            import traceback
            err = PlaceholderPage(page)
            mw.log(f"[{page.id}] 页面创建失败: {e}\n{traceback.format_exc()}", "ERROR")
            return err
        _load_into(w, mw.config, mw, page.id)
        return w
    return PlaceholderPage(page)


# 注册所有自定义页面
from . import status as _status        # noqa: E402,F401
from . import api as _api              # noqa: E402,F401
from . import prompt as _prompt        # noqa: E402,F401
from . import listen as _listen        # noqa: E402,F401
from . import group as _group          # noqa: E402,F401
from . import keyword as _keyword      # noqa: E402,F401
from . import forward as _forward      # noqa: E402,F401
from . import schedule as _schedule    # noqa: E402,F401
from . import moments as _moments      # noqa: E402,F401
from . import memory as _memory        # noqa: E402,F401
from . import backup as _backup        # noqa: E402,F401
from . import account as _account      # noqa: E402,F401
from . import license_page as _license # noqa: E402,F401
from . import nd_search as _nd_search  # noqa: E402,F401
from . import nd_account as _nd_acc    # noqa: E402,F401
from . import nd_template as _nd_tpl   # noqa: E402,F401
from . import nd_convert as _nd_conv   # noqa: E402,F401
from . import about as _about          # noqa: E402,F401
