# -*- coding: utf-8 -*-
"""제안서 디자인 정본 — python-pptx 구현 (농업 PPTX 생성기용)
=================================================================
정본 문서 : `_디자인정본/제안서디자인정본_v1.md`
규격 근거 : 마스터 PPT `상월면 상도리 V4.pptx` p7(카드)·p11(칩) 실측.
`표준.py`(PIL)와 **같은 이름·같은 규격**이다. 매체만 다르다.

쓰는 법
    import sys
    sys.path.insert(0, r"...\Looperget-Work\_디자인정본")
    import 표준_pptx as DS

    DS.chip(slide, 5.114, 5.196, "루퍼젯H25", "25mm 암나사", png)
    x, y, w, h = DS.card(slide, 0.683, 4.335, 3.279)
    DS.badge(slide, x + DS.BADGE.IN, y + DS.BADGE.IN, "a")

⛔ 부속을 흰 바닥에 그냥 놓지 않는다. 부속 소개 자리는 전부 chip() 또는 card() 안이다.
"""
import os
import copy
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from PIL import Image

# ══════════════════════════════════════════════════════════════════════
# 1. 색 — 정본 §2
# ══════════════════════════════════════════════════════════════════════
_rgb = lambda s: RGBColor.from_string(s.lstrip("#"))


class C:
    YELLOW    = _rgb("#F3DC18")   # 브랜드 옐로 정본 (#218)
    INK       = _rgb("#231815")
    NAVY      = _rgb("#0C3B81")
    NAVY900   = _rgb("#062557")
    NAVY300   = _rgb("#B0C4DC")
    INK700    = _rgb("#3A3D44")
    INK500    = _rgb("#6E7280")
    WHITE     = _rgb("#FFFFFF")
    CARD_LINE = _rgb("#DCDAD2")
    BURIED    = _rgb("#9A9A9A")


# ══════════════════════════════════════════════════════════════════════
# 2. 서체 — 정본 §3.  ⚠ 수치·규격·품목코드는 MONO. 예외 없음.
# ══════════════════════════════════════════════════════════════════════
class T:
    TITLE   = "Pretendard ExtraBold"
    HEAD    = "Pretendard Bold"
    BODY    = "Pretendard Regular"
    CAPTION = "Pretendard Medium"
    LIGHT   = "Pretendard Light"
    MONO    = "JetBrains Mono"
    LATIN   = "Chakra Petch"


# ══════════════════════════════════════════════════════════════════════
# 3. 그리드 · 컴포넌트 규격 — 정본 §4·§5 (실측)
# ══════════════════════════════════════════════════════════════════════
SLIDE_W, SLIDE_H = 13.333, 7.5


class G:
    MARGIN_L    = 0.584
    MARGIN_R    = 0.600
    TITLE_XY    = (0.584, 0.629)
    TITLE_H     = 0.505
    BODY_TOP    = 1.134
    ROW1_Y      = 1.135
    ROW2_Y      = 4.340
    SAFE_BOTTOM = 7.100
    LOGO_XY     = (0.580, 6.550)


class CHIP:
    FRAME_W, FRAME_H = 0.898, 0.881
    BORDER_PT        = 2.0
    PAD              = 0.018
    NAME_W, NAME_H   = 0.907, 0.498
    GAP_BELOW        = 0.125
    GAP_ABOVE        = 0.040
    PITCH_MIN        = 0.970
    PITCH_MAX        = 1.120


class CARD:
    H            = 2.362
    LINE_PT      = 1.0
    SHADOW_DY_PT = 4
    SHADOW_BLUR  = 8
    SHADOW_ALPHA = 0.12


class BADGE:
    D  = 0.30
    IN = 0.12


class HOSE:
    MAIN_PT   = 3.0
    BRANCH_PT = 1.5
    BURIED_PT = 1.5


# ══════════════════════════════════════════════════════════════════════
# 4. 그림자 — 정본 §5-2.  🔴 카드 그림자를 끄지 않는다.
# ══════════════════════════════════════════════════════════════════════
_SHADOW_XML = (
    '<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    '<a:outerShdw blurRad="{blur}" dist="{dist}" dir="5400000" rotWithShape="0">'
    '<a:srgbClr val="000000"><a:alpha val="{alpha}"/></a:srgbClr>'
    '</a:outerShdw></a:effectLst>')


