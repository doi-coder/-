"""분석 결과를 브랜드 PDF 리포트로 만든다 (reportlab, 한글 폰트 임베딩).

브랜드 컬러/로고는 지정된 게 없어서 기본값을 넣어뒀음.
나중에 사장님이 로고 파일/브랜드 컬러를 주면 BRAND_* 상수와 logo_path만 바꾸면 됨.

사용법: `python tools/report_builder.py <입력 json 경로> <출력 pdf 경로>` (인자 없이 실행하면
샘플 데이터로 테스트). 입력 JSON은 `tools/run_daily_report.py`가 만든 candidates 데이터에,
실행하는 에이전트가 title/search_intent/target_analysis/keyword_analysis를 채운 posts를
포함해야 한다 (data 형식은 generate_report() 아래 docstring 참고).
"""
import json
import os
import sys
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, HRFlowable,
)

BRAND_PRIMARY = colors.HexColor("#1F6F5C")
BRAND_ACCENT = colors.HexColor("#E8B84B")
BRAND_TEXT = colors.HexColor("#222222")

ASSETS_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")

FONT_CANDIDATES = [
    # 저장소에 번들된 폰트 (로컬/클라우드 어디서 실행되든 항상 동작)
    (os.path.join(ASSETS_FONT_DIR, "NanumGothic-Regular.ttf"), os.path.join(ASSETS_FONT_DIR, "NanumGothic-Bold.ttf")),
    # Windows 로컬 실행 시 시스템 폰트 (번들 폰트가 없을 때의 대비책)
    (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
]


def _register_korean_font():
    for regular, bold in FONT_CANDIDATES:
        if os.path.exists(regular):
            pdfmetrics.registerFont(TTFont("Korean", regular))
            pdfmetrics.registerFont(TTFont("Korean-Bold", bold if os.path.exists(bold) else regular))
            return "Korean", "Korean-Bold"
    raise RuntimeError(
        "한글 폰트를 찾을 수 없습니다. Windows의 맑은 고딕(malgun.ttf)이 없다면 "
        "FONT_CANDIDATES에 사용할 폰트 파일 경로를 추가하세요."
    )


def _build_styles(font, font_bold):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "KTitle", fontName=font_bold, fontSize=24, leading=30, textColor=BRAND_PRIMARY, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "KSubtitle", fontName=font, fontSize=12, leading=16, textColor=BRAND_TEXT, spaceAfter=20,
    ))
    styles.add(ParagraphStyle(
        "KHeading", fontName=font_bold, fontSize=15, textColor=BRAND_PRIMARY,
        spaceBefore=16, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "KBody", fontName=font, fontSize=10, textColor=BRAND_TEXT, leading=14,
    ))
    styles.add(ParagraphStyle(
        "KNote", fontName=font, fontSize=8, textColor=colors.grey, leading=11,
    ))
    return styles


def _table(rows, col_widths, font, font_bold):
    style = TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), font_bold),
        ("FONTNAME", (0, 1), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ])
    return Table(rows, colWidths=col_widths, style=style, repeatRows=1)


def _load_side_data(input_path, report_date):
    """같은 폴더의 display_<날짜>.json(네이버 검색 결과, 표시 전용)과 candidates_<날짜>.json을 읽는다.

    네이버 검색 API 결과는 2026-09-07 개정 약관상 AI에 넣을 수 없어서, 에이전트가 만드는 JSON에는
    들어가지 않는다. 대신 이 스크립트(사람이 보는 PDF를 조립하는 코드)가 직접 읽어 출처와 함께
    그대로 표시한다.
    """
    base = os.path.dirname(os.path.abspath(input_path)) if input_path else ""
    out = {}
    for name in ("display", "candidates"):
        path = os.path.join(base, f"{name}_{report_date}.json")
        if base and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                out[name] = json.load(f)
    return out.get("display", {}), out.get("candidates", {})


def _fetch_blog_counts(keywords, known):
    """PDF 표시용 블로그 글 수. display 파일에 없는 키워드(에이전트가 고른 수술실 주제 등)만 새로 조회."""
    counts = dict(known)
    missing = [k for k in dict.fromkeys(keywords) if k and k not in counts]
    if not missing:
        return counts
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import naver_blog_search
        for k in missing:
            try:
                counts[k] = naver_blog_search.keyword_saturation(k)["total_count"]
            except Exception:
                pass
    except Exception:
        pass
    return counts


