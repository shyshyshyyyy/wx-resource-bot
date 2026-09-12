# -*- coding: utf-8 -*-
"""
wxautox4 / wxauto4 兼容层 —— 底座(SiverWXbot_plus)唯一的内核入口。

底座原本在模块顶层写死 `from wxautox4 import WeChat`，没有免费回退。
这里把内核选择收拢到一处：

  Plus 可用且已激活  → 用 wxautox4，能力全开
  否则               → 用 wxauto4 免费版，缺失的增强能力自动降级

降级原则：**静默降级，不抛异常打断业务**。
朋友圈、全局监听这类免费版真没有的能力，返回空/失败并在日志里说明，
让上层按"没取到"处理，而不是让整个机器人挂掉。

对外导出（与 wxautox4 同名，底座代码无需改动）：
    WeChat, WxParam, msgs, check_license, CORE, CORE_LABEL, CAPS
"""

import logging

log = logging.getLogger("wx_compat")

CORE_PLUS = "plus"
CORE_FREE = "free"
CORE_NONE = "none"


# ----------------------------------------------------------
# 降级用的占位实现
# ----------------------------------------------------------
class _StubMoments:
    """免费版没有朋友圈，返回空结果而不是抛异常。"""

    def GetMoments(self, *a, **kw):
        return []

    def Publish(self, *a, **kw):
        return _fail("免费版 wxauto4 不支持发布朋友圈")

    def Close(self, *a, **kw):
        return None


def _ok(**kw):
    return dict(status="成功", message="", data=kw or None)


def _fail(msg):
    return dict(status="失败", message=msg, data=None)


def _patch_message_classes(msgs_mod):
    """给免费版的消息类补上 Plus 才有的方法（全部返回失败/空）。"""
    from wxauto4.param import WxResponse as _WxResponse

    def _unsupported(name):
        def _fn(self, *a, **kw):
            log.debug("免费版不支持 %s，已跳过", name)
            return None
        _fn.__name__ = name
        return _fn

    def _download(self, *a, **kw):
        log.debug("免费版不支持下载消息附件，已跳过")
        return None

    def _forward(self, targets, message=None, timeout=3, interval=0.1):
        log.debug("免费版不支持转发消息，已跳过")
        return _WxResponse("失败", "免费版不支持转发消息")

    def _quote(self, text, at=None, timeout=3):
        log.debug("免费版不支持引用回复，降级为普通发送")
        return _WxResponse("失败", "免费版不支持引用回复")

    patches = {
        "download": _download,
        "download_quote_image": _download,
        "to_text": _unsupported("to_text"),
        "ocr": _unsupported("ocr"),
        "forward": _forward,
        "quote": _quote,
        "sender_info": _unsupported("sender_info"),
        "get_content": _unsupported("get_content"),
        "save_files": _unsupported("save_files"),
        "to_markdown": _unsupported("to_markdown"),
    }
    for cls_name in dir(msgs_mod):
        cls = getattr(msgs_mod, cls_name)
        if not isinstance(cls, type):
            continue
        if not cls_name.endswith("Message") and cls_name != "Message":
            continue
        for method, impl in patches.items():
            if not hasattr(cls, method):
                try:
                    setattr(cls, method, impl)
                except Exception:
                    pass


# ----------------------------------------------------------
# 内核探测
# ----------------------------------------------------------
def _probe_plus_activated():
    """wxautox4 是否装了且已激活。任一策略给出明确结论即采信。"""
    try:
        import wxautox4  # noqa: F401
    except Exception:
        return False, "未安装 wxautox4"

    try:
        import wxautox4 as x
        for name in ("check_license", "check_activation", "is_activated"):
            fn = getattr(x, name, None)
            if callable(fn):
                try:
                    if bool(fn()):
                        return True, "wxautox4 已激活"
                except Exception:
                    continue
        from wxautox4.utils.useful import check_license as _cl  # noqa
        try:
            if bool(_cl()):
                return True, "wxautox4 已激活"
        except Exception:
            pass
    except Exception as e:
        return False, "wxautox4 激活检测失败: %s" % e

    return False, "wxautox4 未激活"


