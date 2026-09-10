# -*- coding: utf-8 -*-
"""
入口。

隐藏参数 --wx-cli：打包成 exe 后没有 python.exe，
用自身 exe 代跑 wxautox4 的命令行（激活/查询激活状态）。
"""

import os
import sys
import time
import logging
import threading
import webbrowser


def _wx_cli_passthrough():
    """把 --wx-cli 之后的参数原样交给 wxautox4 的 main。"""
    args = sys.argv[sys.argv.index("--wx-cli") + 1:]
    try:
        import wxautox4
    except Exception as e:
        print("wxautox4 未安装: %s" % e)
        return 2
    sys.argv = ["wxautox4"] + args
    for modname in ("wxautox4.__main__", "wxautox4.cli", "wxautox4"):
        try:
            mod = __import__(modname, fromlist=["main"])
            fn = getattr(mod, "main", None)
            if callable(fn):
                r = fn()
                return int(r or 0)
        except SystemExit as e:
            return int(e.code or 0)
        except Exception:
            continue
    print("找不到 wxautox4 命令行入口")
    return 3


if "--wx-cli" in sys.argv:
    sys.exit(_wx_cli_passthrough())


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config_manager as cm            # noqa: E402
import license as lic                  # noqa: E402
from core.bot import Bot               # noqa: E402
from search.pansou_local import PansouLocal   # noqa: E402
from search.pansou_client import PansouClient  # noqa: E402
from transfer import base as tbase     # noqa: E402
from panel import server as psrv       # noqa: E402

# 注册转存适配器（子类在 import 时通过 @register 自动登记）
try:
    from transfer import adapters      # noqa: F401,E402
except Exception:
    pass

log = logging.getLogger("main")


def setup_logging(cfg):
    level = getattr(logging, cfg.get("advanced", {}).get("log_level", "INFO"), logging.INFO)
    logdir = os.path.join(cm.data_dir(), "logs")
    os.makedirs(logdir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)

    fh = logging.FileHandler(
        os.path.join(logdir, time.strftime("%Y-%m-%d") + ".log"), encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if sys.stdout:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    psrv.install_log_handler()


class Runtime:
    """把各模块串起来，面板通过它控制运行时。"""

    def __init__(self):
        self.cfg = cm.load_config()
        self.local = None
        self.searcher = None
        self.pool = tbase.AccountPool(self.cfg, cm.save_config)
        self.transfer = tbase.TransferService(self.cfg, self.pool)
        self.bot = None
        self._build()

    def _build(self):
        lcfg = self.cfg.get("search", {}).get("local", {})
        exe = lcfg.get("exe", "bin/pansou.exe")
        if not os.path.isabs(exe):
            exe = os.path.join(cm.app_dir(), exe)
        self.local = PansouLocal(
            exe_path=exe, port=int(lcfg.get("port", 8888)),
            channels=lcfg.get("channels", "tgsearchers3"),
            extra_env=lcfg.get("extra_env", {}),
            workdir=cm.data_dir())
        self.searcher = PansouClient(self.cfg, self.local)

    def reload(self):
        self.cfg = cm.load_config(force=True)
        self._build()
        self.pool.cfg = self.cfg
        self.transfer.cfg = self.cfg
        if self.bot:
            self.bot.cfg = self.cfg
            self.bot.searcher = self.searcher

    def autostart(self):
        lcfg = self.cfg.get("search", {}).get("local", {})
        if lcfg.get("enabled") and lcfg.get("autostart", True):
            ok, msg = self.local.start()
            log.info("本地盘搜：%s", msg) if ok else log.warning("本地盘搜启动失败：%s", msg)

    def start_bot(self):
        info = lic.check_license(self.cfg)
        if not info["ok"]:
            return False, "未激活：%s" % info["msg"]
        if not self.bot:
            self.bot = Bot(self.cfg, self.searcher, self.transfer, info)
        self.bot.license_info = info
        return self.bot.start()

    def stop_bot(self):
        if not self.bot:
            return True, "未在运行"
        return self.bot.stop()


def main():
    cfg = cm.load_config()
    setup_logging(cfg)

    log.info("=" * 52)
    log.info("微信资源搜索机器人启动")
    log.info("程序目录: %s", cm.app_dir())
    log.info("机器码: %s", lic.get_machine_code())

    info = lic.check_license(cfg)
    log.info("授权状态: %s", info["msg"])

    runtime = Runtime()
    threading.Thread(target=runtime.autostart, daemon=True).start()

    app = psrv.create_app(runtime)

    p = cfg.get("panel", {})
    host, port = p.get("host", "127.0.0.1"), int(p.get("port", 8765))
    url = "http://127.0.0.1:%d/" % port
    log.info("控制台: %s", url)

    if p.get("auto_open_browser", True):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn
    uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger("main").exception("启动失败")
        if sys.stdout and sys.stdout.isatty():
            input("按回车退出…")
        raise
