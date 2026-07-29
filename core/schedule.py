"""
课表模块

职责：
1. 从教务系统爬取个人课表（一年/学期一次），保存为静态 JSON 资源
2. 读取静态课表文件，提供当日课程筛选、周视图、唯一课程提取等纯函数

课表只爬一次：get_schedule() 优先读 data/schedule_{xh}.json，
不存在（或 force=True）时才请求教务系统并落盘。
"""

import json
import os
import re
from datetime import date, datetime

BASE_URL = "http://59.74.174.150/jwglxt/"

DATA_DIR = "data"

# 学年/学期与成绩模块保持一致（config.py 中已有 XNM/XQM）
try:
    from config import XNM, XQM
except ImportError:
    XNM = "2026"
    XQM = "3"

# 本学期开学日期（第一周周一）。
# 如需调整，在 config.py 中添加：SEMESTER_START = "2026-03-02"
try:
    from config import SEMESTER_START
except ImportError:
    SEMESTER_START = "2026-03-02"

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 学期最多周数（超过则视为假期）
MAX_WEEKS = 25


# ======================
# 爬取与持久化
# ======================

def _path(xh):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    return f"{DATA_DIR}/schedule_{xh}.json"


def fetch_schedule(session):
    """
    请求教务系统个人课表接口，返回 kbList 列表；失败返回 None。
    接口：POST kbcx/xskbcx_cxXsgrkb.html?gnmkdm=N253508
    """
    url = BASE_URL + "kbcx/xskbcx_cxXsgrkb.html"

    data = {
        "xnm": XNM,
        "xqm": XQM,
        "kzlx": "ck",
        "xsdm": "",
        "kclbdm": "",
        "kclxdm": ""
    }

    headers = {
        "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
        "Referer":
        BASE_URL + "kbcx/xskbcx_cxXsgrkb.html?gnmkdm=N253508"
    }

    try:
        r = session.post(
            url,
            params={"gnmkdm": "N253508"},
            data=data,
            headers=headers,
            timeout=15
        )
        result = r.json()
    except Exception:
        return None

    kb_list = result.get("kbList")

    if not isinstance(kb_list, list):
        return None

    return kb_list


def save_schedule(xh, kb_list):
    """课表落盘为静态资源文件"""
    payload = {
        "xh": xh,
        "xnm": XNM,
        "xqm": XQM,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kbList": kb_list
    }

    with open(_path(xh), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

    return payload


def load_schedule(xh):
    """读取静态课表文件；不存在或损坏返回 None"""
    path = _path(xh)

    if not os.path.exists(path):
        return None

    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload.get("kbList"), list):
        return None

    return payload


def get_schedule(session, xh, force=False):
    """
    获取课表：优先静态缓存；缓存缺失或 force=True 时爬取一次并保存。
    爬取失败时回退到旧缓存（若有），实在没有返回 None。
    """
    if not force:
        cached = load_schedule(xh)
        if cached:
            return cached

    kb_list = fetch_schedule(session)

    if kb_list is None:
        return load_schedule(xh)

    return save_schedule(xh, kb_list)


# ======================
# 学期周次
# ======================

def semester_start():
    """开学日期（第一周周一）"""
    try:
        return datetime.strptime(str(SEMESTER_START), "%Y-%m-%d").date()
    except ValueError:
        return date(2026, 3, 2)


def current_week(today=None):
    """
    今天是学期第几周。返回值 <=0 表示未开学，> MAX_WEEKS 表示学期已结束。
    """
    today = today or date.today()
    return (today - semester_start()).days // 7 + 1


def in_semester(week):
    return 1 <= week <= MAX_WEEKS


# ======================
# 课表解析
# ======================

def parse_weeks(zcd):
    """
    解析周次字段为周数集合。
    支持：'1-16周'、'2-16周(双)'、'1-8周,10-16周'、'3周' 等写法。
    """
    weeks = set()

    if not zcd:
        return weeks

    for part in re.split(r"[,，、]", str(zcd)):
        part = part.strip()

        if not part:
            continue

        odd = "单" in part
        even = "双" in part

        nums = re.findall(r"\d+", part)

        if not nums:
            continue

        if len(nums) >= 2:
            a, b = int(nums[0]), int(nums[1])
            rng = range(min(a, b), max(a, b) + 1)
        else:
            rng = [int(nums[0])]

        for w in rng:
            if odd and w % 2 == 0:
                continue
            if even and w % 2 == 1:
                continue
            weeks.add(w)

    return weeks


def parse_jc(jc):
    """'1-2节' → 起始节次（用于排序），解析失败排到最后"""
    m = re.search(r"\d+", str(jc or ""))
    return int(m.group()) if m else 99


def _weekday_of(course):
    """课程记录对应的星期（1-7），优先 xqj 数字字段，其次 xqjmc 中文"""
    xqj = str(course.get("xqj", "")).strip()

    if xqj.isdigit():
        return int(xqj)

    name = str(course.get("xqjmc", "")).strip()

    if name in WEEKDAY_CN:
        return WEEKDAY_CN.index(name) + 1

    return None


def courses_on(kb_list, weekday, week=None):
    """
    筛选某天（weekday: 1-7）在指定学期周次（week）有课的记录，按节次排序。
    week 传 None 时不校验周次（用于整周视图之外的场景）。
    """
    items = []

    for c in kb_list or []:
        if _weekday_of(c) != weekday:
            continue

        if week is not None and week not in parse_weeks(c.get("zcd")):
            continue

        items.append(c)

    return sorted(items, key=lambda c: parse_jc(c.get("jc")))


def week_grid(kb_list, week=None):
    """{1: [...], ..., 7: [...]} 一周课表，按节次排序"""
    return {d: courses_on(kb_list, d, week) for d in range(1, 8)}


def unique_courses(kb_list):
    """按课程名去重，保留首次出现的记录（含教师/学分等信息）"""
    seen = {}

    for c in kb_list or []:
        name = str(c.get("kcmc", "")).strip()

        if not name or name in seen:
            continue

        seen[name] = c

    return list(seen.values())


def normalize_name(name):
    """课程名归一化（去空白），用于课表与成绩数据匹配"""
    return re.sub(r"\s+", "", str(name or ""))