def activate_plus(code):
    """
    尝试用授权码激活 wxautox4 内核。
    返回 (ok: bool, msg: str)。

    wxautox4 不同版本暴露的激活入口不完全一致，这里按候选名依次尝试，
    每次调用后重新探测激活状态，以探测结果为准。
    """
    if not code or not str(code).strip():
        return False, "请输入授权码"
    code = str(code).strip()

    try:
        import wxautox4 as x
    except Exception:
        return False, ("未安装 wxautox4 内核，无法激活。"
                       "当前使用免费版 wxauto4，基础收发与监听不受影响。")

    modules = _iter_plus_modules()

    names = ("authenticate", "activate", "activate_license", "set_license",
             "register", "license", "check_and_activate", "auth")
    last_err = ""
    for mod in modules:
        for n in names:
            fn = getattr(mod, n, None)
            if not callable(fn):
                continue
            try:
                try:
                    ret = fn(code)
                except TypeError:
                    continue
                ok, detail = _probe_plus_activated()
                if ok:
                    # 关键：持久化授权，否则重启后又是免费版。两样都存：
                    #  ① 授权文件 —— wxautox4 默认只写在「当前工作目录」，
                    #     exe 的 CWD 不可控，必须挪到稳定的 data/ 下。
                    #  ② 授权码   —— 在线激活未必落文件，留着码下次可重新激活。
                    parts = []
                    if _save_license_dat():
                        parts.append("授权文件已保存到 data/")
                    if _save_license_code(code):
                        parts.append("授权码已保存")
                    if parts:
                        detail = "%s（%s，重启后仍为 Plus 版）" % (
                            detail, "、".join(parts))
                    else:
                        detail = ("%s（警告：授权未能持久化，重启后可能需要"
                                  "重新激活）" % detail)
                    return True, detail
                return False, "已调用 %s()，但激活状态未生效：%s（返回：%s）" % (
                    getattr(mod, "__name__", "?") + "." + n, detail, ret)
            except Exception as e:
                last_err = "%s.%s: %s" % (getattr(mod, "__name__", "?"), n, e)
                continue

    return False, last_err or "未找到可用的激活入口，请确认 wxautox4 版本"


