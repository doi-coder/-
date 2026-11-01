"""네이버 검색광고 API의 연관키워드 도구(keywordstool)로 롱테일 키워드와 월간 검색량을 가져온다.

왜 필요한가 (2026-11-01 사장님 확인): 건강 리포트는 미리 정해둔 약 60개 키워드를 날짜로 돌려
쓰는 구조라 결국 주제가 고갈된다. 데이터랩은 내가 넣은 키워드의 상대적 증감률만 알려줄 뿐 새
키워드를 찾아주지 못한다. 이 도구는 씨앗 키워드(예: '오메가3')를 넣으면 실제로 검색되는 연관
키워드 수십~수백 개를 **월간 검색량(PC+모바일 실제 수치)**과 함께 돌려준다 — 롱테일까지 내려가면
사실상 고갈되지 않는다.

필요한 값(.env): SEARCHAD_API_KEY(액세스라이선스), SEARCHAD_SECRET_KEY(비밀키),
SEARCHAD_CUSTOMER_ID(고객 ID). 검색광고 시스템 '도구 > API 사용 관리'에서 발급. 광고비는 필요 없다.
세 값이 없으면 `is_configured()`가 False를 돌려주고, 호출하는 쪽은 이 단계를 건너뛴다.

사용법: `python tools/naver_searchad.py 오메가3`
"""
import base64
import hashlib
import hmac
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.searchad.naver.com"
KEYWORDSTOOL_URI = "/keywordstool"


def is_configured():
    return all(os.environ.get(k) for k in (
        "SEARCHAD_API_KEY", "SEARCHAD_SECRET_KEY", "SEARCHAD_CUSTOMER_ID",
    ))


def _signature(timestamp, method, uri, secret_key):
    message = f"{timestamp}.{method}.{uri}"
    digest = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _headers(method, uri):
    timestamp = str(int(time.time() * 1000))
    return {
        "X-Timestamp": timestamp,
        "X-API-KEY": os.environ["SEARCHAD_API_KEY"],
        "X-Customer": str(os.environ["SEARCHAD_CUSTOMER_ID"]),
        "X-Signature": _signature(timestamp, method, uri, os.environ["SEARCHAD_SECRET_KEY"]),
    }


def _to_int(value):
    """검색량이 아주 적으면 API가 숫자 대신 '< 10' 문자열을 준다 -> 5로 간주."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().startswith("<"):
        return 5
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def parse_keyword_list(payload):
    """API 응답을 [{"keyword", "monthly_pc", "monthly_mobile", "monthly_total", "competition"}]로 정리."""
    out = []
    for item in payload.get("keywordList", []):
        pc = _to_int(item.get("monthlyPcQcCnt"))
        mobile = _to_int(item.get("monthlyMobileQcCnt"))
        out.append({
            "keyword": item.get("relKeyword", ""),
            "monthly_pc": pc,
            "monthly_mobile": mobile,
            "monthly_total": pc + mobile,
            "competition": item.get("compIdx"),  # 광고 경쟁 정도: 낮음/중간/높음
        })
    return out


def related_keywords(hint_keywords):
    """씨앗 키워드(최대 5개, 공백 없이)로 연관 키워드와 월간 검색량 조회."""
    hints = [h.replace(" ", "") for h in hint_keywords if h][:5]
    params = {"hintKeywords": ",".join(hints), "showDetail": "1"}
    resp = requests.get(
        BASE_URL + KEYWORDSTOOL_URI,
        headers=_headers("GET", KEYWORDSTOOL_URI),
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    return parse_keyword_list(resp.json())


if __name__ == "__main__":
    import json
    import sys
    if not is_configured():
        print("SEARCHAD_API_KEY / SEARCHAD_SECRET_KEY / SEARCHAD_CUSTOMER_ID 가 .env에 없습니다.")
        sys.exit(1)
    seed = sys.argv[1:] or ["오메가3"]
    rows = sorted(related_keywords(seed), key=lambda r: r["monthly_total"], reverse=True)
    print(json.dumps(rows[:20], ensure_ascii=False, indent=2))
