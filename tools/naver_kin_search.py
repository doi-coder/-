"""네이버 지식iN 검색 API로 수술실·수술 관련 최신 질문을 모은다.

목적: 수술실 주제를 에이전트의 머릿속 지식이 아니라 "사람들이 실제로 모르는 것"에서
출발시키기 위함 (2026-11-01 사장님 요청). 간호학생·신규 간호사·수술을 앞둔 환자가 실제로
올린 질문을 관련도순으로, 날짜마다 다른 페이지에서 가져와 주제 후보로 쓴다.

블로그 검색과 같은 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET을 쓴다 (추가 발급 불필요).
주의: 지식iN API는 질문 작성일을 주지 않는다.
사용법: `python tools/naver_kin_search.py` (기본 검색어로 테스트)
"""
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

KIN_SEARCH_URL = "https://openapi.naver.com/v1/search/kin.json"

# 간호사·학생 쪽 질문과 환자 쪽 질문을 둘 다 잡도록 섞었다.
KIN_QUERIES = [
    "수술실 간호사",
    "스크럽 간호사",
    "써큐 간호사",
    "수술실 신규",
    "수술 기구 이름",
    "전신마취 수술",
    "척추마취",
    "수술 전 금식",
    "수술 후 소변줄",
    "복강경 수술 후",
    "수술 동의서",
    "회복실 마취",
]

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text):
    return _TAG_RE.sub("", text or "").replace("&quot;", '"').replace("&amp;", "&").strip()


def _headers():
    return {
        "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
    }


def search_kin(query, display=10, sort="sim", start=1):
    params = {"query": query, "display": display, "sort": sort, "start": start}
    resp = requests.get(KIN_SEARCH_URL, headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def recent_or_questions(queries=None, per_query=10, limit=40, today=None):
    """검색어마다 관련 질문을 모아 링크·제목 기준으로 중복 제거 후 반환.

    정렬은 관련도순(sim). 최신순(date)은 검색어를 스치듯 언급한 무관한 질문(직장 괴롭힘, 피부염
    등)이 대부분이었다(2026-11-01 실제 실행에서 확인). 관련도순은 매일 같은 결과가 나오므로,
    날짜에 따라 읽는 페이지(start)를 1~91 사이에서 돌려 매일 다른 질문을 가져온다.

    반환: [{"query", "title", "description", "link"}, ...] (최대 limit개)
    한 검색어가 실패해도 나머지는 계속 모은다. 전부 실패하면 예외를 올린다.
    """
    import datetime
    queries = queries or KIN_QUERIES
    today = today or datetime.date.today()
    start = 1 + (today.timetuple().tm_yday % 10) * 10
    seen, seen_titles, out, errors = set(), set(), [], []
    for q in queries:
        try:
            data = search_kin(q, display=per_query, start=start)
        except Exception as e:
            errors.append(f"{q}: {e}")
            continue
        for item in data.get("items", []):
            link = item.get("link")
            title = _clean(item.get("title"))
            # 같은 질문이 링크만 다르게 여러 번 올라오는 경우가 많아 제목으로도 중복 제거
            if not link or link in seen or title in seen_titles:
                continue
            seen.add(link)
            seen_titles.add(title)
            out.append({
                "query": q,
                "title": _clean(item.get("title")),
                "description": _clean(item.get("description"))[:200],
                "link": link,
            })
    if not out and errors:
        raise RuntimeError("지식iN 검색이 모두 실패: " + "; ".join(errors))
    return out[:limit]


if __name__ == "__main__":
    import json
    print(json.dumps(recent_or_questions(per_query=3, limit=10), ensure_ascii=False, indent=2))