def _detect(prefer="auto"):
    """
    返回 (core, WeChat, WxParam, msgs, check_license, detail)
    prefer: auto | plus | free
    """
    if prefer != "free":
        activated, detail = _probe_plus_activated()
        if activated:
            try:
                import wxautox4
                from wxautox4 import WeChat as _PlusWeChat, WxParam as _PlusParam
                from wxautox4 import msgs as _plus_msgs
                from wxautox4.utils.useful import check_license as _plus_check
                return (CORE_PLUS, _PlusWeChat, _PlusParam, _plus_msgs,
                        _plus_check, detail)
            except Exception as e:
                detail = "wxautox4 导入失败: %s" % e
        if prefer == "plus":
            return (CORE_NONE, None, None, None, None,
                    "Plus 不可用：%s" % detail)

    try:
        import wxauto4
        from wxauto4 import WeChat as _FreeWeChat, WxParam as _FreeParam
        from wxauto4 import msgs as _free_msgs
        _patch_message_classes(_free_msgs)

        class _FreeWeChatPatched(_FreeWeChat):
            """免费版：把 Plus 专属方法补成安全降级。"""

            # ---- 朋友圈 ----
            def Moments(self, timeout=3):
                log.debug("免费版不支持朋友圈，返回空")
                return _StubMoments()

            def PublishMoment(self, text=None, media_files=None,
                              privacy_config=None):
                return _fail("免费版 wxauto4 不支持发布朋友圈")

            # ---- 消息获取（Plus 专用轮询接口）----
            def GetNextNewMessage(self, filter_mute=False, callback=None,
                                  timeout=None):
                log.debug("免费版不支持 GetNextNewMessage（全局监听模式）")
                return {}

            def GetListenMessage(self, who=None):
                log.debug("免费版不支持 GetListenMessage")
                return {}

            def GetHistoryMessage(self, n, callback=None, interval=0.2,
                                   speed=1, goback=True, timeout=None):
                return []

            # ---- 好友 ----
            def GetNewFriends(self, acceptable=True, roll_times=0):
                return []

            def AddNewFriend(self, keywords, addmsg=None, remark=None,
                             tags=None, permission="朋友圈", timeout=5):
                return _fail("免费版不支持添加好友")

            def GetFriendDetails(self, n=None, timeout=0xFFFFF, **kw):
                return []

            def GetTagContacts(self, tag, **kw):
                return None

            # ---- 群 ----
            def CreateGroup(self, contacts):
                return _fail("免费版不支持建群")

            def SetGroupName(self, value):
                return _fail("免费版不支持改群名")

            def SetGroupRemark(self, value):
                return _fail("免费版不支持改群备注")

            def SetGroupAnnouncement(self, value):
                return _fail("免费版不支持群公告")

            def SetGroupMyNickname(self, value):
                return _fail("免费版不支持改群昵称")

            def GetAllRecentGroups(self, speed=1, interval=0.1, timeout=None):
                return []

            def GetDialog(self, wait=3):
                return None

            # ---- 发送增强 ----
            def SendUrlCard(self, url, friends, message=None, timeout=10):
                return _fail("免费版不支持链接卡片")

            def SendAudio(self, filepath, duration=None, start=0, who=None,
                          exact=False, max_retries=3):
                return _fail("免费版不支持发送语音")

        return (CORE_FREE, _FreeWeChatPatched, _FreeParam, _free_msgs,
                _free_check_license, "回落到免费版 wxauto4")
    except Exception as e:
        return (CORE_NONE, None, None, None, None,
                "wxauto4 / wxautox4 都不可用: %s" % e)


def _free_check_license():
    """
    免费版没有内核授权概念。
    返回 False，让底座知道「Plus 未激活」——但底座已被改成回退而非退出，
    真正的软件授权由 license.py 独立控制，两者互不影响。
    """
    return False


# ----------------------------------------------------------
# Plus 授权持久化
#
# 客户反馈「买了 wxautox4 授权码，激活后程序仍显示免费版」，根因有三：
#
# 1. wxautox4 原生只认「当前工作目录」下的 WXAUTOX_LICENSE ——
#    get_licence_file() 返回的是**相对路径**。打包成 exe 后 CWD 不可控
#    （双击/快捷方式/开机自启时 CWD 可能是 System32），激活时写进去、
#    重启后文件找不到 → check_license() 返回 False → 又变免费版。
# 2. 授权文件没被打进 exe（spec 的 datas 为空），且**不能**打 ——
#    开发者的授权绑定开发者机器，给客户毫无用处。
# 3. CORE 是模块级一次性计算，activate_plus() 成功后当前进程的 CORE
#    不会变，面板永远显示「免费版」。
#
# 对策：激活成功后把授权文件复制到 data/wxautox_license.dat（稳定目录），
# 每次启动**在 _detect 之前**显式加载它；并提供 reload_core() 让面板
# 立即刷新内核状态。
# ----------------------------------------------------------
import os as _os  # noqa: E402

_LICENSE_DAT_NAME = "wxautox_license.dat"
_LICENSE_CODE_NAME = "wxautox_code.txt"


def plus_license_dat():
    """本程序持久化的 wxautox4 授权文件路径：{data}/wxautox_license.dat"""
    try:
        from core import paths as _p
        return _os.path.join(_p.data_dir(), _LICENSE_DAT_NAME)
    except Exception:
        return None


