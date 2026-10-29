"""
西科大教务助手 —— 打包启动器

本地运行：  python run.py
打包后运行：XustGradeWeb.exe  （双击即可，自动起服务并打开浏览器）

设计要点：
- 冻结模式（PyInstaller onefile）下，程序文件被解压到临时目录 _MEIPASS，
  而运行时需要「可写」的数据目录与「真实路径」的模板/静态目录。
- 因此首次运行时把只读资源（templates/static）与种子数据
  （data/cookies/users/history/key.key）落到持久化目录：
      Windows -> %APPDATA%/xust-grade-web
      Linux/Mac -> ~/.xust-grade-web
- 随后 chdir 到该目录，使 app.py 里所有相对路径（templates/、static/、
  data/、users/、cookies/、history/、key.key）都正确解析。
- app.py / config.py / core/ 由 PyInstaller 作为模块自动收集，无需复制。
"""

import os
import sys
import shutil
import threading
import webbrowser

FROZEN = getattr(sys, "frozen", False)


def _resolve_base():
    """确定持久化数据目录（可写，跨运行保留登录态/课表缓存）"""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(appdata, "xust-grade-web")
    return os.path.join(os.path.expanduser("~"), ".xust-grade-web")


def _seed(src_rel, dst_rel=None, file_ok=False):
    """
    把 _MEIPASS 中的资源 / 种子数据复制到 base（仅在目标缺失时，避免覆盖用户新数据）。
    src_rel / dst_rel 均为相对路径；file_ok=True 表示处理单个文件。
    """
    base = _BASE
    dst_rel = dst_rel or src_rel
    src = os.path.join(sys._MEIPASS, src_rel)
    dst = os.path.join(base, dst_rel)

    if file_ok:
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
        return

    if os.path.isdir(src) and not os.path.exists(dst):
        shutil.copytree(src, dst)


if FROZEN:
    _BASE = _resolve_base()
    os.makedirs(_BASE, exist_ok=True)

    # 只读资源：模板与静态文件需以真实路径存在
    _seed("templates")
    _seed("static")

    # 种子数据：仅首次运行时播种，之后以用户数据为准
    for d in ("data", "cookies", "users", "history"):
        _seed(d)
    _seed("key.key", file_ok=True)

    # 让所有相对路径解析到持久化目录
    os.chdir(_BASE)


PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")


def _open_browser():
    try:
        webbrowser.open(f"http://{HOST}:{PORT}")
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn

    print(f"西科大教务助手已启动：http://{HOST}:{PORT}")
    print("（关闭此窗口即停止服务）")
    threading.Timer(1.5, _open_browser).start()
    uvicorn.run("app:app", host=HOST, port=PORT, log_level="info")
