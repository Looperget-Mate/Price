# -*- coding: utf-8 -*-
"""
농업 제안서 오버레이 유틸  (2026-08-24 · B안)
=============================================
설계 좌표(미터) → PPT 네이티브 도형. 정본(논산·영광)의 오버레이 문법을 따른다:
배관 = 노랑 선 · 살수원 = 파랑 반투명 · 치수/강조 = 빨강 · 라벨 = 흰 원 + 검정.
전부 PPT 도형이므로 대표가 PPT에서 직접 미세조정할 수 있다(정본과 같은 편집성).

사용: 지면마다 MapFrame(슬라이드 배치 사각 + 미터 좌표 범위)을 만들고
pipe()/spray()/head_dot()/badge()/dim()/note()를 호출한다.
"""
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn

# ── 정본 오버레이 팔레트 ──
PIPE_MAIN = RGBColor(0xE6, 0xB4, 0x00)   # 주관 — 진한 옐로우(정본 노랑 선)
PIPE_SUB = RGBColor(0xF4, 0xD6, 0x24)    # 지관 — 브랜드 옐로우
SPRAY = RGBColor(0x0A, 0x84, 0xFF)       # 살수원 — 물빛 파랑(2026-08-26 대표 교정:
                                         # 기존 #4472C4는 위성의 회녹색과 붙어 잘 안 보였다)
DIM = RGBColor(0xE0, 0x28, 0x28)         # 치수·강조 — 빨강
INK = RGBColor(0x19, 0x14, 0x14)         # 검정(브랜드)
GREY = RGBColor(0x76, 0x76, 0x76)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRN = RGBColor(0x2E, 0x8A, 0x4C)
FONT = "맑은 고딕"


class MapFrame:
    """슬라이드의 (left,top,w,h) 인치 사각에 미터 영역 (x0,y0)~(x1,y1)을 사상.
    종횡비 유지(중앙 정렬). y는 아래로 증가."""

    def __init__(self, left_in, top_in, w_in, h_in, x0, y0, x1, y1):
        sx = w_in / (x1 - x0)
        sy = h_in / (y1 - y0)
        self.s = min(sx, sy)                       # in/m
        self.ox = left_in + (w_in - (x1 - x0) * self.s) / 2 - x0 * self.s
        self.oy = top_in + (h_in - (y1 - y0) * self.s) / 2 - y0 * self.s

    def xy(self, xm, ym):
        return Inches(self.ox + xm * self.s), Inches(self.oy + ym * self.s)

    def d(self, m):
        return Inches(m * self.s)


def _fill_alpha(shape, pct_opaque):
    """solidFill에 알파(불투명 %) 주입 — python-pptx 미지원 영역이라 XML로."""
    sf = shape._element.spPr.find(qn("a:solidFill"))
    clr = sf.find(qn("a:srgbClr"))
    clr.append(clr.makeelement(qn("a:alpha"),
                               {"val": str(int(pct_opaque * 1000))}))


def pipe(slide, fr, pts, color=PIPE_MAIN, weight=5.0, dash=None):
    """폴리라인 배관 — 세그먼트별 직선 커넥터."""
    out = []
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        x1, y1 = fr.xy(xa, ya)
        x2, y2 = fr.xy(xb, yb)
        cn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x1, y1, x2, y2)
        cn.line.color.rgb = color
        cn.line.width = Pt(weight)
        if dash:
            cn.line.dash_style = dash
        cn.shadow.inherit = False
        out.append(cn)
    return out


def spray(slide, fr, xm, ym, r_m, color=SPRAY, opaque=20, line_opaque=75, line_w=1.0):
    """살수원 — 반투명 파랑 원(정본 문법)."""
    x, y = fr.xy(xm - r_m, ym - r_m)
    sp = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, fr.d(2 * r_m), fr.d(2 * r_m))
    sp.fill.solid()
    sp.fill.fore_color.rgb = color
    _fill_alpha(sp, opaque)
    sp.line.color.rgb = color
    sp.line.width = Pt(line_w)
    ln = sp.line._get_or_add_ln().find(qn("a:solidFill"))
    ln.find(qn("a:srgbClr")).append(
        ln.makeelement(qn("a:alpha"), {"val": str(line_opaque * 1000)}))
    sp.shadow.inherit = False
    return sp


