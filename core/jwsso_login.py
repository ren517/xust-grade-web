import base64
import os
import re
import uuid

from urllib.parse import urljoin

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

try:
    from login import JWXTLogin
except ImportError:  # 作为包被导入时（core.jwsso_login）
    from core.login import JWXTLogin


# =====================
# 统一用户中心（新入口）
# =====================

JWSSO_BASE = "http://jwsso.xust.edu.cn"

# 教务系统的 CAS 认证入口（访问它会 302 到 jwsso 的 CAS 登录地址）
CAS_ENTRY = "http://59.74.174.150/jwglxt/auth/auth_casAuthLogin.html"

LOGIN_URL = JWSSO_BASE + "/auth/oauth/login"

# 账号密码登录片段（内含 __token__）
FRAGMENT_URL = LOGIN_URL + "?login_type=normal&login_type_fragment=ImplNormal"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"

# 页面 Vue.encrypt 的 key / iv 取自当前 __token__ 的前 16 位，每次请求都会变


class JwssoLogin(JWXTLogin):
    """
    新认证入口：统一用户中心 jwsso.xust.edu.cn

    复用 JWXTLogin 的 session / base_url / check_login，
    只替换 login() 的取 cookie 方式。

    登录分两步：
    1.在 jwsso 完成账号密码登录，拿到 jwsso 会话
    2.携带票据回老教务系统，换取 59.74.174.150 域下的 JSESSIONID + route
    """

    def __init__(self, authorize_url=None, client_id=None, redirect_uri=None):

        super().__init__()

        # 本机有系统代理时，访问教务的 CAS 端点会返回 503，新入口统一直连
        self.session.trust_env = False

        self.authorize_url = authorize_url or os.environ.get("JWSSO_AUTHORIZE")

        self.client_id = client_id or os.environ.get("JWSSO_CLIENT_ID")

        self.redirect_uri = redirect_uri or os.environ.get("JWSSO_REDIRECT_URI")

    # =====================
    # 请求参数
    # =====================

    def base_params(self):
        """
        教务系统作为 OAuth 客户端时的参数

        不带 client_id 时是裸登录（登录到个人中心，拿不到教务会话）
        """

        params = {}

        if self.client_id:

            params["client_id"] = self.client_id

        if self.redirect_uri:

            params["redirect_uri"] = self.redirect_uri

            params["response_type"] = "code"

        return params

    # =====================
    # 密码加密
    # =====================

    def aes_encrypt(self, password, token):
        """
        与页面 Vue.encrypt 等价：
        AES-128-CBC，ZeroPadding

        注意：key 与 iv 都是当前 __token__ 的前 16 位，
        每次请求都会变，不能写死
        """

        key = token[:16].encode("utf-8")

        data = password.strip().encode("utf-8")

        rem = len(data) % 16

        if rem:

            data += b"\x00" * (16 - rem)

        cipher = Cipher(algorithms.AES(key), modes.CBC(key)).encryptor()

        return base64.b64encode(cipher.update(data) + cipher.finalize()).decode()

    # =====================
    # 登录页
    # =====================

    def get_token(self, url=None):

        params = self.base_params()

        params["login_type"] = "normal"

        params["login_type_fragment"] = "ImplNormal"

        r = self.session.get(
            url or LOGIN_URL, params=params, headers={"User-Agent": UA}
        )

        html = r.text

        if "应用未注册或地址不匹配" in html:

            print("jwsso 提示应用未注册或地址不匹配")

            print("client_id:", self.client_id, "redirect_uri:", self.redirect_uri)

            return ""

        tag = re.search(r'name="__token__"\s+value="([^"]+)"', html)

        if tag:

            return tag.group(1)

        soup = BeautifulSoup(html, "html.parser")

        i = soup.find("input", {"name": "__token__"})

        return i["value"] if i else ""

    # =====================
    # 登录
    # =====================

    def get_cas_login_url(self):
        """
        第一步：访问教务系统的 CAS 入口，拿到 jwsso 的 CAS 登录地址
        """

        r = self.session.get(
            CAS_ENTRY, headers={"User-Agent": UA}, allow_redirects=False
        )

        location = r.headers.get("Location")

        if r.status_code in (301, 302, 303, 307) and location:

            return location

        print("教务 CAS 入口未跳转:", r.status_code, "（若走系统代理会返回 503）")

        return ""

    def login(self, username, password):
        """
        CAS 流程：
        1.访问教务 CAS 入口，拿到 jwsso 的 CAS 登录地址
        2.在该地址完成账号密码登录（AES 加密）
        3.带 ticket 回教务系统，换取 JSESSIONID + route
        """

        cas_login = self.get_cas_login_url()

        if not cas_login:

            return False

        token = ""

        for _ in range(3):

            token = self.get_token(cas_login)

            if token:

                break

        if not token:

            print("未取到 __token__")

            return False

        data = {
            "username": username.strip(),
            "password": self.aes_encrypt(password, token),
            "__token__": token,
            "fingerprint": uuid.uuid4().hex,
        }

        headers = {
            "User-Agent": UA,
            "Referer": cas_login,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        r = self.session.post(
            cas_login,
            params={"login_type": "normal"},
            data=data,
            headers=headers,
            allow_redirects=False,
        )

        # 失败：页面重新渲染登录框并给出错误
        if "o-form-error-container" in r.text or "normal_login_container" in r.text:

            print("登录失败:", self.parse_error(r.text))

            return False

        # 成功：带 ticket 回教务系统换取会话
        return self.follow_ticket(r)

    def follow_ticket(self, r):
        """
        逐步跟随跳转，直到教务系统建立会话
        """

        location = r.headers.get("Location")

        base = r.url

        hops = 0

        while location and hops < 8:

            hops += 1

            r = self.session.get(
                urljoin(base, location), headers={"User-Agent": UA}, allow_redirects=False
            )

            base = r.url

            location = r.headers.get("Location")

        return True

    def parse_error(self, html):

        soup = BeautifulSoup(html, "html.parser")

        box = soup.find("div", {"data-se": "o-form-error-container"})

        if box:

            return box.get_text(" ", strip=True)

        return "账号不存在或密码错误"
