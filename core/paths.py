# -*- coding: utf-8 -*-
"""
统一路径管理（打包后必须可用）

硬性要求：
- 所有可写数据落在 **exe 同级 data/ 目录**，禁止写 _MEIPASS 临时目录
- 判断依据必须是 sys.executable + getattr(sys,'frozen',False)，**不能用 __file__**
"""

import os
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """exe 所在目录（开发环境为项目根目录）"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    """数据根目录：{app_dir}/data"""
    p = os.path.join(app_dir(), "data")
    os.makedirs(p, exist_ok=True)
    return p


def sub_dir(name: str) -> str:
    """data 下的子目录，自动创建"""
    p = os.path.join(data_dir(), name)
    os.makedirs(p, exist_ok=True)
    return p


def config_dir() -> str:
    """配置文件目录：data/config"""
    return sub_dir("config")


def config_file() -> str:
    return os.path.join(config_dir(), "config.json")


def prompt_dir() -> str:
    return sub_dir(os.path.join("config", "prompt"))


def log_dir() -> str:
    return sub_dir("logs")


def memory_dir() -> str:
    return sub_dir("memory")


def netdisk_dir() -> str:
    """网盘相关配置目录：data/netdisk"""
    return sub_dir("netdisk")


def netdisk_config_file() -> str:
    return os.path.join(netdisk_dir(), "netdisk.json")


def license_file() -> str:
    return os.path.join(data_dir(), "license.dat")


def assets_dir() -> str:
    """静态资源：打包后在 _MEIPASS/assets，开发时在 ./assets"""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", app_dir())
        return os.path.join(base, "assets")
    return os.path.join(app_dir(), "assets")