def shadow_on(shape, blur_pt=CARD.SHADOW_BLUR, dist_pt=CARD.SHADOW_DY_PT,
              alpha=CARD.SHADOW_ALPHA):
    """도형에 그림자를 켠다.

    python-pptx 의 `shape.shadow` 는 상속 해제만 가능해서 실제 그림자를 못 켠다.
    현행 생성기가 `shadow.inherit = False` 로 그림자를 **꺼 놓은** 것이
    「카드가 카드로 안 읽히는」 원인이었다(2026-08-29 실측). 여기서 XML로 켠다."""
    from lxml import etree
    spPr = shape._element.spPr
    for tag in ("a:effectLst",):
        old = spPr.find(qn(tag))
        if old is not None:
            spPr.remove(old)
    spPr.append(etree.fromstring(_SHADOW_XML.format(
        blur=int(blur_pt * 12700), dist=int(dist_pt * 12700), alpha=int(alpha * 100000))))
    return shape


# ══════════════════════════════════════════════════════════════════════
# 5. 프리미티브
# ══════════════════════════════════════════════════════════════════════
def text(slide, x, y, s, size=11, font=T.CAPTION, color=C.INK, w=3.0, h=0.28,
         bold=False, align=PP_ALIGN.LEFT, wrap=True):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, line in enumerate(str(s).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.name = font
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
    return tb


def _rect(slide, shp, x, y, w, h, fill=None, line=None, line_pt=1.0):
    s = slide.shapes.add_shape(shp, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(line_pt)
    s.shadow.inherit = False
    return s


# ══════════════════════════════════════════════════════════════════════
# 6. 컴포넌트 — 정본 §5
# ══════════════════════════════════════════════════════════════════════
def chip(slide, x, y, name, spec="", png=None, color=None, name_below=True):
    """칩 — 부속 1점 + 이름표 (정본 §5-1, 마스터 p11 실측).

    부속을 소개하는 자리는 **전부 이 칩을 쓴다.**
    반환 = (w, h) 인치 — 다음 칩은 x + PITCH 로 놓는다."""
    col = color or C.YELLOW
    fy = y + (0 if name_below else CHIP.NAME_H + CHIP.GAP_ABOVE)
    ny = (fy + CHIP.FRAME_H + CHIP.GAP_BELOW) if name_below else y

    _rect(slide, MSO_SHAPE.RECTANGLE, x, fy, CHIP.FRAME_W, CHIP.FRAME_H,
          fill=C.WHITE, line=col, line_pt=CHIP.BORDER_PT)

    if png and os.path.exists(png):
        iw, ih = Image.open(png).size
        bw, bh = CHIP.FRAME_W - CHIP.PAD * 2, CHIP.FRAME_H - CHIP.PAD * 2
        sc = min(bw / (iw / 96.0), bh / (ih / 96.0)) if iw and ih else 1.0
        pw, ph = (iw / 96.0) * sc, (ih / 96.0) * sc
        slide.shapes.add_picture(png, Inches(x + (CHIP.FRAME_W - pw) / 2),
                                 Inches(fy + (CHIP.FRAME_H - ph) / 2), Inches(pw))

    _rect(slide, MSO_SHAPE.RECTANGLE, x, ny, CHIP.NAME_W, CHIP.NAME_H, fill=col)
    text(slide, x + 0.05, ny + 0.06, name, size=9.5, font=T.CAPTION,
         color=C.INK, w=CHIP.NAME_W - 0.08, h=0.20)
    if spec:
        text(slide, x + 0.05, ny + 0.26, spec, size=8.5, font=T.MONO,
             color=C.INK, w=CHIP.NAME_W - 0.08, h=0.20)
    return max(CHIP.FRAME_W, CHIP.NAME_W), CHIP.FRAME_H + CHIP.GAP_BELOW + CHIP.NAME_H


def chip_row(slide, x0, y, items, pitch=None, name_below=True):
    """칩 여러 개를 **같은 피치**로 한 행에 세운다 (정본 §5-1).
    items = [(name, spec, png), …]"""
    p = pitch or CHIP.PITCH_MIN
    if not (CHIP.PITCH_MIN <= p <= CHIP.PITCH_MAX):
        raise ValueError("칩 피치는 %.2f~%.2f in (정본 §5-1). 받은 값 %.2f"
                         % (CHIP.PITCH_MIN, CHIP.PITCH_MAX, p))
    for i, (nm, sp, png) in enumerate(items):
        chip(slide, x0 + i * p, y, nm, sp, png, name_below=name_below)
    return x0 + len(items) * p


def card(slide, x, y, w, h=None, caption=None, setname=None):
    """카드 — 조립 상태 1개를 담는 그릇 (정본 §5-2, 마스터 p7 실측).
    높이는 한 행 안에서 CARD.H 로 통일한다. 🔴 그림자는 켠다."""
    h = CARD.H if h is None else h
    s = _rect(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h,
              fill=C.WHITE, line=C.CARD_LINE, line_pt=CARD.LINE_PT)
    shadow_on(s)
    if setname:
        text(slide, x + 0.22, y + 0.10, "세트  %s" % setname, size=9.5,
             font=T.CAPTION, color=C.INK500, w=w - 0.44, h=0.20)
    if caption:
        text(slide, x + 0.22, y + h - 0.56, caption, size=9.5, font=T.CAPTION,
             color=C.INK, w=w - 0.44, h=0.46)
    return x, y, w, h


def badge(slide, x, y, ch, fill=None):
    """뱃지 — 조립 순서 기호 a·b·c (정본 §5-3)."""
    s = _rect(slide, MSO_SHAPE.OVAL, x, y, BADGE.D, BADGE.D, fill=fill or C.INK)
    tf = s.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = ch
    r.font.name = T.HEAD
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.color.rgb = C.WHITE
    return s


def hose(slide, x, y, length, kind="main", vertical=False):
    """배관 (정본 §5-4). kind = main | branch | buried.
    주배관이 가지관보다 항상 굵다(설계 규칙 4).
    ⛔ 검정 채움 사각으로 관을 그리지 않는다 — 먹칠로 읽힌다."""
    thick = {"main": 0.20, "branch": 0.10, "buried": 0.10}[kind]
    col = C.BURIED if kind == "buried" else C.YELLOW
    w, h = (thick, length) if vertical else (length, thick)
    s = _rect(slide, MSO_SHAPE.RECTANGLE, x, y, w, h, fill=col)
    if kind == "buried":
        s.fill.solid()
        s.fill.fore_color.rgb = C.BURIED
    return s


def leader(slide, x1, y1, x2, y2, color=None):
    """리더선 (정본 §5-1). ⛔ 사선 금지 — 수직·수평만."""
    if abs(x1 - x2) > 1e-6 and abs(y1 - y2) > 1e-6:
        raise ValueError("리더선은 수직·수평만 (정본 §5-1). 꺾으려면 두 번 부른다.")
    from pptx.enum.shapes import MSO_CONNECTOR
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1),
                                   Inches(x2), Inches(y2))
    c.line.color.rgb = color or C.YELLOW
    c.line.width = Pt(1.5)
    return c


