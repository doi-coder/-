"""분석 결과를 브랜드 PDF 리포트로 만든다 (reportlab, 한글 폰트 임베딩).

브랜드 컬러/로고는 지정된 게 없어서 기본값을 넣어뒀음.
나중에 사장님이 로고 파일/브랜드 컬러를 주면 BRAND_* 상수와 logo_path만 바꾸면 됨.
"""
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
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
      "recommended_topics": [
        {"topic": str, "segment": str, "reason": str}, ...
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

    story.append(Paragraph("오늘의 추천 포스팅 주제", styles["KHeading"]))
    rows = [["순위", "주제", "타겟", "추천 이유"]]
    for i, topic in enumerate(data.get("recommended_topics", []), start=1):
        rows.append([
            str(i),
            Paragraph(topic["topic"], styles["KBody"]),
            topic["segment"],
            Paragraph(topic["reason"], styles["KBody"]),
        ])
    story.append(_table(rows, [15 * mm, 55 * mm, 30 * mm, 70 * mm], font, font_bold))

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
    sample = {
        "report_date": "2026-07-25",
        "failed_sources": [],
        "recommended_topics": [
            {"topic": "오메가3 vs 유산균, 뭘 먼저 먹어야 할까", "segment": "30대 x 여성", "reason": "검색 관심도 30일간 +42% 상승, 블로그 경쟁 낮음"},
        ],
        "segment_trends": {"30대 x 여성": [{"category": "영양제/보충제", "rising_pct": 42.3}]},
        "youtube_top": [{"title": "샘플 영상", "channel": "샘플 채널", "view_count": 123456, "like_count": 3456, "url": "https://youtube.com"}],
        "blog_saturation": [{"keyword": "오메가3", "total_count": 152000}],
    }
    out = generate_report(sample, os.path.join(os.path.dirname(__file__), "..", ".tmp", "sample_report.pdf"))
    print(f"생성됨: {out}")
