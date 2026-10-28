import json
import os
import sys
from datetime import date
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import ADMIN_PASSWORD, ADMIN_USER, NAME, SECRET_KEY, WEB_USERS_FILE, XH

# ======================
# 部署开关
# ======================
# 本地 http 开发保持默认 0；
# 部署到公网 HTTPS 站点时设置环境变量 HTTPS_ONLY=1，
# 否则 http 下 Cookie 不下发、登录后会一直被弹回登录页。

HTTPS_ONLY = os.environ.get("HTTPS_ONLY", "0") == "1"

# ======================
# 引入核心代码
# ======================
sys.path.append("./core")
from core.cookie_manager import clear_cookie, find_user, load_users
from core.history import compare_courses, load_history, save_history
from core.main import DEFAULT_ENTRY, create_user, login_user
from core.schedule import (
    WEEKDAY_CN,
    courses_on,
    current_week,
    get_schedule,
    in_semester,
    load_schedule,
    normalize_name,
    unique_courses,
    week_grid,
)
from core.score import select_score

# ======================
# 创建APP
# ======================

app = FastAPI(title="西科大教务助手")


# ======================
# 登录保护
# ======================


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        # 放行
        allow = ["/login", "/static"]

        if any(path.startswith(x) for x in allow):
            return await call_next(request)

        # 检查登录状态
        if not request.session.get("login"):
            return RedirectResponse("/login", status_code=302)

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
app.add_middleware(AuthMiddleware)

# 后添加：最外层，先执行
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    # 由 HTTPS_ONLY 环境变量控制：本地 http 为 0，公网 HTTPS 部署设为 1
    https_only=HTTPS_ONLY,
    same_site="lax",
)


# ======================
# 静态文件（带强缓存头，降低 2GB 小内存机器的重复请求压力）
# ===========================================


