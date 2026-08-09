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
        "KTitle", fontName=font_bold, fontSize=24, textColor=BRAND_PRIMARY, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "KSubtitle", fontName=font, fontSize=12, textColor=BRAND_TEXT, spaceAfter=20,
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


def generate_report(data, output_path, logo_path=None):
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
        }, ...
      ],
      "segment_trends": {"30대 x 여성": [{"category": str, "rising_pct": float|None}, ...], ...},
      "youtube_top": [{"title","channel","view_count","like_count","url"}, ...],
      "blog_saturation": [{"keyword": str, "total_count": int}, ...],
    }
    """
    font, font_bold = _register_korean_font()
    styles = _build_styles(font, font_bold)
    story = []

    if logo_path and os.path.exists(logo_path):
        story.append(Image(logo_path, width=30 * mm, height=30 * mm))
        story.append(Spacer(1, 10))

    story.append(Paragraph("건강 콘텐츠 트렌드 리포트", styles["KTitle"]))
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
        story.append(Paragraph(f"※ 데이터 근거: {post.get('reason', '-')}", styles["KNote"]))
        story.append(Paragraph("※ 전체 포스팅 초안은 별첨 텍스트 파일을 참고하세요.", styles["KNote"]))
        story.append(Spacer(1, 12))

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

    story.append(Paragraph("참고: 키워드별 블로그 포화도", styles["KHeading"]))
    rows = [["키워드", "전체 게시물 수(추정)"]]
    for item in data.get("blog_saturation", []):
        rows.append([item["keyword"], f'{item["total_count"]:,}'])
    story.append(_table(rows, [80 * mm, 90 * mm], font, font_bold))

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
        result = generate_report(payload, out_path)
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
            "segment_trends": {"30대 x 여성": [{"category": "영양제/보충제", "rising_pct": 42.3}]},
            "youtube_top": [{"title": "샘플 영상", "channel": "샘플 채널", "view_count": 123456, "like_count": 3456, "url": "https://youtube.com"}],
            "blog_saturation": [{"keyword": "오메가3", "total_count": 152000}],
        }
        out = generate_report(sample, os.path.join(os.path.dirname(__file__), "..", ".tmp", "sample_report.pdf"))
        print(f"생성됨: {out}")
