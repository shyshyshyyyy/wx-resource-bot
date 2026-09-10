# -*- coding: utf-8 -*-
"""管理面板后端。FastAPI + 单页前端。"""

import os
import time
import json
import secrets
import logging
import collections

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config_manager as cm
import license as lic
from core import env_check, template as tpl, session as sess
from core.wx_adapter import (probe_plus_activation, activate_plus,
                             export_core_machine_code)
from transfer import base as tbase

log = logging.getLogger("panel")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# 内存日志环，供面板实时查看
LOG_RING = collections.deque(maxlen=800)


class RingHandler(logging.Handler):
    def emit(self, record):
        try:
            LOG_RING.append({
                "t": time.strftime("%H:%M:%S", time.localtime(record.created)),
                "lv": record.levelname,
                "src": record.name,
                "msg": self.format(record),
            })
        except Exception:
            pass


def install_log_handler():
    h = RingHandler()
    h.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(h)


_SESSIONS = {}          # token -> expire_ts
_SESSION_TTL = 8 * 3600


def create_app(runtime):
    """runtime 由 main.py 构造，持有 bot / searcher / local pansou / pool。"""
    app = FastAPI(title="微信资源搜索机器人", docs_url=None, redoc_url=None)
    cfg = cm.load_config()

    # ---------- 鉴权 ----------
    def issue_token():
        tok = secrets.token_urlsafe(24)
        _SESSIONS[tok] = time.time() + _SESSION_TTL
        return tok

    def auth(request: Request):
        tok = request.cookies.get("wsb_token") or \
            request.headers.get("X-Token", "")
        exp = _SESSIONS.get(tok, 0)
        if not exp or exp < time.time():
            raise HTTPException(401, "登录已过期，请重新登录")
        return tok

    @app.post("/api/login")
    async def login(request: Request):
        body = await request.json()
        p = cfg.get("panel", {})
        if body.get("username") != p.get("username") or \
           body.get("password") != p.get("password"):
            raise HTTPException(401, "账号或密码不对")
        tok = issue_token()
        resp = JSONResponse({
            "ok": True,
            "must_change_password": p.get("password") == "admin123",
        })
        resp.set_cookie("wsb_token", tok, httponly=True, samesite="lax",
                        max_age=_SESSION_TTL)
        return resp

    @app.post("/api/logout")
    async def logout(tok=Depends(auth)):
        _SESSIONS.pop(tok, None)
        return {"ok": True}

    # ---------- 概览 ----------
    @app.get("/api/overview")
    async def overview(_=Depends(auth)):
        info = lic.check_license(cfg)
        return {
            "license": {
                "ok": info["ok"], "msg": info["msg"],
                "machine": lic.get_machine_code(),
                "days_left": lic.days_left(info),
                "expiry": info.get("expiry", 0),
            },
            "bot": runtime.bot.status() if runtime.bot else {"running": False},
            "pansou": runtime.local.status() if runtime.local else {},
            "accounts": {
                p: len(runtime.pool.usable(p))
                for p in tbase.registered_pans()
            },
            "env": env_check.run_all(),
        }

    @app.get("/api/env")
    async def env(_=Depends(auth)):
        return {"check": env_check.run_all(),
                "machine_factors": lic.machine_factor_report()}

    # ---------- 授权 ----------
    @app.get("/api/license")
    async def get_license(_=Depends(auth)):
        info = lic.check_license(cfg)
        core_ok, core_detail = probe_plus_activation()
        return {
            "machine": lic.get_machine_code(),
            "info": info,
            "days_left": lic.days_left(info),
            "core": {"activated": core_ok, "detail": core_detail,
                     "machine": export_core_machine_code()},
        }

    @app.post("/api/license")
    async def set_license(request: Request, _=Depends(auth)):
        body = await request.json()
        code = (body.get("code") or "").strip()
        info = lic.verify_license(code, current_code=lic.get_machine_code())
        if info["ok"]:
            lic.save_license(cfg, code)
        return {"ok": info["ok"], "msg": info["msg"],
                "expiry": info.get("expiry", 0)}

    @app.post("/api/core/activate")
    async def core_activate(request: Request, _=Depends(auth)):
        body = await request.json()
        ok, msg = activate_plus(body.get("code", ""))
        return {"ok": ok, "msg": msg}

    # ---------- 配置 ----------
    @app.get("/api/config")
    async def get_config(_=Depends(auth)):
        out = json.loads(json.dumps(cfg))
        out["license"] = "***" if out.get("license") else ""
        out.get("panel", {}).pop("password", None)
        for a in out.get("transfer", {}).get("accounts", []):
            a["cookie"] = ("已配置（%d 字符）" % len(a["cookie"])) if a.get("cookie") else ""
        return out

    @app.post("/api/config/{section}")
    async def set_config(section: str, request: Request, _=Depends(auth)):
        if section not in cfg:
            raise HTTPException(404, "没有这个配置分区")
        body = await request.json()
        cm.update(section, body)
        runtime.reload()
        return {"ok": True}

    @app.post("/api/panel/password")
    async def change_password(request: Request, _=Depends(auth)):
        body = await request.json()
        new = (body.get("password") or "").strip()
        if len(new) < 8:
            raise HTTPException(400, "密码至少 8 位")
        cm.update("panel", {"password": new})
        return {"ok": True}

    # ---------- 模板 ----------
    @app.get("/api/templates")
    async def get_templates(_=Depends(auth)):
        return {
            "values": cfg.get("templates", {}),
            "help": {k: tpl.help_for(k) for k in tpl.PLACEHOLDER_HELP},
        }

    @app.post("/api/templates")
    async def set_templates(request: Request, _=Depends(auth)):
        body = await request.json()
        problems = {}
        for k, v in body.items():
            ok, unknown = tpl.validate(k, v)
            if not ok:
                problems[k] = unknown
        if problems:
            return {"ok": False, "problems": problems}
        cm.update("templates", body)
        runtime.reload()
        return {"ok": True}

    @app.post("/api/templates/preview")
    async def preview_template(request: Request, _=Depends(auth)):
        body = await request.json()
        demo = {
            "keyword": "三体", "pan_name": "夸克", "total": 23, "page": 1,
            "pages": 3, "index": 1, "title": "三体 全集 4K 修复版",
            "source": "tgsearchers3", "size": "82.4GB", "datetime": "2026-08-20",
            "share_url": "https://pan.quark.cn/s/xxxxxxxx",
            "password_line": "提取码：a1b2", "password": "a1b2",
            "expire": "永久", "reason": "账号今日额度已用完",
            "origin_url": "https://pan.quark.cn/s/origin123", "max": 8,
        }
        return {"text": tpl.render(body.get("text", ""), **demo)}

    # ---------- 转存账号 ----------
    @app.get("/api/accounts")
    async def list_accounts(_=Depends(auth)):
        out = []
        for a in runtime.pool.list():
            b = dict(a)
            b["cookie"] = "已配置" if a.get("cookie") else ""
            out.append(b)
        return {"accounts": out,
                "pans": [{"key": k, "name": sess.PAN_DISPLAY.get(k, k),
                          "supported": tbase.is_implemented(k)}
                         for k in sess.PAN_DISPLAY if k not in ("magnet", "ed2k", "others")]}

    @app.post("/api/accounts")
    async def add_account(request: Request, _=Depends(auth)):
        body = await request.json()
        acc = dict(cm.ACCOUNT_TEMPLATE)
        acc.update({k: v for k, v in body.items() if k in acc})
        return {"ok": True, "account": runtime.pool.add(acc)}

    @app.put("/api/accounts/{acc_id}")
    async def edit_account(acc_id: str, request: Request, _=Depends(auth)):
        body = await request.json()
        # cookie 传占位符时表示不改
        if body.get("cookie") in ("已配置", "***"):
            body.pop("cookie")
        acc = runtime.pool.update(acc_id, body)
        if not acc:
            raise HTTPException(404, "账号不存在")
        return {"ok": True}

    @app.delete("/api/accounts/{acc_id}")
    async def del_account(acc_id: str, _=Depends(auth)):
        return {"ok": runtime.pool.remove(acc_id)}

    @app.post("/api/accounts/{acc_id}/check")
    async def check_account(acc_id: str, _=Depends(auth)):
        for a in runtime.pool.list():
            if a.get("id") == acc_id:
                cls = tbase.get_adapter(a.get("pan"))
                if not cls:
                    return {"ok": False, "msg": "该网盘的转存适配器尚未实现"}
                try:
                    ok, msg = cls(a).check()
                except Exception as e:
                    ok, msg = False, str(e)
                runtime.pool.update(acc_id, {"status": "ok" if ok else "invalid",
                                             "last_check": int(time.time())})
                return {"ok": ok, "msg": msg}
        raise HTTPException(404, "账号不存在")

    @app.get("/api/accounts/{acc_id}/dirs")
    async def list_dirs(acc_id: str, parent: str = "0", _=Depends(auth)):
        for a in runtime.pool.list():
            if a.get("id") == acc_id:
                cls = tbase.get_adapter(a.get("pan"))
                if not cls:
                    raise HTTPException(400, "该网盘的转存适配器尚未实现")
                return {"dirs": cls(a).list_dir(parent)}
        raise HTTPException(404, "账号不存在")

    # ---------- 盘搜 ----------
    @app.post("/api/search/test")
    async def test_search(request: Request, _=Depends(auth)):
        body = await request.json()
        kw = body.get("kw") or "测试"
        results, errors = runtime.searcher.search(kw, refresh=True)
        return {"count": len(results), "errors": errors,
                "sample": [{"title": r["title"],
                            "pan": sess.PAN_DISPLAY.get(r["pan"], r["pan"]),
                            "url": r["url"]} for r in results[:5]]}

    @app.post("/api/pansou/{action}")
    async def pansou_ctl(action: str, _=Depends(auth)):
        if not runtime.local:
            raise HTTPException(400, "本地盘搜未启用")
        if action == "start":
            ok, msg = runtime.local.start()
            return {"ok": ok, "msg": msg}
        if action == "stop":
            runtime.local.stop()
            return {"ok": True, "msg": "已停止"}
        if action == "restart":
            runtime.local.stop()
            ok, msg = runtime.local.start()
            return {"ok": ok, "msg": msg}
        raise HTTPException(404)

    # ---------- 机器人控制 ----------
    @app.post("/api/bot/{action}")
    async def bot_ctl(action: str, _=Depends(auth)):
        if action == "start":
            ok, msg = runtime.start_bot()
        elif action == "stop":
            ok, msg = runtime.stop_bot()
        elif action == "restart":
            runtime.stop_bot()
            ok, msg = runtime.start_bot()
        else:
            raise HTTPException(404)
        return {"ok": ok, "msg": msg}

    # ---------- 日志 ----------
    @app.get("/api/logs")
    async def logs(_=Depends(auth)):
        return {"lines": list(LOG_RING)}

    @app.get("/api/logs/stream")
    async def logs_stream(_=Depends(auth)):
        def gen():
            last = len(LOG_RING)
            while True:
                cur = len(LOG_RING)
                if cur != last:
                    items = list(LOG_RING)[-(cur - last if cur > last else 20):]
                    yield "data: %s\n\n" % json.dumps(items, ensure_ascii=False)
                    last = cur
                time.sleep(1)
        return StreamingResponse(gen(), media_type="text/event-stream")

    # ---------- 静态 ----------
    @app.get("/")
    async def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
