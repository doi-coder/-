"""건강 리포트 완료 전 검증 (2026-11-18 추가).

사장님께 결과물을 보내기 전에, 정답이 정해진 항목을 프로그램이 직접 확인한다. 에이전트가
"괜찮아 보인다"고 스스로 판단하는 대신, 항목마다 통과/실패/확인필요를 근거와 함께 출력한다.

사용법:
    python tools/draft_checker.py .tmp/health_data/report_<날짜>.json

같은 날짜의 초안(.tmp/reports/health_report_<날짜>_draft1~3.txt), candidates_<날짜>.json,
data/published_posts.md, data/or_knowledge_map.md를 함께 읽는다.
네이버 검색 결과(display_<날짜>.json)는 약관상 AI 입력 금지라 **절대 열지 않는다**.

결과는 화면에 출력하고 .tmp/reports/health_report_<날짜>_check.txt에도 저장한다.
실패가 하나라도 있으면 종료 코드 1, 없으면 0.

초안 파일 형식: 맨 위 분석 블록 → `=== 본문 ===` 한 줄 → 실제 초안. 구분선 아래만 검사한다.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BODY_MARKER = "=== 본문 ==="

# 분량: 워크플로우 기준 800~1200자 "내외" → 공백 포함, 줄바꿈 제외로 세고 앞뒤 여유를 둔다.
MIN_CHARS, MAX_CHARS = 750, 1300
# 메인 키워드가 본문에 나오는 횟수: 도입부 1회 + 본문 1~2회 = 2~3회가 목표, 5회 넘으면 반복 과다.
MIN_KEYWORD_HITS, MAX_KEYWORD_HITS = 2, 5

# 의료광고법·약사법, "지어내지 않기" 원칙상 쓰면 안 되는 표현. 사장님이 추가하고 싶으면 여기에.
BANNED_PHRASES = [
    "완치", "100%", "무조건", "특효", "기적", "부작용 없", "부작용이 없", "확실히 낫",
    "반드시 낫", "최고의 치료", "당신은", "틀림없",
]
# 메인 키워드로 고르면 안 되는 쇼핑·제품형 키워드 (워크플로우 "롱테일 키워드 선택" 1번)
SHOPPING_WORDS = ["추천", "최저가", "가격", "구매", "파는곳", "쿠팡", "할인", "브랜드", "순위"]

POST_FIELDS = ["title", "keyword", "search_intent", "target_analysis", "keyword_analysis", "differentiation"]
OR_FIELDS = ["title", "keyword", "axis", "source", "source_detail", "target", "outline", "differentiation"]

PASS, FAIL, CHECK = "통과", "실패", "확인필요"


def _norm(text):
    return re.sub(r"\s+", "", text or "")


def _contains_keyword(text, keyword):
    """키워드가 그대로(띄어쓰기 무시) 들어 있으면 True."""
    return bool(keyword) and _norm(keyword) in _norm(text)


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _split_draft(raw):
    if BODY_MARKER not in raw:
        return None
    return raw.split(BODY_MARKER, 1)[1].strip()


def _first_sentences(body, n=3):
    parts = re.split(r"(?<=[.!?。])\s+|\n+", body)
    return " ".join([p for p in parts if p.strip()][:n])


def _numbers_in(body):
    """본문 속 숫자 표현(근거를 대야 하는 것)을 문맥과 함께 뽑는다. 줄 맨 앞 목록 번호는 제외."""
    found = []
    for line in body.splitlines():
        line_wo_list = re.sub(r"^\s*\d+[.)]\s*", "", line)
        for m in re.finditer(r"\d[\d,.]*\s*(%|퍼센트|배|명|세|살|mg|g|kg|kcal|mmHg|시간|분|일|주|개월|년|회|잔|개)?",
                             line_wo_list):
            start, end = max(0, m.start() - 12), min(len(line_wo_list), m.end() + 12)
            found.append(line_wo_list[start:end].strip())
    return found


def _published_titles(path):
    titles = []
    if not os.path.exists(path):
        return titles
    for line in _read(path).splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            titles.append(parts[2])
    return titles


def _knowledge_map_items(path):
    """체크리스트 항목 → (영역 제목, 상태 기호)."""
    items, section = [], ""
    if not os.path.exists(path):
        return items
    for line in _read(path).splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        m = re.match(r"\s*-\s*(✅|🔶|⬜)\s*(.+)", line)
        if m:
            items.append((section, m.group(1), m.group(2).strip()))
    return items


def _find_map_item(detail, items):
    """source_detail과 단어가 가장 많이 겹치는 체크리스트 항목을 찾는다 (항목명을 줄여 써도 찾도록).

    항목 단어의 절반 이상, 최소 2개가 source_detail에 있어야 같은 항목으로 본다.
    """
    detail_n = _norm(detail)
    best, best_score = None, 0
    for section, mark, text in items:
        text = re.sub(r"\(\d{4}-\d{2}-\d{2}\)", "", text)  # "(2026-10-20)" 같은 발행일 표기 제외
        # 항목 전체로도, 콜론 앞 제목 부분("멸균법 비교: …"의 "멸균법 비교")만으로도 맞춰 본다
        for part in {text, text.split(":")[0]}:
            words = [w for w in re.split(r"[\s·,:/()]+", part) if len(w) >= 2]
            matched = sum(1 for w in words if w in detail_n)
            if words and matched >= 2 and matched * 2 >= len(words) and matched > best_score:
                best, best_score = (section, mark, text.strip()), matched
    return best


def check_post_draft(i, post, body, results):
    tag = f"건강 초안 {i}"
    kw = post.get("keyword", "")

    n = len(body.replace("\n", "").replace("\r", ""))
    results.append((tag, "분량", PASS if MIN_CHARS <= n <= MAX_CHARS else FAIL,
                    f"{n}자 (기준 {MIN_CHARS}~{MAX_CHARS}자)"))

    results.append((tag, "제목에 메인 키워드", PASS if _contains_keyword(post.get("title"), kw) else FAIL,
                    f"키워드 '{kw}' / 제목 '{post.get('title')}'"))

    intro = _first_sentences(body)
    results.append((tag, "도입부 3문장 안 키워드", PASS if _contains_keyword(intro, kw) else FAIL,
                    f"도입부: {intro[:60]}…"))

    hits = _norm(body).count(_norm(kw)) if kw else 0
    status = PASS if MIN_KEYWORD_HITS <= hits <= MAX_KEYWORD_HITS else FAIL
    results.append((tag, "키워드 반복 횟수", status, f"본문에 {hits}회 (기준 {MIN_KEYWORD_HITS}~{MAX_KEYWORD_HITS}회)"))

    md = [l.strip() for l in body.splitlines()
          if re.match(r"\s*(#|[-*]\s|>)", l) or "**" in l or "`" in l]
    results.append((tag, "마크다운 기호 없음", FAIL if md else PASS,
                    "발견: " + " / ".join(md[:3]) if md else "붙여넣기 가능"))

    tail = body[-400:]
    ok = "정보 제공" in tail and "병원" in tail
    results.append((tag, "면책 문구", PASS if ok else FAIL,
                    "끝부분에 '정보 제공'·'병원' 포함" if ok else "끝부분에 면책 문구('정보 제공 목적…병원 상담') 없음"))

    banned = [p for p in BANNED_PHRASES if p in body or p in post.get("title", "")]
    results.append((tag, "금지 표현 없음", FAIL if banned else PASS,
                    "발견: " + ", ".join(banned) if banned else "없음"))

    nums = _numbers_in(body)
    results.append((tag, "숫자 근거", CHECK if nums else PASS,
                    ("숫자마다 근거를 대거나 지울 것: " + " | ".join(nums[:8])) if nums else "본문에 숫자 없음"))


def check_report(report_path):
    report = json.loads(_read(report_path))
    date = report.get("report_date", "")
    data_dir = os.path.dirname(os.path.abspath(report_path))
    reports_dir = os.path.join(ROOT, ".tmp", "reports")
    results = []

    cand_path = os.path.join(data_dir, f"candidates_{date}.json")
    candidates = json.loads(_read(cand_path)).get("candidates", []) if os.path.exists(cand_path) else []
    published = _published_titles(os.path.join(ROOT, "data", "published_posts.md"))
    map_items = _knowledge_map_items(os.path.join(ROOT, "data", "or_knowledge_map.md"))

    # ── 건강 주제 전체 ──
    posts = report.get("posts", [])
    results.append(("건강 전체", "주제 3개", PASS if len(posts) == 3 else FAIL, f"{len(posts)}개"))
    kws = [_norm(p.get("keyword")) for p in posts]
    results.append(("건강 전체", "키워드 서로 다름", PASS if len(set(kws)) == len(kws) else FAIL,
                    ", ".join(p.get("keyword", "") for p in posts)))

    for i, post in enumerate(posts, start=1):
        tag = f"건강 초안 {i}"
        missing = [f for f in POST_FIELDS if not str(post.get(f, "")).strip()]
        results.append((tag, "필수 항목 채움", FAIL if missing else PASS,
                        "빠짐: " + ", ".join(missing) if missing else "전부 있음"))

        kw = post.get("keyword", "")
        shop = [w for w in SHOPPING_WORDS if w in kw]
        results.append((tag, "쇼핑·제품형 키워드 아님", FAIL if shop else PASS,
                        f"'{kw}'에 {', '.join(shop)}" if shop else kw))

        # 롱테일: 후보 목록에서 골랐는지 + 실제 월간 검색량을 그대로 적었는지
        seed = post.get("seed_keyword") or kw
        cand = next((c for c in candidates if c.get("keyword") == seed), None)
        if cand is None and i - 1 < len(candidates):
            cand = candidates[i - 1]
        opts = (cand or {}).get("longtail_options", [])
        if opts:
            opt = next((o for o in opts if _norm(o.get("keyword")) == _norm(kw)), None)
            if opt is None:
                results.append((tag, "롱테일 목록에서 선택", FAIL, f"'{kw}'가 longtail_options에 없음"))
            else:
                vol = opt.get("monthly_total")
                analysis = _norm(post.get("keyword_analysis")).replace(",", "")
                ok = vol is not None and str(vol) in analysis
                results.append((tag, "월간 검색량 실제 값 기재", PASS if ok else FAIL,
                                f"실제 값 {vol:,}" if isinstance(vol, int) else f"실제 값 {vol}"))
        else:
            results.append((tag, "롱테일 목록에서 선택", PASS, "롱테일 후보 없음 → 배정 키워드 사용"))

        # 중복: 발행 글 제목에 같은 키워드가 있는데 "관련 기존 글 없음"이라고 쓰면 모순
        related = [t for t in published if _contains_keyword(t, seed) or _contains_keyword(t, kw)]
        diff = post.get("differentiation", "")
        if any(_norm(t) == _norm(post.get("title")) for t in published):
            results.append((tag, "발행 글과 중복 아님", FAIL, "이미 발행한 글과 제목이 같음"))
        elif related and "관련기존글없음" in _norm(diff):
            results.append((tag, "발행 글과 중복 아님", FAIL,
                            "관련 글이 있는데 '관련 기존 글 없음'으로 적음: " + " / ".join(related[:3])))
        else:
            results.append((tag, "발행 글과 중복 아님", PASS,
                            ("관련 글: " + " / ".join(related[:3])) if related else "관련 발행 글 없음"))

        draft_path = os.path.join(reports_dir, f"health_report_{date}_draft{i}.txt")
        if not os.path.exists(draft_path):
            results.append((tag, "초안 파일", FAIL, f"없음: {draft_path}"))
            continue
        body = _split_draft(_read(draft_path))
        if body is None:
            results.append((tag, "초안 파일 형식", FAIL, f"'{BODY_MARKER}' 구분선 없음"))
            continue
        check_post_draft(i, post, body, results)

    # ── 수술실 주제 ──
    topics = report.get("or_topics", [])
    results.append(("수술실", "주제 3개", PASS if len(topics) == 3 else FAIL, f"{len(topics)}개"))
    for i, t in enumerate(topics, start=1):
        missing = [f for f in OR_FIELDS if not str(t.get(f, "")).strip()]
        results.append((f"수술실 {i}", "필수 항목 채움", FAIL if missing else PASS,
                        "빠짐: " + ", ".join(missing) if missing else "전부 있음"))
        if any(_norm(x) == _norm(t.get("title")) for x in published):
            results.append((f"수술실 {i}", "발행 글과 중복 아님", FAIL, "이미 발행한 글과 제목이 같음"))

    checklist = [t for t in topics if "체크리스트" in t.get("source", "")]
    axis_topics = [t for t in topics if "축" in t.get("source", "")]
    ok = len(checklist) == 2 and len(axis_topics) == 1
    results.append(("수술실", "출처 구성(체크리스트 2 + 주제 축 1)", PASS if ok else FAIL,
                    f"체크리스트 {len(checklist)}개, 주제 축 {len(axis_topics)}개"))

    sections = []
    for t in checklist:
        item = _find_map_item(t.get("source_detail", ""), map_items)
        if item is None:
            results.append(("수술실", "체크리스트 항목 확인", CHECK,
                            f"체크리스트에서 못 찾음: '{t.get('source_detail')}' — 직접 확인"))
            continue
        section, mark, text = item
        sections.append(section)
        results.append(("수술실", "체크리스트 항목 아직 안 씀", FAIL if mark == "✅" else PASS,
                        f"{mark} {text} ({section})"))
    if len(sections) == 2:
        results.append(("수술실", "체크리스트 2개 영역 다름", PASS if sections[0] != sections[1] else FAIL,
                        " / ".join(sections)))

    axes = report.get("or_axes", [])
    for t in axis_topics:
        in_axes = any(_norm(a) == _norm(t.get("axis")) for a in axes)
        overlap = any(_norm(c.get("axis")) == _norm(t.get("axis")) for c in checklist)
        ok = in_axes and not overlap
        results.append(("수술실", "주제 축 선택", PASS if ok else FAIL,
                        f"'{t.get('axis')}' — 오늘 축 목록에 {'있음' if in_axes else '없음'}"
                        f"{', 1·2번과 겹침' if overlap else ''}"))
    return date, results


def format_results(date, results):
    lines = [f"[건강 리포트 검증 결과 {date}]"]
    for tag, name, status, detail in results:
        lines.append(f"[{status}] {tag} · {name} — {detail}")
    fails = sum(1 for r in results if r[2] == FAIL)
    checks = sum(1 for r in results if r[2] == CHECK)
    lines.append(f"합계: 실패 {fails}개, 확인필요 {checks}개, 전체 {len(results)}개")
    return "\n".join(lines), fails


def main():
    if len(sys.argv) != 2:
        print("사용법: python tools/draft_checker.py .tmp/health_data/report_<날짜>.json")
        sys.exit(2)
    date, results = check_report(sys.argv[1])
    text, fails = format_results(date, results)
    print(text)
    out_dir = os.path.join(ROOT, ".tmp", "reports")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"health_report_{date}_check.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
