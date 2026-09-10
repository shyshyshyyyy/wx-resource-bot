# -*- coding: utf-8 -*-
"""
各网盘转存适配器。从 xinyue-search 的 extend/netdisk/pan/*.php 移植。

相对原实现做的改动：
1. 账号维度化 —— 原版每个盘只能配一套 cookie（存在 ThinkPHP 的 Config 里），
   这里改成账号池，每个账号自带 cookie 和转存目录，支持轮转。
2. token 缓存按账号隔离（原版是全局一个文件，多账号会互相踩）。
3. 阿里云盘的 drive_id 原版写死成 2008425230（那是作者自己的号），
   这里改成登录后动态取 default_drive_id，否则换账号必然失败。
4. 迅雷/阿里刷新 token 后回写账号，避免下次重启用旧的 refresh_token。
5. 百度的分享提取码原版写死 '6666'，改成随机生成。
6. 错误分类成「可重试 / 账号失效 / 硬失败」，交给账号池决定要不要换号。
"""

import os
import re
import sys
import json
import time
import base64
import random
import string
import logging
import threading

import requests

from transfer.base import (BaseAdapter, ShareResult, TransferError, register)

log = logging.getLogger("transfer.adapters")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")

_token_lock = threading.RLock()


def _token_dir():
    import config_manager as cm
    d = os.path.join(cm.data_dir(), "tokens")
    os.makedirs(d, exist_ok=True)
    return d


def _token_load(acc_id, kind):
    try:
        with open(os.path.join(_token_dir(), "%s_%s.json" % (acc_id, kind)),
                  "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _token_save(acc_id, kind, data):
    try:
        with open(os.path.join(_token_dir(), "%s_%s.json" % (acc_id, kind)),
                  "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _token_clear(acc_id):
    """清掉某个账号的全部令牌缓存文件（tokens/<acc_id>_*.json）。

    用户主动改/删凭据、或重新填令牌时用：迅雷 refresh_token 是「一次性轮转」的，
    旧缓存里若是已作废的令牌，会遮蔽用户刚填的新令牌，必须清掉让它重新换发。
    """
    try:
        d = _token_dir()
        for fn in os.listdir(d):
            if fn.startswith("%s_" % acc_id) and fn.endswith(".json"):
                try:
                    os.remove(os.path.join(d, fn))
                except Exception:
                    pass
    except Exception:
        pass


def _rand_code(n=4):
    return "".join(random.choice(string.ascii_lowercase + string.digits)
                   for _ in range(n))


class _HttpAdapter(BaseAdapter):
    IMPLEMENTED = False
    BASE = ""
    SHARE_RE = r""
    NAME = "网盘"

    def __init__(self, account):
        super().__init__(account)
        self.acc_id = account.get("id") or "default"
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})
        self.banned = [w.strip() for w in
                       (account.get("banned_words") or "").split(",") if w.strip()]
        self._title = ""

    def parse_share_id(self, url):
        m = re.search(self.SHARE_RE, url or "")
        if not m:
            raise TransferError("识别不了这个%s分享链接" % self.NAME)
        return m.group(1).split("#")[0]

    def req(self, method, url, **kw):
        kw.setdefault("timeout", 25)
        try:
            r = self.s.request(method, url, **kw)
        except requests.RequestException as e:
            raise TransferError("网络错误: %s" % e, retryable=True)
        if r.status_code in (401, 403):
            raise TransferError("登录状态失效，请更新 Cookie", invalid_account=True)
        if r.status_code == 429:
            raise TransferError("请求过于频繁", retryable=True)
        if r.status_code >= 500:
            raise TransferError("%s 服务异常 %d" % (self.NAME, r.status_code),
                                retryable=True)
        try:
            return r.json()
        except ValueError:
            raise TransferError("响应不是 JSON，可能被风控拦截", retryable=True)

    def is_ad(self, filename):
        low = (filename or "").lower()
        return any(w.lower() in low for w in self.banned)

    # 基类的四个抽象方法统一转发到 _xxx 实现
    def check(self):
        return self._check()

    def list_dir(self, parent_id="0"):
        return self._list_dir(parent_id)

    def save(self, share_url, password="", target_dir_id=""):
        return self._save(share_url, password, target_dir_id)

    def share(self, file_ids, title="", expire_days=0):
        return self._share(file_ids, title, expire_days)

    def _check(self):
        return False, "适配器未实现"

    def _list_dir(self, parent_id):
        return []

    def _save(self, share_url, password, target_dir_id):
        raise TransferError("%s 的转存适配器未实现" % self.NAME)

    def _share(self, file_ids, title, expire_days):
        raise TransferError("%s 的转存适配器未实现" % self.NAME)


# ==========================================================
# 夸克 / UC —— 同一套 API，只有域名和 pr 参数不同
# ==========================================================
class _QuarkFamily(_HttpAdapter):
    PR = "ucpro"
    ORIGIN = "https://pan.quark.cn"
    IMPLEMENTED = True

    def __init__(self, account):
        super().__init__(account)
        self.s.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": self.ORIGIN + "/",
            "Origin": self.ORIGIN,
            "Cookie": self.cookie,
        })

    def _q(self, **extra):
        d = {"pr": self.PR, "fr": "pc", "uc_param_str": ""}
        d.update(extra)
        return d

    def _call(self, method, path, params=None, body=None):
        res = self.req(method, self.BASE + path,
                       params=self._q(**(params or {})),
                       json=body if body is not None else {})
        status = res.get("status")
        msg = res.get("message", "") or ""
        if status != 200:
            if "require login" in msg or "guest" in msg:
                raise TransferError("%s 未登录，请检查 Cookie" % self.NAME,
                                    invalid_account=True)
            if "capacity limit" in msg:
                raise TransferError("网盘容量不足")
            if "频繁" in msg or "limit" in msg.lower():
                raise TransferError(msg, retryable=True)
            raise TransferError(msg or "接口返回 %s" % status)
        return res.get("data") or {}

    def _check(self):
        try:
            self._call("GET", "/1/clouddrive/file/sort",
                       params={"pdir_fid": "0", "_page": 1, "_size": 1,
                               "_fetch_total": 1})
            return True, "Cookie 有效"
        except TransferError as e:
            return False, str(e)

    def _list_dir(self, parent_id):
        data = self._call("GET", "/1/clouddrive/file/sort",
                          params={"pdir_fid": parent_id or "0", "_page": 1,
                                  "_size": 200, "_fetch_total": 1,
                                  "_fetch_sub_dirs": 0,
                                  "_sort": "file_type:asc,updated_at:desc"})
        return [{"id": f["fid"], "name": f.get("file_name", ""),
                 "is_dir": bool(f.get("dir") or f.get("file_type") == 0)}
                for f in data.get("list", [])]

    def _stoken(self, pwd_id, passcode=""):
        d = self._call("POST", "/1/clouddrive/share/sharepage/token",
                       body={"pwd_id": pwd_id, "passcode": passcode or ""})
        return (d.get("stoken") or "").replace(" ", "+")

    def _create_dir(self, parent_id, name):
        """对齐 xinyue-search 的 QuarkPan::createFolder：同名复用，不存在才建。"""
        parent_id = parent_id or "0"
        try:
            for it in self._list_dir(parent_id):
                if it.get("is_dir") and it.get("name") == name:
                    return {"id": it["id"], "name": name, "reused": True}
        except TransferError:
            pass
        d = self._call("POST", "/1/clouddrive/file",
                       body={"pdir_fid": parent_id, "file_name": name,
                             "dir_path": "", "dir_init_lock": False})
        fid = (d.get("data") or {}).get("fid") if isinstance(d.get("data"), dict) \
            else (d.get("fid") or "")
        fid = fid or d.get("fid") or ""
        if not fid:
            raise TransferError("新建文件夹失败，接口没返回 fid")
        return {"id": fid, "name": name, "reused": False}

    def _detail(self, pwd_id, stoken):
        return self._call("GET", "/1/clouddrive/share/sharepage/detail",
                          params={"pwd_id": pwd_id, "stoken": stoken,
                                  "pdir_fid": "0", "force": "0", "_page": "1",
                                  "_size": "100", "_fetch_banner": "1",
                                  "_fetch_share": "1", "_fetch_total": "1",
                                  "_sort": "file_type:asc,updated_at:desc"})

    def _task(self, task_id):
        for i in range(50):
            d = self._call("GET", "/1/clouddrive/task",
                           params={"task_id": task_id, "retry_index": i})
            if d.get("status") == 2:
                return d
            time.sleep(0.6)
        raise TransferError("任务超时（%s 侧一直没返回完成）" % self.NAME,
                            retryable=True)

    def _save(self, share_url, password, target_dir_id):
        pwd_id = self.parse_share_id(share_url)
        stoken = self._stoken(pwd_id, password)
        detail = self._detail(pwd_id, stoken)

        files = detail.get("list") or []
        if not files:
            raise TransferError("分享内容为空或已失效")
        self._title = (detail.get("share") or {}).get("title", "")

        d = self._call("POST", "/1/clouddrive/share/sharepage/save",
                       params={"entry": "update_share"},
                       body={"fid_list": [f["fid"] for f in files],
                             "fid_token_list": [f["share_fid_token"] for f in files],
                             "to_pdir_fid": target_dir_id or "0",
                             "pwd_id": pwd_id, "stoken": stoken,
                             "pdir_fid": "0", "scene": "link"})
        task = self._task(d["task_id"])
        top_fids = (task.get("save_as") or {}).get("save_as_top_fids") or []
        if not top_fids:
            raise TransferError("转存完成但没拿到文件 ID")

        self._clean_ads(top_fids)
        return top_fids

    def _clean_ads(self, top_fids):
        """删掉转存进来的广告文件；全是广告就整个删掉并报错。"""
        if not self.banned:
            return
        try:
            children = self._list_dir(top_fids[0])
        except TransferError:
            return
        if not children:
            return
        ads = [c["id"] for c in children if self.is_ad(c["name"])]
        if not ads:
            return
        if len(ads) == len(children):
            self.cleanup(top_fids)
            raise TransferError("资源内容全是广告，已删除")
        self.cleanup(ads)

    def _share(self, file_ids, title, expire_days):
        expired_type = 2 if expire_days else 1
        d = self._call("POST", "/1/clouddrive/share",
                       body={"fid_list": list(file_ids),
                             "expired_type": expired_type,
                             "title": title or self._title or "分享",
                             "url_type": 1})
        task = self._task(d["task_id"])
        share_id = task.get("share_id")
        if not share_id:
            raise TransferError("创建分享失败")
        d = self._call("POST", "/1/clouddrive/share/password",
                       body={"share_id": share_id})
        return ShareResult({
            "url": d.get("share_url", ""),
            "password": d.get("passcode", "") or "",
            "expire": "永久" if expired_type == 1 else "%d 天" % expire_days,
        })

    def cleanup(self, file_ids):
        try:
            self._call("POST", "/1/clouddrive/file/delete",
                       body={"action_type": 2, "exclude_fids": [],
                             "filelist": list(file_ids)})
            return True
        except TransferError:
            return False


