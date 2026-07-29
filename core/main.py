from cookie_manager import *
from score import *
from history import *
from login import *
from crypto import *


def login_user(user):

    """
    登录处理
    """

    login_client = JWXTLogin()


    # 尝试加载Cookie

    has_cookie = load_cookie(
        login_client.session,
        user["xh"]
    )


    if has_cookie:

        print("检测缓存登录...")


        if login_client.check_login():

            print("Cookie有效")


        else:

            print("Cookie失效，重新登录")


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
                user["xh"]
            )


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
            user["xh"]
        )


    print("登录成功")


    return login_client



def add_user():


    name = input("姓名:")
    xh = input("学号:")
    password = input("教务系统密码:")


    password = encrypt_password(
        password
    )


    save_user(
        name,
        xh,
        {
            "password": password
        }
    )


    print("用户添加成功")





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


        print(
            "第一次运行，保存成绩"
        )


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

            print(
                "没有新增成绩"
            )



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



    for i,u in enumerate(users):

        print(
            i+1,
            u["name"],
            u["xh"]
        )


    print("0 添加用户")


    choice=input(
        "请选择:"
    )


    if choice=="0":

        add_user()

        return



    user = users[
        int(choice)-1
    ]


    print(
        "当前用户:",
        user["name"]
    )


    check_score(
        user
    )




if __name__=="__main__":

    main()