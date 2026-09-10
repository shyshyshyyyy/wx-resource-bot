# -*- coding: utf-8 -*-
"""
转存适配器基类 + 账号池。

每个网盘实现一个子类，只需实现 4 个方法：
    check()        校验 cookie 是否有效
    list_dir()     列目录（面板选转存文件夹用）
    save()         把分享链接转存到自己的网盘
    share()        把转存到的文件生成分享链接

具体的接口签名、加密参数需要从 xinyue-search 的 PHP 实现移植，
子类里标了 NotImplementedError 的地方就是待填的。
"""

import abc
import time
import uuid
import random
import logging
import threading

log = logging.getLogger("transfer")

_REGISTRY = {}
_ADAPTERS_LOADED = False


def _ensure_adapters():
    """确保 transfer/adapters.py 已被导入。

    各适配器靠 @register 装饰器登记到 _REGISTRY，而装饰器只有在模块被
    **导入时**才执行。命令行入口 main.py 里有显式 import，但 PySide6 面板
    入口不经过它 —— 结果就是注册表一片空白，get_adapter() 全返回 None，
    表现为"暂不支持 quark"（实际上连自动转存、分享转链都是坏的）。
    这里统一兜底，任何入口都不会漏。
    """
    global _ADAPTERS_LOADED
    if _ADAPTERS_LOADED:
        return
    _ADAPTERS_LOADED = True          # 先置位，避免循环导入时递归
    try:
        import transfer.adapters  # noqa: F401
    except Exception as e:
        log.warning("转存适配器加载失败: %s", e)


def register(pan_key):
    def deco(cls):
        _REGISTRY[pan_key] = cls
        cls.PAN = pan_key
        return cls
    return deco


def get_adapter(pan_key):
    _ensure_adapters()
    return _REGISTRY.get(pan_key)


def registered_pans():
    """所有已登记的网盘（含骨架未填完的）。"""
    _ensure_adapters()
    return sorted(_REGISTRY.keys())


def supported_pans():
    """真正能用的网盘：适配器已接入实现。"""
    _ensure_adapters()
    return sorted(k for k, c in _REGISTRY.items()
                  if getattr(c, "IMPLEMENTED", False))


def is_implemented(pan_key):
    _ensure_adapters()
    cls = _REGISTRY.get(pan_key)
    return bool(cls and getattr(cls, "IMPLEMENTED", False))


class TransferError(Exception):
    def __init__(self, msg, retryable=False, invalid_account=False, dead_link=False):
        super().__init__(msg)
        self.retryable = retryable
        self.invalid_account = invalid_account
        # dead_link：源分享链接本身失效（被取消/封禁/清空），与买家自己的
        # 网盘账号无关。单独归类，是为了让 bot 给出"这是上游资源问题"的
        # 准确提示，而不是误导用户去查自己的 Cookie。
        self.dead_link = dead_link


# ----------------------------------------------------------------------
# 失败原因分类：把 TransferError 的文字归到 3 类，
# 这样 bot 层不必关心各网盘五花八门的错误措辞，只需按类别给不同提示。
# 适配器里个别 raise 已经标了 invalid_account / retryable，
# 但「死链」类错误（源链接失效）散落在 30 多处文案里、且 pansou 服务端
# 直接返回的失败原因（如"分享者用户封禁链接查看受限"）根本不走适配器，
# 所以这里再做一层基于关键词的兜底分类，确保都能被正确识别。
# 优先级：账号失效 > 死链 > 可重试 > 其他。
# ----------------------------------------------------------------------
_DEAD_LINK_HINTS = (
    "已失效", "链接失效", "分享内容为空", "读不到分享内容", "分享已失效",
    "资源已失效", "内容为空", "链接可能已失效", "没取到分享参数",
    "内容为空或全是广告", "已删除", "访问受限", "查看受限", "被取消",
    "不存在", "封禁", "链接获取失败",
)
_ACCOUNT_HINTS = (
    "登录状态失效", "请更新 cookie", "请更新cookie", "请重新获取 refresh_token",
    "登录失效", "refresh_token 已失效", "令牌可能已失效", "身份验证失败",
    "未授权", "unauthorized", "cookie 已", "cookie已",
)
_RETRY_HINTS = (
    "请求过于频繁", "网络错误", "网络超时", "timeout", "被风控拦截",
    "响应不是 json", "验证码", "captcha", "登录校验",
)


def classify_transfer_error(msg):
    """把一段错误文字归类。返回 {retryable, invalid_account, dead_link}。"""
    m = (msg or "").lower()
    if any(h in m for h in _ACCOUNT_HINTS):
        return {"retryable": False, "invalid_account": True, "dead_link": False}
    if any(h in m for h in _DEAD_LINK_HINTS):
        return {"retryable": False, "invalid_account": False, "dead_link": True}
    if any(h in m for h in _RETRY_HINTS):
        return {"retryable": True, "invalid_account": False, "dead_link": False}
    return {"retryable": False, "invalid_account": False, "dead_link": False}