@register("quark")
class QuarkAdapter(_QuarkFamily):
    NAME = "夸克"
    BASE = "https://drive-pc.quark.cn"
    ORIGIN = "https://pan.quark.cn"
    PR = "ucpro"
    SHARE_RE = r"pan\.quark\.cn/s/([0-9a-zA-Z]+)"


@register("uc")
class UcAdapter(_QuarkFamily):
    NAME = "UC"
    BASE = "https://pc-api.uc.cn"
    ORIGIN = "https://drive.uc.cn"
    PR = "UCBrowser"
    SHARE_RE = r"(?:drive|fast)\.uc\.cn/s/([0-9a-zA-Z]+)"


# ==========================================================
# 迅雷
# ==========================================================
@register("xunlei")
class XunleiAdapter(_HttpAdapter):
    NAME = "迅雷"
    BASE = "https://api-pan.xunlei.com"
    SHARE_RE = r"pan\.xunlei\.com/s/([0-9a-zA-Z_\-]+)"
    IMPLEMENTED = True

    CLIENT_ID = "Xqp0kJBXWhwaTpB6"
    DEVICE_ID = "925b7631473a13716b791d7f28289cad"

    def __init__(self, account):
        super().__init__(account)
        # 迅雷的「Cookie」字段填的是 refresh_token
        self.refresh_token = (self.cookie or "").strip()
        self.s.headers.update({
            "Content-Type": "application/json",
            "Origin": "https://pan.xunlei.com",
            "Referer": "https://pan.xunlei.com/",
            "x-client-id": self.CLIENT_ID,
            "x-device-id": self.DEVICE_ID,
        })

    @staticmethod
    def _xunlei_debug(stage, **kv):
        try:
            import sys as _sys
            d = (os.path.dirname(_sys.executable)
                 if getattr(_sys, "frozen", False) else os.getcwd())
            path = os.path.join(d, "xunlei_debug.log")
            lines = ["==== %s %s ====" % (stage, time.strftime("%Y-%m-%d %H:%M:%S"))]
            for k, v in kv.items():
                s = str(v)
                if len(s) > 1500:
                    s = s[:1500] + "...(truncated)"
                lines.append("%s=%s" % (k.upper(), s))
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass

    def _access_token(self):
        with _token_lock:
            c = _token_load(self.acc_id, "xunlei")
            fresh = self.refresh_token
            cached_rt = c.get("refresh_token")
            # 迅雷 refresh_token 是「一次性轮转」的：每次用它换 access_token 后，旧
            # 的 refresh_token 立即被迅雷作废，接口返回一个新的 refresh_token。
            # 因此必须优先使用「缓存里最新轮转出来的 refresh_token」，绝不能回退到
            # 配置里那份（已被迅雷作废）。只有缓存为空（首次使用 / 用户刚清过缓存）
            # 才用用户粘贴的 fresh。早期「fresh != cached_rt 就丢弃缓存」的逻辑是
            # 错的：它会把刚轮转出来、仍有效的缓存丢掉，回退到已作废的配置令牌 →
            # invalid_grant 4126。用户主动换令牌时由面板 on_edit/on_add 调
            # _token_clear 清缓存来强制用 fresh，不必在这里猜。

            if c.get("access_token") and time.time() < c.get("expires_at", 0):
                return c["access_token"]

            # 优先用缓存里最新轮转出来的 refresh_token（仍有效），其次才用用户粘贴的
            rt = cached_rt or fresh
            if not rt:
                raise TransferError("迅雷 refresh_token 为空", invalid_account=True)

            head = (rt[:8] + "..." + rt[-4:]) if len(rt) > 16 else rt
            self._xunlei_debug("token_exchange_request",
                               refresh_token_len=len(rt), refresh_token_head=head)
            try:
                res = self.req("POST", "https://xluser-ssl.xunlei.com/v1/auth/token",
                               json={"client_id": self.CLIENT_ID,
                                     "grant_type": "refresh_token",
                                     "refresh_token": rt})
            except TransferError as e:
                self._xunlei_debug("token_exchange_error", error=str(e))
                raise

            tok = res.get("access_token")
            if not tok:
                self._xunlei_debug("token_exchange_fail", response=res)
                raise TransferError(
                    "迅雷登录失效，请重新获取 refresh_token。"
                    "注意：凭据里应填 refresh_token（以 eyJ 或长串字符开头），"
                    "不是 access_token，也不是浏览器 Cookie。详情见 xunlei_debug.log",
                    invalid_account=True)
            new = {"access_token": tok,
                   "refresh_token": res.get("refresh_token") or rt,
                   "expires_at": time.time() + int(res.get("expires_in", 3600)) - 60}
            _token_save(self.acc_id, "xunlei", new)
            # 同步，避免下次被误判为「新令牌」而重复刷新
            self.refresh_token = new["refresh_token"]
            self.account["cookie"] = new["refresh_token"]
            # 迅雷令牌一次性轮转：把刚轮转出来的新 refresh_token 写回磁盘配置，
            # 否则重启后配置里仍是已作废的旧令牌 → invalid_grant 4126。
            # self.account 是对配置里该账号 dict 的活引用，改它即改配置，再落盘。
            self._persist_account()
            self._xunlei_debug("token_exchange_ok", access_token_len=len(tok))
            return tok

    def _captcha_token(self, action="get:/drive/v1/share"):
        with _token_lock:
            c = _token_load(self.acc_id, "xunlei_captcha")
            if c.get("captcha_token") and time.time() < c.get("expires_at", 0):
                return c["captcha_token"]
            res = self.req(
                "POST", "https://xluser-ssl.xunlei.com/v1/shield/captcha/init",
                json={"client_id": self.CLIENT_ID, "action": action,
                      "device_id": self.DEVICE_ID,
                      "meta": {"username": "", "phone_number": "", "email": "",
                               "package_name": "pan.xunlei.com",
                               "client_version": "1.45.0",
                               "captcha_sign": "1.fe2108ad808a74c9ac0243309242726c",
                               "timestamp": "1645241033384", "user_id": "0"}})
            tok = res.get("captcha_token")
            if not tok:
                raise TransferError("获取迅雷 captcha_token 失败", retryable=True)
            _token_save(self.acc_id, "xunlei_captcha",
                        {"captcha_token": tok,
                         "expires_at": time.time() + int(res.get("expires_in", 300)) - 30})
            return tok

    def _auth(self):
        self.s.headers["Authorization"] = "Bearer " + self._access_token()
        self.s.headers["x-captcha-token"] = self._captcha_token()

    def _call(self, method, path, params=None, body=None):
        self._auth()
        res = self.req(method, self.BASE + path, params=params, json=body)
        if res.get("error_code"):
            desc = res.get("error_description") or res.get("error") or "接口错误"
            self._xunlei_debug("api_error", path=path,
                               error_code=res.get("error_code"), desc=desc)
            if "token" in str(desc).lower():
                raise TransferError(desc, invalid_account=True)
            raise TransferError(desc)
        return res

    def _check(self):
        try:
            self._call("GET", "/drive/v1/files",
                       params={"parent_id": "", "limit": 1})
            return True, "登录有效"
        except TransferError as e:
            return False, str(e)

    def _list_dir(self, parent_id):
        res = self._call("GET", "/drive/v1/files",
                         params={"parent_id": parent_id or "", "limit": 200,
                                 "filters": '{"kind":{"eq":"drive#folder"}}'})
        return [{"id": f["id"], "name": f.get("name", ""), "is_dir": True}
                for f in res.get("files", [])]

    def _save(self, share_url, password, target_dir_id):
        share_id = self.parse_share_id(share_url)
        code = (password or "").replace("#", "")

        info = self._call("GET", "/drive/v1/share",
                          params={"share_id": share_id, "pass_code": code,
                                  "limit": 100, "pass_code_token": "",
                                  "page_token": "",
                                  "thumbnail_size": "SIZE_SMALL"})
        status = info.get("share_status")
        if status and status != "OK":
            if status == "SENSITIVE_RESOURCE":
                raise TransferError("该分享因涉及违规内容无法访问")
            raise TransferError(info.get("share_status_text") or "资源已失效")

        files = info.get("files") or []
        if not files:
            raise TransferError("分享内容为空")
        self._title = files[0].get("name", "")

        res = self._call("POST", "/drive/v1/share/restore",
                         body={"parent_id": target_dir_id or "",
                               "share_id": share_id,
                               "pass_code_token": info.get("pass_code_token", ""),
                               "ancestor_ids": [],
                               "specify_parent_id": True,
                               "file_ids": [f["id"] for f in files]})
        task_id = res.get("restore_task_id")
        if not task_id:
            raise TransferError("转存任务创建失败")

        task = None
        for _ in range(20):
            task = self._call("GET", "/drive/v1/tasks/" + task_id)
            if task.get("progress") == 100:
                break
            time.sleep(0.8)
        if not task or task.get("progress") != 100:
            raise TransferError((task or {}).get("message") or "转存超时",
                                retryable=True)

        ids = []
        trace = (task.get("params") or {}).get("trace_file_ids")
        if trace:
            try:
                parsed = json.loads(trace)
                ids = list(parsed.values()) if isinstance(parsed, dict) else list(parsed)
            except Exception:
                pass
        if not ids:
            raise TransferError("转存完成但没拿到文件 ID")

        self._clean_ads(ids)
        return ids

    def _clean_ads(self, ids):
        if not self.banned:
            return
        try:
            res = self._call("GET", "/drive/v1/files",
                             params={"parent_id": ids[0], "limit": 200})
        except TransferError:
            return
        children = res.get("files", [])
        if not children:
            return
        ads = [f["id"] for f in children if self.is_ad(f.get("name", ""))]
        if not ads:
            return
        if len(ads) == len(children):
            self.cleanup(ids)
            raise TransferError("资源内容全是广告，已删除")
        self.cleanup(ads)

    def _share(self, file_ids, title, expire_days):
        res = self._call("POST", "/drive/v1/share",
                         body={"file_ids": list(file_ids),
                               "share_to": "copy",
                               "params": {"subscribe_push": "false",
                                          "WithPassCodeInLink": "true"},
                               "title": title or self._title or "云盘资源分享",
                               "restore_limit": "-1",
                               "expiration_days": str(expire_days) if expire_days else "-1"})
        url = res.get("share_url", "")
        code = res.get("pass_code", "")
        return ShareResult({
            "url": "%s?pwd=%s" % (url, code) if code else url,
            "password": code,
            "expire": "永久" if not expire_days else "%d 天" % expire_days,
        })

    def cleanup(self, file_ids):
        try:
            self._call("POST", "/drive/v1/files:batchDelete",
                       body={"ids": list(file_ids)})
            return True
        except TransferError:
            return False