def plus_license_code_file():
    """持久化的 wxautox4 授权码：{data}/wxautox_code.txt。

    为什么要连授权码一起存：wxautox4 在线激活未必落授权文件（只在本机内存里
    生效），此时 authenticate_with_file 就无从下手。留着码，下次启动可以重新
    authenticate(code)。软件授权（license.py）本来就是这么存的，保持一致。
    """
    try:
        from core import paths as _p
        return _os.path.join(_p.data_dir(), _LICENSE_CODE_NAME)
    except Exception:
        return None


def _iter_plus_modules():
    """wxautox4 里可能暴露授权接口的模块（不同版本位置不同）"""
    mods = []
    for name in ("wxautox4", "wxautox4.utils.useful", "wxautox4.utils",
                 "wxautox4.license"):
        try:
            mods.append(__import__(name, fromlist=["*"]))
        except Exception:
            continue
    return mods


def _call_plus(fn_names, *args):
    """按候选名依次尝试调用，返回 (是否调用成功, 返回值或错误信息)。"""
    for mod in _iter_plus_modules():
        for n in fn_names:
            fn = getattr(mod, n, None)
            if not callable(fn):
                continue
            try:
                return True, fn(*args)
            except TypeError:
                continue          # 签名不符，换下一个候选
            except Exception as e:
                return True, "%s.%s: %s" % (
                    getattr(mod, "__name__", "?"), n, e)
    return False, None


def load_saved_license():
    """启动时恢复 wxautox4 授权。返回 (ok, detail)。

    必须在 _detect() 之前调用 —— 否则内核探测时 check_license() 还是 False。

    两级恢复：
      ① 授权文件（离线可用，优先）
      ② 授权码（需要网络，作为授权文件缺失/失效时的兜底）
    """
    path = plus_license_dat()
    if path and _os.path.exists(path):
        called, ret = _call_plus(
            ("authenticate_with_file2", "authenticate_with_file"), path)
        if called:
            ok, detail = _probe_plus_activated()
            if ok:
                return True, "已加载已保存的授权文件"
            log.warning("已保存的授权文件未生效：%s（返回：%s）", detail, ret)
        else:
            log.warning("wxautox4 未提供授权文件加载入口")

    code_path = plus_license_code_file()
    if code_path and _os.path.exists(code_path):
        try:
            with open(code_path, "r", encoding="utf-8") as f:
                code = f.read().strip()
        except Exception:
            code = ""
        if code:
            called, ret = _call_plus(("authenticate",), code)
            if called:
                ok, detail = _probe_plus_activated()
                if ok:
                    _save_license_dat()      # 顺手把文件也补上，下次离线可用
                    return True, "已用保存的授权码重新激活"
                log.warning("保存的授权码未能激活：%s（返回：%s）", detail, ret)
    return False, "无已保存的 wxautox4 授权"


def _save_license_code(code):
    """把授权码本身存到 data/ 下，作为授权文件缺失时的兜底。"""
    p = plus_license_code_file()
    if not p or not code:
        return None
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(str(code).strip())
        return p
    except Exception:
        return None


def _save_license_dat():
    """把 wxautox4 刚生成的授权文件复制到 data/ 下持久化。返回保存路径或 None。"""
    dest = plus_license_dat()
    if not dest:
        return None
    # 候选位置：wxautox4 报的路径（可能是相对 CWD）、CWD、exe 目录、data 目录。
    # 打包成 exe 后 CWD 不可控（快捷方式/开机自启时可能是 System32），
    # 所以四个地方都要试，不能只信 get_licence_file()。
    cands = []
    for mod in _iter_plus_modules():
        fn = getattr(mod, "get_licence_file", None)
        if callable(fn):
            try:
                v = fn()
            except Exception:
                v = None
            if v:
                cands.append(v)
    cands.append("WXAUTOX_LICENSE")
    try:
        from core import paths as _p
        cands.append(_os.path.join(_p.app_dir(), "WXAUTOX_LICENSE"))
        cands.append(_os.path.join(_p.data_dir(), "WXAUTOX_LICENSE"))
    except Exception:
        pass

    src = None
    for c in cands:
        if not c:
            continue
        p = c if _os.path.isabs(c) else _os.path.join(_os.getcwd(), c)
        if _os.path.exists(p):
            src = p
            break
    if not src:
        return None
    try:
        with open(src, "rb") as f:
            data = f.read()
        if not data:
            return None
        with open(dest, "wb") as f:
            f.write(data)
        return dest
    except Exception:
        return None


