"""
考试安排模块

职责：
1. 从教务系统爬取期末考试安排，缓存为静态 JSON（与课表一样一学期爬一次）
2. 提供考试时间解析、排序、教师名格式化等纯函数

接口：POST kwgl/kscx_cxXsksxxIndex.html?doType=query&gnmkdm=N358105
字段：ksmc / xnmc / xqmmc / xqmc / kcmc / khfs / xf / kssj / cdbh / zwh / kkxy / jsxx
"""

import json
import os
import re
import time
from datetime import datetime

BASE_URL = "http://59.74.174.150/jwglxt/"

DATA_DIR = "data"

try:
    from config import XNM, XQM
except ImportError:
    XNM = "2026"
    XQM = "3"

# 教务原始字段 -> 中文含义（便于调试与后续扩展）
FIELD_LABELS = {
    "ksmc": "考试名称",
    "xnmc": "学年",
    "xqmmc": "学期",
    "xqmc": "校区",
    "kcmc": "课程名称",
    "khfs": "考核方式",
    "xf": "学分",
    "kssj": "考试时间",
    "cdbh": "考场",
    "zwh": "座位号",
    "kkxy": "开课学院",
    "jsxx": "教师",
}


# ======================
# 爬取与持久化
# ======================

def _path(xh):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    return f"{DATA_DIR}/exam_{xh}.json"


def fetch_exam(session, xnm=XNM, xqm=XQM, timeout=15):
    """
    请求考试安排接口，返回 items 列表；失败返回 None。

    xnm: 学年（如 "2026" 表示 2026-2027 学年）
    xqm: "3" 第一学期 / "12" 第二学期 / "" 整个学年
    """
    url = BASE_URL + "kwgl/kscx_cxXsksxxIndex.html?doType=query&gnmkdm=N358105"

    headers = {
        "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
        "Referer":
        BASE_URL + "kwgl/kscx_cxXsksxxIndex.html?gnmkdm=N358105&layout=default",
        "X-Requested-With": "XMLHttpRequest",
    }

    data = {
        "xnm": xnm,
        "xqm": xqm,
        "_search": "false",
        "nd": int(time.time() * 1000),
        "queryModel.showCount": "100",
        "queryModel.currentPage": "1",
        "queryModel.sortName": "",
        "queryModel.sortOrder": "asc",
        "time": "0",
    }

    try:
        r = session.post(url, headers=headers, data=data, timeout=timeout)
        result = r.json()
    except Exception:
        return None

    items = result.get("items")

    if not isinstance(items, list):
        return None

    return items


def save_exam(xh, items, xnm=XNM, xqm=XQM):
    """考试安排落盘为静态缓存"""
    payload = {
        "xh": xh,
        "xnm": xnm,
        "xqm": xqm,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
    }

    with open(_path(xh), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

    return payload


def load_exam(xh):
    """读取缓存；不存在或损坏返回 None"""
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


def get_exam(session, xh, force=False, xnm=XNM, xqm=XQM):
    """优先读缓存；缓存缺失或 force=True 时爬取一次并保存"""
    if not force:
        cached = load_exam(xh)
        if cached:
            return cached

    items = fetch_exam(session, xnm=xnm, xqm=xqm)

    if items is None:
        return load_exam(xh)

    return save_exam(xh, items, xnm=xnm, xqm=xqm)


# ======================
# 解析与展示
# ======================

def parse_time(kssj):
    """'2026-06-25(14:00-16:00)' -> ('2026-06-25', '14:00-16:00')"""
    s = str(kssj or "").strip()

    m = re.match(r"(\d{4}-\d{2}-\d{2})\s*[（(]([^）)]*)[）)]", s)

    if m:
        return m.group(1), m.group(2).strip()

    return (s, "")


def format_teachers(jsxx):
    """'001344/罗清郁;000850/刘文刚' -> '罗清郁、刘文刚'（去掉工号前缀）"""
    s = str(jsxx or "").strip()

    if not s:
        return ""

    names = []

    for part in re.split(r"[;；]", s):
        part = part.strip()

        if not part:
            continue

        if "/" in part:
            part = part.split("/", 1)[1].strip()

        if part:
            names.append(part)

    return "、".join(names)


def normalize(items):
    """把教务原始 items 转成模板可直接渲染的结构，并按考试时间排序"""
    out = []

    for it in items or []:
        if not isinstance(it, dict):
            continue

        day, rng = parse_time(it.get("kssj"))

        out.append({
            "course": str(it.get("kcmc") or "").strip() or "—",
            "time_text": str(it.get("kssj") or "").strip() or "—",
            "date": day,
            "range": rng,
            "place": str(it.get("cdbh") or "").strip() or "—",
            "seat": str(it.get("zwh") or "").strip() or "—",
            "credit": str(it.get("xf") or "").strip() or "—",
            "college": str(it.get("kkxy") or "").strip() or "—",
            "teachers": format_teachers(it.get("jsxx")) or "—",
            "method": str(it.get("khfs") or "").strip() or "—",
            "campus": str(it.get("xqmc") or "").strip() or "—",
            "exam_name": str(it.get("ksmc") or "").strip(),
            "xn": str(it.get("xnmc") or "").strip(),
            "xq": str(it.get("xqmmc") or "").strip(),
        })

    out.sort(key=lambda e: (e["date"] or "9999-99-99", e["range"] or ""))

    return out