# ==========================================================
# 阿里云盘
# ==========================================================
@register("aliyun")
class AliyunAdapter(_HttpAdapter):
    NAME = "阿里云盘"
    BASE = "https://api.aliyundrive.com"
    SHARE_RE = r"(?:aliyundrive|alipan)\.com/s/([0-9a-zA-Z]+)"
    IMPLEMENTED = True

    def __init__(self, account):
        super().__init__(account)
        # 阿里的「Cookie」字段填的是 refresh_token
        self.refresh_token = (self.cookie or "").strip()
        self.s.headers.update({
            "Content-Type": "application/json",
            "Origin": "https://www.alipan.com",
            "Referer": "https://www.alipan.com/",
        })
        self._drive_id = None

    def _access_token(self):
        with _token_lock:
            c = _token_load(self.acc_id, "aliyun")
            if (c.get("access_token") and time.time() < c.get("expires_at", 0)
                    and c.get("refresh_token") == self.refresh_token):
                self._drive_id = c.get("drive_id")
                return c["access_token"]

            if not self.refresh_token:
                raise TransferError("阿里云盘 refresh_token 为空",
                                    invalid_account=True)
            res = self.req("POST", self.BASE + "/token/refresh",
                           json={"refresh_token": self.refresh_token})
            tok = res.get("access_token")
            if not tok:
                raise TransferError("阿里云盘登录失效，请重新获取 refresh_token",
                                    invalid_account=True)
            drive_id = res.get("default_drive_id") or ""
            new_rt = res.get("refresh_token") or self.refresh_token
            _token_save(self.acc_id, "aliyun",
                        {"access_token": tok, "refresh_token": new_rt,
                         "drive_id": drive_id,
                         "expires_at": time.time() + int(res.get("expires_in", 7200)) - 60})
            self.account["cookie"] = new_rt
            self._drive_id = drive_id
            return tok

    def _auth(self):
        self.s.headers["Authorization"] = "Bearer " + self._access_token()

    @property
    def drive_id(self):
        if not self._drive_id:
            self._access_token()
        if not self._drive_id:
            raise TransferError("拿不到 drive_id", invalid_account=True)
        return self._drive_id

    def _call(self, path, body):
        self._auth()
        res = self.req("POST", self.BASE + path, json=body)
        if isinstance(res, dict) and res.get("code") and \
                not res.get("items") and not res.get("responses"):
            msg = res.get("message") or res.get("code")
            raise TransferError(msg, invalid_account="Token" in str(res.get("code", "")))
        return res

    def _check(self):
        try:
            self._call("/adrive/v3/file/list",
                       {"drive_id": self.drive_id, "parent_file_id": "root",
                        "limit": 1, "all": False})
            return True, "登录有效"
        except TransferError as e:
            return False, str(e)

    def _list_dir(self, parent_id):
        res = self._call("/adrive/v3/file/list",
                         {"drive_id": self.drive_id,
                          "parent_file_id": parent_id or "root",
                          "limit": 200, "all": False, "fields": "*",
                          "order_by": "updated_at", "order_direction": "DESC"})
        return [{"id": f["file_id"], "name": f.get("name", ""),
                 "is_dir": f.get("type") == "folder"}
                for f in res.get("items", []) if f.get("type") == "folder"]

    def _create_dir(self, parent_id, name):
        """阿里云盘新建文件夹。同名会报 409（AlreadyExist.File），此时回查复用。"""
        parent_id = parent_id or "root"
        self._auth()
        try:
            res = self.req("POST", self.BASE + "/adrive/v1.0/openFile/create",
                           json={"drive_id": self.drive_id,
                                 "parent_file_id": parent_id,
                                 "name": name, "type": "folder",
                                 "check_name_mode": "refuse"})
        except TransferError as e:
            if "5" not in str(e) and "429" not in str(e):
                raise
            res = None
        fid = (res or {}).get("file_id") or ""
        if fid:
            return {"id": fid, "name": name, "reused": False}
        # 建失败（多半是同名已存在）→ 回查
        for it in self._list_dir(parent_id):
            if it.get("name") == name:
                return {"id": it["id"], "name": name, "reused": True}
        raise TransferError("阿里云盘新建文件夹失败")

    def _share_token(self, share_id, password=""):
        res = self.req("POST", self.BASE + "/v2/share_link/get_share_token",
                       json={"share_id": share_id, "share_pwd": password or ""})
        tok = res.get("share_token")
        if not tok:
            raise TransferError(res.get("message") or "分享已失效或需要提取码")
        return tok

    def _save(self, share_url, password, target_dir_id):
        share_id = self.parse_share_id(share_url)

        anon = self.req(
            "POST", self.BASE + "/adrive/v3/share_link/get_share_by_anonymous",
            json={"share_id": share_id})
        files = anon.get("file_infos") or []
        if not files:
            raise TransferError("分享内容为空或已失效")
        self._title = anon.get("share_name") or files[0].get("file_name", "")

        share_token = self._share_token(share_id, password)

        body = {"requests": [], "resource": "file"}
        for i, f in enumerate(files):
            body["requests"].append({
                "body": {"file_id": f["file_id"], "share_id": share_id,
                         "auto_rename": True,
                         "to_drive_id": self.drive_id,
                         "to_parent_file_id": target_dir_id or "root"},
                "headers": {"Content-Type": "application/json",
                            "x-share-token": share_token},
                "id": str(i), "method": "POST", "url": "/file/copy",
            })

        self._auth()
        self.s.headers["x-share-token"] = share_token
        try:
            res = self.req("POST", self.BASE + "/adrive/v4/batch", json=body)
        finally:
            self.s.headers.pop("x-share-token", None)

        ids = [r["body"]["file_id"] for r in res.get("responses", [])
               if (r.get("body") or {}).get("file_id")]
        if not ids:
            raise TransferError("转存失败，没拿到文件 ID")
        return ids

    def _share(self, file_ids, title, expire_days):
        expiration = ""
        if expire_days:
            expiration = time.strftime(
                "%Y-%m-%dT%H:%M:%S.000Z",
                time.gmtime(time.time() + expire_days * 86400))
        res = self._call("/adrive/v2/share_link/create",
                         {"drive_id": self.drive_id, "expiration": expiration,
                          "share_pwd": "", "file_id_list": list(file_ids)})
        url = res.get("share_url") or ""
        if not url:
            raise TransferError(res.get("message") or "创建分享失败")
        return ShareResult({
            "url": url, "password": res.get("share_pwd", "") or "",
            "expire": "永久" if not expire_days else "%d 天" % expire_days,
        })

    def cleanup(self, file_ids):
        try:
            reqs = [{"body": {"file_id": fid, "drive_id": self.drive_id},
                     "headers": {"Content-Type": "application/json"},
                     "id": str(i), "method": "POST", "url": "/recyclebin/trash"}
                    for i, fid in enumerate(file_ids)]
            self._call("/adrive/v4/batch", {"requests": reqs, "resource": "file"})
            return True
        except TransferError:
            return False


