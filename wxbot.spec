# -*- mode: python ; coding: utf-8 -*-
"""
微信资源搜索机器人 —— PyInstaller 单文件打包配置

用法：
    .venv313\Scripts\python.exe -m PyInstaller wxbot.spec --noconfirm --clean

要点：
- onefile + windowed（不弹黑窗）
- 所有可写数据运行时落在 exe 同级 data/（见 core/paths.py）
- wxauto4 依赖 tkinter，必须显式带上
- wxautox4 为可选内核，装了就一起打进去
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = os.path.abspath(SPECPATH) if 'SPECPATH' in globals() else os.path.abspath('.')

datas = []
binaries = []
hiddenimports = [
    # 侧边栏图标用 Bootstrap Icons 的 SVG，走 QSvgRenderer 渲染（不用图标字体，
    # 避免 Windows 分数缩放下字体渲染异常）
    'PySide6.QtSvg', 'PySide6.QtXml',
    # wxauto4 依赖 tkinter（UI 自动化取窗口句柄）
    'tkinter', 'tkinter.ttk', 'tkinter.font', 'tkinter.messagebox', 'tkinter.filedialog',
    # 业务模块（动态 import 的部分）
    'schedule', 'requests', 'PIL', 'PIL.Image', 'PIL.ImageTk',
    'email_send', 'webhook_send', 'logger', 'license', 'config_manager',
    'netdisk_bot', 'wxbot_core',
    # 转存适配器：靠 @register 装饰器登记，且是运行时动态 import，
    # 不打进包会导致"暂不支持 xxx"
    'transfer', 'transfer.base', 'transfer.adapters',
    # wxauto4/utils/tools.pyd 是编译扩展，内部 import httpx，静态分析抓不到，必须显式声明
    'httpx', 'httpx._client', 'httpx._transports.default',
    'httpcore', 'httpcore._sync.connection_pool', 'httpcore._backends.sync',
    'h11', 'sniffio', 'anyio', 'anyio._backends._asyncio',
    'certifi', 'idna', 'charset_normalizer',
]

# wxauto4 的 .pyd 扩展通过 C API 动态导入标准库，静态分析抓不到，
# 这里把常用标准库显式声明，避免运行时 ModuleNotFoundError。
_STDLIB_EXTRA = [
    'difflib', 'csv', 'configparser', 'filecmp', 'fnmatch', 'glob', 'shutil',
    'tempfile', 'random', 'secrets', 'statistics', 'pprint', 'textwrap',
    'unicodedata', 'uuid', 'platform', 'getpass', 'socket', 'ssl', 'selectors',
    'asyncio', 'subprocess', 'winreg', 'msvcrt', 'ctypes', 'ctypes.wintypes',
    'concurrent.futures', 'concurrent.futures.thread', 'concurrent.futures.process',
    'dataclasses', 'typing', 'enum', 'contextlib', 'copy', 'pickle', 'shelve',
    'sqlite3', 'sqlite3.dbapi2', 'logging', 'logging.handlers', 'warnings',
    'pydoc', 'doctest', 'calendar', 'zoneinfo', 'locale', 'gettext',
    'urllib.parse', 'urllib.request', 'urllib.error', 'urllib.robotparser',
    'http.client', 'http.cookies', 'http.server', 'xmlrpc.client', 'xmlrpc.server',
    'smtplib', 'imaplib', 'poplib', 'ftplib', 'email', 'email.parser',
    'email.header', 'email.mime.text', 'email.mime.multipart', 'email.mime.base',
    'email.mime.image', 'email.mime.application', 'html.parser', 'html.entities',
    'xml.etree.ElementTree', 'xml.dom.minidom', 'xml.sax', 'json.decoder',
    'json.encoder', 'base64', 'binascii', 'quopri', 'uu', 'hashlib', 'hmac',
    'struct', 'zlib', 'gzip', 'bz2', 'lzma', 'zipfile', 'tarfile', 'mimetypes',
    'inspect', 'importlib.metadata', 'importlib.resources', 'importlib.util',
    'collections.abc', 'numbers', 'decimal', 'fractions', 'operator',
    'itertools', 'functools', 'string', 're', 'math', 'cmath', 'array',
    'queue', 'threading', 'multiprocessing', 'signal', 'errno', 'stat',
]
hiddenimports += _STDLIB_EXTRA

for mod in ('core', 'transfer', 'search', 'panel_qt', 'panel_qt.pages'):
    try:
        hiddenimports += collect_submodules(mod)
    except Exception as e:
        print('[spec] collect_submodules skip %s: %s' % (mod, e))

# 包体资源（二进制 / 数据文件）
for pkg in ('wxauto4', 'cryptography', 'PIL', 'schedule', 'psutil', 'pyperclip',
            'httpx', 'httpcore', 'anyio', 'h11', 'sniffio', 'sounddevice'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
        print('[spec] collect_all ok: %s' % pkg)
    except Exception as e:
        print('[spec] collect_all skip %s: %s' % (pkg, e))

# 可选：付费内核 wxautox4，装了才打
try:
    import wxautox4  # noqa: F401
    d, b, h = collect_all('wxautox4')
    datas += d
    binaries += b
    hiddenimports += h
    print('[spec] wxautox4 included')
except Exception:
    print('[spec] wxautox4 not installed, skip')

# 图标
if os.path.exists(os.path.join(SPEC_DIR, 'assets', 'logo.ico')):
    datas.append((os.path.join(SPEC_DIR, 'assets'), 'assets'))

excludes = [
    'flask', 'fastapi', 'uvicorn', 'starlette', 'pydantic',
    'IPython', 'notebook', 'pytest', 'setuptools._distutils',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.Qt3DCore',
    'matplotlib', 'scipy', 'numpy', 'pandas',
]

a = Analysis(
    [os.path.join(SPEC_DIR, 'gui_main.py')],
    pathex=[SPEC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='微信资源搜索机器人',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(SPEC_DIR, 'assets', 'logo.ico') if os.path.exists(
        os.path.join(SPEC_DIR, 'assets', 'logo.ico')) else None,
)