class ShareResult(dict):
    """转存结果：{"url": ..., "password": ..., "expire": ...}"""


class BaseAdapter(abc.ABC):
    PAN = "base"
    NAME = "网盘"

    def __init__(self, account, cfg=None, save_fn=None):
        self.account = account          # dict，见 config_manager.ACCOUNT_TEMPLATE
        self.cookie = account.get("cookie", "")
        # cfg / save_fn：用于把「账号配置在运行期的变更」（如迅雷 refresh_token
        # 轮转）写回磁盘。不注入时静默跳过，保持向后兼容。
        self._cfg = cfg
        self._save_fn = save_fn

    def _persist_account(self):
        """把 self.account 的就地修改（如迅雷 refresh_token 轮转）写回磁盘配置。

        不注入 save_fn 时静默跳过；失败只告警不抛出，避免影响主流程。
        """
        if self._save_fn is None:
            return
        try:
            self._save_fn(self._cfg if self._cfg is not None else self.account)
        except Exception as e:
            log.warning("[%s] 账号配置持久化失败: %s", self.PAN, e)

    # ---------- 子类必须实现 ----------
    @abc.abstractmethod
    def check(self):
        """返回 (ok: bool, msg: str)。用来在面板上显示账号状态。"""

    @abc.abstractmethod
    def list_dir(self, parent_id="0"):
        """返回 [{"id":..., "name":..., "is_dir":True}]，供面板选文件夹。"""

    @abc.abstractmethod
    def save(self, share_url, password="", target_dir_id=""):
        """转存。返回本次转存产生的文件/目录 ID 列表。"""

    @abc.abstractmethod
    def share(self, file_ids, title="", expire_days=0):
        """生成分享。返回 ShareResult。"""

    # ---------- 可选覆盖 ----------
    def cleanup(self, file_ids):
        """删除转存出来的文件。默认不做。"""
        return True

    def create_dir(self, parent_id, name):
        """在 parent_id 下新建文件夹，返回 {"id":..., "name":...}。

        与 xinyue-search 的 createFolder 对齐：同名文件夹直接复用，不重复建。
        适配器实现 _create_dir(parent_id, name) -> {"id","name"}。
        """
        name = (name or "").strip()
        if not name:
            raise TransferError("文件夹名不能为空")
        fn = getattr(self, "_create_dir", None)
        if fn is None:
            raise TransferError("%s 暂不支持在线新建文件夹，请直接在网盘里建好再选择"
                                % self.NAME)
        return fn(parent_id, name)

    # ---------- 通用流程 ----------
    def transfer_and_share(self, share_url, password="", title="", expire_days=0,
                           use_temp=False, cleanup_after=False):
        """转存 + 分享。

        use_temp       ：用「临时目录」（分享有效期非永久时走它），
                         与 xinyue-search 的 quark_file_time 对应。
        cleanup_after  ：分享后是否删掉刚转存的文件。**默认 False** ——
                         删了文件分享链接立刻失效，只有明确要"阅后即焚"
                         的场景才开（比如只想要个一次性短链）。
        """
        dir_id = (self.account.get("temp_dir_id") if use_temp
                  else self.account.get("save_dir_id")) or ""
        file_ids = self.save(share_url, password, dir_id)
        if not file_ids:
            raise TransferError("转存后没有拿到文件 ID")
        result = self.share(file_ids, title=title, expire_days=expire_days)
        if cleanup_after:
            try:
                self.cleanup(file_ids)
            except Exception as e:
                log.warning("[%s] 转存文件清理失败: %s", self.PAN, e)
        return result