# ----------------------------------------------------------
# 模块级导出
# ----------------------------------------------------------

_PREFER = (_os.environ.get("WXBOT_CORE") or "auto").strip().lower()

# 先加载已保存的授权，再探测内核 —— 顺序不能反，
# 否则 CORE 会在授权生效前就被判定为免费版。
_SAVED_OK, _SAVED_DETAIL = load_saved_license()

CORE, WeChat, WxParam, msgs, check_license, CORE_DETAIL = _detect(_PREFER)

CORE_LABEL = {
    CORE_PLUS: "Plus 版（wxautox4）",
    CORE_FREE: "免费版（wxauto4）",
    CORE_NONE: "内核不可用",
}.get(CORE, CORE)

def _build_caps(core):
    """能力表：上层据此决定功能是否可用（面板上显示为"需要 Plus"）"""
    return {
        "moments": core == CORE_PLUS,              # 朋友圈
        "global_listen": core == CORE_PLUS,        # 全局（黑名单）监听模式
        "download_media": core == CORE_PLUS,       # 下载图片/文件（图片识别依赖）
        "quote_reply": core == CORE_PLUS,          # 引用回复
        "forward_msg": core == CORE_PLUS,          # 转发消息
        "new_friends": core == CORE_PLUS,          # 好友申请处理
        "url_card": core == CORE_PLUS,             # 链接卡片
        "listen": core != CORE_NONE,               # 回调监听（两个内核都有）
        "send": core != CORE_NONE,                 # 发消息（两个内核都有）
        "at": core == CORE_PLUS,                   # @某人（SendMsg 的 at 参数，仅 Plus）
    }


CAPS = _build_caps(CORE)


def reload_core():
    """重新探测内核并刷新模块级导出（激活 Plus 后调用，面板可立即显示新内核）。

    注意：只会刷新本模块的 CORE / WeChat / CAPS 等**引用**。已经在别处
    `from core.wx_compat import WeChat` 值导入的模块不会跟着变，且已创建的
    WeChat 实例仍是旧内核的 —— 所以激活后**仍建议重启软件**，
    这里只是让面板状态立刻正确、避免客户以为"激活没生效"。
    """
    global CORE, WeChat, WxParam, msgs, check_license, CORE_DETAIL, CORE_LABEL
    global _SAVED_OK, _SAVED_DETAIL
    if CORE != CORE_PLUS:
        # 也许授权文件是刚保存的，先尝试加载再探测
        _SAVED_OK, _SAVED_DETAIL = load_saved_license()
    CORE, WeChat, WxParam, msgs, check_license, CORE_DETAIL = _detect(_PREFER)
    CORE_LABEL = {
        CORE_PLUS: "Plus 版（wxautox4）",
        CORE_FREE: "免费版（wxauto4）",
        CORE_NONE: "内核不可用",
    }.get(CORE, CORE)
    CAPS.clear()
    CAPS.update(_build_caps(CORE))
    log.info("内核已重新探测: %s (%s)", CORE_LABEL, CORE_DETAIL)
    return CORE, CORE_LABEL, CORE_DETAIL


__all__ = ["WeChat", "WxParam", "msgs", "check_license", "CORE",
           "CORE_LABEL", "CORE_DETAIL", "CAPS",
           "CORE_PLUS", "CORE_FREE", "CORE_NONE",
           "activate_plus", "reload_core", "load_saved_license",
           "plus_license_dat"]

log.info("微信内核: %s (%s)", CORE_LABEL, CORE_DETAIL)
if _SAVED_OK:
    log.info("wxautox4 授权: %s", _SAVED_DETAIL)