# ==========================================================
# 百度网盘
# ==========================================================
@register("baidu")
class BaiduAdapter(_HttpAdapter):
    NAME = "百度"
    BASE = "https://pan.baidu.com"
    SHARE_RE = r"pan\.baidu\.com/s/([0-9a-zA-Z_\-]+)"
    IMPLEMENTED = True

    ERRNO = {
        -1: "链接失效或没取到分享参数", -6: "身份验证失败，请更新 Cookie",
        -7: "转存目录名含非法字符", -8: "目录中已有同名文件",
        -9: "提取码错误", -10: "容量不足", -12: "批量转存出错",
        0: "成功", 2: "转存目标目录不存在", 4: "转存文件重复",
        12: "转存文件数超限或部分文件已存在", 105: "链接地址格式错误",
        111: "有转存任务正在进行，请稍后再试", 404: "转存失败，请稍后重试",
    }

    def __init__(self, account):
        super().__init__(account)
        self.s.headers.update({"Referer": "https://pan.baidu.com",
                               "Cookie": self.cookie})
        self.bdstoken = ""

    def _err(self, errno):
        return self.ERRNO.get(errno, "未知错误 errno=%s" % errno)

    def _get(self, path, params):
        return self.req("GET", self.BASE + path, params=params)

    def _post(self, path, params, data):
        return self.req("POST", self.BASE + path, params=params, data=data)

    def _ensure_token(self):
        if self.bdstoken:
            return
        res = self._get("/api/gettemplatevariable",
                        {"clienttype": "0", "app_id": "38824127", "web": "1",
                         "fields": '["bdstoken","token","uk","isdocuser","servertime"]'})
        if res.get("errno") != 0:
            raise TransferError(self._err(res.get("errno")), invalid_account=True)
        self.bdstoken = res["result"]["bdstoken"]

    def _check(self):
        try:
            self._ensure_token()
            return True, "Cookie 有效"
        except TransferError as e:
            return False, str(e)

    def _raw_list(self, path):
        self._ensure_token()
        return self._get("/api/list",
                         {"order": "time", "desc": "1", "showempty": "0",
                          "web": "1", "page": "1", "num": "1000",
                          "dir": path, "bdstoken": self.bdstoken})

    def _list_dir(self, parent_id):
        # 百度用路径当 ID
        path = parent_id if (parent_id and parent_id != "0") else "/"
        res = self._raw_list(path)
        if res.get("errno") != 0:
            return []
        return [{"id": path.rstrip("/") + "/" + f["server_filename"],
                 "name": f["server_filename"], "is_dir": True}
                for f in res.get("list", []) if f.get("isdir") == 1]

    def _create_dir(self, parent_id, name):
        """百度用路径当 ID，新建文件夹也是传完整路径。"""
        parent = parent_id if (parent_id and parent_id != "0") else "/"
        path = parent.rstrip("/") + "/" + name
        res = self._post("/api/create",
                         {"a": "commit", "bdstoken": self.bdstoken},
                         {"path": path, "isdir": "1", "block_list": "[]"})
        if res.get("errno", -1) != 0:
            # 多半是同名已存在，回查复用
            for it in self._list_dir(parent):
                if it.get("name") == name:
                    return {"id": it["id"], "name": name, "reused": True}
            raise TransferError(self._err(res.get("errno")))
        return {"id": path, "name": name, "reused": False}

    def _verify_password(self, link_url, code):
        surl = link_url[25:48]
        res = self._post("/share/verify",
                         {"surl": surl, "bdstoken": self.bdstoken,
                          "t": int(time.time() * 1000), "channel": "chunlei",
                          "web": "1", "clienttype": "0"},
                         {"pwd": code, "vcode": "", "vcode_str": ""})
        if res.get("errno") != 0:
            raise TransferError(self._err(res.get("errno")))
        pairs = dict(p.strip().split("=", 1) for p in self.cookie.split(";")
                     if "=" in p)
        pairs["BDCLND"] = res["randsk"]
        self.cookie = "; ".join("%s=%s" % kv for kv in pairs.items())
        self.s.headers["Cookie"] = self.cookie

    def _scrape_params(self, link_url):
        """分享页是 HTML，参数嵌在里面，只能正则抠出来。"""
        try:
            html = self.s.get(link_url, timeout=20, allow_redirects=True).text
        except requests.RequestException as e:
            raise TransferError("打开分享页失败: %s" % e, retryable=True)

        shareid = re.findall(r'"shareid":(\d+?),"', html)
        uk = re.findall(r'"share_uk":"(\d+?)","', html)
        fs_ids = re.findall(r'"fs_id":(\d+?),"', html)
        names = re.findall(r'"server_filename":"(.+?)","', html)
        if not (shareid and uk and fs_ids and names):
            raise TransferError("链接失效，或需要提取码")
        seen, uniq = set(), []
        for n in names:
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        return shareid[0], uk[0], fs_ids, uniq

    def _save(self, share_url, password, target_dir_id):
        self._ensure_token()
        link_url = share_url.split("?")[0]

        if password:
            self._verify_password(link_url, password)

        share_id, uk, fs_ids, names = self._scrape_params(link_url)
        self._title = names[0] if names else ""

        folder = (target_dir_id or "/默认转存文件").strip()
        if not folder.startswith("/"):
            folder = "/" + folder
        for ch in "<>|*?\\:":
            if ch in folder.lstrip("/"):
                raise TransferError("转存目录名不能包含 < > | * ? \\ :")

        if self._raw_list(folder).get("errno") != 0:
            # 百度的 /api/create 支持一次建多级路径，直接传整段即可
            self.create_dir("/", folder.strip("/"))

        res = self._post("/share/transfer",
                         {"shareid": share_id, "from": uk,
                          "bdstoken": self.bdstoken, "channel": "chunlei",
                          "web": "1", "clienttype": "0", "ondup": "newcopy"},
                         {"fsidlist": "[" + ",".join(fs_ids) + "]",
                          "path": folder})
        if res.get("errno") != 0:
            errno = res.get("errno")
            raise TransferError(self._err(errno),
                                retryable=errno in (111, 404),
                                invalid_account=errno == -6)

        listed = self._raw_list(folder)
        if listed.get("errno") != 0:
            raise TransferError(self._err(listed.get("errno")))

        fs_id_list, ad_paths = [], []
        found = False
        for f in listed.get("list", []):
            if f["server_filename"] not in names:
                continue
            found = True
            p = folder.rstrip("/") + "/" + f["server_filename"]
            if self.is_ad(f["server_filename"]):
                ad_paths.append(p)
            else:
                fs_id_list.append(str(f["fs_id"]))

        if not found:
            raise TransferError("转存后找不到文件")
        if ad_paths:
            self.cleanup(ad_paths)
        if not fs_id_list:
            raise TransferError("资源内容为空或全是广告，已删除")
        return fs_id_list

    def _share(self, file_ids, title, expire_days):
        code = _rand_code(4)
        res = self._post("/share/set",
                         {"channel": "chunlei", "bdstoken": self.bdstoken,
                          "clienttype": "0", "app_id": "250528", "web": "1"},
                         {"period": expire_days or 0, "pwd": code,
                          "eflag_disable": "true", "channel_list": "[]",
                          "schannel": "4",
                          "fid_list": "[" + ",".join(file_ids) + "]"})
        if res.get("errno") != 0:
            raise TransferError(self._err(res.get("errno")))
        link = res.get("link", "")
        return ShareResult({
            "url": "%s?pwd=%s" % (link, code) if link else "",
            "password": code,
            "expire": "永久" if not expire_days else "%d 天" % expire_days,
        })

    def cleanup(self, file_paths):
        try:
            self._post("/api/filemanager",
                       {"async": "2", "onnest": "fail", "opera": "delete",
                        "bdstoken": self.bdstoken, "newVerify": "1",
                        "clienttype": "0", "app_id": "250528", "web": "1"},
                       {"filelist": json.dumps(list(file_paths),
                                               ensure_ascii=False)})
            return True
        except TransferError:
            return False


