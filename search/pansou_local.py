# -*- coding: utf-8 -*-
"""
本地 pansou.exe 进程管理。

pansou 是 Go 编译的单文件二进制，随程序分发到 bin/pansou.exe，
程序启动时拉起、退出时关掉，用户无感。
"""

import os
import sys
import time
import socket
import logging
import subprocess
import threading

import requests

log = logging.getLogger("pansou.local")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _port_free(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) != 0


def pick_port(preferred, tries=30):
    if _port_free(preferred):
        return preferred
    for p in range(preferred + 1, preferred + tries):
        if _port_free(p):
            return p
    raise RuntimeError("找不到可用端口（从 %d 起试了 %d 个）" % (preferred, tries))


class PansouLocal:
    def __init__(self, exe_path, port=8888, channels="tgsearchers3",
                 extra_env=None, workdir=None):
        self.exe_path = exe_path
        self.want_port = port
        self.port = port
        self.channels = channels
        self.extra_env = dict(extra_env or {})
        self.workdir = workdir or os.path.dirname(exe_path)
        self.proc = None
        self.last_error = ""
        self._lock = threading.Lock()

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.port

    def available(self):
        return os.path.isfile(self.exe_path)

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, wait=25):
        with self._lock:
            if self.running():
                return True, "已在运行"
            if not self.available():
                self.last_error = "找不到 %s" % self.exe_path
                return False, self.last_error

            try:
                self.port = pick_port(self.want_port)
            except Exception as e:
                self.last_error = str(e)
                return False, self.last_error

            env = os.environ.copy()
            env["PORT"] = str(self.port)
            env["CHANNELS"] = self.channels
            env.setdefault("CACHE_PATH", os.path.join(self.workdir, "cache"))
            env.update({k: str(v) for k, v in self.extra_env.items()})

            try:
                os.makedirs(env["CACHE_PATH"], exist_ok=True)
            except Exception:
                pass

            try:
                self.proc = subprocess.Popen(
                    [self.exe_path],
                    cwd=self.workdir, env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    creationflags=_CREATE_NO_WINDOW,
                )
            except Exception as e:
                self.last_error = "启动失败: %s" % e
                return False, self.last_error

        deadline = time.time() + wait
        while time.time() < deadline:
            if self.proc.poll() is not None:
                err = ""
                try:
                    err = (self.proc.stderr.read() or b"").decode("utf-8", "ignore")[:400]
                except Exception:
                    pass
                self.last_error = "进程已退出: %s" % (err or "无输出")
                return False, self.last_error
            if self.health():
                log.info("pansou 已就绪 %s", self.base_url)
                return True, self.base_url
            time.sleep(0.7)

        self.last_error = "启动超时（%ds 内没有响应健康检查）" % wait
        self.stop()
        return False, self.last_error

    def health(self):
        for path in ("/api/health", "/api/status", "/"):
            try:
                r = requests.get(self.base_url + path, timeout=2.5)
                if r.status_code < 500:
                    return True
            except Exception:
                continue
        return False

    def stop(self):
        with self._lock:
            if not self.proc:
                return
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except Exception:
                pass
            self.proc = None

    def status(self):
        return {
            "available": self.available(),
            "running": self.running(),
            "port": self.port,
            "base_url": self.base_url if self.running() else "",
            "exe": self.exe_path,
            "error": self.last_error,
        }
