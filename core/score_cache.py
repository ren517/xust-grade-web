"""成绩缓存：与课表缓存对齐，按学号落盘为静态 JSON。

页面 GET 读缓存（不触发查询）；「更新数据」爬取后写这里。
"""
import json
import os
from datetime import datetime

DATA_DIR = "data"


def _path(xh):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    return f"{DATA_DIR}/score_{xh}.json"


def save_score(xh, xnm, xqm, items, _new=None):
    payload = {
        "xh": xh,
        "xnm": xnm,
        "xqm": xqm,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
        "_new": _new or [],
    }
    with open(_path(xh), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)
    return payload


def load_score(xh):
    path = _path(xh)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload.get("items"), list):
        return None
    return payload