# ==========================================================
# 光鸭云盘 —— 迅雷旗下，复用迅雷系 XLPs 鉴权范式
# ----------------------------------------------------------
# 从 xinyue-search 的 extend/netdisk/pan/GuangyaPan.php 移植。
#
# 账号配置：
#   cookie  填 refresh_token（推荐，长期有效，轮转后自动回写账号）
#           若只有短期 access_token，在前面加 "AT:" 前缀
#   save_dir_id  转存目标目录 ID，空 = 根目录
# ==========================================================
def _guangya_localized(payload):
    """从 Google-OAuth 风格响应的 details[].message（locale=zh）取中文错误。"""
    det = payload.get("details") if isinstance(payload, dict) else None
    if isinstance(det, list):
        for d in det:
            if isinstance(d, dict) and d.get("locale") == "zh":
                return d.get("message") or ""
    return ""


@register("guangya")
class GuangyaAdapter(_HttpAdapter):
    NAME = "光鸭"
    BASE = "https://api.guangyapan.com"
    ACCOUNT_BASE = "https://account.guangyapan.com"
    WEB_BASE = "https://www.guangyapan.com"
    SHARE_RE = r"guangyapan\.com/s/([0-9A-Za-z_\-]+)"
    IMPLEMENTED = True

    CLIENT_ID = "aMe-8VSlkrbQXpUR"
    TASK_POLL_TIMES = 20
    TASK_POLL_INTERVAL = 1.0

    def __init__(self, account):
        super().__init__(account)
        raw = (account.get("cookie") or "").strip()
        if raw.upper().startswith("AT:"):
            self._refresh_token = ""
            self._access_token_fallback = raw[3:].strip()
        else:
            self._refresh_token = raw
            self._access_token_fallback = ""
        cached = _token_load(self.acc_id, "guangya")
        # device_id 优先级：账号配置 > 缓存 > 随机。
        # 关键：光鸭 refresh_token 可能绑定首次签发时的 device_id（与网站一致），
        # 若 Bot 用随机 device_id 刷新会被服务端判 “token does not match”。
        # 因此允许在账号配置里显式填 device_id，对齐网站 qfshop.guangya_device_id。
        self._device_id = (account.get("device_id")
                           or cached.get("device_id") or os.urandom(16).hex())
        # 把 device_id 回写账号字典，便于上层（账号池/面板）持久化，
        # 避免每次重启都换 device_id 导致 device-bound 的 refresh_token 刷新失败。
        account["device_id"] = self._device_id
        self._token_cache = cached
        # 兜底：账号没填 cookie，但本地缓存里有 refresh_token，也能续期。
        if not self._refresh_token and cached.get("refresh_token"):
            self._refresh_token = cached["refresh_token"]

    # ---------- 基础请求 ----------
    def _base_headers(self):
        return {
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache",
            "Content-Type": "application/json",
            "Origin": self.WEB_BASE,
            "Referer": self.WEB_BASE + "/",
            "User-Agent": UA,
            "X-Client-Id": self.CLIENT_ID,
            "X-Device-Id": self._device_id,
        }

    def _account_headers(self):
        """账号类请求头（token/captcha 端点）：光鸭要求带 X-Captcha-Token。"""
        h = self._base_headers()
        h["X-Captcha-Token"] = ""
        return h

    def _raw_post(self, url, data, headers, timeout=25):
        try:
            r = self.s.post(url, json=data, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            raise TransferError("网络错误: %s" % e, retryable=True)
        try:
            return r.json()
        except ValueError:
            raise TransferError("光鸭响应不是 JSON，可能被风控拦截",
                                retryable=True)

    def _unwrap(self, payload):
        """兼容 {code,data,msg} 与 {errno,...} 两种返回。"""
        code = payload.get("code", payload.get("errno", 0))
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = 0 if not code else 1
        return code, payload.get("data") or {}, (
            payload.get("msg") or payload.get("message") or
            payload.get("error") or "")

    def _call(self, endpoint, data, auth=True):
        url = self.BASE + endpoint
        headers = self._base_headers()
        if auth:
            headers["Authorization"] = "Bearer " + self._access_token()
        payload = self._raw_post(url, data, headers)
        code, data_out, msg = self._unwrap(payload)
        if code != 0:
            low = (msg or "").lower()
            if any(k in low for k in ("登录", "令牌", "未授权", "token",
                                      "unauthorized")):
                raise TransferError(msg or "登录状态失效",
                                    invalid_account=True)
            raise TransferError(msg or "光鸭接口返回 %s" % code, retryable=True)
        return data_out if isinstance(data_out, dict) else {}

    # ---------- 令牌 ----------
    def _access_token(self):
        now = int(time.time())
        if self._token_cache.get("expires_at", 0) > now:
            return self._token_cache["access_token"]

        if self._refresh_token:
            rt = self._refresh_token
            # 非阻断提示：浏览器 Cookie 常含 "cookie" 或大量 '='，但真实
            # refresh_token 也可能含 '='（base64 填充）或偶含 "cookie" 子串，
            # 不应据此直接拒绝（否则会把合法 token 误判为 Cookie 而报"无效"）。
            if "cookie" in rt.lower() or rt.count("=") >= 2:
                log.warning("[光鸭] 凭据疑似浏览器 Cookie（含 'cookie' 或 '='），"
                            "仍照常尝试刷新；若失败请确认填的是 guangyapan.com 的 refresh_token")
            # 若误贴了 access_token（JWT，eyJ 开头），刷新必失败，提前明确提示
            if rt[:3] == "eyJ":
                raise TransferError(
                    "光鸭填的是 access_token（JWT，eyJ 开头），不是 refresh_token。"
                    "请到 guangyapan.com 复制 refresh_token（gy. 开头）",
                    invalid_account=True)
            payload = self._raw_post(
                self.ACCOUNT_BASE + "/v1/auth/token",
                {"client_id": self.CLIENT_ID, "grant_type": "refresh_token",
                 "refresh_token": self._refresh_token},
                self._account_headers())
            code, data, msg = self._unwrap(payload)
            # 兼容两种成功返回：
            #   网站风格      {"code":0,"data":{"access_token":...}}
            #   Google-OAuth  {"access_token":...,"expires_in":...}（无 code/error 字段）
            top_token = payload.get("access_token") if isinstance(payload, dict) else ""
            data_token = data.get("access_token") if isinstance(data, dict) else ""
            token = data_token or top_token
            is_error = isinstance(payload, dict) and "error" in payload
            if (code == 0 or (not is_error and token)) and token:
                new_refresh = ((data.get("refresh_token") if isinstance(data, dict) else "")
                               or payload.get("refresh_token") or self._refresh_token)
                self._token_cache = {
                    "access_token": token,
                    "refresh_token": new_refresh,
                    "expires_at": now + int(data.get("expires_in",
                                                  payload.get("expires_in", 7200))) - 60,
                    "device_id": self._device_id,
                }
                _token_save(self.acc_id, "guangya", self._token_cache)
                # refresh_token 可能轮转，回写账号避免下次用旧的
                if new_refresh and new_refresh != self._refresh_token:
                    self._refresh_token = new_refresh
                    self.account["cookie"] = new_refresh
                return token
            # 失败：透出服务器真实错误（Google-OAuth 的 error_description / 本地化消息）
            real_err = (payload.get("error_description") if isinstance(payload, dict) else "") \
                or _guangya_localized(payload) or msg or \
                (payload.get("error") if isinstance(payload, dict) else "") or "未知错误"
            log.warning("[光鸭] refresh_token 续期失败: %s", real_err)
            hint = ""
            low = (real_err or "").lower()
            if "does not match" in low or "mismatch" in low:
                hint = ("；若提示 token does not match，多半是 refresh_token 绑定了"
                        "首次签发时的 device_id，请在账号配置里填上与官网一致的 device_id")
            elif "过期" in (real_err or "") or "expired" in low or "invalid" in low:
                hint = "；refresh_token 可能已过期，请重新获取（手机验证码登录或到官网复制）"
            raise TransferError("光鸭 refresh_token 失效：%s%s" % (real_err, hint),
                                invalid_account=True)

        if self._access_token_fallback:
            return self._access_token_fallback
        raise TransferError("光鸭未配置令牌（cookie 填 refresh_token）",
                            invalid_account=True)

    # ---------- 四个抽象方法 ----------
    def _check(self):
        try:
            self._list_dir()
        except TransferError as e:
            return False, str(e)
        return True, "正常"

    def _list_dir(self, parent_id="0"):
        pid = str(parent_id or "")
        if pid in ("0", "root"):
            pid = ""
        data = self._call("/nd.bizuserres.s/v1/file/get_file_list", {
            "parentId": pid, "pageSize": 200,
            "orderBy": 3, "sortType": 1, "fileTypes": [],
        })
        items = data.get("list") or data.get("fileList")
        if items is None:
            raise TransferError("光鸭登录态校验失败，请确认令牌有效",
                                invalid_account=True)
        out = []
        for it in items:
            fid = str(it.get("fileId") or it.get("id") or "")
            if not fid:
                continue
            out.append({
                "id": fid,
                "name": str(it.get("fileName") or it.get("name") or
                            it.get("title") or ""),
                "is_dir": self._is_dir(it),
            })
        return out

    @staticmethod
    def _is_dir(item):
        for key, dir_val in (("resType", 2), ("dirType", 1)):
            if key in item:
                return str(item[key]) == str(dir_val)
        for key in ("fileType", "type"):
            if key in item:
                return str(item[key]) in ("folder", "1")
        return False

    def _save(self, share_url, password="", target_dir_id=""):
        share_id = self.parse_share_id(share_url)
        self._access_token()  # 提前校验登录态，别等转存时才失败

        # 1) 分享访问令牌（公开接口）
        data = self._call(
            "/nd.bizuserres.s/v1/get_share_access_token",
            {"shareId": share_id, "code": (password or "").strip()},
            auth=False)
        share_token = data.get("accessToken") or ""
        if not share_token:
            extra = "（该分享需要提取码）" if not password else ""
            raise TransferError("获取分享访问令牌失败%s" % extra)

        # 2) 列举分享内文件
        listing = self._call(
            "/nd.bizuserres.s/v1/get_share_page_files_list",
            {"accessToken": share_token, "parentId": "", "page": 1,
             "pageSize": 100, "orderBy": 0, "sortType": 0}, auth=False)
        file_ids = [str(it.get("fileId") or it.get("fid") or "")
                    for it in (listing.get("list") or [])]
        file_ids = [f for f in file_ids if f]
        if not file_ids:
            raise TransferError("分享内没有可转存的文件")

        # 3) 转存
        self._title = (listing.get("title") or "").strip()
        parent = target_dir_id or self.account.get("save_dir_id") or ""
        saved = self._call("/nd.bizuserres.s/v1/restore_share", {
            "accessToken": share_token, "fileIds": file_ids,
            "parentId": parent})
        task_id = str(saved.get("taskId") or saved.get("task_id") or "")
        if not task_id:
            raise TransferError("光鸭转存请求失败")

        # 4) 轮询任务（超时不致命，下一步按目录读回文件来兜底）
        for _ in range(self.TASK_POLL_TIMES):
            st = self._call("/nd.bizuserres.s/v1/get_task_status",
                            {"taskId": task_id})
            if str(st.get("status")) in ("2", "SUCCESS") or st.get("success"):
                break
            time.sleep(self.TASK_POLL_INTERVAL)

        # 5) 从目标目录读回转存后的文件 ID
        saved_ids = [it["id"] for it in self._list_dir(parent)]
        if not saved_ids:
            raise TransferError("转存成功但读不到文件，请检查转存目录配置")
        return saved_ids

    def _share(self, file_ids, title="", expire_days=0):
        data = self._call("/nd.bizuserres.s/v1/share_file", {
            "fileIds": list(file_ids or []),
            "title": title or self._title or "资源",
            "validateDuration": int(expire_days or 0),
            "shareType": 1, "code": "", "autoFillCode": True,
            "trafficLimit": "0", "maxRestoreCount": 0, "downloadType": 1,
        })
        url = data.get("shareUrl") or data.get("shortUrl") or data.get("url")
        share_id = data.get("shareId") or data.get("shareKey") or ""
        if not url and share_id:
            url = self.WEB_BASE + "/s/" + share_id
        if not url:
            raise TransferError("光鸭创建分享失败")
        pwd = data.get("accessCode") or data.get("code") or ""
        return ShareResult(url=url, password=pwd,
                           expire="%d天" % int(expire_days or 0)
                           if expire_days else "永久")

    def cleanup(self, file_ids):
        try:
            self._call("/nd.bizuserres.s/v1/file/delete_file",
                       {"fileIds": list(file_ids or [])})
            return True
        except TransferError as e:
            log.warning("[光鸭] 清理失败: %s", e)
            return False


# ==========================================================
# 移动云盘（Cloud139 / yun.139.com）
# ----------------------------------------------------------
# 从 xinyue-search 的 extend/netdisk/pan/YidongPan.php 移植。
#
# ⚠️ 原 PHP 实现自带「尽力实现 + 待实测」标注：外链接口是 AES-128-CBC 加解密，
#    密钥固定，加解密部分可靠；但「建外链」createOutLink 的端点与字段是按
#    读接口推断的。上机实测若分享失败，优先核对 _share() 里的端点/字段。
#
# 账号配置：
#   cookie      填 Authorization Basic 令牌（可带 Basic 前缀，会自动去掉）或 Cookie
#   phone       手机号（部分接口需要，可留空）
#   save_dir_id 转存目标目录 ID，空 = 根目录 "/"
# ==========================================================
@register("mobile")
class MobileAdapter(_HttpAdapter):
    NAME = "移动云盘"
    BASE = "https://share-kd-njs.yun.139.com"
    PERSONAL_BASE = "https://personal-kd-njs.yun.139.com"
    # 匹配 https://yun.139.com/w/i/<id> 与 .../i/<id>
    SHARE_RE = r"(?:/w)?/i/([0-9A-Za-z_\-]+)"
    IMPLEMENTED = True

    AES_KEY = b"PVGDwmcvfs1uV3d1"
    # 转存任务轮询：最多 30 次，每次 1 秒
    TASK_POLL_TIMES = 30
    TASK_POLL_INTERVAL = 1.0
    _SUCCESS_STATUS = ("succeed", "success", "2")

    def __init__(self, account):
        super().__init__(account)
        raw = (account.get("cookie") or "").strip()
        # authorization 优先；以 Basic 开头 / pc: 开头 / 一长串无等号的都当令牌。
        # 注意：移动 Basic 令牌形如 pc:<手机号>:<令牌>，令牌段常带 "=" 填充，
        # 不能仅凭“含 =”就当成 Cookie，否则会被误判到 Cookie 分支而认证失败。
        if raw.lower().startswith("basic "):
            self._authorization = raw[6:].strip()
            self._raw_cookie = ""
        elif raw.startswith("pc:"):
            # 网站 yidong_authorization 在库里存的就是 base64(pc:手机号:令牌)，
            # 个人接口 Authorization: Basic 要的也正是这个 base64 串。
            # 用户若直接贴 pc:... 明文，这里自动 base64 一遍，与网站发出的完全一致。
            self._authorization = base64.b64encode(
                raw.strip().encode("utf-8")).decode("ascii").rstrip("=")
            self._raw_cookie = ""
        elif raw and "=" not in raw and " " not in raw and len(raw) > 40:
            self._authorization = raw
            self._raw_cookie = ""
        else:
            self._authorization = ""
            self._raw_cookie = raw
        self._phone = (account.get("phone") or "").strip()

    # ---------- AES-128-CBC：IV 前置 + Base64 ----------
    def _aes_encrypt(self, plain_json):
        iv = os.urandom(16)
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        padder = padding.PKCS7(128).padder()
        data = padder.update(plain_json.encode("utf-8")) + padder.finalize()
        enc = Cipher(algorithms.AES(self.AES_KEY), modes.CBC(iv)).encryptor()
        return base64.b64encode(iv + enc.update(data) + enc.finalize()).decode()

    def _aes_decrypt(self, b64_text):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        try:
            raw = base64.b64decode(b64_text)
        except Exception:
            return ""
        if len(raw) < 17:
            return ""
        iv, cipher = raw[:16], raw[16:]
        try:
            dec = Cipher(algorithms.AES(self.AES_KEY), modes.CBC(iv)).decryptor()
            padded = dec.update(cipher) + dec.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            return (unpadder.update(padded) + unpadder.finalize()).decode(
                "utf-8", "ignore")
        except Exception:
            return ""

    # ---------- 请求 ----------
    def _headers(self):
        h = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "X-Deviceinfo": ("||9|12.27.0|chrome|120.0|||windows unknow"
                             "|1920X526|zh-CN|||"),
            "hcy-cool-flag": "1",
            "CMS-DEVICE": "default",
            "x-m4c-caller": "PC",
            "X-Yun-Api-Version": "v1",
            "Origin": "https://yun.139.com",
            "Referer": "https://yun.139.com/",
        }
        if self._authorization:
            h["Authorization"] = "Basic " + self._authorization
        elif self._raw_cookie:
            h["Cookie"] = self._raw_cookie
        return h

    def _share_post(self, path, data):
        """外链接口：请求体加密，响应解密；解不开就按明文 JSON 兜底。"""
        url = self.BASE + "/yun-share" + path
        body = self._aes_encrypt(json.dumps(data, ensure_ascii=False))
        try:
            r = self.s.post(url, data=body.encode("utf-8"),
                            headers=self._headers(), timeout=25)
        except requests.RequestException as e:
            raise TransferError("网络错误: %s" % e, retryable=True)
        if r.status_code in (401, 403):
            raise TransferError("登录状态失效，请更新令牌或 Cookie",
                                invalid_account=True)
        text = (r.text or "").strip()
        dec = self._aes_decrypt(text)
        payload = None
        for candidate in (dec, text):
            if not candidate:
                continue
            try:
                obj = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(obj, dict):
                payload = obj
                break
        if payload is None:
            raise TransferError("移动云盘响应解析失败，可能被风控拦截",
                                retryable=True)
        self._raise_if_error(payload)
        return payload

    @staticmethod
    def _raise_if_error(payload):
        # 成功判定：success 为真，或 code ∈ {0, 0000, 200, 空}。
        # 移动个人盘接口成功返回 success:true + code:"0000"，必须按 success 优先判定，
        # 否则会把“请求成功”误判成错误，导致检测失败（网站即用 success 优先判定）。
        if payload.get("success"):
            return
        code = str(payload.get("code", "0"))
        if code in ("0", "0000", "200", ""):
            return
        msg = payload.get("message") or payload.get("msg") or "未知错误"
        low = msg.lower()
        # 认证类失败一律判为账号失效（含“认证失败”/auth/token 等）
        if any(k in low for k in ("登录", "未授权", "失效", "unauthorized",
                                  "认证", "auth", "token")):
            raise TransferError(msg, invalid_account=True)
        raise TransferError(msg, retryable=True)

    # ---------- 读分享 ----------
    def _read_share(self, link_id, password=""):
        payload = self._share_post(
            "/richlifeApp/devapp/IOutLink/getOutLinkInfoV6",
            {"getOutLinkInfoReq": {
                "account": "", "linkID": link_id, "passwd": password,
                "caSrt": 0, "coSrt": 0, "srtDr": 1, "bNum": 1,
                "pCaID": "root", "eNum": 200,
            }})
        data = payload.get("data") or payload
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _extract_list(data):
        """分享内容：真实结构 data.caLst[]（文件夹）/ data.coLst[]（文件）。
        统一归一成 {'path','name','dir'} 供 _save 分流。"""
        if not isinstance(data, dict):
            return []
        out = []
        for key, is_dir in (("caLst", 1), ("coLst", 0)):
            lst = data.get(key)
            if not isinstance(lst, list):
                continue
            for it in lst:
                if not isinstance(it, dict):
                    continue
                if is_dir:
                    path = str(it.get("path") or it.get("caID") or
                               it.get("catalogID") or "")
                    name = str(it.get("caName") or it.get("catalogName") or "")
                else:
                    path = str(it.get("path") or it.get("coID") or
                               it.get("contentID") or "")
                    name = str(it.get("coName") or it.get("contentName") or "")
                if not path:
                    continue
                out.append({"path": path, "name": name, "dir": is_dir})
        return []

    @staticmethod
    def _mcloud_sign(raw_body):
        """对齐网站 YidongPan::mcloudSign。
        sign = UPPER(MD5( MD5(BASE64(sort(urlencode(body)))) + MD5(ts + ':' + rand) ))
        ts 用北京时间(UTC+8)。个人盘接口必须带此签名，否则列目录返回空。"""
        import hashlib, base64, random, string
        from datetime import datetime, timezone, timedelta
        import urllib.parse
        enc = urllib.parse.quote(raw_body, safe="")          # rawurlencode
        r = hashlib.md5(base64.b64encode(
            "".join(sorted(enc)).encode("utf-8"))).hexdigest()
        ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        rs = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        c = hashlib.md5((ts + ":" + rs).encode("utf-8")).hexdigest()
        return hashlib.md5((r + c).encode("utf-8")).hexdigest().upper(), ts, rs

    def _personal_headers(self, sign, ts, rs):
        h = {
            "Content-Type": "application/json",
            "caller": "web",
            "x-m4c-caller": "PC",
            "x-m4c-src": "10002",
            "mcloud-client": "10701",
            "mcloud-version": "7.17.2",
            "mcloud-channel": "1000101",
            "mcloud-route": "001",
            "mcloud-sign": "%s,%s,%s" % (ts, rs, sign),
            "INNER-HCY-ROUTER-HTTPS": "1",
            "x-inner-ntwk": "2",
            "x-yun-channel-source": "10000034",
            "x-huawei-channelSrc": "10000034",
            "x-yun-svc-type": "1",
            "x-SvcType": "1",
            "x-yun-module-type": "100",
            "x-yun-app-channel": "10000034",
            "x-yun-api-version": "v1",
            "x-yun-client-info": "||9|7.17.2|chrome|143.0.0.0|php-port||linux||zh-CN|||",
            "X-Deviceinfo": "||9|7.17.2|chrome|143.0.0.0|php-port||linux||zh-CN|||",
            "CMS-DEVICE": "default",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Origin": "https://yun.139.com",
            "Referer": "https://yun.139.com/",
        }
        if self._authorization:
            h["Authorization"] = "Basic " + self._authorization
        elif self._raw_cookie:
            h["Cookie"] = self._raw_cookie
        return h

    def _personal_post(self, host, path, body):
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        url = host + path
        sign, ts, rs = self._mcloud_sign(raw)
        headers = self._personal_headers(sign, ts, rs)
        try:
            r = self.s.post(url, data=raw.encode("utf-8"),
                           headers=headers, timeout=30)
        except requests.RequestException as e:
            raise TransferError("网络错误: %s" % e, retryable=True)
        # 诊断日志：把个人接口“发了什么 + 服务端回了什么”都落盘，
        # 方便排查“认证失败 / 空列表”。Cookie 只记长度与首尾若干字符，不落全量。
        try:
            _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            _dbg = os.path.join(_exe_dir, "mobile_personal_debug.log")
            _ck = self._raw_cookie or ""
            _ck_mask = ("len=%d %s...%s" % (len(_ck), _ck[:10], _ck[-10:])
                        if _ck else "none")
            _has_sign = "mcloud-sign" in headers
            with open(_dbg, "a", encoding="utf-8") as _f:
                _f.write("[%s] POST %s\nHTTP=%s\nAUTH=%s\nSIGN=%s\nCOOKIE=%s\n"
                         "BODY=%s\n\n" % (
                    time.strftime("%m-%d %H:%M:%S"), url, r.status_code,
                    "Basic" if self._authorization else "Cookie",
                    _has_sign, _ck_mask, (r.text or "")[:2000]))
        except Exception:
            pass
        if r.status_code in (401, 403):
            raise TransferError("登录状态失效，请更新令牌或 Cookie",
                                invalid_account=True)
        try:
            payload = r.json()
        except ValueError:
            raise TransferError("移动云盘响应异常，令牌可能已失效",
                                invalid_account=True)
        self._raise_if_error(payload)
        return payload

    # ---------- 四个抽象方法 ----------
    def _check(self):
        if not self._authorization and not self._raw_cookie:
            return False, ("未填写凭据（移动云盘个人接口可用 Basic 授权令牌 "
                           "pc:手机号:令牌，也可用 yun.139.com 会话 Cookie）")
        try:
            self._list_dir()
        except TransferError as e:
            msg = str(e)
            # 凭据被服务端拒绝：先怀疑凭据失效/不完整，而非“接口不支持 Cookie”
            # —— 网站本身也用 Cookie 走通了个人接口，所以不要误判。
            if self._raw_cookie and not self._authorization:
                msg += ("（若你确认网站用的就是这份 Cookie 且仍有效，请检查粘贴的是否为"
                        "完整、未过期的 yun.139.com 会话 Cookie；也可改用网站后台 "
                        "yidong_authorization 令牌试试。详细原因见 mobile_personal_debug.log）")
            return False, msg
        return True, "正常"

    def _list_dir(self, parent_id="0"):
        # 对齐网站 YidongPan::listDir / getFiles：
        #   端点 personalHost + /hcy/file/list，明文 JSON + mcloud-sign，
        #   响应取 data.items / data.fileList；按 type/category=='folder' 判定目录。
        #   旧实现错用 getCatalogInfo 且无签名，接口返回空，_check 误判“正常”却列不到目录。
        pid = str(parent_id or "")
        if pid in ("0", "root", ""):
            pid = "/"
        body = {
            "pageInfo": {"pageSize": 200, "pageCursor": None},
            "orderBy": "updated_at",
            "orderDirection": "DESC",
            "parentFileId": pid,
            "imageThumbnailStyleList": [],
        }
        payload = self._personal_post(
            self.PERSONAL_BASE, "/hcy/file/list", body)
        code = str(payload.get("code", "0"))
        if not payload.get("success") and code not in ("0", "200", ""):
            msg = payload.get("message") or payload.get("msg") or "未知错误"
            raise TransferError("移动云盘列目录失败：%s" % msg,
                                invalid_account=any(
                                    k in msg for k in ("登录", "失效", "未授权")))
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            log.warning("[移动云盘] /hcy/file/list 返回结构异常：%s",
                        json.dumps(payload, ensure_ascii=False)[:2000])
            return []
        raw_list = data.get("items") or data.get("fileList") or []
        out = []
        for it in (raw_list or []):
            if not isinstance(it, dict):
                continue
            fid = str(it.get("fileId") or it.get("id") or "")
            if not fid:
                continue
            is_dir = str(it.get("type") or it.get("category") or "").lower() == "folder"
            if not is_dir:
                continue
            out.append({
                "id": fid,
                "name": str(it.get("name") or it.get("fileName") or ""),
                "is_dir": True,
            })
        if not out:
            log.warning("[移动云盘] 目录 %s 未解析到子目录，原始响应：%s",
                        parent_id, json.dumps(payload, ensure_ascii=False)[:2000])
        return out

    def _save(self, share_url, password="", target_dir_id=""):
        link_id = self.parse_share_id(share_url)
        data = self._read_share(link_id, (password or "").strip())
        items = self._extract_list(data)
        if not items:
            raise TransferError("读不到分享内容，链接可能已失效")

        content_list, catalog_list = [], []
        for it in items:
            path = (it.get("path") or it.get("filePath") or
                    it.get("name") or "")
            if not path:
                continue
            if str(it.get("dir") or it.get("type") or 0) == "1":
                catalog_list.append(path)
            else:
                content_list.append(path)
        if not content_list and not catalog_list:
            raise TransferError("分享内容里没有可转存的条目")

        new_catalog = target_dir_id or self.account.get("save_dir_id") or "/"
        payload = self._share_post(
            "/richlifeApp/devapp/IBatchOprTask/createOuterLinkBatchOprTask",
            {"createOuterLinkBatchOprTaskReq": {
                "msisdn": self._phone, "ownerAccount": "", "taskType": 1,
                "linkID": link_id,
                "needPassword": 1 if password else 0,
                "taskInfo": {
                    "linkID": link_id,
                    "needPassword": 1 if password else 0,
                    "contentInfoList": content_list,
                    "catalogInfoList": catalog_list,
                    "newCatalogID": new_catalog,
                },
            }})

        task_id = ""
        d = payload.get("data") or {}
        for src in (d, payload):
            for key in ("taskID", "taskId"):
                if src.get(key):
                    task_id = str(src[key])
                    break
            if task_id:
                break
        if not task_id:
            raise TransferError(payload.get("message") or
                                "转存任务创建失败")

        return self._wait_task(task_id, link_id)

    def _wait_task(self, task_id, link_id):
        for _ in range(self.TASK_POLL_TIMES):
            payload = self._share_post(
                "/richlifeApp/devapp/IOutLink/getTaskStatus",
                {"getTaskStatusReq": {"taskId": task_id}})
            d = payload.get("data") or payload
            status = str(d.get("status") or "").lower()
            if status in self._SUCCESS_STATUS:
                for key in ("fileIdList", "batchFileResults"):
                    fids = d.get(key)
                    if fids:
                        return [str(x) for x in fids]
                raise TransferError("转存完成但没拿到文件 ID")
            if status in ("failed", "fail", "3", "-1"):
                raise TransferError(d.get("message") or "转存任务失败")
            time.sleep(self.TASK_POLL_INTERVAL)
        raise TransferError("转存任务超时（%d 秒）" %
                            int(self.TASK_POLL_TIMES * self.TASK_POLL_INTERVAL))

    def _share(self, file_ids, title="", expire_days=0):
        """
        生成自己的外链。
        ⚠️ 端点与字段为按读接口推断，实测若失败优先核对这里。
        """
        new_catalog = self.account.get("save_dir_id") or "/"
        payload = self._share_post(
            "/richlifeApp/devapp/IOutLink/createOutLink",
            {"createOutLinkReq": {
                "title": title or "资源",
                "urlType": 0,
                "fileIdList": list(file_ids or []),
                "expiredTime": int(expire_days or 0),
                "newCatalogID": new_catalog,
            }})
        out_set = (payload.get("getOutLinkRes", {}) or {}).get(
            "getOutLinkResSet") or (payload.get("data", {}) or {}).get(
            "getOutLinkResSet") or []
        if not out_set:
            raise TransferError(payload.get("message") or
                                "创建分享失败（需核对 createOutLink 端点/字段）")
        first = out_set[0] if isinstance(out_set[0], dict) else {}
        url = first.get("linkUrl") or ""
        if not url:
            raise TransferError("创建分享未返回链接")
        return ShareResult(url=url, password=first.get("passwd") or "",
                           expire="%d天" % int(expire_days or 0)
                           if expire_days else "永久")
