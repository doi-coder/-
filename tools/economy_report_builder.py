"""경제 블로그용 하루 3회 리포트(국내장/실용정보/미국장)를 PDF로 조립한다.

report_builder.py(건강 리포트)와 같은 reportlab + 한글 폰트 임베딩 방식을 그대로 따른다.
다만 이 리포트는 고정 API 데이터가 아니라, 실행하는 에이전트가 그때그때 뉴스를 검색/해석해서
채운 JSON 데이터를 받아 PDF로 렌더링만 한다 (에이전트가 조사한 내용을 신뢰하고 그대로 조립).

data 형식은 파일 하단 `if __name__ == "__main__":` 샘플 참고.
사용법: python tools/economy_report_builder.py <입력 json 경로> <출력 pdf 경로>
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
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, HRFlowable,
)

BRAND_PRIMARY = colors.HexColor("#1F3C5C")
BRAND_ACCENT = colors.HexColor("#D98E28")
BRAND_TEXT = colors.HexColor("#222222")

ASSETS_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")

FONT_CANDIDATES = [
    (os.path.join(ASSETS_FONT_DIR, "NanumGothic-Regular.ttf"), os.path.join(ASSETS_FONT_DIR, "NanumGothic-Bold.ttf")),
    (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
]

# 리포트 종류별 제목/부제/면책문구. report_type 키는 워크플로우 문서와 반드시 맞춰야 함.
REPORT_META = {
    "domestic_market": {
        "title": "국내 증시 브리핑",
        "subtitle": "주린이를 위한 오늘의 국장 소식",
        "disclaimer": (
            "본 리포트는 정보 제공을 목적으로 작성되었으며, 특정 종목의 매수·매도를 권유하는 "
            "투자자문이 아닙니다. 시장 상황은 실시간으로 변하므로, 실제 투자 판단과 그 결과에 대한 "
            "책임은 전적으로 투자자 본인에게 있습니다."
        ),
    },
    "us_market": {
        "title": "미국 증시 브리핑",
        "subtitle": "주린이를 위한 오늘의 미장 소식",
        "disclaimer": (
            "본 리포트는 정보 제공을 목적으로 작성되었으며, 특정 종목의 매수·매도를 권유하는 "
            "투자자문이 아닙니다. 환율·시차로 인해 실제 개장 시점의 상황과 다를 수 있으니, "
            "최종 투자 판단과 그 결과에 대한 책임은 전적으로 투자자 본인에게 있습니다."
        ),
    },
    "practical_info": {
        "title": "오늘의 실용경제 정보",
        "subtitle": "직장인이 바로 써먹는 정책·혜택 브리핑",
        "disclaimer": (
            "본 리포트는 정보 제공을 목적으로 작성되었으며, 신청 조건·기한·금액 등은 변경될 수 "
            "있습니다. 실제 신청 전에는 반드시 해당 기관(정부24, 국세청, 금융사 등) 공식 채널에서 "
            "최신 내용을 다시 확인하세요."
        ),
    },
    "stock_deepdive": {
        "title": "종목 딥다이브 리포트",
        "subtitle": "이번 주 종목 하나, 제대로 파헤치기",
        "disclaimer": (
            "본 리포트는 정보 제공을 목적으로 작성되었으며, 특정 종목의 매수·매도를 권유하는 "
            "투자자문이 아닙니다. 밸류에이션·실적 수치는 발행 시점 기준 공개 자료를 참고한 것으로 "
            "실제와 다를 수 있으며, 최종 투자 판단과 그 결과에 대한 책임은 전적으로 투자자 본인에게 "
            "있습니다."
        ),
    },
}


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
    styles.add(ParagraphStyle("KTitle", fontName=font_bold, fontSize=22, textColor=BRAND_PRIMARY, spaceAfter=4))
    styles.add(ParagraphStyle("KSubtitle", fontName=font, fontSize=12, textColor=BRAND_TEXT, spaceAfter=4))
    styles.add(ParagraphStyle("KDate", fontName=font, fontSize=10, textColor=colors.grey, spaceAfter=16))
    styles.add(ParagraphStyle(
        "KHeadline", fontName=font_bold, fontSize=13, textColor=colors.white, backColor=BRAND_ACCENT,
        borderPadding=8, spaceAfter=16, leading=18,
    ))
    styles.add(ParagraphStyle("KHeading", fontName=font_bold, fontSize=14, textColor=BRAND_PRIMARY, spaceBefore=14, spaceAfter=6))
    styles.add(ParagraphStyle("KBody", fontName=font, fontSize=10.5, textColor=BRAND_TEXT, leading=16, spaceAfter=4))
    styles.add(ParagraphStyle("KSource", fontName=font, fontSize=9, textColor=colors.HexColor("#555555"), leading=13))
    styles.add(ParagraphStyle("KNote", fontName=font, fontSize=8, textColor=colors.grey, leading=11))
    return styles


def generate_report(data, output_path):
    """data 형식:
    {
      "report_type": "domestic_market" | "us_market" | "practical_info",
      "report_date": "2026-08-06",
      "slot_label": "아침 6시 브리핑",
      "headline": "오늘 한 줄 요약",
      "sections": [{"heading": str, "body": str}, ...],   # body 안 줄바꿈(\\n)은 문단 구분으로 처리
      "sources": ["기사 제목 (매체명) - URL", ...],
      "data_note": "실시간 웹 검색 기반이라 발행 이후 시황이 바뀔 수 있음" 같은 선택적 보충 설명(없으면 생략)
    }
    """
    report_type = data.get("report_type")
    if report_type not in REPORT_META:
        raise ValueError(f"알 수 없는 report_type: {report_type} (가능한 값: {list(REPORT_META)})")
    meta = REPORT_META[report_type]

    font, font_bold = _register_korean_font()
    styles = _build_styles(font, font_bold)
    story = []

    story.append(Paragraph(meta["title"], styles["KTitle"]))
    story.append(Paragraph(f"{meta['subtitle']} · {data.get('slot_label', '')}", styles["KSubtitle"]))
    story.append(Paragraph(data.get("report_date", ""), styles["KDate"]))

    if data.get("headline"):
        story.append(Paragraph(data["headline"], styles["KHeadline"]))

    for section in data.get("sections", []):
        story.append(Paragraph(section["heading"], styles["KHeading"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DDDDDD"), spaceAfter=6))
        for para in section.get("body", "").split("\n"):
            para = para.strip()
            if para:
                story.append(Paragraph(para, styles["KBody"]))

    titles = data.get("suggested_titles") or []
    if titles:
        story.append(Paragraph("네이버 블로그 제목 후보", styles["KHeading"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DDDDDD"), spaceAfter=6))
        if data.get("recommended_title"):
            story.append(Paragraph(
                f"★ 이번 회차 추천 제목: {data['recommended_title']}"
                f" (키워드: {data.get('recommended_keyword', '-')}) — 초안 별첨",
                styles["KBody"],
            ))
            if data.get("search_intent"):
                story.append(Paragraph(f"<b>검색 의도</b>: {data['search_intent']}", styles["KBody"]))
            if data.get("target_analysis"):
                story.append(Paragraph(f"<b>타겟 독자</b>: {data['target_analysis']}", styles["KBody"]))
            if data.get("keyword_analysis"):
                story.append(Paragraph(f"<b>키워드 분석</b>: {data['keyword_analysis']}", styles["KBody"]))
            story.append(Spacer(1, 4))
        story.append(ListFlowable(
            [ListItem(Paragraph(t, styles["KBody"])) for t in titles],
            bulletType="bullet", start="circle", leftIndent=12,
        ))

    sources = data.get("sources") or []
    if sources:
        story.append(Paragraph("참고 기사·출처", styles["KHeading"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DDDDDD"), spaceAfter=6))
        story.append(ListFlowable(
            [ListItem(Paragraph(s, styles["KSource"])) for s in sources],
            bulletType="bullet", start="circle", leftIndent=12,
        ))

    story.append(Spacer(1, 14))
    if data.get("data_note"):
        story.append(Paragraph(f"※ {data['data_note']}", styles["KNote"]))
    story.append(Paragraph(f"※ {meta['disclaimer']}", styles["KNote"]))

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
            "report_type": "domestic_market",
            "report_date": "2026-08-06",
            "slot_label": "아침 6시 브리핑",
            "headline": "반도체 업종 강세, 코스피 2주 만에 최고치 경신",
            "sections": [
                {
                    "heading": "오늘의 기업/시장 소식",
                    "body": "삼성전자·SK하이닉스가 반도체 업황 개선 기대감에 동반 상승했습니다.\n"
                            "간밤 미국 반도체 관련주 강세가 국내 증시에도 영향을 준 것으로 풀이됩니다.",
                },
                {
                    "heading": "주린이를 위한 해설",
                    "body": "'업황 개선 기대감'이란 실제 실적이 좋아진 게 아니라, 앞으로 좋아질 거라는 "
                            "전망이 반영됐다는 뜻이에요. 그래서 관련 뉴스가 나와도 주가가 먼저 움직이고, "
                            "실제 실적 발표는 나중에 따라오는 경우가 많습니다.",
                },
                {
                    "heading": "투자 방향 참고",
                    "body": "단기 뉴스에 따라 급하게 매수하기보다, 실적 발표 일정을 함께 확인하고 "
                            "분할로 접근하는 방법이 초보자에게는 상대적으로 안전합니다.",
                },
            ],
            "sources": ["삼성전자 반도체 훈풍 (매일경제) - https://example.com/news1"],
            "suggested_titles": ["반도체 훈풍 코스피, 주린이가 지금 봐야 할 것", "삼성전자 오른 진짜 이유 (초보자용 정리)"],
            "recommended_title": "반도체 훈풍 코스피, 주린이가 지금 봐야 할 것",
            "recommended_keyword": "반도체 훈풍 코스피",
            "search_intent": "오늘 코스피가 왜 올랐는지, 내 계좌에도 영향이 있는지 궁금해서 검색",
            "target_analysis": "국내 주식을 조금씩 하고 있는 3040 직장인 초보 투자자. 반도체 관련주를 들고 있거나 관심 있는 층.",
            "keyword_analysis": "'반도체 훈풍 코스피'는 오늘 뉴스와 직접 연결되면서도 블로그 경쟁이 아직 과열되지 않은 시의성 키워드.",
            "data_note": "이 리포트는 발행 시점 기준 웹 검색 결과를 요약한 것으로, 장중 상황과 다를 수 있습니다.",
        }
        out = generate_report(sample, os.path.join(os.path.dirname(__file__), "..", ".tmp", "sample_economy_report.pdf"))
        print(f"생성됨: {out}")
