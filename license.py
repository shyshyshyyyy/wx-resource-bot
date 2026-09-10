# -*- coding: utf-8 -*-
"""
离线机器码授权（RSA-2048 非对称签名）。

在你原版基础上做的改动（签发端 workbuddy 无需任何改动）：
  1. 机器码来源换掉 wmic + MAC —— wmic 在 Win11 24H2 / Server 2025 已被移除，
     MAC 在虚拟机 / 多网卡场景不稳定。改为多因子 + 容错匹配。
  2. 首次计算出的机器码写入用户级目录锁定（machine.lock），之后优先读锁定值，
     只要"多因子中至少 N 个仍然吻合"就继续沿用，硬件小改动不会导致授权失效。
  3. 子进程加 CREATE_NO_WINDOW，无控制台 exe 不再闪黑框。
  4. 增加时间回拨检测：记录曾见过的最大时间戳，系统时间往回调会被识别。
  5. 去掉重复定义的 load_license。
  6. payload 兼容两种格式：老的 "机器码|到期时间戳"，
     以及可选的 JSON（便于以后加授权等级、额度），老码继续有效。

激活码格式保持不变： base64url(payload) + "." + base64url(签名)
"""

import os
import sys
import json
import time
import base64
import logging
import hashlib
import subprocess

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.exceptions import InvalidSignature
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False

# 混淆后的内置公钥（base64 后整体反转，运行时还原；仅用于验签）
# 与「授权生成器」keys/public.pem 为同一对密钥（2026-09-09 对齐）
_PUB_SCRAMBLED = "t0SLt0SWFtEIDlETCVFUgQkTF1SLt0SLKIUQRFERJd3SKMXZXJ0RT90TG9UeWFEZ2l2UEFTNwEWeyoFWWBTUsVDb1VnSoNHN3AFWmlUMyMHSHR0QMFWOWxmRthXYXFEeXRkC0VDSZh2Tsp1TwVlQWR1coNEWYlmc09SdmFVWmN1LCVDSRB3aqVHRPJneEVnZoNUeyc3cLZnaYFVVzlnazRFZRpwLrkEVKdXe3s2TVNEattkeIRUR3EEVL1WUL9idP9CUzgzZXBncOd1Y0cnS51EUnZ0KyVVQjJjWFJ0daZmd582dKcnaxpnZ4IVeytUaylmWlFkMoBXURlmR48UUZVnNidnRaZ1QqlDNkVHcMJkclBVMtVWUTh3TTV3SzdmZlRWZyZjCuNnUvkWS1E1clJFbSNVSNJzTlVTS6x2KSVDbppUZWdVNTV2MSNEasJ2QvQUVIdXW5sEUJ9mNX1GUVlWQnNTdCpwR2VVe0tCatFVTrQjRVREZrA1NwFURRF0QLd2QClUSNFEORF0QPFUQGVUUBJEM3lzRptGaxt2ZC5UQqlkQJlUTK0SLt0SLZV0SgMUSMJUVQBiTJdURC1SLt0SL"

# 本软件的 appId —— 必须与「授权生成器 → 我的软件」里新增的软件 appId 完全一致。
# 注意：一旦开始对外发码，这个值就不能再改，否则已发出的授权码会全部失效。
APP_ID = "wx-resource-bot"

APP_DIR_NAME = "WxSearchBot"

log = logging.getLogger("license")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ----------------------------------------------------------
# 用户级数据目录
# ----------------------------------------------------------
def user_data_dir():
    """授权数据目录。

    优先落到程序 data/ 目录（可备份、可迁移，也符合"不往系统盘写"的原则），
    取不到时再退回用户目录兜底。
    """
    try:
        from core import paths
        return paths.data_dir()
    except Exception:
        pass
    base = (os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~"))
    d = os.path.join(base, APP_DIR_NAME)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _user_license_path():
    return os.path.join(user_data_dir(), ".license")


def _machine_lock_path():
    return os.path.join(user_data_dir(), "machine.lock")


def _clock_path():
    return os.path.join(user_data_dir(), ".clock")


# ----------------------------------------------------------
# 机器指纹（多因子 + 容错）
# ----------------------------------------------------------
def _powershell(script):
    """用 PowerShell 取 CIM 信息，替代已被移除的 wmic。"""
    if sys.platform != "win32":
        return ""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            stderr=subprocess.DEVNULL, timeout=8,
            creationflags=_CREATE_NO_WINDOW,
        )
        return out.decode("utf-8", "ignore").strip()
    except Exception:
        return ""


