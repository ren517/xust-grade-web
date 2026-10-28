from cookie_manager import *
from score import *
from history import *
from login import *
from crypto import *

try:
    from jwsso_login import JwssoLogin
except ImportError:  # 作为包被导入时（core.main）
    from core.jwsso_login import JwssoLogin


# ======================
# 登录入口
# ======================
# 默认 jwsso：统一认证新入口（jwsso.xust.edu.cn）
# 可选 legacy：老教务系统 RSA 登录，只在登录换 cookie 这一步不同

DEFAULT_ENTRY = "jwsso"


def get_entry(user):
    """用户未指定入口时用默认入口"""

    return (user or {}).get("entry") or DEFAULT_ENTRY


def create_client(entry):
    """按入口创建登录对象"""

    if entry == "legacy":

        return JWXTLogin()

    return JwssoLogin()


def login_user(user):
    """
    登录教务系统并返回客户端；失败返回 None

    legacy 保持老 cookie 文件名，新入口单独缓存，两套互不覆盖
    """

    entry = get_entry(user)

    login_client = create_client(entry)

    cookie_entry = None if entry == "legacy" else entry

    # 尝试加载Cookie

    has_cookie = load_cookie(
        login_client.session,
        user["xh"],
        cookie_entry
    )

    if has_cookie:

        print("检测缓存登录...")

        if login_client.check_login():

            print("Cookie有效")

            return login_client

        print("Cookie失效，重新登录")

    else:

        print("无缓存Cookie，首次登录")

    password = decrypt_password(
        user["password"]
    )

    success = login_client.login(
        user["xh"],
        password
    )

    if not success:

        return None

    save_cookie(
        login_client.session,
        user["xh"],
        cookie_entry
    )

    print("登录成功")

    return login_client


# ======================
# 用户校验与添加
# ======================


def validate_new_user(name, xh, password):
    """
    校验新用户：姓名/学号/密码非空，学号不重复

    返回 (是否通过, 提示信息)
    """

    name = (name or "").strip()
    xh = (xh or "").strip()
    password = password or ""

    if not name:

        return False, "姓名不能为空"

    if not xh:

        return False, "学号不能为空"

    if not password:

        return False, "教务系统密码不能为空"

    if find_user(xh) is not None:

        return False, f"学号 {xh} 已存在，不能重复添加"

    return True, ""


def _with_timeout(session, timeout=15):
    """
    给 session 的所有请求加上默认超时

    JWXTLogin / JwssoLogin 内部请求都没有设置 timeout，
    网络不可达时会一直挂着，验证密码前统一兜一层
    """

    origin = session.request

    def request(*args, **kwargs):

        kwargs.setdefault("timeout", timeout)

        return origin(*args, **kwargs)

    session.request = request

    return session


def verify_password(xh, password, entry=None):
    """
    用账号密码真正登录一次教务系统，验证凭据是否正确

    返回 (是否通过, 提示信息)；登录成功顺带把 Cookie 缓存下来
    """

    entry = entry or DEFAULT_ENTRY

    client = create_client(entry)

    _with_timeout(client.session)

    cookie_entry = None if entry == "legacy" else entry

    try:

        ok = client.login(
            str(xh).strip(),
            password
        )

    except Exception as e:

        return False, f"教务系统连接失败（{type(e).__name__}），请确认服务器能访问教务系统"

    if not ok:

        return False, "教务系统账号或密码错误，未通过验证"

    save_cookie(
        client.session,
        xh,
        cookie_entry
    )

    return True, ""


def create_user(name, xh, password, verify=False):
    """
    校验并保存新用户（密码加密后落盘）

    verify=True 时先用账号密码登录一次教务系统，通过才保存

    返回 (是否成功, 提示信息)
    """

    ok, msg = validate_new_user(name, xh, password)

    if not ok:

        return False, msg

    if verify:

        ok, msg = verify_password(xh.strip(), password)

        if not ok:

            return False, msg

    save_user(
        name.strip(),
        xh.strip(),
        {
            "password": encrypt_password(password),
            "entry": DEFAULT_ENTRY
        }
    )

    return True, f"用户 {name.strip()}（{xh.strip()}）添加成功"


def add_user():

    name = input("姓名:")
    xh = input("学号:")
    password = input("教务系统密码:")

    ok, msg = create_user(name, xh, password)

    print(msg)


def check_score(user):

    login_client = login_user(user)

    if login_client is None:

        print("登录失败")

        return

    # 查询成绩

    result = select_score(
        login_client.session,
        user["name"]
    )

    if result is None:

        print("成绩查询失败")

        return

    courses = result["items"]

    print("================")
    print("成绩:")
    print("================")

    for c in courses:

        print(
            c["kcmc"],
            "成绩:",
            c.get("cj"),
            "学分:",
            c.get("xf"),
            "出分:",
            c.get("cjbdsj")
        )

        # 如果有详情

        if "detail" in c:

            print(
                "详情:",
                c["detail"]
            )

        print("----------------")

    # ======================
    # 成绩变化检测
    # ======================

    history = load_history(
        user["xh"]
    )

    if history is None:

        print("第一次运行，保存成绩")

    else:

        old_courses = history["courses"]

        new = compare_courses(
            old_courses,
            courses
        )

        if new:

            print("================")
            print("发现新增成绩:")
            print("================")

            for c in new:

                print(
                    c["kcmc"],
                    "成绩:",
                    c.get("cj"),
                    "学分:",
                    c.get("xf")
                )

        else:

            print("没有新增成绩")

    save_history(
        user["xh"],
        user["name"],
        courses
    )


def main():

    users = load_users()

    print("===================")
    print(" 西科大教务助手")
    print("===================")

    for i, u in enumerate(users):

        print(
            i + 1,
            u["name"],
            u["xh"]
        )

    print("0 添加用户")

    choice = input(
        "请选择:"
    )

    if choice == "0":

        add_user()

        return

    user = users[
        int(choice) - 1
    ]

    print(
        "当前用户:",
        user["name"]
    )

    check_score(
        user
    )


if __name__ == "__main__":

    main()
