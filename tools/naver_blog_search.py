"""네이버 블로그 검색 API. 특정 키워드로 이미 나온 콘텐츠 양(포화도)을 참고용으로 확인한다.

주의: 이 API는 정확도순/최신순만 지원하고 조회수·좋아요 같은 인기 지표는 없다.
"인기 포스팅 랭킹"이 아니라 "이 키워드로 글이 얼마나 많이 이미 올라와 있는지"를 보는 용도.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

BLOG_SEARCH_URL = "https://openapi.naver.com/v1/search/blog.json"


def _headers():
    return {
        "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
    }


def search_blog(query, display=10, sort="sim"):
    params = {"query": query, "display": display, "sort": sort}
    resp = requests.get(BLOG_SEARCH_URL, headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def keyword_saturation(keyword):
    """키워드별 전체 검색결과 수(totalcount)와 상위 글 제목 몇 개를 반환."""
    data = search_blog(keyword, display=5, sort="sim")
    return {
        "keyword": keyword,
        "total_count": data.get("total", 0),
        "top_titles": [
            item["title"].replace("<b>", "").replace("</b>", "")
            for item in data.get("items", [])
        ],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(keyword_saturation("오메가3"), ensure_ascii=False, indent=2))
