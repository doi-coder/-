"""매일 아침 실행되는 데이터 수집 스크립트 (1단계).

절차: 데이터랩 트렌드 조회 -> 오늘 날짜 로테이션으로 카테고리 2개 배정 -> 블로그 포화도 확인 ->
유튜브 화제 콘텐츠 확인 -> 후보 데이터를 JSON으로 저장.

카테고리 선정은 상승률 랭킹이 아니라 날짜 기반 강제 로테이션을 쓴다 — 특정 카테고리("노년건강"
등)가 계속 상위권을 차지해서 거의 매일 같은 주제만 나오는 문제가 있었기 때문(2026-08 확인).
자세한 이유는 `_todays_categories()` docstring 참고.

이 스크립트는 데이터만 모은다 — 검색의도 분석, 제목 선정, 포스팅 초안 작성은 사람의 판단이
필요한 영역이라 코드로 대신할 수 없다. 그래서 여기서 저장한 JSON을 실행하는 에이전트가 읽어서
`candidates` 각각에 title/search_intent/target_analysis/keyword_analysis를 채운 `posts`로
만든 뒤, `tools/report_builder.py <json경로> <pdf경로>`로 최종 PDF를 만든다
(workflows/daily_health_topic_report.md 참고 — economy_daily_reports.md와 같은 패턴).

각 데이터 소스는 실패해도 전체가 멈추지 않고, 캐시된 이전 결과로 대체한 뒤
리포트에 "갱신 실패" 표시를 남긴다. 사용법: `python tools/run_daily_report.py`
"""
import json
import os
import sys
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import naver_trend
import naver_blog_search
import naver_kin_search
import naver_searchad
import youtube_trend

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(BASE_DIR, ".tmp")
CACHE_DIR = os.path.join(TMP_DIR, "cache")
DATA_DIR = os.path.join(TMP_DIR, "health_data")
REPORT_DIR = os.path.join(TMP_DIR, "reports")
LOG_DIR = os.path.join(TMP_DIR, "logs")
HISTORY_PATH = os.path.join(TMP_DIR, "recommendation_history.json")
# 이미 발행한 글 목록. .tmp/는 실행마다 초기화되므로 저장소에 커밋된 파일을 쓴다.
PUBLISHED_POSTS_PATH = os.path.join(BASE_DIR, "data", "published_posts.md")
# 수술실 업무 지식 체크리스트 (영역별 ✅ 이미 씀 / ⬜ 아직 안 씀). 2026-11-01 추가.
OR_KNOWLEDGE_MAP_PATH = os.path.join(BASE_DIR, "data", "or_knowledge_map.md")

# 2026-11-01 사장님 요청: 건강 주제 2개 -> 3개로 확장
CATEGORIES_PER_DAY = 3

# 2026-11-01 사장님 요청: 매일 수술실 업무 주제 3개도 함께 추천.
# 수술실 주제는 데이터랩 검색량이 거의 잡히지 않는 전문 용어가 많아서, 건강 카테고리처럼
# 날짜 로테이션으로 "오늘 생각해볼 주제 축" 3개를 배정하고 구체적 주제는 에이전트가 정한다.
# '환자 질문형'은 발행 글 중 조회수가 높은 유형(복강경 후 어깨 통증, 수술 탈의, 금식 등)이라 포함.
OR_TOPIC_AXES = [
    "정형외과(OS) 수술·기구",
    "외과(GS)·복강경 수술",
    "신경외과·척추 수술",
    "산부인과·비뇨의학과 수술",
    # 성형외과는 사장님이 수술에 들어가지 않으므로 축에서 제외 (운영·시스템 각도로만 다룸)
    "이비인후과·안과·흉부외과·혈관외과 등 기타 과 수술",
    "감염관리·소독·멸균",
    "마취·수술 약물",
    "수술실 장비·소모품(전기소작기, 석션, 봉합사, 드레싱 등)",
    "신규 간호사 실무·커리어",
    "환자 질문형(수술받는 일반인이 수술실에 대해 궁금해하는 것)",
]
OR_TOPICS_PER_DAY = 3


# 검색광고 연관키워드(롱테일) 설정 — 2026-11-01 추가. 키가 없으면 이 단계는 건너뛴다.
LONGTAIL_MIN_MONTHLY = 300      # 월간 검색량(PC+모바일)이 이보다 적은 키워드는 버림
LONGTAIL_PER_CANDIDATE = 8      # 후보 1개당 블로그 경쟁도까지 확인할 롱테일 수



def _ensure_dirs():
    for d in (TMP_DIR, CACHE_DIR, DATA_DIR, REPORT_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)


def _cache_path(name):
    return os.path.join(CACHE_DIR, f"{name}.json")