def head_dot(slide, fr, xm, ym, r_in=0.055, color=INK):
    """스프링클러 헤드 점 — 흰 원 + 검정 테두리."""
    x, y = fr.xy(xm, ym)
    sp = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(x - Inches(r_in))),
                                Emu(int(y - Inches(r_in))),
                                Inches(2 * r_in), Inches(2 * r_in))
    sp.fill.solid()
    sp.fill.fore_color.rgb = WHITE
    sp.line.color.rgb = color
    sp.line.width = Pt(1.6)
    sp.shadow.inherit = False
    return sp


def box(slide, fr, x0, y0, x1, y1, fill=None, line=INK, weight=1.5,
        text="", size=11, bold=True, font_color=None, dash=None, opaque=None):
    """미터 좌표 사각(탱크·펌프·필드 외곽 등). fill=None이면 투명."""
    xa, ya = fr.xy(x0, y0)
    sp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, xa, ya,
                                fr.d(x1 - x0), fr.d(y1 - y0))
    sp.adjustments[0] = 0.12
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
        if opaque is not None:
            _fill_alpha(sp, opaque)
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(weight)
        if dash:
            sp.line.dash_style = dash
    sp.shadow.inherit = False
    if text:
        tf = sp.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Pt(2)
        tf.margin_top = tf.margin_bottom = Pt(1)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = text
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = font_color if font_color else (line or INK)
    return sp


def badge(slide, fr, xm, ym, char, r_in=0.16, fill=WHITE, line=INK, size=13):
    """정본 a/b/c 스타일 원형 라벨."""
    x, y = fr.xy(xm, ym)
    sp = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(x - Inches(r_in))),
                                Emu(int(y - Inches(r_in))),
                                Inches(2 * r_in), Inches(2 * r_in))
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    sp.line.color.rgb = line
    sp.line.width = Pt(1.75)
    sp.shadow.inherit = False
    tf = sp.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = char
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = line
    return sp


def dim(slide, fr, x0, y0, x1, y1, text, offset=0.0, size=10):
    """치수선(빨강, 양끝 화살표) + 값 라벨 — 정본 구역면 문법."""
    horizontal = abs(y1 - y0) < 1e-9
    if horizontal:
        y0 = y1 = y0 + offset
    else:
        x0 = x1 = x0 + offset
    xa, ya = fr.xy(x0, y0)
    xb, yb = fr.xy(x1, y1)
    cn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, xa, ya, xb, yb)
    cn.line.color.rgb = DIM
    cn.line.width = Pt(1.5)
    cn.shadow.inherit = False
    ln = cn.line._get_or_add_ln()
    for tag in ("a:headEnd", "a:tailEnd"):
        ln.append(ln.makeelement(qn(tag), {"type": "triangle", "w": "med", "len": "med"}))
    w_in, h_in = 0.9, 0.28
    cx = (fr.ox + ((x0 + x1) / 2) * fr.s) - w_in / 2
    cy = (fr.oy + ((y0 + y1) / 2) * fr.s) - h_in / 2
    tb = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(cx), Inches(cy),
                                Inches(w_in), Inches(h_in))
    tb.fill.solid()
    tb.fill.fore_color.rgb = DIM
    tb.line.fill.background()
    tb.shadow.inherit = False
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = WHITE
    return cn


def note(slide, left_in, top_in, w_in, lines, size=12, title=None,
         title_color=None, border=GREY):
    """설명 상자(인치 좌표) — lines는 문자열 리스트."""
    tb = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left_in),
                                Inches(top_in), Inches(w_in),
                                Inches(0.34 + 0.26 * (len(lines) + (1 if title else 0))))
    tb.adjustments[0] = 0.06
    tb.fill.solid()
    tb.fill.fore_color.rgb = WHITE
    tb.line.color.rgb = border
    tb.line.width = Pt(1.25)
    tb.shadow.inherit = False
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Pt(8)
    tf.margin_top = tf.margin_bottom = Pt(5)
    first = True
    if title:
        p = tf.paragraphs[0]
        first = False
        r = p.add_run()
        r.text = title
        r.font.name = FONT
        r.font.size = Pt(size + 1)
        r.font.bold = True
        r.font.color.rgb = title_color if title_color else INK
    for s in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        r = p.add_run()
        r.text = s
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.color.rgb = INK
    return tb