def _reg_machine_guid():
    """HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid —— 装机时生成，重装系统才变。"""
    if sys.platform != "win32":
        return ""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography", 0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        val, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return str(val).strip()
    except Exception:
        return ""


def _reg_install_id():
    """Windows 安装的 ProductId / InstallDate，重装才变。"""
    if sys.platform != "win32":
        return ""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", 0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        pid = ""
        for name in ("ProductId", "InstallDate"):
            try:
                v, _ = winreg.QueryValueEx(key, name)
                pid += str(v)
            except Exception:
                pass
        winreg.CloseKey(key)
        return pid.strip()
    except Exception:
        return ""


def _volume_serial():
    """系统盘卷序列号，格式化才变。"""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        root = (os.environ.get("SystemDrive") or "C:") + "\\"
        serial = ctypes.c_ulong(0)
        ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), None, 0,
            ctypes.byref(serial), None, None, None, 0)
        return "%08X" % serial.value if serial.value else ""
    except Exception:
        return ""


def _board_uuid():
    """主板 UUID。虚拟机里也有（VMware/Hyper-V 会给一个稳定值）。"""
    v = _powershell(
        "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID")
    v = (v or "").strip()
    # 一些主板会返回全 0 或全 F 的无效值
    if not v or set(v.replace("-", "")) <= {"0"} or set(v.replace("-", "").upper()) <= {"F"}:
        return ""
    return v.upper()


def _cpu_id():
    v = _powershell("(Get-CimInstance -ClassName Win32_Processor).ProcessorId")
    return (v or "").strip().upper()


def _hostname():
    return (os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "").strip().upper()


def _collect_factors():
    """返回有序因子字典。顺序固定，不要随意调整。"""
    return {
        "guid": _reg_machine_guid(),
        "board": _board_uuid(),
        "cpu": _cpu_id(),
        "vol": _volume_serial(),
        "inst": _reg_install_id(),
        "host": _hostname(),
    }


def _fmt_code(seed):
    digest = hashlib.sha256(seed.encode("utf-8", "ignore")).hexdigest().upper()
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))


def _compute_code(factors):
    seed = "|".join("%s=%s" % (k, v) for k, v in factors.items() if v)
    if not seed:
        seed = "fallback"
    return _fmt_code(seed)


# 至少要有几个因子仍然吻合，才认为还是同一台机器
_MATCH_THRESHOLD = 3


def get_machine_code():
    """
    优先返回已锁定的机器码。
    只有当"当前因子与锁定时记录的因子吻合数 < 阈值"时，才认为换机器了并重新生成。
    这样硬件小改动（换网卡、加硬盘、改主机名）不会让客户的授权失效。
    """
    cur = _collect_factors()
    lock_path = _machine_lock_path()

    try:
        if os.path.exists(lock_path):
            with open(lock_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            old = saved.get("factors") or {}
            code = saved.get("code") or ""
            if code:
                hits = sum(1 for k, v in old.items() if v and cur.get(k) == v)
                # 强因子（guid / board）任一命中即可直接沿用
                strong = any(old.get(k) and cur.get(k) == old.get(k)
                             for k in ("guid", "board"))
                if strong or hits >= _MATCH_THRESHOLD:
                    return code
    except Exception:
        pass

    code = _compute_code(cur)
    try:
        with open(lock_path, "w", encoding="utf-8") as f:
            json.dump({"code": code, "factors": cur,
                       "created": int(time.time())}, f, ensure_ascii=False)
    except Exception:
        pass
    return code


def machine_factor_report():
    """面板"环境自检"用：展示各因子是否取到，方便远程排障。"""
    f = _collect_factors()
    return {k: ("已获取" if v else "不可用") for k, v in f.items()}


# ----------------------------------------------------------
# 公钥加载（反混淆）
# ----------------------------------------------------------
_pub_cache = None


def _load_public_key():
    global _pub_cache
    if _pub_cache is not None:
        return _pub_cache
    if not _HAS_CRYPTO:
        return None
    try:
        raw = base64.b64decode(_PUB_SCRAMBLED[::-1])
        _pub_cache = serialization.load_pem_public_key(raw)
        return _pub_cache
    except Exception as e:
        log.warning("公钥加载失败: %s", e)
        return None


# ----------------------------------------------------------
# 反调试
# ----------------------------------------------------------
def _is_debugged():
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.IsDebuggerPresent())
    except Exception:
        return False