class CachedStaticFiles(StaticFiles):
    """
    继承 Starlette 的 StaticFiles，给命中(200)的静态资源追加
    Cache-Control: public, max-age=86400, immutable。

    效果：浏览器在 24h 内直接读本地磁盘缓存，不再向服务器发请求，
    对 2GB 内存的小机器尤其友好——少一次连接、少占一点内存与 CPU。
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)

        if response.status_code == 200:
            response.headers.setdefault(
                "Cache-Control", "public, max-age=86400, immutable"
            )

        return response


app.mount("/static", CachedStaticFiles(directory="static"), name="static")


# ======================
# 开启 GZip 响应压缩（最外层，压缩所有 HTML/CSS/JS 响应）
# ======================

app.add_middleware(GZipMiddleware, minimum_size=500)

templates = Jinja2Templates(directory="templates")


# ======================
# Web 登录凭据（简单实现：JSON 明文存储）
# ======================


def _load_web_users():
    """
    读取 Web 登录凭据。文件不存在或损坏时重建，
    并保证内置管理员账号始终可用。
    """

    os.makedirs(os.path.dirname(WEB_USERS_FILE) or ".", exist_ok=True)

    users = {}

    if os.path.exists(WEB_USERS_FILE):
        try:
            with open(WEB_USERS_FILE, encoding="utf-8") as f:
                users = json.load(f)
        except (json.JSONDecodeError, OSError):
            users = {}

    if not isinstance(users, dict):
        users = {}

    # 内置管理员账号
    users.setdefault(ADMIN_USER, ADMIN_PASSWORD)

    _save_web_users(users)

    return users


def _save_web_users(users):
    """Web 登录凭据落盘"""

    with open(WEB_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=4)


# ======================
# 当前教务账号（多用户切换的核心状态）
# ======================


def _cookie_entry():
    """legacy 沿用老 cookie 文件名，其余入口单独缓存"""

    return None if DEFAULT_ENTRY == "legacy" else DEFAULT_ENTRY


def _current_account(request):
    """
    当前选中的教务账号

    优先级：session 中已切换的账号 > 第一个已保存账号 > config 兜底
    """

    xh = request.session.get("xh")

    if xh:
        user = find_user(xh)

        if user:
            return user

    users = load_users()

    if users:
        return users[0]

    # 没有任何教务账号时，退回 config，保证页面不至于崩掉
    return {"name": NAME, "xh": XH}


def _current_xh(request):
    """当前账号学号（课表缓存按学号隔离）"""

    return _current_account(request).get("xh") or XH


def _reset_jwxt_state(request):
    """
    重置教务相关会话状态：
    清除 session 中的当前账号与已加载数据，并清掉该账号的教务 Cookie 缓存，
    避免切换后仍复用上一个账号的登录态。
    """

    old_xh = request.session.get("xh")

    for key in ("xh", "name", "schedule"):
        request.session.pop(key, None)

    if old_xh:
        try:
            clear_cookie(old_xh, _cookie_entry())
        except Exception:
            pass


def _redirect_msg(url, msg, ok):
    """重定向并带上一次性提示（成功/失败）"""

    flag = "1" if ok else "0"

    return RedirectResponse(
        f"{url}?msg={quote(str(msg))}&ok={flag}", status_code=302
    )


# ======================
# 登录页面
# ======================


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form("")):
    username = (username or "").strip()

    if not username or not password:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "用户名和密码不能为空", "username": username},
            status_code=400,
        )

    if _load_web_users().get(username) != password:
        # 登录失败：重渲染登录页，保留已输入的用户名并提示错误
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "用户名或密码错误，请重试", "username": username},
            status_code=401,
        )

    request.session["login"] = True
    request.session["user"] = username

    # 登录后从干净的教务状态开始
    _reset_jwxt_state(request)

    return RedirectResponse("/", status_code=302)


# ======================
# 登出
# ======================


@app.get("/logout")
def logout(request: Request):
    _reset_jwxt_state(request)

    request.session.clear()

    return RedirectResponse("/login", status_code=302)


# ======================
# 用户管理：列表 / 切换 / 添加
# ======================


@app.get("/users")
def users_page(request: Request):
    account = _current_account(request)

    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context={
            "active": "users",
            "users": load_users(),
            "current_xh": account.get("xh"),
            "current_name": account.get("name"),
            "web_user": request.session.get("user"),
            "msg": request.query_params.get("msg"),
            "ok": request.query_params.get("ok") == "1",
        },
    )


@app.post("/users/switch")
def users_switch(request: Request, xh: str = Form("")):
    """切换当前教务账号：先注销旧账号（清会话与缓存），再绑定新账号"""

    xh = (xh or "").strip()

    if not xh:
        return _redirect_msg("/users", "学号不能为空", False)

    user = find_user(xh)

    if user is None:
        return _redirect_msg("/users", f"学号 {xh} 不存在，无法切换", False)

    # 注销当前账号：重置会话状态与已加载数据
    _reset_jwxt_state(request)

    request.session["xh"] = str(user.get("xh"))
    request.session["name"] = user.get("name", "")

    return _redirect_msg("/users", f"已切换到 {user.get('name')}（{xh}）", True)


@app.post("/users/add")
def users_add(
    request: Request,
    name: str = Form(""),
    xh: str = Form(""),
    password: str = Form(""),
    verify: str = Form(""),
):
    """
    添加教务账号：校验非空与学号重复，密码加密后保存

    verify=1 时先用该账号密码登录一次教务系统，验证通过才保存
    """

    ok, msg = create_user(name, xh, password, verify=(verify == "1"))

    return _redirect_msg("/users", msg, ok)


# ======================
# 公共：教务会话与课表同步
# ======================


def _jwxt_session(request):
    """用当前账号登录教务系统并返回 session；失败返回 None"""

    user = _current_account(request)

    # config 兜底账号没有密码，无法登录
    if not user.get("password"):
        return None

    try:
        login_client = login_user(user)
    except Exception:
        return None

    if login_client is None:
        return None

    return login_client.session


def _sync_schedule(request, force=False):
    """
    课表只爬一次：优先读静态缓存 data/schedule_{xh}.json，
    缓存缺失（或 force）才登录教务系统爬取并落盘。
    任何失败都静默降级为旧缓存或 None，绝不让页面崩掉。
    """
    xh = _current_xh(request)

    try:
        session = _jwxt_session(request)

        if session is None:
            return load_schedule(xh)

        return get_schedule(session, xh, force=force)
    except Exception:
        return load_schedule(xh)


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

    xh = _current_xh(request)

    # 读静态课表；仅当从未同步过时触发一次性爬取
    payload = load_schedule(xh)

    if payload is None:
        payload = _sync_schedule(request)

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
            "today_courses": (courses_on(kb, weekday, week) if in_sem else []),
            "schedule_synced": payload is not None,
            "fetched_at": (payload.get("fetched_at") if payload else None),
        },
    )


# ======================
# 每日课表
# ======================


@app.get("/schedule")
def schedule_page(request: Request):
    today = date.today()
    week = current_week(today)
    weekday = today.isoweekday()

    xh = _current_xh(request)

    payload = load_schedule(xh)

    if payload is None:
        payload = _sync_schedule(request)

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
            "today_courses": (courses_on(kb, weekday, week) if in_sem else []),
            "week_grid": (week_grid(kb, week) if in_sem else week_grid(kb)),
            "weekdays": WEEKDAY_CN,
            "today_weekday": weekday,
            "schedule_synced": payload is not None,
            "fetched_at": (payload.get("fetched_at") if payload else None),
        },
    )


@app.get("/schedule/refresh")
def schedule_refresh(request: Request):
    """强制重新爬取课表（新学期或课表变更时手动触发）"""
    _sync_schedule(request, force=True)

    return RedirectResponse("/schedule", status_code=302)


# ======================
# 课程总览与进度追踪
# ======================


@app.get("/progress")
def progress(request: Request):
    xh = _current_xh(request)

    # 课表：静态资源
    payload = load_schedule(xh)

    if payload is None:
        payload = _sync_schedule(request)

    kb = payload["kbList"] if payload else []
    all_courses = unique_courses(kb)

    # 成绩：每次刷新实时爬取
    score_error = False
    score_items = []

    try:
        session = _jwxt_session(request)
        result = select_score(session, _current_account(request).get("name")) if session else None

        if result is None:
            score_error = True
        else:
            score_items = result.get("items", [])
    except Exception:
        score_error = True

    scored = {normalize_name(c.get("kcmc")): c for c in score_items}

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
            "percent": (round(done_count / total * 100) if total else 0),
            "score_error": score_error,
            "schedule_synced": payload is not None,
            "fetched_at": (payload.get("fetched_at") if payload else None),
        },
    )


# ======================
# 成绩查询
# ======================


@app.get("/score")
def score(request: Request):
    account = _current_account(request)

    xh = account.get("xh") or XH
    name = account.get("name") or NAME

    session = _jwxt_session(request)

    if session is None:
        return HTMLResponse("教务系统登录失败，请稍后再试（请先在「用户管理」添加并切换教务账号）")

    result = select_score(session, name)

    if result is None:
        return HTMLResponse("成绩查询失败")

    courses = result["items"]

    # ======================
    # 查询历史
    # ======================

    new_courses = []

    history = load_history(xh)

    if history:
        new_courses = compare_courses(history["courses"], courses)

    # ======================
    # 保存网页查询历史
    # ======================

    save_history(xh, name, courses)

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
        "gpa": (round(weighted_jd / gpa_credits, 2) if gpa_credits > 0 else None),
        "new_count": len(new_courses),
    }

    return templates.TemplateResponse(
        request=request,
        name="score.html",
        context={
            "courses": courses,
            "new_courses": new_courses,
            "stats": stats,
            "active": "score",
        },
    )