# ══════════════ 2026-08-25 추가 — 대표 교정 반영 (익산 정본 문법) ══════════════

ORANGE = RGBColor(0xE8, 0x6A, 0x1A)      # 구역 외곽 점선 (대표 교정본 톤)
BADGE_GREY = RGBColor(0x59, 0x59, 0x59)  # 정본 a/b/c 라벨 — 회색 원 + 흰 글자


def dim_white(slide, fr, x0, y0, x1, y1, text, size=10):
    """익산 정본식 간격 표시 — 흰 양방향 화살선 + 흰 바탕 검정 숫자(단위 없음)."""
    xa, ya = fr.xy(x0, y0)
    xb, yb = fr.xy(x1, y1)
    cn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, xa, ya, xb, yb)
    cn.line.color.rgb = WHITE
    cn.line.width = Pt(1.75)
    cn.shadow.inherit = False
    ln = cn.line._get_or_add_ln()
    for tag in ("a:headEnd", "a:tailEnd"):
        ln.append(ln.makeelement(qn(tag), {"type": "triangle", "w": "med", "len": "med"}))
    w_in, h_in = 0.34, 0.22
    cx = (fr.ox + ((x0 + x1) / 2) * fr.s) - w_in / 2
    cy = (fr.oy + ((y0 + y1) / 2) * fr.s) - h_in / 2
    tb = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(cx), Inches(cy),
                                Inches(w_in), Inches(h_in))
    tb.fill.solid()
    tb.fill.fore_color.rgb = WHITE
    tb.line.fill.background()
    tb.shadow.inherit = False
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = INK
    return cn


def spray_double(slide, fr, xm, ym, r_out=10.0, r_in=7.0, color=SPRAY,
                 opaque=19, line_opaque=78):
    """임팩트 스프링클러 살수원 — 바깥(조절 반경) 채움 + 안쪽(귀환 살수 7 m 고정) 점선.
    2026-08-26 대표 교정: 살수원이 대상지 색과 붙어 안 보인다 → 물빛 파랑으로 올리고
    테두리를 진하게 해 원 하나하나가 또렷하게 읽히도록 했다(겹침부가 뭉개지지 않게 채움은 절제)."""
    outer = spray(slide, fr, xm, ym, r_out, color=color, opaque=opaque, line_opaque=line_opaque)
    x, y = fr.xy(xm - r_in, ym - r_in)
    inner = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, fr.d(2 * r_in), fr.d(2 * r_in))
    inner.fill.background()
    inner.line.color.rgb = RGBColor(0x00, 0x33, 0x7A)
    inner.line.width = Pt(1.0)
    from pptx.enum.dml import MSO_LINE_DASH_STYLE
    inner.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    inner.shadow.inherit = False
    return outer, inner


def badge_grey(slide, fr, xm, ym, char, r_in=0.16, size=13):
    """정본(논산·익산·대표 교정본) a/b/c 라벨 — 회색 원 + 흰 글자."""
    x, y = fr.xy(xm, ym)
    sp = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(x - Inches(r_in))),
                                Emu(int(y - Inches(r_in))), Inches(2 * r_in), Inches(2 * r_in))
    sp.fill.solid()
    sp.fill.fore_color.rgb = BADGE_GREY
    sp.line.fill.background()
    sp.shadow.inherit = False
    tf = sp.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = char
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = WHITE
    return sp


