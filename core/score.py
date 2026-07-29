import requests
import time
import pandas as pd
from config import XNM,XQM
from bs4 import BeautifulSoup


BASE_URL = "http://59.74.174.150/jwglxt/"



def select_score(session, name, export=False):


    headers = {

        "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",

        "Referer":
        BASE_URL,

    }



    url = (
        BASE_URL
        +
        "cjcx/cjcx_cxXsgrcj.html?"
        "doType=query&gnmkdm=N305005"
    )



    data = {

        "xnm": XNM,

        "xqm": XQM,

        "_search": "false",

        "nd": int(time.time()*1000),

        "queryModel.showCount": "100",

        "queryModel.currentPage": "1",

        "queryModel.sortName": "",

        "queryModel.sortOrder": "asc",

        "time": "0",

    }



    response = session.post(
        url,
        headers=headers,
        data=data
    )


    try:

        result = response.json()

    except Exception:

        return None



    courses = result.get(
        "items",
        []
    )



    # 查询详情

    for course in courses:


        try:

            detail = select_score_detail(
                session,
                course
            )


            extra = parse_detail(detail)


            course.update(extra)


        except Exception:


            # 不打印，避免日志爆炸

            continue



    # 是否导出Excel

    if export:


        df = pd.DataFrame(courses)


        columns = [

            "xnmmc",

            "xqmmc",

            "kcmc",

            "kcxzmc",

            "xf",

            "cj",

            "xfjd",

            "cjbdsj",

            "平时成绩",

            "期中成绩",

            "期末成绩",

            "总评成绩"

        ]


        columns = [

            c for c in columns

            if c in df.columns

        ]


        df[columns].to_excel(

            f"{name}_的成绩.xlsx",

            index=False

        )



    result["items"] = courses


    return result





def select_score_detail(session, course):


    url = (

        BASE_URL

        +

        "cjcx/cjcx_cxCjxqGjh.html"

    )



    data = {


        "jxb_id":

        course.get("jxb_id"),



        "xnm":

        XNM,



        "xqm":

        XQM,



        "xh_id":

        course.get("xh_id"),



        "kcmc":

        course.get("kcmc")

    }



    response = session.post(

        url,

        params={

            "gnmkdm":

            "N305005"

        },

        data=data

    )


    return response.text





def parse_detail(html):


    soup = BeautifulSoup(
        html,
        "html.parser"
    )


    table = soup.find(
        "table",
        id="subtab"
    )


    if table is None:

        return {}



    result = {}



    tbody = table.find("tbody")


    if tbody is None:

        return {}



    rows = tbody.find_all("tr")



    for row in rows:


        tds = row.find_all("td")



        if len(tds) != 3:

            continue



        item = tds[0].get_text(
            strip=True
        )


        percent = tds[1].get_text(
            strip=True
        )


        score = tds[2].get_text(
            strip=True
        )



        item = (

            item

            .replace("【","")

            .replace("】","")

            .strip()

        )


        result[item+"成绩"] = score



        if percent:

            result[item+"占比"] = percent



    return result