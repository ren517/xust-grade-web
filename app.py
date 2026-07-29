from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sys
from datetime import date

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from config import (
    ADMIN_USER,
    ADMIN_PASSWORD,
    SECRET_KEY,
    XH,
    NAME
)

# ======================
# 引入核心代码
# ======================

sys.path.append("core")

from score import select_score
from login import JWXTLogin
from cookie_manager import load_cookie, load_users
from main import login_user
from history import (
    load_history,
    save_history,
    compare_courses
)
from schedule import (
    get_schedule,
    load_schedule,
    courses_on,
    week_grid,
    unique_courses,
    current_week,
    in_semester,
    normalize_name,
    WEEKDAY_CN
)

# ======================
# 创建APP
# ======================

app = FastAPI(
    title="西科大教务助手"
)


# ======================
# 登录保护
# ======================

class AuthMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request, call_next):

        path = request.url.path

        # 放行
        allow = [
            "/login",
            "/static"
        ]

        if any(path.startswith(x) for x in allow):
            return await call_next(request)

        # 检查登录状态
        if not request.session.get("login"):
            return RedirectResponse(
                "/login",
                status_code=302
            )

        return await call_next(request)


# ======================
# 中间件注册（顺序是关键！）
#
# Starlette 规则：后添加的中间件 = 最外层 = 先执行。
#
# 修复后的请求执行顺序：
#   SessionMiddleware（外层，先执行，把 session 写入 scope）
#       -> AuthMiddleware（内层，后执行，可以安全读取 request.session）
#           -> 路由
#
# 所以必须「先添加 AuthMiddleware，再添加 SessionMiddleware」，
# 与原来错误的写法正好相反。
# ======================

# 先添加：内层，后执行
app.add_middleware(
    AuthMiddleware
)

# 后添加：最外层，先执行
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    # 公网HTTPS（注意：如果用 http://IP:端口 直连访问，
    # Cookie 不会下发，登录会"形同虚设"，此时应改为 False）
    https_only=True,
    same_site="lax"
)


# ======================
# 静态文件
# ======================

app.mount(
    "/static",
    StaticFiles(
        directory="static"
    ),
    name="static"
)

templates = Jinja2Templates(
    directory="templates"
)


# ======================
# 登录页面
# ======================

@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={}
    )


@app.post("/login")
def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...)
):
    if (
        username == ADMIN_USER
        and
        password == ADMIN_PASSWORD
    ):
        request.session["login"] = True

        return RedirectResponse(
            "/",
            status_code=302
        )

    # 登录失败：重渲染登录页，保留已输入的用户名并提示错误
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": "用户名或密码错误，请重试",
            "username": username
        },
        status_code=401
    )


# ======================
# 登出
# ======================

@app.get("/logout")
def logout(request: Request):
    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=302
    )


# ======================
# 公共：教务会话与课表同步
# ======================

def _jwxt_session():
    """登录教务系统并返回 session；失败返回 None"""
    users = load_users()

    if not users:
        return None

    login_client = login_user(users[0])

    if login_client is None:
        return None

    # 加载教务系统Cookie
    load_cookie(
        login_client.session,
        XH
    )

    return login_client.session


def _sync_schedule(force=False):
    """
    课表只爬一次：优先读静态缓存 data/schedule_{xh}.json，
    缓存缺失（或 force）才登录教务系统爬取并落盘。
    任何失败都静默降级为旧缓存或 None，绝不让页面崩掉。
    """
    try:
        session = _jwxt_session()

        if session is None:
            return load_schedule(XH)

        return get_schedule(session, XH, force=force)
    except Exception:
        return load_schedule(XH)


def _date_cn(d):
    return f"{d.year}年{d.month}月{d.day}日"


# ======================
# 首页
# ======================

@app.get("/")
def index(request: Request):
    today = date.today()
    week = current_week(today)
    weekday = today.isoweekday()

    # 读静态课表；仅当从未同步过时触发一次性爬取
    payload = load_schedule(XH)

    if payload is None:
        payload = _sync_schedule()

    kb = payload["kbList"] if payload else []

    in_sem = in_semester(week)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "西科大教务助手",
            "active": "home",
            "today_cn": _date_cn(today),
            "weekday_cn": WEEKDAY_CN[weekday - 1],
            "semester_week": week,
            "in_semester": in_sem,
            "hero_courses": unique_courses(kb)[:4],
            "today_courses": (
                courses_on(kb, weekday, week)
                if in_sem else []
            ),
            "schedule_synced": payload is not None,
            "fetched_at": (
                payload.get("fetched_at")
                if payload else None
            )
        }
    )