def caption(slide, left_in, top_in, w_in, title, lines, title_size=20, size=14,
            title_color=None):
    """박스 없는 우측 캡션 — 정본 상호확인면 톤(▷ 불릿, 큰 글씨). 시인성 우선."""
    tb = slide.shapes.add_textbox(Inches(left_in), Inches(top_in), Inches(w_in),
                                  Inches(0.5 + 0.38 * len(lines)))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = title
    r.font.name = FONT
    r.font.size = Pt(title_size)
    r.font.bold = True
    r.font.color.rgb = title_color if title_color else INK
    p.space_after = Pt(8)
    for s in lines:
        p = tf.add_paragraph()
        r = p.add_run()
        r.text = "▷ " + s
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.color.rgb = INK
        p.space_after = Pt(4)
    return tb


def leader(slide, fr, target_m, label_m, char, r_in=0.16, size=13):
    """대표 교정본식 지시 라벨 — 회색 원 라벨 + 빨간 지시선 + 대상점 빨간 점 + 주황 점선 원."""
    from pptx.enum.dml import MSO_LINE_DASH_STYLE
    tx, ty = fr.xy(*target_m)
    lx, ly = fr.xy(*label_m)
    cn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, lx, ly, tx, ty)
    cn.line.color.rgb = DIM
    cn.line.width = Pt(1.25)
    cn.shadow.inherit = False
    ring_r = 0.13
    ring = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(tx - Inches(ring_r))),
                                  Emu(int(ty - Inches(ring_r))), Inches(2 * ring_r), Inches(2 * ring_r))
    ring.fill.background()
    ring.line.color.rgb = ORANGE
    ring.line.width = Pt(1.25)
    ring.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    ring.shadow.inherit = False
    dot_r = 0.045
    dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(tx - Inches(dot_r))),
                                 Emu(int(ty - Inches(dot_r))), Inches(2 * dot_r), Inches(2 * dot_r))
    dot.fill.solid()
    dot.fill.fore_color.rgb = DIM
    dot.line.fill.background()
    dot.shadow.inherit = False
    return badge_grey(slide, fr, label_m[0], label_m[1], char, r_in=r_in, size=size)


# ══════ 2026-08-26 추가 — 대표 교정본(482-42) 반영 ══════
# 지시: "간격 표시를 더 상세하게 · 중간중간 · 시작점 간격과 그 이후 간격들 ·
#        간격표시 위에 텍스트가 올라가면 안 된다"
# → 치수 텍스트를 치수선 midpoint에 얹지 않고 **치수선 옆(법선 방향)** 으로 비켜 놓는다.

def dim_side(slide, fr, p0, p1, text, off_m=0.0, side=1, size=9.5,
             line=WHITE, ink=INK, weight=1.75, ext=True, serif_m=1.2):
    """치수선 — 흰 양방향 화살선 + 옆에 놓인 흰 바탕 검정 숫자.

    p0,p1  : 재는 두 점(미터)
    off_m  : 대상선에서 직각으로 띄우는 거리(m). 띄우면 양끝에 인출선을 그린다.
    side   : 라벨을 놓을 쪽(+1 = 진행방향 왼쪽 법선, -1 = 오른쪽)
    serif_m: 치수선 양끝의 직각 짧은 획(m). 0이면 생략.
    글자는 치수선 위에 절대 겹치지 않는다(법선 방향으로 밀어 놓는다).
    """
    import math as _m
    (x0, y0), (x1, y1) = p0, p1
    dx, dy = x1 - x0, y1 - y0
    L = _m.hypot(dx, dy)
    if L < 1e-9:
        return None
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux                                   # 왼쪽 법선
    ax, ay = x0 + nx * off_m, y0 + ny * off_m
    bx, by = x1 + nx * off_m, y1 + ny * off_m

    def _seg(pa, pb, w, arrows=()):
        cn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                        *fr.xy(*pa), *fr.xy(*pb))
        cn.line.color.rgb = line
        cn.line.width = Pt(w)
        cn.shadow.inherit = False
        if arrows:
            ln = cn.line._get_or_add_ln()
            for tag in arrows:
                ln.append(ln.makeelement(qn(tag),
                                         {"type": "triangle", "w": "med", "len": "med"}))
        return cn

    if abs(off_m) > 1e-6 and ext:                      # 인출선(대상 → 치수선)
        _seg((x0, y0), (ax, ay), 0.75)
        _seg((x1, y1), (bx, by), 0.75)
    if serif_m:                                        # 양끝 직각 짧은 획
        for (px, py) in ((ax, ay), (bx, by)):
            _seg((px - nx * serif_m / 2, py - ny * serif_m / 2),
                 (px + nx * serif_m / 2, py + ny * serif_m / 2), 1.0)
    _seg((ax, ay), (bx, by), weight, arrows=("a:headEnd", "a:tailEnd"))

    # 라벨 — 치수선 옆으로 비켜 놓는다
    w_in = max(0.28, 0.095 + 0.085 * len(text))
    h_in = 0.19 + 0.010 * (size - 9.5)
    push = abs(nx) * w_in / 2 + abs(ny) * h_in / 2 + 0.055   # 인치
    mxi = fr.ox + ((ax + bx) / 2) * fr.s + nx * side * push
    myi = fr.oy + ((ay + by) / 2) * fr.s + ny * side * push
    tb = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                Inches(mxi - w_in / 2), Inches(myi - h_in / 2),
                                Inches(w_in), Inches(h_in))
    tb.adjustments[0] = 0.22
    tb.fill.solid()
    tb.fill.fore_color.rgb = WHITE
    tb.line.fill.background()
    tb.shadow.inherit = False
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = ink
    return tb


