# -*- coding: utf-8 -*-
"""
环境自检。UI 自动化对运行环境有硬要求，这里逐项检查并给出可操作的修复建议。
面板首页直接渲染这个结果。
"""

import os
import sys
import ctypes
import platform
import subprocess

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

OK, WARN, FAIL = "ok", "warn", "fail"


def _item(name, level, detail, fix=""):
    return {"name": name, "level": level, "detail": detail, "fix": fix}


def _is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _session_is_interactive():
    """会话 0（服务）里没有桌面，UI 自动化必然失败。"""
    try:
        sid = ctypes.c_ulong()
        pid = ctypes.windll.kernel32.GetCurrentProcessId()
        if ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(sid)):
            return sid.value != 0, sid.value
    except Exception:
        pass
    return True, -1


def _desktop_locked():
    """锁屏时 OpenInputDesktop 会失败。"""
    try:
        user32 = ctypes.windll.user32
        h = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if h:
            user32.CloseDesktop(h)
            return False
        return True
    except Exception:
        return False


def _wechat_process():
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.check_output(
            'tasklist /FI "IMAGENAME eq WeChat.exe" /FO CSV /NH',
            shell=True, stderr=subprocess.DEVNULL, timeout=8,
            creationflags=_CREATE_NO_WINDOW).decode("gbk", "ignore")
        if "WeChat.exe" in out:
            return "WeChat.exe"
        out = subprocess.check_output(
            'tasklist /FI "IMAGENAME eq Weixin.exe" /FO CSV /NH',
            shell=True, stderr=subprocess.DEVNULL, timeout=8,
            creationflags=_CREATE_NO_WINDOW).decode("gbk", "ignore")
        if "Weixin.exe" in out:
            return "Weixin.exe"
    except Exception:
        pass
    return None


def _dpi_scale():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return round(dpi / 96.0, 2)
    except Exception:
        return 1.0


def run_all():
    items = []

    # 操作系统
    if sys.platform != "win32":
        items.append(_item("操作系统", FAIL,
                           "当前是 %s，wxauto 只能在 Windows 上运行" % sys.platform,
                           "请在 Windows 10/11 或 Windows Server 上运行"))
        return {"items": items, "level": FAIL}

    items.append(_item("操作系统", OK, "%s %s" % (platform.system(), platform.release())))

    # Python 版本（源码运行时才有意义）
    if not getattr(sys, "frozen", False):
        v = sys.version_info
        if (3, 9) <= (v.major, v.minor) <= (3, 12):
            items.append(_item("Python 版本", OK, "%d.%d" % (v.major, v.minor)))
        else:
            items.append(_item("Python 版本", WARN,
                               "%d.%d 不在 3.9–3.12 范围内" % (v.major, v.minor),
                               "免费版 wxauto4 只支持 3.9–3.12，建议用 3.12"))

    # 桌面会话
    interactive, sid = _session_is_interactive()
    if interactive:
        items.append(_item("桌面会话", OK, "会话 %s，有交互桌面" % sid))
    else:
        items.append(_item("桌面会话", FAIL, "运行在会话 0（服务会话），没有桌面",
                           "不要注册成 Windows 服务运行。"
                           "服务器上请用计划任务的「用户已登录时运行」，或保持一个 RDP 会话。"))

    # 锁屏
    if _desktop_locked():
        items.append(_item("屏幕状态", FAIL, "当前处于锁屏状态，UI 自动化会失败",
                           "服务器上用 RDP 连接后不要直接关窗口（会锁定会话），"
                           "改用 tscon 把会话转回控制台：\n"
                           "  tscon %SESSIONNAME% /dest:console\n"
                           "同时关掉屏幕保护和自动锁屏。"))
    else:
        items.append(_item("屏幕状态", OK, "桌面可用，未锁屏"))

    # 微信进程
    proc = _wechat_process()
    if proc:
        items.append(_item("微信客户端", OK, "%s 正在运行" % proc))
    else:
        items.append(_item("微信客户端", FAIL, "没有检测到微信进程",
                           "请先启动并登录微信 4.0 客户端，且不要最小化到托盘"))

    # 管理员
    if _is_admin():
        items.append(_item("运行权限", OK, "管理员"))
    else:
        items.append(_item("运行权限", WARN, "非管理员",
                           "建议右键「以管理员身份运行」，否则部分窗口操作可能失败"))

    # 缩放
    scale = _dpi_scale()
    if abs(scale - 1.0) < 0.01:
        items.append(_item("显示缩放", OK, "100%"))
    else:
        items.append(_item("显示缩放", WARN, "%d%%" % int(scale * 100),
                           "非 100% 缩放可能导致控件定位偏移。"
                           "建议在「显示设置」里改成 100%，改完注销重登。"))

    # 分辨率
    try:
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        if w < 1280 or h < 720:
            items.append(_item("分辨率", WARN, "%dx%d 偏小" % (w, h),
                               "虚拟机/无显示器服务器建议设为 1920x1080，"
                               "否则微信窗口可能装不下，控件取不到"))
        else:
            items.append(_item("分辨率", OK, "%dx%d" % (w, h)))
    except Exception:
        pass

    level = OK
    if any(i["level"] == WARN for i in items):
        level = WARN
    if any(i["level"] == FAIL for i in items):
        level = FAIL
    return {"items": items, "level": level}