# ----------------------------------------------------------
# 时间回拨检测
# ----------------------------------------------------------
def _check_clock():
    """返回 (ok, now)。系统时间比历史最大值早超过 1 天则判定为回拨。"""
    now = int(time.time())
    path = _clock_path()
    seen = 0
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                seen = int((f.read() or "0").strip() or 0)
    except Exception:
        seen = 0
    if seen and now < seen - 86400:
        return False, now
    if now > seen:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(str(now))
        except Exception:
            pass
    return True, now


# ----------------------------------------------------------
# 验证激活码
# ----------------------------------------------------------
def _parse_payload(payload_bytes):
    """
    兼容两种 payload：
      老格式： "机器码|到期时间戳"
      新格式： JSON  {"m": 机器码, "e": 到期时间戳, "lv": 等级, "n": 备注}
    """
    text = payload_bytes.decode("utf-8")
    text_s = text.strip()
    if text_s.startswith("{"):
        d = json.loads(text_s)
        return {
            "machine": str(d.get("m") or d.get("machine") or ""),
            "expiry": int(d.get("e") or d.get("expiry") or 0),
            "level": str(d.get("lv") or d.get("level") or "pro"),
            "note": str(d.get("n") or d.get("note") or ""),
        }
    machine, exp_str = text.rsplit("|", 1)
    return {"machine": machine, "expiry": int(exp_str),
            "level": "pro", "note": ""}


def _fail(msg, **kw):
    d = {"ok": False, "msg": msg, "expiry": 0, "machine": "", "level": "",
         "note": "", "licenseId": "", "type": "", "features": [], "appId": ""}
    d.update(kw)
    return d


