"""네이버 데이터랩 검색어트렌드 API로 건강 키워드의 연령대x성별 관심도 추이를 조회한다.

공식 문서: https://developers.naver.com/docs/serviceapi/datalab/search/search.md
- keywordGroups: 최대 5개, 그룹당 keywords 최대 20개
- ages 코드: 1(0-12) 2(13-18) 3(19-24) 4(25-29) 5(30-34) 6(35-39)
            7(40-44) 8(45-49) 9(50-54) 10(55-59) 11(60+)
  네이버가 제공하는 구간이 딱 "10대/20대" 단위로 안 떨어져서,
  아래 AGE_BUCKETS는 근사치임 (예: 10대 버킷에 0-12세도 섞여 들어감).
"""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

DATALAB_URL = "https://openapi.naver.com/v1/datalab/search"

AGE_BUCKETS = {
    "10대": ["1", "2"],
    "20대": ["3", "4"],
    "30대": ["5", "6"],
    "40대": ["7", "8"],
    "50대": ["9", "10"],
    "60대+": ["11"],
}
GENDERS = {"남성": "m", "여성": "f"}

ECONOMY_PRACTICAL_CATEGORIES = {
    "대출/전세자금": ["전세자금대출", "신용대출한도", "중도상환수수료"],
    "청약/부동산정책": ["청약통장", "특별공급", "생애최초주택"],
    "절세/연말정산": ["연말정산", "종합소득세", "세액공제"],
    "카드혜택": ["신용카드혜택", "체크카드추천", "카드전월실적"],
    "앱테크": ["앱테크", "만보기적립", "리워드앱"],
    "부업/부수입": ["부업추천", "재택부업", "부수입만들기"],
    "정부지원금": ["청년지원금", "정부지원금신청", "근로장려금"],
}


def keyword_for_category(category, categories=None, today=None):
    """카테고리 안의 구체적 키워드 중 하나를 날짜 기반 로테이션으로 고른다.

    상승률 1위만 계속 뽑으면 그 카테고리 안에서도 특정 키워드(예: '근로장려금')만 매번 반복되는
    문제가 있었다(건강 리포트에서 먼저 발견, 2026-08-09). `.tmp/`의 추천 이력은 실행마다 초기화될
    수 있어 신뢰할 수 없으므로, 저장 없이도 항상 같은 결과를 내는 날짜(day-of-year) 로테이션을
    쓴다 — 같은 카테고리가 다시 배정되는 날마다 키워드가 자동으로 바뀐다.
    """
    import datetime
    categories = categories or ECONOMY_PRACTICAL_CATEGORIES
    today = today or datetime.date.today()
    keywords = categories[category]
    idx = today.timetuple().tm_yday % len(keywords)
    return keywords[idx]


HEALTH_CATEGORIES = {
    "다이어트/체중관리": ["다이어트", "간헐적단식", "저탄고지", "체지방감량", "다이어트식단", "요요현상", "복부지방"],
    "수면/피로": ["불면증", "수면의질", "수면무호흡증", "만성피로", "멜라토닌", "낮잠"],
    "영양제/보충제": ["오메가3", "비타민디", "유산균추천", "마그네슘", "루테인", "종합비타민", "콜라겐"],
    "정신건강/스트레스": ["번아웃증후군", "불안장애", "스트레스해소법", "공황장애", "무기력증", "심리상담"],
    "면역/감기": ["환절기감기", "독감예방접종", "면역력높이는법", "알레르기비염", "편도염", "장염"],
    "눈/피부": ["안구건조증", "다크서클", "탈모초기증상", "피부트러블", "각질관리"],
    "관절/근육": ["오십견", "손목터널증후군", "거북목증후군", "허리디스크", "무릎통증", "족저근막염"],
    "여성건강": ["생리불순", "다낭성난소증후군", "갱년기증상", "산후우울증", "질건조증"],
    "남성건강": ["전립선비대증", "남성갱년기", "발기부전", "탈모약"],
    "노년건강": ["고혈압관리", "당뇨초기증상", "골다공증", "치매예방", "낙상예방"],
    "소아/육아건강": ["아기열날때", "영유아예방접종", "성장통", "소아아토피", "이유식알레르기"],
}


def _headers():
    client_id = os.environ["NAVER_CLIENT_ID"]
    client_secret = os.environ["NAVER_CLIENT_SECRET"]
    return {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type": "application/json",
    }


def _chunk(items, size):
    items = list(items)
    return [items[i:i + size] for i in range(0, len(items), size)]


def fetch_segment_trend(keyword_groups, start_date, end_date, ages=None, gender="", time_unit="date"):
    """keyword_groups: [{"groupName": str, "keywords": [str, ...]}, ...] (최대 5개)"""
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": time_unit,
        "keywordGroups": keyword_groups,
        "device": "",
        "ages": ages or [],
        "gender": gender,
    }
    resp = requests.post(DATALAB_URL, headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _rising_score(time_series):
    """최근 7일 평균 대비 이전 7일 평균 변화율(%). 데이터가 14일 미만이면 None."""
    points = [p["ratio"] for p in time_series]
    if len(points) < 14:
        return None
    recent = points[-7:]
    previous = points[-14:-7]
    prev_avg = sum(previous) / len(previous)
    recent_avg = sum(recent) / len(recent)
    if prev_avg == 0:
        return None
    return round((recent_avg - prev_avg) / prev_avg * 100, 1)


def get_rising_keywords_by_segment(categories=None, days=14, sleep_between_calls=0.3):
    """연령대 x 성별 세그먼트별로 카테고리별 상승률을 계산해서 반환.

    반환 형식: {"30대 x 여성": [{"category": str, "rising_pct": float|None}, ...], ...}
    """
    categories = categories or HEALTH_CATEGORIES
    category_items = list(categories.items())
    batches = _chunk(category_items, 5)  # keywordGroups 최대 5개 제한

    end_date = time.strftime("%Y-%m-%d")
    start_date = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))

    results = {}
    for age_label, age_codes in AGE_BUCKETS.items():
        for gender_label, gender_code in GENDERS.items():
            segment_key = f"{age_label} x {gender_label}"
            segment_result = []
            for batch in batches:
                keyword_groups = [
                    {"groupName": name, "keywords": keywords[:20]}
                    for name, keywords in batch
                ]
                data = fetch_segment_trend(
                    keyword_groups, start_date, end_date,
                    ages=age_codes, gender=gender_code,
                )
                for result in data.get("results", []):
                    score = _rising_score(result["data"])
                    segment_result.append({
                        "category": result["title"],
                        "rising_pct": score,
                    })
                time.sleep(sleep_between_calls)  # API 호출 과다 방지
            segment_result.sort(key=lambda x: (x["rising_pct"] is None, -(x["rising_pct"] or 0)))
            results[segment_key] = segment_result
    return results


if __name__ == "__main__":
    import json
    print(json.dumps(get_rising_keywords_by_segment(), ensure_ascii=False, indent=2))
