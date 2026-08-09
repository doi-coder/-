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
import youtube_trend

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(BASE_DIR, ".tmp")
CACHE_DIR = os.path.join(TMP_DIR, "cache")
DATA_DIR = os.path.join(TMP_DIR, "health_data")
REPORT_DIR = os.path.join(TMP_DIR, "reports")
LOG_DIR = os.path.join(TMP_DIR, "logs")
HISTORY_PATH = os.path.join(TMP_DIR, "recommendation_history.json")

CATEGORIES_PER_DAY = 2

SATURATION_LABELS = [(50_000, "낮음"), (200_000, "보통")]


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


def _saturation_label(total_count):
    for threshold, label in SATURATION_LABELS:
        if total_count < threshold:
            return label
    return "높음"


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


def _keyword_for_category(category, today):
    keywords = naver_trend.HEALTH_CATEGORIES[category]
    idx = today.timetuple().tm_yday % len(keywords)
    return keywords[idx]


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

    blog_saturation = []
    for c in candidates:
        try:
            sat = naver_blog_search.keyword_saturation(c["keyword"])
            c["total_count"] = sat["total_count"]
        except Exception as e:
            log.append(f"[naver_blog_search:{c['keyword']}] 실패: {e}")
            c["total_count"] = None
        blog_saturation.append({"keyword": c["keyword"], "total_count": c["total_count"] or 0})

    youtube_keywords = [c["keyword"] for c in candidates]
    youtube_top = _with_fallback(
        "youtube_trend",
        lambda: youtube_trend.trending_health_videos(keywords=youtube_keywords),
        failed_sources, log,
    )

    candidates_out = []
    for c in candidates:
        total_count = c.get("total_count")
        saturation = _saturation_label(total_count) if total_count is not None else "확인불가"
        if c["rising_pct"] is not None:
            trend_desc = f"검색 관심도 최근 7일 평균이 이전 7일 대비 {c['rising_pct']:+.1f}% 상승 (타겟: {c['segment']})"
        else:
            trend_desc = "최근 상승률 데이터는 부족하지만 로테이션상 오늘 다룰 차례"
        reason = f"{trend_desc}, 블로그 경쟁도 {saturation}. 매일 다른 카테고리를 다루기 위한 로테이션 배정."
        candidates_out.append({
            "keyword": c["keyword"],
            "category": c["category"],
            "segment": c["segment"],
            "rising_pct": c["rising_pct"],
            "total_count": total_count,
            "reason": reason,
        })

    _save_history(history + [{
        "date": report_date.strftime("%Y-%m-%d"),
        "keywords": [c["keyword"] for c in candidates],
    }])

    data = {
        "report_date": report_date.strftime("%Y-%m-%d"),
        "failed_sources": failed_sources,
        "candidates": candidates_out,
        "segment_trends": segment_trends,
        "youtube_top": youtube_top,
        "blog_saturation": blog_saturation,
    }
    return data, log


def run():
    _ensure_dirs()
    today = datetime.now().date()
    log_lines = [f"=== {today} 실행 시작 ==="]

    try:
        data, fetch_log = build_report_data(today)
        log_lines.extend(fetch_log)

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

    except Exception as e:
        log_lines.append(f"치명적 오류로 실행 중단: {e}\n{traceback.format_exc()}")

    finally:
        log_path = os.path.join(LOG_DIR, f"{today.strftime('%Y-%m-%d')}.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n")
        print("\n".join(log_lines))


if __name__ == "__main__":
    run()