# ----------------------------------------------------------
# 授权生成器 v2 格式（JSON）
# ----------------------------------------------------------
def _canonical(payload: dict) -> str:
    """必须与生成器 canonical() 完全一致：key 排序 + 紧凑分隔 + 不转义中文。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _parse_iso(s):
    """'2027-09-09T08:00:00Z' → epoch 秒（UTC）。失败返回 0。"""
    if not s:
        return 0
    s = str(s).strip()
    try:
        import datetime as _dt
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = _dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return int(d.timestamp())
    except Exception:
        return 0


def _verify_v2(license_str, pub, current_code):
    """验证生成器新版授权码： {"payload": {...}, "signature": "base64"}

    返回 dict；如果文本不是该格式，返回 None（交给旧格式逻辑处理）。
    """
    s = license_str.strip()
    if not s.startswith("{"):
        return None
    try:
        obj = json.loads(s)
        payload = obj.get("payload")
        sig_b64 = obj.get("signature")
        if not isinstance(payload, dict) or not sig_b64:
            return _fail("激活码结构错误（缺少 payload / signature）")
        sig = base64.b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
    except Exception:
        return _fail("激活码格式错误（不是有效的 JSON）")

    data = _canonical(payload).encode("utf-8")
    try:
        pub.verify(sig, data, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return _fail("激活码签名无效（伪造或被篡改）")
    except Exception as e:
        return _fail("验证异常: %s" % e)

    # ---- 签名通过，开始业务校验 ----
    app_id = str(payload.get("appId") or "")
    if app_id and app_id != APP_ID:
        return _fail("该授权码不属于本软件（appId=%s）" % app_id)

    machine = str(payload.get("machineCode") or "")
    if current_code and machine.upper() != current_code.upper():
        return _fail("激活码与本机不匹配（机器码不符）", machine=machine)

    lic_type = str(payload.get("type") or "period")
    expiry = _parse_iso(payload.get("expiresAt"))  # 永久为 None → 0

    clock_ok, now = _check_clock()
    if not clock_ok:
        return _fail("系统时间异常（检测到时间回拨），请校准后重试",
                     machine=machine, expiry=expiry)
    if expiry and now > expiry:
        return _fail("激活码已过期", machine=machine, expiry=expiry)

    feats = payload.get("features") or []
    if not isinstance(feats, list):
        feats = [str(feats)]
    level = {"trial": "试用", "period": "正式", "permanent": "永久",
             "feature": "按功能"}.get(lic_type, lic_type)

    return {"ok": True, "msg": "已激活", "expiry": expiry, "machine": machine,
            "level": level, "note": str(payload.get("note") or ""),
            "licenseId": str(payload.get("licenseId") or ""),
            "type": lic_type, "features": feats, "appId": app_id}


def verify_license(license_str, current_code=None):
    """返回 dict(ok, msg, expiry, machine, level, note, licenseId, type, features)。

    同时兼容两种授权码：
      - 生成器 v2：JSON 文本 {"payload": {...}, "signature": "..."}
      - 旧格式  ：base64url(payload) + "." + base64url(签名)
    """
    if not license_str or not license_str.strip():
        return _fail("未激活")
    if not _HAS_CRYPTO:
        return _fail("客户端缺少加密组件")
    if _is_debugged():
        return _fail("检测到调试环境，已拒绝")

    pub = _load_public_key()
    if pub is None:
        return _fail("公钥缺失")

    s = license_str.strip()

    # ---- 优先按生成器新版 JSON 格式验证 ----
    if s.startswith("{"):
        return _verify_v2(s, pub, current_code)

    # ---- 旧格式：base64url(payload).base64url(sig) ----
    if "." not in s:
        return _fail("激活码结构错误")
    p_b64, s_b64 = s.rsplit(".", 1)
    try:
        p_b64 += "=" * (-len(p_b64) % 4)
        s_b64 += "=" * (-len(s_b64) % 4)
        payload = base64.urlsafe_b64decode(p_b64)
        sig = base64.urlsafe_b64decode(s_b64)
    except Exception:
        return _fail("激活码格式错误")

    try:
        pub.verify(sig, payload, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return _fail("激活码签名无效（伪造或被篡改）")
    except Exception as e:
        return _fail("验证异常: %s" % e)

    try:
        info = _parse_payload(payload)
    except Exception:
        return _fail("激活码内容损坏")

    machine, expiry = info["machine"], info["expiry"]

    if current_code and machine.upper() != current_code.upper():
        return _fail("激活码与本机不匹配（机器码不符）",
                     expiry=expiry, machine=machine)

    clock_ok, now = _check_clock()
    if not clock_ok:
        return _fail("系统时间异常（检测到时间回拨），请校准后重试",
                     expiry=expiry, machine=machine)

    if expiry and now > expiry:
        return _fail("激活码已过期", expiry=expiry, machine=machine)

    return {"ok": True, "msg": "已激活", "expiry": expiry, "machine": machine,
            "level": info.get("level", "pro"), "note": info.get("note", ""),
            "licenseId": "", "type": "period", "features": [], "appId": ""}


# ----------------------------------------------------------
# 持久化
# ----------------------------------------------------------
def _legacy_license_path():
    try:
        import config_manager
        return os.path.join(
            os.path.dirname(config_manager.get_config_path()), ".license")
    except Exception:
        return os.path.join(
            os.path.dirname(os.path.abspath(sys.executable)), ".license")


def _sync_user_license(code):
    if not code:
        return
    p = _user_license_path()
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                if f.read().strip() == code.strip():
                    return
        with open(p, "w", encoding="utf-8") as f:
            f.write(code.strip())
    except Exception:
        pass


def save_license(config, license_str):
    """写三处：config.json、程序目录 .license（老版兼容）、用户级目录（升级免重激活）。"""
    code = (license_str or "").strip()
    config["license"] = code
    try:
        import config_manager
        config_manager.save_config(config)
    except Exception:
        pass
    for path in (_legacy_license_path(), _user_license_path()):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
        except Exception:
            pass


def load_license(config):
    """加载顺序：config.json → 用户级目录 → 程序目录 .license（老版兼容）。"""
    code = (config or {}).get("license", "") or ""
    if code:
        _sync_user_license(code)
        return code
    for path in (_user_license_path(), _legacy_license_path()):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    c = f.read().strip()
                if c:
                    _sync_user_license(c)
                    return c
        except Exception:
            pass
    return ""


def check_license(config):
    """供面板 / 启动校验调用。源码运行时跳过强制授权，方便你自己开发调试。"""
    if getattr(sys, "frozen", False):
        return verify_license(load_license(config),
                              current_code=get_machine_code())
    return {"ok": True, "msg": "开发模式（跳过授权）", "expiry": 0,
            "machine": get_machine_code(), "level": "pro", "note": ""}


def days_left(info):
    exp = int((info or {}).get("expiry") or 0)
    if not exp:
        return -1  # 永久
    return max(0, int((exp - time.time()) // 86400))
