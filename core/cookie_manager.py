import os
import json

USER_DIR = "users"
COOKIE_DIR = "cookies"


def init():

    if not os.path.exists(USER_DIR):
        os.makedirs(USER_DIR)

    if not os.path.exists(COOKIE_DIR):
        os.makedirs(COOKIE_DIR)


# =====================
# 用户管理
# =====================


def load_users():

    init()

    users = []

    for file in os.listdir(USER_DIR):

        if file.endswith(".json"):

            path = os.path.join(USER_DIR, file)

            with open(path, encoding="utf-8") as f:

                users.append(json.load(f))

    return users


def save_user(name, xh, info):

    init()

    user = {"name": name, "xh": xh, **info}

    with open(f"{USER_DIR}/{xh}.json", "w", encoding="utf-8") as f:

        json.dump(user, f, ensure_ascii=False, indent=4)


def find_user(xh):
    """按学号查找用户；不存在返回 None"""

    for u in load_users():

        if str(u.get("xh")) == str(xh):

            return u

    return None


# =====================
def delete_user(xh):
    """按学号删除教务账号：删除 users/{xh}.json 并清理对应的 Cookie 缓存"""

    xh = str(xh).strip()

    path = os.path.join(USER_DIR, f"{xh}.json")

    if os.path.exists(path):

        os.remove(path)

    # 清理该账号的 Cookie 缓存（文件名包含学号的所有缓存）
    if os.path.exists(COOKIE_DIR):

        for f in os.listdir(COOKIE_DIR):

            if xh in f:

                try:

                    os.remove(os.path.join(COOKIE_DIR, f))

                except OSError:

                    pass

    return True


# Cookie管理
# =====================


def cookie_path(xh, entry=None):
    """
    Cookie文件名

    entry 为空时保持旧入口的 cookies/<xh>.json，
    新入口用 cookies/<entry>_<xh>.json，两套缓存互不覆盖
    """

    name = f"{entry}_{xh}.json" if entry else f"{xh}.json"

    return f"{COOKIE_DIR}/{name}"


def save_cookie(session, xh, entry=None):

    init()

    cookies = session.cookies.get_dict()

    with open(cookie_path(xh, entry), "w", encoding="utf-8") as f:

        json.dump(cookies, f, indent=4)


def load_cookie(session, xh, entry=None):

    path = cookie_path(xh, entry)

    if not os.path.exists(path):

        return False

    with open(path, encoding="utf-8") as f:

        cookies = json.load(f)

    session.cookies.update(cookies)

    return True


def clear_cookie(xh, entry=None):

    path = cookie_path(xh, entry)

    if os.path.exists(path):

        os.remove(path)