NAVER_SOURCE_NOTE = "출처: 네이버 검색(블로그·지식iN) 결과를 가공 없이 표시. AI 분석에는 사용하지 않음."


def generate_report(data, output_path, logo_path=None, input_path=None):
    """data 형식:
    {
      "report_date": "2026-07-25",
      "failed_sources": ["youtube"],           # 이번 실행에서 갱신 실패한 소스 (없으면 [])
      "posts": [
        {
          "keyword": str,                      # 메인 키워드
          "title": str,                        # 네이버 블로그 제목
          "search_intent": str,                # 이 키워드를 검색하는 사람들의 니즈/의도
          "target_analysis": str,               # 타겟 독자 분석
          "keyword_analysis": str,              # 메인 키워드 분석(경쟁도·상승률 등 근거)
          "reason": str,                        # run_daily_report.py가 만든 데이터 기반 추천 이유
          "differentiation": str,               # (선택) 이미 쓴 관련 글이 있을 때, 이번 글의 다른 각도
        }, ...
      ],
      "or_axes": [str, ...],                    # (선택) 오늘의 수술실 주제 축
      "or_topics": [                            # (선택) 수술실 업무 주제 추천 3개
        {"title", "keyword", "axis", "source", "source_detail", "target", "outline",
         "differentiation"}, ...
      ],
      # 네이버 검색 결과(블로그 글 수, 지식iN 질문)는 여기 넣지 않는다 — 같은 폴더의
      # display_<날짜>.json에서 이 스크립트가 직접 읽어 표시한다 (AI 입력 금지 약관 대응).
      "segment_trends": {"30대 x 여성": [{"category": str, "rising_pct": float|None}, ...], ...},
      "youtube_top": [{"title","channel","view_count","like_count","url"}, ...],
    }
    """
    font, font_bold = _register_korean_font()
    styles = _build_styles(font, font_bold)
    story = []

    display, candidates = _load_side_data(input_path, data.get("report_date", ""))
    longtails_by_seed = {
        c.get("keyword"): c.get("longtail_options", []) for c in candidates.get("candidates", [])
    }
    count_keywords = [p.get("keyword") for p in data.get("posts", [])]
    count_keywords += [t.get("keyword") for t in data.get("or_topics", [])]
    for opts in longtails_by_seed.values():
        count_keywords += [o.get("keyword") for o in opts]
    blog_counts = _fetch_blog_counts(count_keywords, display.get("blog_counts", {}))

    def _count_text(kw):
        n = blog_counts.get(kw)
        return f"{n:,}건" if isinstance(n, int) else "확인불가"

    if logo_path and os.path.exists(logo_path):
        story.append(Image(logo_path, width=30 * mm, height=30 * mm))
        story.append(Spacer(1, 10))

    story.append(Paragraph("건강·수술실 콘텐츠 리포트", styles["KTitle"]))
    story.append(Paragraph(f"{data['report_date']} · 네이버 블로그 포스팅 주제 추천", styles["KSubtitle"]))

    if data.get("failed_sources"):
        failed = ", ".join(data["failed_sources"])
        story.append(Paragraph(
            f"※ 오늘은 다음 데이터 소스 갱신에 실패해서 이전 데이터로 대체했습니다: {failed}",
            styles["KNote"],
        ))
        story.append(Spacer(1, 10))

    for i, post in enumerate(data.get("posts", []), start=1):
        story.append(Paragraph(f"{i}. {post['title']}", styles["KHeading"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DDDDDD"), spaceAfter=6))
        story.append(Paragraph(f"<b>메인 키워드</b>: {post['keyword']}", styles["KBody"]))
        story.append(Paragraph(f"<b>검색 의도</b>: {post.get('search_intent', '-')}", styles["KBody"]))
        story.append(Paragraph(f"<b>타겟 독자</b>: {post.get('target_analysis', '-')}", styles["KBody"]))
        story.append(Paragraph(f"<b>키워드 분석</b>: {post.get('keyword_analysis', '-')}", styles["KBody"]))
        if post.get("differentiation"):
            story.append(Paragraph(f"<b>기존 글과의 차별점</b>: {post['differentiation']}", styles["KBody"]))
        story.append(Paragraph(f"※ 데이터 근거: {post.get('reason', '-')}", styles["KNote"]))
        story.append(Paragraph(
            f"※ 네이버 블로그 검색 결과: {_count_text(post['keyword'])} (참고용, AI 미사용)", styles["KNote"],
        ))
        opts = longtails_by_seed.get(post.get("seed_keyword") or post["keyword"], [])
        if opts:
            rows = [["롱테일 후보", "월간 검색량", "광고 경쟁", "블로그 글 수"]]
            for o in opts:
                rows.append([o["keyword"], f'{o["monthly_total"]:,}', o.get("competition") or "-",
                             _count_text(o["keyword"])])
            story.append(Spacer(1, 4))
            story.append(_table(rows, [62 * mm, 32 * mm, 26 * mm, 50 * mm], font, font_bold))
            story.append(Paragraph(
                "월간 검색량·광고 경쟁: 네이버 검색광고 / 블로그 글 수: 네이버 검색(표시 전용)", styles["KNote"],
            ))
        story.append(Paragraph("※ 전체 포스팅 초안은 별첨 텍스트 파일을 참고하세요.", styles["KNote"]))
        story.append(Spacer(1, 12))

    or_topics = data.get("or_topics", [])
    if or_topics:
        story.append(PageBreak())
        story.append(Paragraph("오늘의 수술실 업무 주제 추천", styles["KTitle"]))
        if data.get("or_axes"):
            story.append(Paragraph(f"오늘의 주제 축: {', '.join(data['or_axes'])}", styles["KSubtitle"]))
        for i, t in enumerate(or_topics, start=1):
            story.append(Paragraph(f"{i}. {t['title']}", styles["KHeading"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DDDDDD"), spaceAfter=6))
            story.append(Paragraph(f"<b>메인 키워드</b>: {t.get('keyword', '-')}", styles["KBody"]))
            story.append(Paragraph(f"<b>주제 축</b>: {t.get('axis', '-')}", styles["KBody"]))
            if t.get("source"):
                story.append(Paragraph(f"<b>출처</b>: {t['source']} — {t.get('source_detail', '')}", styles["KBody"]))
            story.append(Paragraph(f"<b>타겟 독자</b>: {t.get('target', '-')}", styles["KBody"]))
            story.append(Paragraph(f"<b>다룰 내용</b>: {t.get('outline', '-')}", styles["KBody"]))
            story.append(Paragraph(f"<b>기존 글과의 차별점</b>: {t.get('differentiation', '-')}", styles["KBody"]))
            story.append(Paragraph(
                f"※ 네이버 블로그 검색 결과: {_count_text(t.get('keyword'))} (참고용, AI 미사용)", styles["KNote"],
            ))
            story.append(Spacer(1, 12))

    or_questions = display.get("or_questions", [])
    if or_questions:
        story.append(Paragraph("직접 훑어보기: 지식iN 수술 관련 질문", styles["KHeading"]))
        story.append(Paragraph(
            "실제로 사람들이 올린 질문이에요. 글감이 될 만한 게 있는지 직접 골라보세요. " + NAVER_SOURCE_NOTE,
            styles["KNote"],
        ))
        rows = [["검색어", "질문"]]
        for q in or_questions[:15]:
            rows.append([
                q.get("query", ""),
                Paragraph(f'<link href="{q["link"]}">{q["title"]}</link>', styles["KBody"]),
            ])
        story.append(_table(rows, [35 * mm, 135 * mm], font, font_bold))

    story.append(Paragraph("세그먼트별 상승 키워드 (연령대 x 성별)", styles["KHeading"]))
    rows = [["세그먼트", "상위 상승 카테고리"]]
    for segment, categories in data.get("segment_trends", {}).items():
        top3 = categories[:3]
        summary = ", ".join(
            f"{c['category']}({'+' if c['rising_pct'] and c['rising_pct'] > 0 else ''}{c['rising_pct']}%)"
            if c["rising_pct"] is not None else f"{c['category']}(데이터부족)"
            for c in top3
        )
        rows.append([segment, Paragraph(summary, styles["KBody"])])
    story.append(_table(rows, [40 * mm, 130 * mm], font, font_bold))

    story.append(PageBreak())
    story.append(Paragraph("유튜브 인기 건강 콘텐츠 (최근 3일)", styles["KHeading"]))
    rows = [["제목", "채널", "조회수", "좋아요"]]
    for v in data.get("youtube_top", []):
        rows.append([
            Paragraph(f'<link href="{v["url"]}">{v["title"]}</link>', styles["KBody"]),
            v["channel"],
            f'{v["view_count"]:,}',
            f'{v["like_count"]:,}',
        ])
    story.append(_table(rows, [90 * mm, 40 * mm, 20 * mm, 20 * mm], font, font_bold))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        "※ 본 리포트는 검색 트렌드 기반의 참고 자료이며 의학적 진단이나 치료를 단정하는 내용이 아닙니다. "
        "포스팅 작성 시 의료광고법/약사법에 저촉되지 않도록 정보성 문구로 작성하세요.",
        styles["KNote"],
    ))

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    doc.build(story)
    return output_path


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        in_path, out_path = sys.argv[1], sys.argv[2]
        with open(in_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        result = generate_report(payload, out_path, input_path=in_path)
        print(f"생성됨: {result}")
    else:
        sample = {
            "report_date": "2026-07-25",
            "failed_sources": [],
            "posts": [
                {
                    "keyword": "오메가3",
                    "title": "오메가3 vs 유산균, 뭘 먼저 먹어야 할까",
                    "search_intent": "둘 다 챙겨 먹어야 한다는 건 아는데 뭐부터 시작할지, 같이 먹어도 되는지 궁금해서 검색",
                    "target_analysis": "건강기능식품에 관심 생긴 30대 여성. 아직 뭘 먼저 사야 할지 결정 못 한 입문 단계.",
                    "keyword_analysis": "'오메가3' 자체는 포화도 높지만(15만건), '오메가3 유산균 순서'처럼 비교형 롱테일은 상대적으로 경쟁이 낮음. 검색 관심도 30일간 +42% 상승.",
                    "reason": "검색 관심도 30일간 +42% 상승, 블로그 경쟁 낮음. 매일 다른 카테고리를 다루기 위한 로테이션 배정.",
                },
                {
                    "keyword": "번아웃증후군",
                    "title": "번아웃증후군, 남 일 아니었다 (직장인 자가진단+관리법)",
                    "search_intent": "본인 증상이 번아웃이 맞는지 확인하고, 당장 시도해볼 관리법을 찾는 실행형 검색",
                    "target_analysis": "야근·성과 압박이 큰 3040 직장인, 특히 관리자급. 병원 가기 전에 스스로 먼저 확인해보고 싶어함.",
                    "keyword_analysis": "'번아웃증후군' 블로그 경쟁도 보통, 최근 7일 상승률 +18.5%로 시의성 있음.",
                    "reason": "검색 관심도 최근 7일 평균이 이전 7일 대비 +18.5% 상승 (타겟: 40대 x 남성), 블로그 경쟁도 보통. 매일 다른 카테고리를 다루기 위한 로테이션 배정.",
                },
            ],
            "or_axes": ["마취·수술 약물", "외과(GS)·복강경 수술", "환자 질문형(수술받는 일반인이 수술실에 대해 궁금해하는 것)"],
            "or_topics": [
                {
                    "title": "수술 후 PONV, 마취과에서 미리 막는 약은 뭘까",
                    "keyword": "PONV",
                    "axis": "마취·수술 약물",
                    "source": "업무 지식 체크리스트 빈칸",
                    "source_detail": "I. 마취 협력·약물 — 악성고열증",
                    "target": "마취과 순환 간호사, 수술실 신규 간호사",
                    "outline": "PONV 위험요인 → 예방 약물 계열 → 수술실에서 간호사가 챙길 포인트",
                    "differentiation": "기존 근이완제·브레비블록 글과 겹치지 않는 구토 예방 축. 석시콜린 글 내부링크 후보.",
                },
            ],
            "segment_trends": {"30대 x 여성": [{"category": "영양제/보충제", "rising_pct": 42.3}]},
            "youtube_top": [{"title": "샘플 영상", "channel": "샘플 채널", "view_count": 123456, "like_count": 3456, "url": "https://youtube.com"}],
        }
        out = generate_report(sample, os.path.join(os.path.dirname(__file__), "..", ".tmp", "sample_report.pdf"))
        print(f"생성됨: {out}")
