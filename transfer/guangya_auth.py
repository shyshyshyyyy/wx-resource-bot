# -*- coding: utf-8 -*-
"""
光鸭（Guangya / 迅雷旗下）账号凭证模块。

为什么单独拆出来：
  原 GuangyaAdapter 只支持「手动粘贴 refresh_token」。用户经常踩坑：
  把 Cookie / access_token(JWT) 当 refresh_token 填，或者 refresh_token
  过期后束手无策。本模块实现「手机验证码登录」与「refresh_token 续期」两条
  拿到凭证的路径，供面板调用。

光鸭鉴权范式（迅雷系 XLPs，已对线上接口实测确认）：
  - captcha  : account.guangyapan.com/v1/shield/captcha/init
               -> {"captcha_token": "...", "expires_in": 300}
               ⚠️ 该 captcha_token 必须在**浏览器里过滑块**才能把手机号绑上去，
                  纯接口拿到的 captcha_token 调 auth/verification 会被判
                  captcha_invalid（安全验证未通过）。
  - 发短信   : account.guangyapan.com/v1/auth/verification
               body 需含 phone_number（格式 "+86 138xxxx"）与已绑定手机号的
               captcha_token。同样被滑块前置拦截。
  - 换令牌   : account.guangyapan.com/v1/auth/token
               grant_type=urn:ietf:params:oauth:grant-type:local_oauth
               带 code（短信验证码）-> {access_token, refresh_token, expires_in}
  - 续期     : account.guangyapan.com/v1/auth/token
               grant_type=refresh_token -> {access_token, refresh_token, expires_in}

结论：自动化「手机+短信」接口被人机验证挡死，所以本模块对外提供两种拿到凭证的方式：
  1) login_by_sms()      —— 走完整 API 流程（仅在滑块未强制拦截的环境可用，
                             失败会抛出明确的 CaptchaRequired 让上层引导用户去浏览器）。
  2) browser_assisted()  —— 打开官网登录页，用户过滑块+短信登录后，把页面里
                             的 refresh_token 复制回来。这是 99% 场景的可用路径。
无论哪种，最终都收敛成一个 refresh_token，交给 GuangyaAdapter 自动续期使用。
"""

import json
import time
import logging
import webbrowser

import requests

log = logging.getLogger("transfer.guangya_auth")

CLIENT_ID = "aMe-8VSlkrbQXpUR"
ACCOUNT_BASE = "https://account.guangyapan.com"
WEB_LOGIN = "https://www.guangyapan.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")

# 浏览器登录页（过滑块 + 短信验证码后，从 devtools / localStorage 取 refresh_token）
WEB_LOGIN_URL = WEB_LOGIN + "/login"


class GuangyaAuthError(Exception):
    """光鸭凭证相关错误，带一个 human 可读的中文说明。"""


class CaptchaRequired(GuangyaAuthError):
    """滑块人机验证未过，必须引导用户去浏览器完成。"""


def _headers(device_id, captcha_token=""):
    return {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "Origin": WEB_LOGIN,
        "Referer": WEB_LOGIN + "/",
        "User-Agent": UA,
        "X-Client-Id": CLIENT_ID,
        "X-Device-Id": device_id,
        "X-Captcha-Token": captcha_token,
    }


def _post(path, body, device_id, captcha_token=""):
    try:
        r = requests.post(ACCOUNT_BASE + path, json=body,
                          headers=_headers(device_id, captcha_token), timeout=25)
    except requests.RequestException as e:
        raise GuangyaAuthError("网络错误: %s" % e)
    try:
        data = r.json()
    except ValueError:
        raise GuangyaAuthError("光鸭响应不是 JSON，可能被风控拦截")
    return r.status_code, data


def _norm_phone(phone):
    """统一成 '+86 138xxxx' 形式（光鸭接口要求带国家码、空格分隔）。"""
    p = (phone or "").strip().replace(" ", "").replace("-", "")
    if p.startswith("+86"):
        p = p[3:]
    if p.startswith("86"):
        p = p[2:]
    p = p.lstrip("0")
    if not p.startswith("1") or len(p) != 11:
        raise GuangyaAuthError("手机号格式不对，应为 11 位中国大陆手机号")
    return "+86 " + p


