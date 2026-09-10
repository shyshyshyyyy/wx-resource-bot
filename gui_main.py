# -*- coding: utf-8 -*-
"""微信资源搜索机器人 —— 桌面面板启动入口"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _selftest():
    """隐藏自检模式：构建全部页面并把结果写到 data/_selftest.txt，然后退出。
    用于验证打包后的 exe 在干净环境下能正常加载（windowed 模式没有控制台）。"""
    from PySide6.QtWidgets import QApplication
    from core import paths

    report = []
    try:
        app = QApplication([])
        from panel_qt.theme import apply as apply_theme
        apply_theme(app)
        from panel_qt.main_window import MainWindow

        report.append("frozen=%s" % bool(getattr(__import__("sys"), "frozen", False)))
        report.append("app_dir=%s" % paths.app_dir())
        report.append("data_dir=%s" % paths.data_dir())
        report.append("config_file=%s" % paths.config_file())

        win = MainWindow()
        report.append("pages=%d" % len(win._pages))

        # 页面载入率：任何一页没 load 成功，保存时就会拿控件默认值
        # 覆盖用户的真实配置（历史 bug："盘搜接口重启后没了"）
        _tot = len(win._pages)
        _ok = sum(1 for w in win._pages.values() if getattr(w, "_loaded", False))
        report.append("pages_loaded=%d/%d" % (_ok, _tot))

        # 配置往返：写入哨兵值 -> 页面 load -> 保存 -> 读回，值不能被冲掉
        try:
            import config_manager as _cm
            c = _cm.load_config(True)
            rem = c.setdefault("search", {}).setdefault("remote", {})
            _o_url, _o_to = rem.get("base_url", ""), rem.get("timeout", 20)
            rem["base_url"] = "http://__selftest__:1"
            rem["timeout"] = 47
            _cm.save_config(c)
            for _pg in win._pages.values():
                if hasattr(_pg, "load"):
                    _pg.load(win.config)
            win._save_config(silent=True)
            _cm._cache = None
            back = _cm.load_config(True)["search"]["remote"]
            good = (back.get("base_url") == "http://__selftest__:1"
                    and back.get("timeout") == 47)
            report.append("roundtrip=%s" % ("OK" if good else
                                            "LOST:%s/%s" % (back.get("base_url"),
                                                            back.get("timeout"))))
            back["base_url"], back["timeout"] = _o_url, _o_to   # 还原
            _cm.save_config(_cm.load_config())
        except Exception as e:
            report.append("roundtrip_error=%s" % e)

        bad = []
        for pid, pg in win._pages.items():
            try:
                if hasattr(pg, "load"):
                    pg.load(win.config)
                if hasattr(pg, "collect"):
                    pg.collect()
            except Exception as e:
                bad.append("%s: %s" % (pid, e))
        report.append("page_errors=%d" % len(bad))
        for b in bad:
            report.append("  ERR %s" % b)

        report.append("save=%s" % win._save_config(silent=True))

        # 侧边栏图标：Bootstrap Icons 的 SVG + QSvgRenderer，
        # 打包后要是 assets/icons 没进去或 QtSvg 缺失，这里能第一时间发现
        try:
            from panel_qt import icons as _ic
            from core import paths as _p
            idir = os.path.join(_p.assets_dir(), "icons")
            svgs = [f for f in os.listdir(idir) if f.endswith(".svg")] \
                if os.path.isdir(idir) else []
            report.append("icon_dir=%s" % idir)
            report.append("icon_svg_count=%d" % len(svgs))
            pm = _ic.pixmap("speedometer2", "#FFFFFF", 16)
            report.append("icon_render=%s" % ("OK" if not pm.isNull() else "EMPTY"))
            report.append("icon_size=%dx%d" % (pm.width(), pm.height()))
        except Exception as e:
            report.append("icon_error=%s" % e)

        # 转存适配器注册表：装饰器式注册 + 运行时动态 import，
        # 打包漏了就会全盘"暂不支持"，这里必须验
        try:
            from transfer import base as _tb
            report.append("pans=%s" % _tb.supported_pans())
            report.append("pans_all=%s" % _tb.registered_pans())
        except Exception as e:
            report.append("pans_error=%s" % e)

        try:
            from core import wx_compat
            report.append("wx_core=%s" % wx_compat.CORE_LABEL)
            report.append("wx_caps=%s" % wx_compat.CAPS)
        except Exception as e:
            report.append("wx_core_error=%s" % e)

        report.append("RESULT=OK" if not bad else "RESULT=FAIL")
    except Exception as e:
        import traceback
        report.append("FATAL=%s" % e)
        report.append(traceback.format_exc())
        report.append("RESULT=FAIL")

    out = os.path.join(paths.data_dir(), "_selftest.txt")
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(report))
    except Exception:
        pass
    return 0 if any("RESULT=OK" in r for r in report) else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    from panel_qt.app import run_panel
    sys.exit(run_panel())


if __name__ == "__main__":
    main()