def title(slide, s, sub=None):
    """지면 제목 — 위치 고정 (정본 §4, 마스터 전 지면 실측)."""
    x, y = G.TITLE_XY
    tb = text(slide, x, y, s, size=24, font=T.TITLE, color=C.INK,
              w=SLIDE_W - x - G.MARGIN_R, h=G.TITLE_H, bold=True)
    if sub:
        text(slide, x, y + G.TITLE_H - 0.06, sub, size=11, font=T.BODY,
             color=C.INK500, w=SLIDE_W - x - G.MARGIN_R, h=0.26)
    return tb


# ══════════════════════════════════════════════════════════════════════
# 7. 지면 점검 — 정본 §9 (reviewer 6항목 중 기계로 잡히는 것)
# ══════════════════════════════════════════════════════════════════════
def check_slide(slide, idx=None):
    """돌려주는 것 = 위반 목록. 빈 리스트면 통과."""
    bad = []
    EMU_IN = 914400.0
    used = 0.0
    for sh in slide.shapes:
        if sh.width and sh.height:
            used += (sh.width / EMU_IN) * (sh.height / EMU_IN)
        # 팔레트 밖 채움
        try:
            if sh.fill.type == 1:
                v = str(sh.fill.fore_color.rgb).upper()
                if v == "000000":
                    bad.append("검정 채움 도형 — 먹칠로 읽힌다 (정본 §2-4)")
        except Exception:
            pass
        # 세로쓰기
        try:
            bodyPr = sh.text_frame._txBody.find(qn('a:bodyPr'))
            if bodyPr is not None and bodyPr.get('vert') not in (None, 'horz'):
                bad.append("세로쓰기 텍스트 (정본 §3-1)")
        except Exception:
            pass
        # 안전선 이탈
        if sh.top is not None and sh.height is not None:
            if (sh.top + sh.height) / EMU_IN > G.SAFE_BOTTOM + 0.05:
                bad.append("하단 안전선 이탈: %s" % (sh.name or "?"))
    if used < SLIDE_W * SLIDE_H * 0.45:
        bad.append("빈 지면 — 요소가 지면의 45% 미만 (정본 §4)")
    return sorted(set(bad))