def captcha_init(device_id, phone):
    """拿 captcha_token。注意：纯接口拿到的 token 调发短信会被判 captcha_invalid，
    必须先在浏览器过滑块。这里仅作为 login_by_sms 的前置，失败抛 CaptchaRequired。"""
    phone = _norm_phone(phone)
    st, data = _post("/v1/shield/captcha/init", {
        "client_id": CLIENT_ID,
        "action": "POST:/v1/auth/verification",
        "device_id": device_id,
        "meta": {"username": "", "phone_number": "", "VERIFICATION_PHONE": phone},
    }, device_id)
    if st == 200 and data.get("captcha_token"):
        return data["captcha_token"]
    err = data.get("error_description") or data.get("msg") or data.get("error") or "未知错误"
    raise CaptchaRequired("获取人机验证令牌失败：%s" % err)


def send_sms(device_id, phone, captcha_token):
    """发送短信验证码。滑块未过会抛 CaptchaRequired。"""
    phone = _norm_phone(phone)
    st, data = _post("/v1/auth/verification", {
        "client_id": CLIENT_ID,
        "device_id": device_id,
        "phone_number": phone,
        "VERIFICATION_PHONE": phone,
        "captcha_token": captcha_token,
        "action": "POST:/v1/auth/verification",
    }, device_id, captcha_token)
    # 成功通常返回 {verification_id / verification_token / ...} 或无 error
    if st == 200 and "error" not in data:
        return data.get("verification_id") or data.get("verification_token") or ""
    err = data.get("error_description") or data.get("msg") or data.get("error") or "未知错误"
    if data.get("error") == "captcha_invalid" or "captcha" in (err or "").lower():
        raise CaptchaRequired("发送短信被拦：人机验证未通过（需先在浏览器过滑块）。%s" % err)
    raise GuangyaAuthError("发送验证码失败：%s" % err)


def exchange(device_id, phone, code, captcha_token, verification_id=""):
    """用短信验证码换 access_token + refresh_token。"""
    phone = _norm_phone(phone)
    body = {
        "client_id": CLIENT_ID,
        "device_id": device_id,
        "grant_type": "urn:ietf:params:oauth:grant-type:local_oauth",
        "code": (code or "").strip(),
        "phone_number": phone,
    }
    if verification_id:
        body["verification_id"] = verification_id
    st, data = _post("/v1/auth/token", body, device_id, captcha_token)
    if st == 200 and data.get("refresh_token"):
        return {
            "access_token": data.get("access_token", ""),
            "refresh_token": data.get("refresh_token", ""),
            "expires_in": int(data.get("expires_in", 7200)),
        }
    err = data.get("error_description") or data.get("msg") or data.get("error") or "未知错误"
    if data.get("error") == "authorization_pending" or "not yet authorized" in (err or "").lower():
        raise GuangyaAuthError("验证码不正确或已过期，请重新获取")
    raise GuangyaAuthError("换取令牌失败：%s" % err)


def login_by_sms(device_id, phone, code, captcha_token=None, verification_id=""):
    """完整 API 短信登录。滑块挡住时抛 CaptchaRequired，由上层引导浏览器。"""
    if not captcha_token:
        captcha_token = captcha_init(device_id, phone)
    send_sms(device_id, phone, captcha_token)
    return exchange(device_id, phone, code, captcha_token, verification_id)


def open_browser_login():
    """打开光鸭官网登录页，让用户过滑块+短信登录。"""
    try:
        webbrowser.open(WEB_LOGIN_URL)
        return True
    except Exception as e:
        log.warning("[光鸭] 打开浏览器失败: %s", e)
        return False


def verify_refresh_token(device_id, refresh_token):
    """校验 refresh_token 是否还能换到 access_token（用于『检测』与粘贴后即时校验）。"""
    rt = (refresh_token or "").strip()
    if not rt:
        raise GuangyaAuthError("refresh_token 为空")
    if rt[:3] == "eyJ":
        raise GuangyaAuthError("这是 access_token（JWT，eyJ 开头），不是 refresh_token。"
                               "请到 guangyapan.com 复制 refresh_token（gy. 开头）")
    st, data = _post("/v1/auth/token", {
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": rt,
    }, device_id)
    if st == 200 and data.get("access_token"):
        expires_in = int(data.get("expires_in", 7200))
        return {
            "ok": True,
            "access_token": data.get("access_token", ""),
            "refresh_token": data.get("refresh_token") or rt,
            "expires_in": expires_in,
        }
    err = data.get("error_description") or data.get("msg") or data.get("error") or "未知错误"
    return {"ok": False, "error": err}
