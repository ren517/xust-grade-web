from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sys

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
from cookie_manager import load_cookie

from history import (
    load_history,
    save_history,
    compare_courses
)



# ======================
# 创建APP
# ======================

app = FastAPI(
    title="西科大教务助手"
)



# ======================
# Session
# 注意：
# SessionMiddleware必须先添加
# ======================

app.add_middleware(

    SessionMiddleware,

    secret_key=SECRET_KEY,

    # 公网HTTPS
    https_only=True,

    same_site="lax"

)





# ======================
# 登录保护
# ======================


class AuthMiddleware(BaseHTTPMiddleware):


    async def dispatch(
            self,
            request,
            call_next
    ):


        path = request.url.path



        # 放行

        allow = [

            "/login",

            "/static"

        ]



        if any(
            path.startswith(x)
            for x in allow
        ):

            return await call_next(request)




        # 检查登录状态


        if not request.session.get("login"):


            return RedirectResponse(

                "/login",

                status_code=302

            )



        return await call_next(request)





# 必须最后添加
# 后添加的先执行

app.add_middleware(
    AuthMiddleware
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
def login_page(
        request:Request
):


    return templates.TemplateResponse(

        request=request,

        name="login.html",

        context={}

    )





@app.post("/login")
def login(

        request:Request,

        username:str=Form(...),

        password:str=Form(...)

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




    return HTMLResponse(

        """

        <h3>
        用户名或密码错误
        </h3>

        <a href="/login">
        返回
        </a>

        """

    )







# ======================
# 登出
# ======================


@app.get("/logout")
def logout(

        request:Request

):


    request.session.clear()



    return RedirectResponse(

        "/login",

        status_code=302

    )








# ======================
# 首页
# ======================


@app.get("/")
def index(

        request:Request

):


    return templates.TemplateResponse(

        request=request,

        name="index.html",

        context={

            "title":
            "西科大教务助手"

        }

    )









# ======================
# 成绩查询
# ======================


@app.get("/score")
def score(

        request:Request

):


    xh = XH

    name = NAME




    login_client = JWXTLogin()




    # 加载教务系统Cookie


    load_cookie(

        login_client.session,

        xh

    )





    result = select_score(

        login_client.session,

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


        print(
            "第一次查询"
        )







    # ======================
    # 保存网页查询历史
    # ======================


    save_history(

        xh,

        name,

        courses

    )






    return templates.TemplateResponse(

        request=request,

        name="score.html",

        context={


            "courses":

            courses,



            "new_courses":

            new_courses


        }

    )