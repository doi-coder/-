"""매일 아침 실행되는 오케스트레이션 스크립트.

절차: 데이터랩 트렌드 조회 -> 상승 카테고리 선정 -> 블로그 포화도 확인 ->
유튜브 화제 콘텐츠 확인 -> 최근 추천 이력과 중복 제거 -> 추천 주제 산출 ->
PDF 생성 -> 로그 기록.

PDF는 이메일로 보내지 않는다 — 이 스크립트를 실행하는 에이전트가 생성된 PDF를
채팅 응답에 직접 첨부해서 전달한다 (workflows/daily_health_topic_report.md 참고).

각 데이터 소스는 실패해도 전체가 멈추지 않고, 캐시된 이전 결과로 대체한 뒤
리포트에 "갱신 실패" 표시를 남긴다. 사용법: `python tools/run_daily_report.py`
"""
import json
import os
import sys
import traceback
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import naver_trend
import naver_blog_search
import youtube_trend
import report_builder

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(BASE_DIR, ".tmp")
CACHE_DIR = os.path.join(TMP_DIR, "cache")
REPORT_DIR = os.path.join(TMP_DIR, "reports")
LOG_DIR = os.path.join(TMP_DIR, "logs")
HISTORY_PATH = os.path.join(TMP_DIR, "recommendation_history.json")

HISTORY_COOLDOWN_DAYS = 14
TOP_CANDIDATES = 8

SATURATION_LABELS = [(50_000, "낮음"), (200_000, "보통")]


def _ensure_dirs():
    for d in (TMP_DIR, CACHE_DIR, REPORT_DIR, LOG_DIR):
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


def _recently_recommended_keywords(history, today):
    cutoff = today - timedelta(days=HISTORY_COOLDOWN_DAYS)
    recent = set()
    for entry in history:
        entry_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        if entry_date >= cutoff:
            recent.update(entry["keywords"])
    return recent


def _pick_candidate_categories(segment_trends, recent_keywords):
    """세그먼트별 상승 카테고리를 전부 모아서, 상승률 높은 순으로 중복 제거."""
    seen_categories = set()
    ranked = []
    for segment, categories in segment_trends.items():
        for c in categories:
            if c["rising_pct"] is None or c["category"] in seen_categories:
                continue
            representative_keyword = naver_trend.HEALTH_CATEGORIES[c["category"]][0]
            if representative_keyword in recent_keywords:
                continue
            seen_categories.add(c["category"])
            ranked.append({
                "segment": segment,
                "category": c["category"],
                "rising_pct": c["rising_pct"],
                "keyword": representative_keyword,
            })
    ranked.sort(key=lambda x: x["rising_pct"], reverse=True)
    return ranked[:TOP_CANDIDATES]


def build_report_data(report_date):
    log = []
    failed_sources = []

    segment_trends = _with_fallback(
        "naver_trend", naver_trend.get_rising_keywords_by_segment, failed_sources, log,
    )

    history = _load_history()
    recent_keywords = _recently_recommended_keywords(history, report_date)
    candidates = _pick_candidate_categories(segment_trends, recent_keywords)

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

    recommended_topics = []
    for c in candidates:
        total_count = c.get("total_count")
        saturation = _saturation_label(total_count) if total_count is not None else "확인불가"
        reason = f"검색 관심도 최근 7일 평균이 이전 7일 대비 {c['rising_pct']:+.1f}% 상승 (타겟: {c['segment']}), 블로그 경쟁도 {saturation}"
        recommended_topics.append({
            "topic": f"{c['keyword']} 총정리 - 원인, 증상, 관리법",
            "segment": c["segment"],
            "reason": reason,
        })

    _save_history(history + [{
        "date": report_date.strftime("%Y-%m-%d"),
        "keywords": [c["keyword"] for c in candidates],
    }])

    data = {
        "report_date": report_date.strftime("%Y-%m-%d"),
        "failed_sources": failed_sources,
        "recommended_topics": recommended_topics,
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

        pdf_path = os.path.join(REPORT_DIR, f"health_report_{data['report_date']}.pdf")
        report_builder.generate_report(data, pdf_path)
        log_lines.append(f"PDF 생성 완료: {pdf_path}")
        log_lines.append(f"REPORT_READY_FOR_DELIVERY: {pdf_path}")
        log_lines.append(f"추천 주제 {len(data['recommended_topics'])}개: " + ", ".join(t['topic'] for t in data['recommended_topics']))

    except Exception as e:
        log_lines.append(f"치명적 오류로 실행 중단: {e}\n{traceback.format_exc()}")

    finally:
        log_path = os.path.join(LOG_DIR, f"{today.strftime('%Y-%m-%d')}.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n")
        print("\n".join(log_lines))


if __name__ == "__main__":
    run()