def dim_chain(slide, fr, pts, texts, off_m=2.6, side=1, size=9.5, **kw):
    """연속 치수 — 시작점 간격과 그 이후 간격들을 한 줄로 잇는다(대표 지시)."""
    out = []
    for i in range(len(pts) - 1):
        out.append(dim_side(slide, fr, pts[i], pts[i + 1], texts[i],
                            off_m=off_m, side=side, size=size, **kw))
    return out


def panel(slide, left_in, top_in, w_in, h_in, fill=RGBColor(0xFA, 0xFA, 0xFA),
          border=RGBColor(0xC4, 0xC4, 0xC4), weight=1.25, radius=0.035, opaque=None):
    """부품 묶음(세트) 테두리 상자 — 상세면에서 '이 묶음이 한 세트'임을 보인다."""
    sp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left_in),
                                Inches(top_in), Inches(w_in), Inches(h_in))
    sp.adjustments[0] = radius
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
        if opaque is not None:
            _fill_alpha(sp, opaque)
    sp.line.color.rgb = border
    sp.line.width = Pt(weight)
    sp.shadow.inherit = False
    sp._element.getparent().remove(sp._element)          # 사진 뒤로 보낸다
    slide.shapes._spTree.insert(2, sp._element)
    return sp


def chip(slide, left_in, top_in, char, title, code, w_in=2.6,
         size=13.5, code_size=10.5, badge_r=0.155):
    """세트 머리표 — 회색 원 라벨(a/b/c) + 굵은 이름 + 회색 코드 한 줄."""
    cy = top_in + badge_r
    sp = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                Inches(left_in), Inches(top_in),
                                Inches(2 * badge_r), Inches(2 * badge_r))
    sp.fill.solid()
    sp.fill.fore_color.rgb = BADGE_GREY
    sp.line.fill.background()
    sp.shadow.inherit = False
    tf = sp.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = char
    r.font.name = FONT
    r.font.size = Pt(12)
    r.font.bold = True
    r.font.color.rgb = WHITE

    tx = left_in + 2 * badge_r + 0.10
    tb = slide.shapes.add_textbox(Inches(tx), Inches(top_in - 0.075),
                                  Inches(w_in), Inches(0.56))
    tfr = tb.text_frame
    tfr.word_wrap = True
    for i, (txt, sz, col, bold) in enumerate([(title, size, INK, True),
                                              (code, code_size, GREY, True)]):
        p = tfr.paragraphs[0] if i == 0 else tfr.add_paragraph()
        p.space_after = Pt(0)
        rr = p.add_run()
        rr.text = txt
        rr.font.name = FONT
        rr.font.size = Pt(sz)
        rr.font.bold = bold
        rr.font.color.rgb = col
    return sp, tb