def _load_cache(name):
    path = _cache_path(name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_cache(name, data):
    with open(_cache_path(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _with_fallback(name, fetch_fn, failed_sources, log):
    try:
        data = fetch_fn()
        _save_cache(name, data)
        return data
    except Exception as e:
        log.append(f"[{name}] 실패: {e}\n{traceback.format_exc()}")
        failed_sources.append(name)
        cached = _load_cache(name)
        if cached is None:
            raise
        return cached


def _load_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _todays_categories(today):
    """오늘 날짜 기준으로 다룰 카테고리 2개를 강제 로테이션으로 뽑는다.

    예전에는 상승률이 가장 높은 카테고리들을 매번 새로 골랐는데, "노년건강"(고혈압관리)이나
    "남성건강"(전립선비대증) 카테고리가 거의 매일 상위권을 차지해서 같은 주제만 계속 나오는
    문제가 있었다(2026-08 확인). 게다가 카테고리 안에서도 항상 첫 번째 키워드만 대표로 썼다.
    그래서 지금은 11개 카테고리를 날짜 기준으로 순서대로 로테이션시켜 매일 다른 카테고리 2개가
    나오게 하고, 카테고리 안의 구체적 키워드도 날짜에 따라 돌아가며 바뀌게 했다.
    """
    order = list(naver_trend.HEALTH_CATEGORIES.keys())
    n = len(order)
    day_index = today.timetuple().tm_yday
    start = (day_index * CATEGORIES_PER_DAY) % n
    return [order[(start + i) % n] for i in range(CATEGORIES_PER_DAY)]


def _todays_or_axes(today):
    """오늘 다룰 수술실 주제 축 3개를 날짜 로테이션으로 뽑는다 (건강 카테고리와 같은 방식)."""
    n = len(OR_TOPIC_AXES)
    start = (today.timetuple().tm_yday * OR_TOPICS_PER_DAY) % n
    return [OR_TOPIC_AXES[(start + i) % n] for i in range(OR_TOPICS_PER_DAY)]


def _keyword_for_category(category, today):
    keywords = naver_trend.HEALTH_CATEGORIES[category]
    idx = today.timetuple().tm_yday % len(keywords)
    return keywords[idx]


def _longtail_options(seed, log):
    """씨앗 키워드로 검색광고 연관키워드를 받아, 씨앗이 들어간 롱테일만 월간 검색량 순으로 정리.

    여기 들어가는 값은 검색광고 API(월간 검색량·광고 경쟁도)뿐이다. 네이버 '검색 API'(블로그 글 수
    등)는 섞지 않는다 — 2026-09-07 개정 약관이 검색 API 결과를 AI에 넣는 것을 금지하기 때문
    (자세한 내용은 workflows/daily_health_topic_report.md "네이버 검색 데이터 취급 원칙").
    블로그 글 수는 _display_blog_counts()로 따로 모아 PDF에만 표시한다.
    """
    if not naver_searchad.is_configured():
        return []
    # 씨앗 하나만 넣는다. 여러 개를 넣으면 결과가 섞이고(루테인 -> 마그네슘), 연관키워드 도구는
    # 광고 관점의 넓은 키워드(병원, 강남역 등)도 같이 주기 때문에 씨앗이 포함된 키워드만 남긴다.
    # (2026-11-01 실제 실행에서 확인된 문제)
    try:
        rows = naver_searchad.related_keywords([seed])
    except Exception as e:
        log.append(f"[naver_searchad:{seed}] 실패: {e}")
        return []
    seed_key = seed.replace(" ", "")
    rows = [r for r in rows
            if seed_key in r["keyword"].replace(" ", "")
            and r["monthly_total"] >= LONGTAIL_MIN_MONTHLY]
    rows.sort(key=lambda r: r["monthly_total"], reverse=True)
    return rows[:LONGTAIL_PER_CANDIDATE]


def _display_blog_counts(keywords, log):
    """PDF 표시 전용: 키워드별 네이버 블로그 검색 결과 수. AI용 JSON에는 절대 넣지 않는다."""
    counts = {}
    for kw in keywords:
        try:
            counts[kw] = naver_blog_search.keyword_saturation(kw)["total_count"]
        except Exception as e:
            log.append(f"[naver_blog_search:{kw}] 실패: {e}")
    return counts


def _best_segment_for_category(segment_trends, category):
    """해당 카테고리의 상승률이 가장 높은 세그먼트를 찾는다 (추천 이유 문구에 사용, 카테고리 선정 자체에는 안 씀)."""
    best_segment, best_pct = None, None
    for segment, categories in segment_trends.items():
        for c in categories:
            if c["category"] == category and c["rising_pct"] is not None:
                if best_pct is None or c["rising_pct"] > best_pct:
                    best_segment, best_pct = segment, c["rising_pct"]
    return best_segment, best_pct


def _pick_candidate_categories(segment_trends, today):
    """오늘 로테이션으로 배정된 카테고리들에 대해, 대표 세그먼트/키워드를 채워서 반환."""
    picked = []
    for category in _todays_categories(today):
        segment, rising_pct = _best_segment_for_category(segment_trends, category)
        picked.append({
            "segment": segment or "전체",
            "category": category,
            "rising_pct": rising_pct,
            "keyword": _keyword_for_category(category, today),
        })
    return picked


def build_report_data(report_date):
    log = []
    failed_sources = []

    segment_trends = _with_fallback(
        "naver_trend", naver_trend.get_rising_keywords_by_segment, failed_sources, log,
    )

    history = _load_history()
    candidates = _pick_candidate_categories(segment_trends, report_date)

    youtube_keywords = [c["keyword"] for c in candidates]
    youtube_top = _with_fallback(
        "youtube_trend",
        lambda: youtube_trend.trending_health_videos(keywords=youtube_keywords),
        failed_sources, log,
    )

    # ---- AI용 데이터: 네이버 검색 API 결과는 넣지 않는다 ----
    candidates_out = []
    for c in candidates:
        if c["rising_pct"] is not None:
            trend_desc = f"검색 관심도 최근 7일 평균이 이전 7일 대비 {c['rising_pct']:+.1f}% 상승 (타겟: {c['segment']})"
        else:
            trend_desc = "최근 상승률 데이터는 부족하지만 로테이션상 오늘 다룰 차례"
        candidates_out.append({
            "keyword": c["keyword"],
            "category": c["category"],
            "segment": c["segment"],
            "rising_pct": c["rising_pct"],
            "longtail_options": _longtail_options(c["keyword"], log),
            "reason": f"{trend_desc}. 매일 다른 카테고리를 다루기 위한 로테이션 배정.",
        })

    _save_history(history + [{
        "date": report_date.strftime("%Y-%m-%d"),
        "keywords": [c["keyword"] for c in candidates],
    }])

    data = {
        "report_date": report_date.strftime("%Y-%m-%d"),
        "failed_sources": failed_sources,
        "candidates": candidates_out,
        "or_axes": _todays_or_axes(report_date),
        "published_posts_path": PUBLISHED_POSTS_PATH,
        "or_knowledge_map_path": OR_KNOWLEDGE_MAP_PATH,
        "segment_trends": segment_trends,
        "youtube_top": youtube_top,
    }

    # ---- 표시 전용 데이터: 네이버 검색 API 결과. PDF 조립 때 report_builder.py가 직접 붙인다 ----
    count_keywords = []
    for c in candidates_out:
        count_keywords.append(c["keyword"])
        count_keywords.extend(o["keyword"] for o in c["longtail_options"])
    try:
        or_questions = _with_fallback(
            "naver_kin", naver_kin_search.recent_or_questions, failed_sources, log,
        )
    except Exception as e:
        log.append(f"[naver_kin] 캐시도 없어 질문 없이 진행: {e}")
        or_questions = []
    display = {
        "report_date": data["report_date"],
        "notice": "네이버 검색 API 결과 — 표시 전용. AI(에이전트)는 이 파일을 열거나 읽지 않는다.",
        "blog_counts": _display_blog_counts(dict.fromkeys(count_keywords), log),
        "or_questions": or_questions,
    }
    return data, display, log


def run():
    _ensure_dirs()
    today = datetime.now().date()
    log_lines = [f"=== {today} 실행 시작 ==="]

    try:
        data, display, fetch_log = build_report_data(today)
        log_lines.extend(fetch_log)

        display_path = os.path.join(DATA_DIR, f"display_{data['report_date']}.json")
        with open(display_path, "w", encoding="utf-8") as f:
            json.dump(display, f, ensure_ascii=False, indent=2)

        data_path = os.path.join(DATA_DIR, f"candidates_{data['report_date']}.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log_lines.append(f"CANDIDATES_READY: {data_path}")
        log_lines.append(
            "다음 단계(에이전트가 할 일): 위 JSON의 candidates 각각에 title/search_intent/"
            "target_analysis/keyword_analysis를 채워 posts로 만들고, tools/report_builder.py "
            "<json경로> <pdf경로>로 PDF를 생성하세요."
        )
        log_lines.append(
            f"오늘 배정된 키워드 {len(data['candidates'])}개: " +
            ", ".join(c["keyword"] for c in data["candidates"])
        )
        if naver_searchad.is_configured():
            log_lines.append("롱테일 후보: " + ", ".join(
                f"{c['keyword']} {len(c['longtail_options'])}개" for c in data["candidates"]))
        else:
            log_lines.append("검색광고 API 키 없음 — 롱테일 후보 없이 기존 키워드로 진행")
        log_lines.append("오늘 수술실 주제 축: " + ", ".join(data["or_axes"]))
        log_lines.append(
            f"표시 전용 네이버 검색 데이터 저장(에이전트는 열지 말 것): 블로그 글 수 "
            f"{len(display['blog_counts'])}개, 지식iN 질문 {len(display['or_questions'])}개"
        )

    except Exception as e:
        log_lines.append(f"치명적 오류로 실행 중단: {e}\n{traceback.format_exc()}")

    finally:
        log_path = os.path.join(LOG_DIR, f"{today.strftime('%Y-%m-%d')}.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n")
        print("\n".join(log_lines))


if __name__ == "__main__":
    run()