# ======================
# 每日课表
# ======================

@app.get("/schedule")
def schedule_page(request: Request):
    today = date.today()
    week = current_week(today)
    weekday = today.isoweekday()

    payload = load_schedule(XH)

    if payload is None:
        payload = _sync_schedule()

    kb = payload["kbList"] if payload else []
    in_sem = in_semester(week)

    return templates.TemplateResponse(
        request=request,
        name="schedule.html",
        context={
            "active": "schedule",
            "today_cn": _date_cn(today),
            "weekday_cn": WEEKDAY_CN[weekday - 1],
            "semester_week": week,
            "in_semester": in_sem,
            "today_courses": (
                courses_on(kb, weekday, week)
                if in_sem else []
            ),
            "week_grid": (
                week_grid(kb, week)
                if in_sem else week_grid(kb)
            ),
            "weekdays": WEEKDAY_CN,
            "today_weekday": weekday,
            "schedule_synced": payload is not None,
            "fetched_at": (
                payload.get("fetched_at")
                if payload else None
            )
        }
    )


@app.get("/schedule/refresh")
def schedule_refresh(request: Request):
    """强制重新爬取课表（新学期或课表变更时手动触发）"""
    _sync_schedule(force=True)

    return RedirectResponse(
        "/schedule",
        status_code=302
    )


# ======================
# 课程总览与进度追踪
# ======================

@app.get("/progress")
def progress(request: Request):
    # 课表：静态资源
    payload = load_schedule(XH)

    if payload is None:
        payload = _sync_schedule()

    kb = payload["kbList"] if payload else []
    all_courses = unique_courses(kb)

    # 成绩：每次刷新实时爬取
    score_error = False
    score_items = []

    try:
        session = _jwxt_session()
        result = (
            select_score(session, NAME)
            if session else None
        )

        if result is None:
            score_error = True
        else:
            score_items = result.get("items", [])
    except Exception:
        score_error = True

    scored = {
        normalize_name(c.get("kcmc")): c
        for c in score_items
    }

    done = []
    pending = []

    for c in all_courses:
        key = normalize_name(c.get("kcmc"))

        if key in scored:
            merged = dict(c)
            merged["score"] = scored[key]
            done.append(merged)
        else:
            pending.append(c)

    total = len(all_courses)
    done_count = len(done)

    return templates.TemplateResponse(
        request=request,
        name="progress.html",
        context={
            "active": "progress",
            "total": total,
            "done": done,
            "pending": pending,
            "done_count": done_count,
            "percent": (
                round(done_count / total * 100)
                if total else 0
            ),
            "score_error": score_error,
            "schedule_synced": payload is not None,
            "fetched_at": (
                payload.get("fetched_at")
                if payload else None
            )
        }
    )


# ======================
# 成绩查询
# ======================

@app.get("/score")
def score(request: Request):
    xh = XH
    name = NAME

    session = _jwxt_session()

    if session is None:
        return HTMLResponse(
            "教务系统登录失败，请稍后再试"
        )

    result = select_score(
        session,
        name
    )

    if result is None:
        return HTMLResponse(
            "成绩查询失败"
        )

    courses = result["items"]

    # ======================
    # 查询历史
    # ======================

    new_courses = []

    history = load_history(xh)

    if history:
        new_courses = compare_courses(
            history["courses"],
            courses
        )
    else:
        print("第一次查询")

    # ======================
    # 保存网页查询历史
    # ======================

    save_history(
        xh,
        name,
        courses
    )

    # ======================
    # 统计概览（供前端卡片展示）
    # ======================

    def _num(v):
        """安全转 float，非法值返回 None"""
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    total_credits = 0.0
    weighted_jd = 0.0
    gpa_credits = 0.0

    for c in courses:
        xf = _num(c.get("xf"))
        jd = _num(c.get("xfjd"))
        if xf is not None:
            total_credits += xf
            if jd is not None:
                weighted_jd += xf * jd
                gpa_credits += xf

    stats = {
        "count": len(courses),
        "credits": round(total_credits, 1),
        "gpa": (
            round(weighted_jd / gpa_credits, 2)
            if gpa_credits > 0 else None
        ),
        "new_count": len(new_courses)
    }

    return templates.TemplateResponse(
        request=request,
        name="score.html",
        context={
            "courses": courses,
            "new_courses": new_courses,
            "stats": stats,
            "active": "score"
        }
    )