# ----------------------------------------------------------
# 账号池
# ----------------------------------------------------------
class AccountPool:
    """
    按网盘分组管理账号，轮转使用，超日限或失效自动跳过。
    夸克/迅雷这类风控严的盘，靠这个把单账号频率压下来。
    """

    def __init__(self, config_ref, save_fn):
        self.cfg = config_ref
        self.save_fn = save_fn
        self._lock = threading.RLock()
        self._cursor = {}

    def _accounts(self):
        return self.cfg.get("transfer", {}).setdefault("accounts", [])

    def add(self, data):
        with self._lock:
            acc = dict(data)
            acc.setdefault("id", uuid.uuid4().hex[:12])
            acc.setdefault("status", "unknown")
            self._accounts().append(acc)
            self.save_fn(self.cfg)
            return acc

    def update(self, acc_id, data):
        with self._lock:
            for acc in self._accounts():
                if acc.get("id") == acc_id:
                    acc.update(data)
                    self.save_fn(self.cfg)
                    return acc
        return None

    def remove(self, acc_id):
        with self._lock:
            accs = self._accounts()
            for i, acc in enumerate(accs):
                if acc.get("id") == acc_id:
                    accs.pop(i)
                    self.save_fn(self.cfg)
                    return True
        return False

    def list(self, pan=None):
        accs = self._accounts()
        if pan:
            return [a for a in accs if a.get("pan") == pan]
        return list(accs)

    def usable(self, pan):
        """可用账号 = 该网盘 + 启用 + 有凭据。

        不再用 ``status=="invalid"`` 永久封禁账号。失效是「实时」概念，
        应由每次转存时的真实请求判定，而不是卡在某次失败后的陈旧标记上——
        否则会出现「明明填了有效 cookie，却一直报 没有可用账号」的怪象
        （典型场景：初次检测失败 / 某次转存偶发 401，status 被钉死为
        invalid，之后即使 cookie 已更新也永远被跳过）。

        status 字段仅用于面板展示（上次检测：正常/失效），不再参与门控。
        """
        out = []
        with self._lock:
            for acc in self._accounts():
                if acc.get("pan") != pan or not acc.get("enabled", True):
                    continue
                if not acc.get("cookie"):
                    continue
                out.append(acc)
        return out

    def acquire(self, pan):
        """取一个可用账号，轮转起点避免总是打第一个号。

        优先取「未判失效」的账号（跳过明确失效的，省一次必然失败的请求）；
        若同网盘所有账号都曾被判失效，则仍挑一个出来实时试一次——
        cookie 可能已更新、或过期 refresh_token 已被刷新，试一次即可自愈，
        不会再卡在「没有可用账号」。
        """
        pool = self.usable(pan)
        if not pool:
            return None
        good = [a for a in pool if a.get("status") != "invalid"]
        candidates = good or pool
        with self._lock:
            i = self._cursor.get(pan, random.randrange(len(candidates)))
            self._cursor[pan] = (i + 1) % max(1, len(candidates))
            return candidates[i % len(candidates)]

    def mark_used(self, acc_id, ok=True, invalid=False):
        with self._lock:
            for acc in self._accounts():
                if acc.get("id") != acc_id:
                    continue
                if ok:
                    acc["status"] = "ok"
                elif invalid:
                    acc["status"] = "invalid"
                acc["last_check"] = int(time.time())
                self.save_fn(self.cfg)
                return


# ----------------------------------------------------------
# 高层转存服务
# ----------------------------------------------------------
class TransferService:
    def __init__(self, config, pool):
        self.cfg = config
        self.pool = pool

    def available_pans(self):
        return [p for p in supported_pans() if self.pool.usable(p)]

    def run(self, pan, share_url, password="", title=""):
        """
        返回 (ShareResult | None, error_msg, category)。
        category = {retryable, invalid_account, dead_link}，供 bot 层按类别给提示。
        """
        _OK = {"retryable": False, "invalid_account": False, "dead_link": False}
        cls = get_adapter(pan)
        if cls is None:
            return None, "暂不支持「%s」的自动转存" % pan, _OK

        tcfg = self.cfg.get("transfer", {})
        retry = int(tcfg.get("retry", 2))
        expire = int(tcfg.get("share_expire_days", 0))
        cleanup_after = bool(tcfg.get("cleanup_after_share", False))

        last_err = "没有可用账号"
        last_exc = None
        for attempt in range(retry + 1):
            acc = self.pool.acquire(pan)
            if not acc:
                return None, last_err, _OK
            try:
                adapter = cls(acc, cfg=self.cfg, save_fn=self.pool.save_fn)
                # 只有「有效期非永久」才走临时目录，且必须有配置才切
                use_temp = bool(expire and acc.get("temp_dir_id"))
                res = adapter.transfer_and_share(
                    share_url, password=password, title=title,
                    expire_days=expire, use_temp=use_temp,
                    cleanup_after=cleanup_after)
                self.pool.mark_used(acc["id"], ok=True)
                return res, "", _OK
            except TransferError as e:
                last_err = str(e)
                last_exc = e
                self.pool.mark_used(acc["id"], ok=False,
                                    invalid=e.invalid_account)
                log.warning("[%s] 转存失败(%d/%d) 账号=%s: %s",
                            pan, attempt + 1, retry + 1, acc.get("name"), e)
                if not e.retryable and not e.invalid_account:
                    break
            except Exception as e:
                last_err = "未知错误: %s" % e
                log.exception("[%s] 转存异常", pan)
        # 综合「适配器自带标志」与「文字兜底分类」，两者任一命中即算。
        cat = classify_transfer_error(last_err)
        if last_exc is not None:
            cat["retryable"] = cat["retryable"] or last_exc.retryable
            cat["invalid_account"] = cat["invalid_account"] or last_exc.invalid_account
            cat["dead_link"] = cat["dead_link"] or getattr(last_exc, "dead_link", False)
        return None, last_err, cat
