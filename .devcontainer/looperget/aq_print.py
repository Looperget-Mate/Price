# -*- coding: utf-8 -*-
"""루퍼젯 프로 매니저 — 아쿠나리스 인쇄물 엔진 (스티커 · 가이드북 · 배치도 PDF)

[V72, 2026-08-05] app.py L1034-2035에서 **기계적 추출**. 본문 로직 무변경.
⚠ 배포 단위 = app.py + aquanaris_layout.py + looperget/ 폴더 (셋은 항상 세트).

app.py가 bind()로 주입하는 것:
    FONT_REGULAR, FONT_BOLD          폰트 파일 경로 상수
    aq_err_str                       시트 예외 → 한국어 문장
    aq_load_items/sites/boxes        AQ_* 시트 로더 (st.cache_data 경유)
    download_image_by_id             Drive 이미지 다운로드
"""
import os
import io
import math
import json
import base64
import datetime

import streamlit as st
from fpdf import FPDF
from PIL import Image

from aquanaris_layout import *   # 배치 엔진(색상 팔레트·인스턴스 좌표·정준 정렬)

# ── app.py 주입 슬롯 — bind()가 채운다 ──────────────────────────────
FONT_REGULAR = "NanumGothic.ttf"
FONT_BOLD = "NanumGothic-Bold.ttf"
aq_err_str = None
aq_load_items = None
aq_load_sites = None
aq_load_boxes = None
download_image_by_id = None


def bind(**fns):
    """app.py가 시트·Drive·폰트 의존을 주입한다. import 직후 1회 호출."""
    globals().update(fns)


__all__ = [
    "AQ_STICKER_SPEC",
    "_aq_pil_from_any", "_aq_trim_white",
    "aq_sticker_pdf_bytes", "aq_layout_pdf_bytes", "aq_guidebook_pdf_bytes",
    "aq_iso_data_uri",
    "bind",
]

# ══ [V52] 스티커·가이드북 인쇄물 자동 생성 — 색상 중심 디자인 v2 (대표님 스케치 2026-07-21) ══
# 카드 = 부속군 색 프레임 + [제품명|규격] / [이미지|QR|농협 바코드] / [제품설명]. 섹션/단/열 표기 폐기.
_AQ_EAN_L = ["0001101", "0011001", "0010011", "0111101", "0100011",
             "0110001", "0101111", "0111011", "0110111", "0001011"]
_AQ_EAN_G = ["0100111", "0110011", "0011011", "0100001", "0011101",
             "0111001", "0000101", "0010001", "0001001", "0010111"]
_AQ_EAN_R = ["1110010", "1100110", "1101100", "1000010", "1011100",
             "1001110", "1010000", "1000100", "1001000", "1110100"]
_AQ_EAN_PAR = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
               "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]
AQ_STICKER_SPEC = {   # 아이라밸 실측 격자(mm) — [V53] 표기 = 실제 사이즈·라벨 규격코드·적용 부품상자
    "80":  {"w": 80.0, "h": 45.0,  "xs": [23.5, 108.5], "y0": 13.5, "rows": 6, "pitch": 45.0,
            "label": "80×45mm · 아이라벨 826 · 6호 상자", "fname": "스티커_80x45_아이라벨826_6호상자"},
    "98":  {"w": 98.8, "h": 33.67, "xs": [5.0, 107.3],  "y0": 13.0, "rows": 8, "pitch": 33.67,
            "label": "98.8×33.7mm · 아이라벨 228 · 3호 상자", "fname": "스티커_98x33_아이라벨228_3호상자"},
    "160": {"w": 160.0, "h": 70.0, "xs": [25.0],        "y0": 8.5,  "rows": 4, "pitch": 70.0,
            "label": "160×70mm · 아이라벨 814 · 431-1/432호 상자", "fname": "스티커_160x70_아이라벨814_431-432호상자"},
}

def aq_ean13_bits(code):
    """EAN-13 13자리 → 95비트 문자열. 형식/체크섬 오류 시 None."""
    s = "".join(ch for ch in str(code) if ch.isdigit())
    if len(s) != 13: return None
    d = [int(c) for c in s]
    chk = (10 - (sum(d[i] * (3 if i % 2 else 1) for i in range(12)) % 10)) % 10
    if chk != d[12]: return None
    bits = "101"
    for i, dig in enumerate(d[1:7]):
        bits += (_AQ_EAN_L if _AQ_EAN_PAR[d[0]][i] == "L" else _AQ_EAN_G)[dig]
    bits += "01010"
    for dig in d[7:13]: bits += _AQ_EAN_R[dig]
    return bits + "101"

def _aq_hexrgb(h):
    h = (h or "#9AA0A6").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def _aq_lum_txt(rgb):
    r, g, b = rgb
    return (25, 20, 20) if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else (255, 255, 255)

AQ_ASSET_DIR = "assets"   # [V53] 리포 동봉 자산 — Pretendard·JetBrains Mono·SJ 로고 (디자인가이드 v1 §3·§4)

class _AqPrintPDF(FPDF):
    """[V52] 인쇄물 공용 PDF — [V53] 디자인가이드 v1: Pretendard 본문 + JetBrains Mono 데이터,
    자산 없으면 NanumGothic(앱 표준) 폴백. 지면 기조 = 화이트 + 잉크 블랙."""
    BLACK = (22, 24, 28); DARK = (64, 64, 64); GREY = (191, 191, 191)
    INK500 = (115, 115, 115); YEL = (244, 214, 36)

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)
        self._fam, self._famx, self._mono, self._hasb = "Helvetica", None, None, False
        self._dx = 0.0   # [V71] 제본(gutter) 보정 가로 이동량 — 아래 gutter() 참조
        try:   # ① Pretendard (디자인가이드 §4)
            self.add_font("PT", "", os.path.join(AQ_ASSET_DIR, "Pretendard-Regular.otf"))
            self.add_font("PT", "B", os.path.join(AQ_ASSET_DIR, "Pretendard-Bold.otf"))
            self.add_font("PTX", "", os.path.join(AQ_ASSET_DIR, "Pretendard-ExtraBold.otf"))
            self._fam, self._famx, self._hasb = "PT", "PTX", True
        except Exception:
            try:   # ② NanumGothic 폴백 (앱 표준 다운로드 폰트)
                self.add_font("NanumGothic", "", FONT_REGULAR, uni=True)
                if os.path.exists(FONT_BOLD):
                    self.add_font("NanumGothic", "B", FONT_BOLD, uni=True); self._hasb = True
                self._fam = "NanumGothic"
            except Exception:
                pass
        try:   # 데이터 층(규격·바코드 번호·HEX) = JetBrains Mono
            self.add_font("JBM", "", os.path.join(AQ_ASSET_DIR, "JetBrainsMono-Regular.ttf"))
            self.add_font("JBM", "B", os.path.join(AQ_ASSET_DIR, "JetBrainsMono-Bold.ttf"))
            self._mono = "JBM"
        except Exception:
            pass

    # ── [V71] 제본(gutter) 보정 — 책자로 접으면 페이지 사이 가운데가 잘 안 보인다(대표님 지시) ──
    #  펼쳤을 때 **짝수 페이지 = 왼쪽 면 → 살짝 왼쪽으로**, **홀수 페이지 = 오른쪽 면 → 살짝 오른쪽으로**.
    #  아래 rect/line/image/sxy를 거치는 모든 그리기가 self._dx만큼 가로 이동한다.
    #  표지(1페이지)와 스티커는 _dx=0이라 종전과 완전히 동일.
    def gutter(self, delta=0.0):
        self._dx = float(delta) if (self.page_no() % 2) else -float(delta)

    def rect(self, x, y, *a, **k):
        return super().rect(x + self._dx, y, *a, **k)

    def line(self, x1, y1, x2, y2, *a, **k):
        return super().line(x1 + self._dx, y1, x2 + self._dx, y2, *a, **k)

    def image(self, name, x=None, y=None, *a, **k):
        if isinstance(x, (int, float)): x = x + self._dx
        return super().image(name, x, y, *a, **k)

    def sxy(self, x, y):
        """제본 보정을 적용한 set_xy — multi_cell/cell 직전 위치 지정은 이걸 쓴다."""
        return self.set_xy(x + self._dx, y)

    def f(self, size, bold=False):
        try: self.set_font(self._fam, "B" if (bold and self._hasb) else "", size)
        except Exception: self.set_font("Helvetica", "", size)

    def fx(self, size):
        """워드마크·헤드라인 — Pretendard ExtraBold (없으면 Bold)."""
        try: self.set_font(self._famx or self._fam, "" if self._famx else ("B" if self._hasb else ""), size)
        except Exception: self.set_font("Helvetica", "B", size)

    def fmono(self, size, bold=False):
        try: self.set_font(self._mono or self._fam, "B" if bold else "", size)
        except Exception: self.f(size, bold)

    @staticmethod
    def _mono_ok(s):
        """[V54] JetBrains Mono엔 한글 글리프가 없음 — 한글 포함 문자열은 본문 폰트로 폴백."""
        return not any("가" <= ch <= "힣" or "㄰" <= ch <= "㆏" for ch in str(s))

    def txt(self, x, y, w, h, s, size, bold=False, color=None, align="L", mono=False):
        (self.fmono if (mono and self._mono_ok(s)) else self.f)(size, bold)
        self.set_text_color(*(color or self.BLACK))
        self.sxy(x, y); self.cell(w, h, str(s), align=align)

    def fit_txt(self, x, y, w, h, s, size, bold=False, color=None, align="L", min_size=5.5, mono=False):
        s = str(s); sz = size
        _setf = self.fmono if (mono and self._mono_ok(s)) else self.f
        while sz > min_size:
            _setf(sz, bold)
            if self.get_string_width(s) <= w - 0.6: break
            sz -= 0.5
        _setf(sz, bold)
        if self.get_string_width(s) > w - 0.6:
            while s and self.get_string_width(s + "…") > w - 0.6: s = s[:-1]
            s += "…"
        self.set_text_color(*(color or self.BLACK))
        self.sxy(x, y); self.cell(w, h, s, align=align)

    def sj_logo(self, x, y, w):
        """SJ 보증 로고(ShinJinChemTech.png) — 자산 없으면 조용히 생략(텍스트 타이핑 금지)."""
        try:
            self.image(os.path.join(AQ_ASSET_DIR, "ShinJinChemTech.png"), x=x, y=y, w=w)
            return True
        except Exception:
            return False

    def lbox(self, x, y, w, h):
        self.set_draw_color(*self.GREY); self.set_line_width(0.2); self.rect(x, y, w, h, "D")

    def cframe(self, x, y, w, h, rgb, ft):
        self.set_fill_color(*rgb); self.rect(x, y, w, h, "F")
        self.set_fill_color(255, 255, 255); self.rect(x + ft, y + ft, w - 2 * ft, h - 2 * ft, "F")

    def img_fit(self, img, x, y, w, h):
        """PIL 이미지 비율 유지 중앙 배치 (keep_aspect_ratio 미의존 — fpdf2 구버전 호환)."""
        if img is None: return
        try:
            iw, ih = float(img.width), float(img.height)
            r = min(w / iw, h / ih)
            dw, dh = iw * r, ih * r
            self.image(img, x=x + (w - dw) / 2, y=y + (h - dh) / 2, w=dw, h=dh)
        except Exception:
            pass

    def ean13(self, code, x, y, w, h, digits_pt=6.5, digits_room=None):
        bits = aq_ean13_bits(code)
        if not bits:
            self.txt(x, y + h / 2, w, 4, f"바코드 확인 필요: {code}", 6, color=(180, 60, 60), align="C")
            return False
        mw = w / 95.0
        self.set_fill_color(*self.BLACK)
        for i, b in enumerate(bits):
            if b == "1":
                guard = i < 3 or i >= 92 or 45 <= i < 50
                self.rect(x + i * mw, y, mw, h + (1.4 if guard else 0), "F")
        # [V58] 하단 숫자 = 가능한 최대 크기(굵게) — 리더기 없는 농협은 눈으로 숫자를 읽음(대표님 요청).
        # [V71] **축소만 하던 것 → 확대 겸용**: 바코드 폭에 꽉 차게 자동으로 키운다(대표님 첨부 이미지의
        #  빨간 박스 = 바 바로 아래, 바코드 폭만큼). 가이드북 카드도 이 규칙을 그대로 따른다(스티커와 동일).
        #  폭은 실측(get_string_width), 세로는 digits_room(mm, 바 아래 여유)으로 제한.
        pt = float(digits_pt)
        room_w = max(1.0, w - 0.6)
        try:
            self.fmono(pt, True)
            _wd = self.get_string_width(str(code))
            if _wd > 0:
                pt = max(4.0, min(48.0, pt * room_w / _wd))   # 폭에 정확히 맞춘 크기(확대·축소 공통)
                self.fmono(pt, True)
            while pt > 4.0 and self.get_string_width(str(code)) > room_w:
                pt -= 0.25; self.fmono(pt, True)
        except Exception:
            pass
        if digits_room:
            pt = min(pt, max(4.0, (digits_room - 1.0) / 0.3528))   # 1.0=바-숫자 간격, 1pt=0.3528mm
        self.txt(x, y + h + 1.0, w, pt * 0.42, code, pt, bold=True, align="C", mono=True)   # [V53] 데이터=모노
        return True

    def qr(self, data, x, y, size, label=""):
        """QR(segno, 가드 임포트) — 데이터 없거나 라이브러리 없으면 자리표시(영상 준비중)."""
        ok = False
        if data:
            try:
                import segno
                mat = [list(row) for row in segno.make(data, micro=False).matrix]
                n = len(mat); quiet = 2
                mw = size / (n + quiet * 2)
                self.set_fill_color(*self.BLACK)
                for r, row in enumerate(mat):
                    for c, v in enumerate(row):
                        if v: self.rect(x + (c + quiet) * mw, y + (r + quiet) * mw, mw, mw, "F")
                ok = True
            except Exception:
                ok = False
        if not ok:
            self.set_draw_color(*self.GREY); self.set_line_width(0.25); self.rect(x, y, size, size, "D")
            self.txt(x, y + size * 0.22, size, size * 0.3, "QR", max(7, size * 0.79), color=self.GREY, align="C")
            self.txt(x, y + size * 0.56, size, size * 0.2, "영상 준비중", max(5, size * 0.28), color=self.GREY, align="C")
        if label and ok:
            self.txt(x, y + size + 0.6, size, 2.6, label, 5.5, color=self.DARK, align="C")

def _aq_pil_from_any(v):
    """[V53] download_image_by_id 반환(base64 data-URI 문자열) → PIL 이미지.
    (이 문자열을 PIL로 착각해 스티커·가이드북 이미지가 통째로 빠지던 버그의 수정점.)"""
    if v is None:
        return None
    if isinstance(v, str):
        try:
            b64 = v.split(",", 1)[1] if "," in v else v
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            img.load()
            return img
        except Exception:
            return None
    return v

def _aq_trim_white(img, thresh=244, pad=0.05):
    """[V54] 흰 여백 자동 크롭(누끼 효과) — 피사체가 카드 이미지 칸을 최대한 채우게.
    [V73] 알파가 있으면 알파를 마스크로 쓴다. 촬영 트랙의 등각 컷은 rembg 투명 PNG인데
    `convert("L")`은 알파를 버려 투명부(RGB 0,0,0)를 피사체로 읽는다 → bbox가 전면이 되어
    크롭이 통째로 무효가 되고 제품이 카드 안에서 작게 찍힌다."""
    try:
        if "A" in img.getbands():
            mask = img.getchannel("A").point(lambda p: 255 if p > 8 else 0)
        else:
            mask = img.convert("L").point(lambda p: 255 if p < thresh else 0)
        bbox = mask.getbbox()
        if not bbox:
            return img
        w, h = img.size
        px = int((bbox[2] - bbox[0]) * pad) + 2
        py = int((bbox[3] - bbox[1]) * pad) + 2
        return img.crop((max(0, bbox[0] - px), max(0, bbox[1] - py),
                         min(w, bbox[2] + px), min(h, bbox[3] + py)))
    except Exception:
        return img

_AQ_PR_GLYPH = {"㎜": "mm", "㎝": "cm", "㎞": "km", "ℓ": "L", "中": "중", "小": "소", "大": "대"}

def _aq_pr_clean(s):
    """NanumGothic에 없는 글리프(㎜·ℓ·中·小 등) 치환 — 서버 PDF 빈 글자 방지."""
    s = str(s or "").strip()
    for k, v in _AQ_PR_GLYPH.items():
        s = s.replace(k, v)
    return s

def _aq_pr_item(r):
    """AQ_Items 레코드 → 인쇄용 dict (QR링크 컬럼 생기면 자동 사용)."""
    qr = ""
    for col in ("QR링크", "영상링크", "참고영상"):
        if str(r.get(col, "") or "").strip():
            qr = str(r.get(col)).strip(); break
    return {"code": str(r.get("품목코드", "")).strip().zfill(5),
            "name": _aq_pr_clean(r.get("품목명_AQ")),
            "spec": _aq_pr_clean(r.get("규격_AQ")),
            "grp": str(r.get("진열분류", "") or "").strip(),
            "desc": _aq_pr_clean(r.get("설명")),
            "bc_std": str(r.get("표준바코드", "") or "").strip(),
            "bc_local": str(r.get("지역바코드", "") or "").strip(),
            "qr": qr}

def _aq_pr_bc(it, bc_mode):
    return it["bc_std"] if bc_mode == "표준" else (it["bc_local"] or it["bc_std"])

_AQ_STICKER_CAPTION = "Aqunaris · ShinJinChemTech · sjct.kr"   # [V53] 보증 캡션 — [V54] sjct.kr 병기

def _aq_sticker_card(pdf, s, x, y, it, rgb, bc, img):
    """스티커 카드 1장 — [V53] 디자인가이드 v1 §5-1: 상단 색 밴드(부속군명 병기) + 얇은 색 테두리,
    [제품명|규격(모노)] / [이미지|QR(≥15mm)|바코드] / [설명] + 하단 보증 캡션."""
    tcol = _aq_lum_txt(rgb)
    if s == "160":
        W, H, FT, BH = 160.0, 70.0, 1.5, 7.0
        pdf.cframe(x, y, W, H, rgb, FT)
        pdf.set_fill_color(*rgb); pdf.rect(x, y, W, BH, "F")                     # 상단 색 밴드
        pdf.fit_txt(x + 4, y + 1.2, W * 0.6, BH - 2.4, it["grp"] or "부속", 11, bold=True, color=tcol)
        pdf.txt(x + W * 0.55, y + 1.6, W * 0.45 - 4, BH - 3.2, _AQ_STICKER_CAPTION, 7, color=tcol, align="R")
        cx, cw = x + FT + 3, W - 2 * (FT + 3)
        r1y, r1h = y + BH + 2, 9
        nw = cw * 0.60
        pdf.lbox(cx, r1y, nw, r1h); pdf.fit_txt(cx + 2, r1y + 0.7, nw - 4, r1h - 1.4, it["name"], 13, bold=True)
        pdf.lbox(cx + nw + 2, r1y, cw - nw - 2, r1h)
        pdf.fit_txt(cx + nw + 4, r1y + 0.9, cw - nw - 6, r1h - 1.8, it["spec"], 10, bold=True, color=pdf.DARK, mono=True)
        r2y, r2h = r1y + r1h + 2, 31
        pdf.lbox(cx, r2y, 40, r2h); pdf.img_fit(img, cx + 1.5, r2y + 1.5, 37, r2h - 3)
        pdf.qr(it["qr"], cx + 44, r2y + 1.5, 27, label="영상 보기")
        bx = cx + 44 + 27 + 6; bw = cx + cw - bx - 2
        if bc: pdf.ean13(bc, bx, r2y + 4, bw, 17, digits_pt=18, digits_room=r2h - 22.6)   # [V58] 숫자 최대 확대
        else: pdf.txt(bx, r2y + 12, bw, 5, "바코드 없음", 9, color=(180, 60, 60), align="C")
        r3y = r2y + r2h + 1.6; r3h = y + H - FT - 4.2 - r3y
        pdf.lbox(cx, r3y, cw, r3h)
        if it["desc"]:
            pdf.f(8.5); pdf.set_text_color(*pdf.BLACK); pdf.sxy(cx + 2, r3y + 1)
            pdf.multi_cell(cw - 4, 3.9, it["desc"][:130], max_line_height=3.9)
        pdf.txt(cx, y + H - FT - 3.4, cw, 2.6, _AQ_STICKER_CAPTION, 5.5, color=pdf.INK500, align="C")
    elif s == "80":
        W, H, FT, BH = 80.0, 45.0, 1.0, 4.8
        pdf.cframe(x, y, W, H, rgb, FT)
        pdf.set_fill_color(*rgb); pdf.rect(x, y, W, BH, "F")
        pdf.fit_txt(x + 2.5, y + 0.7, W - 5, BH - 1.4, it["grp"] or "부속", 7.2, bold=True, color=tcol)
        cx, cw = x + FT + 1.5, W - 2 * (FT + 1.5)
        r1y, r1h = y + BH + 1.2, 6.0
        nw = cw * 0.60
        pdf.lbox(cx, r1y, nw, r1h); pdf.fit_txt(cx + 1.2, r1y + 0.4, nw - 2.4, r1h - 0.8, it["name"], 8.2, bold=True)
        pdf.lbox(cx + nw + 1.2, r1y, cw - nw - 1.2, r1h)
        pdf.fit_txt(cx + nw + 2.2, r1y + 0.6, cw - nw - 3.2, r1h - 1.2, it["spec"], 6.8, bold=True, color=pdf.DARK, mono=True)
        r2y, r2h = r1y + r1h + 1.2, 19.5
        pdf.lbox(cx, r2y, 18, r2h); pdf.img_fit(img, cx + 0.8, r2y + 0.8, 16.4, r2h - 1.6)
        pdf.qr(it["qr"], cx + 19.4, r2y + 2, 15)   # §5-1 QR 최소 15mm
        bx = cx + 19.4 + 15 + 2; bw = cx + cw - bx - 0.5
        if bc: pdf.ean13(bc, bx, r2y + 2.5, bw, 9.0, digits_pt=14, digits_room=r2h - 12.9)   # [V58] 숫자 최대 확대(바 11.5→9.0)
        else: pdf.txt(bx, r2y + 8, bw, 4, "바코드 없음", 6.5, color=(180, 60, 60), align="C")
        r3y = r2y + r2h + 1.0; r3h = y + H - FT - 3.4 - r3y
        pdf.lbox(cx, r3y, cw, r3h)
        if it["desc"]:
            pdf.f(6); pdf.set_text_color(*pdf.BLACK); pdf.sxy(cx + 1.2, r3y + 0.7)
            pdf.multi_cell(cw - 2.4, 2.7, it["desc"][:80], max_line_height=2.7)
        pdf.txt(cx, y + H - FT - 2.8, cw, 2.2, _AQ_STICKER_CAPTION, 4.6, color=pdf.INK500, align="C")
    else:  # "98" — 저높이 라벨: 설명 우측 세로칸
        W, H, FT, BH = 98.8, 33.67, 0.9, 4.2
        pdf.cframe(x, y, W, H, rgb, FT)
        pdf.set_fill_color(*rgb); pdf.rect(x, y, W, BH, "F")
        pdf.fit_txt(x + 2.2, y + 0.6, W * 0.55, BH - 1.2, it["grp"] or "부속", 6.6, bold=True, color=tcol)
        pdf.txt(x + W * 0.5, y + 0.9, W * 0.5 - 2.5, BH - 1.8, _AQ_STICKER_CAPTION, 5, color=tcol, align="R")
        cx, cw = x + FT + 1.2, W - 2 * (FT + 1.2)
        r1y, r1h = y + BH + 0.9, 5.2
        nw = cw * 0.56
        pdf.lbox(cx, r1y, nw, r1h); pdf.fit_txt(cx + 1.2, r1y + 0.3, nw - 2.4, r1h - 0.6, it["name"], 7.8, bold=True)
        pdf.lbox(cx + nw + 1.2, r1y, cw - nw - 1.2, r1h)
        pdf.fit_txt(cx + nw + 2.2, r1y + 0.5, cw - nw - 3.2, r1h - 1.0, it["spec"], 6.6, bold=True, color=pdf.DARK, mono=True)
        r2y = r1y + r1h + 0.9
        r2h = y + H - FT - 1.0 - r2y
        pdf.lbox(cx, r2y, 16.5, r2h); pdf.img_fit(img, cx + 0.8, r2y + 0.8, 14.9, r2h - 1.6)
        qs = 15.0   # §5-1 QR 최소 15mm
        pdf.qr(it["qr"], cx + 18, r2y + max(0.5, (r2h - qs) / 2), qs)
        bx = cx + 18 + qs + 2; bw = 30   # [V58] 바코드 폭 26→30 — 숫자 확대
        if bc: pdf.ean13(bc, bx, r2y + 1.8, bw, 11, digits_pt=11, digits_room=r2h - 13.7)   # [V58] 숫자 최대 확대
        else: pdf.txt(bx, r2y + 6, bw, 4, "바코드 없음", 6.2, color=(180, 60, 60), align="C")
        dx = bx + bw + 2; dw = cx + cw - dx
        pdf.lbox(dx, r2y, dw, r2h)
        if it["desc"]:
            pdf.f(5.6); pdf.set_text_color(*pdf.BLACK); pdf.sxy(dx + 1, r2y + 0.7)
            pdf.multi_cell(dw - 2, 2.6, it["desc"][:100], max_line_height=2.6)

def aq_sticker_pdf_bytes(recs, size_key, bc_mode, img_of=None):
    """스티커 PDF 생성 → bytes. recs=AQ_Items 레코드 목록, img_of=코드→PIL 이미지(없으면 이미지 생략)."""
    spec = AQ_STICKER_SPEC[size_key]
    items = [_aq_pr_item(r) for r in recs]
    order = {g: i for i, g in enumerate(AQ_GROUP_COLORS)}
    for it in items: it["grp"] = aq_grp_norm(it["grp"])   # [V59] 구군 명칭 정규화
    items.sort(key=lambda d: (order.get(d["grp"], 99), d["code"]))   # 부속군 군집 → 같은 색끼리
    pdf = _AqPrintPDF()
    per_page = len(spec["xs"]) * spec["rows"]
    for i, it in enumerate(items):
        k = i % per_page
        if k == 0: pdf.add_page()
        x = spec["xs"][k % len(spec["xs"])]
        y = spec["y0"] + (k // len(spec["xs"])) * spec["pitch"]
        img = img_of(it["code"]) if img_of else None
        _aq_sticker_card(pdf, size_key, x, y, it, _aq_hexrgb(AQ_GROUP_COLORS.get(aq_grp_norm(it["grp"]))), _aq_pr_bc(it, bc_mode), img)
    return bytes(pdf.output())

AQ_GB_GUTTER = 5.0   # [V71] 제본 보정 이동량(mm) — 짝수 페이지는 왼쪽, 홀수 페이지는 오른쪽으로

def _aq_guide_card(pdf, x, y, it, rgb, bc, bc_note, img):
    """가이드북 품목 카드 88×62 — 대표님 스케치 레이아웃."""
    CW, CH, FT = 88, 62, 2.0
    pdf.cframe(x, y, CW, CH, rgb, FT)
    cx, cw = x + FT + 2, CW - 2 * (FT + 2)
    r1y, r1h = y + FT + 2, 8.5
    nw = cw * 0.58
    pdf.lbox(cx, r1y, nw, r1h); pdf.fit_txt(cx + 1.5, r1y + 0.6, nw - 3, r1h - 1.2, it["name"], 10.5, bold=True)
    pdf.lbox(cx + nw + 1.5, r1y, cw - nw - 1.5, r1h)
    pdf.fit_txt(cx + nw + 3, r1y + 0.9, cw - nw - 4.5, r1h - 1.8, it["spec"], 8.5, bold=True, color=pdf.DARK, mono=True)   # [V53] 데이터=모노
    r2y, r2h = r1y + r1h + 2, 30
    pdf.lbox(cx, r2y, 29, r2h); pdf.img_fit(img, cx + 0.8, r2y + 0.8, 27.4, r2h - 1.6)   # [V54] 이미지 확대
    qx = cx + 31
    pdf.qr(it["qr"], qx, r2y + 3.5, 20, label="영상 보기")
    bx = qx + 23; bw = cx + cw - bx
    if bc:
        # [V71] 하단 숫자를 바코드 폭에 꽉 차게 확대(스티커와 동일 규칙) — 6.5pt 고정 → 약 9pt
        pdf.ean13(bc, bx, r2y + 4, bw, 16, digits_pt=12, digits_room=5.2)
        if bc_note: pdf.txt(bx, r2y + 25.5, bw, 3.2, bc_note, 6.5, color=(180, 60, 60), align="C")
    else:
        pdf.txt(bx, r2y + 12, bw, 5, "바코드 없음", 8, color=(180, 60, 60), align="C")
    r3y = r2y + r2h + 2; r3h = y + CH - FT - 2 - r3y
    pdf.lbox(cx, r3y, cw, r3h)
    if it["desc"]:
        pdf.f(6.9); pdf.set_text_color(*pdf.BLACK); pdf.sxy(cx + 1.5, r3y + 1.2)
        pdf.multi_cell(cw - 3, 3.2, it["desc"][:160], max_line_height=3.2)

# ══ [V69] 배치도 벡터 렌더 — 화면 SVG와 같은 인스턴스 좌표를 PDF에 직접 그린다 ══
#  화면 캡처는 화질이 떨어져 인쇄물에 못 쓴다(대표님 지적). 좌표를 벡터로 다시 그리면
#  확대해도 선명하고, 같은 로직으로 가이드북 지면에도 그대로 실린다.
AQ_PDF_FRAME_T = 19        # 랙 기둥 두께(mm 실척) — SVG `_aq_rack_parts`와 동일
AQ_PDF_GAP_X = 70.0        # 랙 사이 가로 간격(mm 실척)
AQ_PDF_GAP_Y = 230.0       # 줄 사이 세로 간격(랙 이름 자리 포함)

def _aq_pdf_rack_wh(rk):
    """랙 1대의 실척 크기(mm) — 렌더러와 같은 식(Σ단높이+단두께×(단수−1)+기둥)."""
    hs = list(rk.get("단높이") or [])
    t = int(rk.get("단두께") or 0)
    return (int(rk.get("내측폭") or 0) + AQ_PDF_FRAME_T * 2,
            sum(hs) + t * max(0, len(hs) - 1) + AQ_PDF_FRAME_T)

def _aq_pdf_fit(racks, area_w, area_h):
    """줄당 랙수를 바꿔가며 **배율이 최대가 되는 조합**을 고른다 — 잘리지 않고 빈 공간 최소.
    반환 (줄당 랙수, 배율, 전체폭mm실척, 전체높이mm실척)."""
    sizes = [_aq_pdf_rack_wh(rk) for rk in racks]
    if not sizes or area_w <= 0 or area_h <= 0:
        return 1, 0.0, 0.0, 0.0
    best = None
    for per in range(1, len(sizes) + 1):
        rows = [sizes[i:i + per] for i in range(0, len(sizes), per)]
        w = max(sum(s[0] for s in r) + AQ_PDF_GAP_X * (len(r) - 1) for r in rows)
        h = sum(max(s[1] for s in r) for r in rows) + AQ_PDF_GAP_Y * (len(rows) - 1)
        if w <= 0 or h <= 0: continue
        sc = min(area_w / w, area_h / h)
        if best is None or sc > best[1] + 1e-9:
            best = (per, sc, w, h)
    return best or (1, 0.0, 0.0, 0.0)

def _aq_pdf_blend(rgb, a=0.72):
    """SVG의 fill-opacity 0.72와 같은 색 — PDF는 알파 대신 흰색과 미리 섞는다."""
    return tuple(int(round(255 - (255 - c) * a)) for c in rgb)

# ══ [V71] 배치도 상자 라벨 — 품명+규격 2줄, 12pt 지향·10pt 하한 (대표님 지시) ══
#  "텍스트를 자르지는 말고, 잘릴 것 같으면 대표 명칭 또는 줄임말로. 품명과 규격이 같이 들어가야 하고,
#   많이 줄이더라도. 결국 안 되면 그때는 크기를 줄여라."
#  → ①줄임 단계로 폭을 맞춘다(자르지 않음) ②그래도 안 들어가면 마지막에 글자 크기를 낮춘다.
AQ_LBL_PT_HI = 12.0    # 지향 크기(이 이상이면 좋음 — 상자가 크면 14pt까지 키운다)
AQ_LBL_PT_LO = 10.0    # 하한(여기까지는 줄임말로 버틴다)
AQ_LBL_PT_MIN = 5.5    # 최후 수단 — 물리적으로 불가능할 때만 여기까지 내려간다
_AQ_LBL_K = 0.70       # 한글 글자 잉크 높이 / em (실측 근사)
_AQ_LBL_GAP = 0.10     # 두 줄 사이 간격 / em

def _aq_lbl_cands(s, keep_min=2):
    """라벨 줄임 단계 — (문자열, 잘랐는가) 를 긴 것부터. 말줄임표(…)는 쓰지 않는다.
    '잘랐는가'=False인 단계까지는 **대표 명칭**(괄호부·뒤 수식어 제거)이라 뜻이 온전하다."""
    s = _aq_pr_clean(s)
    out, seen = [], set()
    def _add(t, cut):
        t = str(t or "").strip()
        if t and t not in seen:
            seen.add(t); out.append((t, cut))
    _add(s, False)
    _add(_aq_strip_paren(s), False)          # 괄호부 제거 — 밸브바디(조임식연결구) → 밸브바디
    if not out: return []
    toks = out[-1][0].split()
    while len(toks) > 1:                     # 뒤 수식어부터 제거 — '엘보 20mm 조임식' → '엘보 20mm' → '엘보'
        toks = toks[:-1]; _add(" ".join(toks), False)
    head = out[-1][0]
    for n in range(len(head) - 1, keep_min - 1, -1):   # 그래도 넘치면 앞 n글자(줄임말)
        _add(head[:n], True)
    return out

def _aq_lbl_spec_cands(s):
    """규격 전용 줄임 — **절대 자르지 않는다**(25mm→25m가 되면 뜻이 달라짐).
    괄호부 제거 후 구분자(+ * × / , 공백) 단위로 뒤에서부터 덜어낸다.
    예: '20mm*13mm'→'20mm' · '삼발이+연결대+닛쁠'→'삼발이+연결대'→'삼발이' · '50mm 일반형'→'50mm'."""
    s = _aq_pr_clean(s)
    out, seen = [], set()
    def _add(t):
        t = str(t or "").strip().strip("+*×/,·- ")
        if t and t not in seen:
            seen.add(t); out.append((t, False))
    _add(s)
    _add(_aq_strip_paren(s))
    cur = out[-1][0] if out else ""
    for _ in range(6):
        pos = max((cur.rfind(sep) for sep in ("+", "*", "×", "/", ",", " ")), default=-1)
        if pos <= 0: break
        cur = cur[:pos]
        _add(cur)
    # 단위(mm) 축약 — 배치도의 기본 단위는 mm이므로 '20mm*13mm'→'20*13' · '물호스16mm'→'물호스16'.
    #  단위가 빠진 표기는 조금 덜 친절하므로 **원표기 후보를 모두 시도한 뒤에** 쓴다.
    alt = []
    for t, _c in list(out):
        if "mm" not in t: continue
        u = t.replace("mm", "").strip()
        if u and u not in seen:
            seen.add(u); alt.append((u, False))
    out.sort(key=lambda p: -len(p[0]))   # 정보가 많은(긴) 것부터 시도
    alt.sort(key=lambda p: -len(p[0]))
    return out + alt

def _aq_lbl_fit(pdf, cands, pt, bold, room_w, allow_cut):
    """이 크기에서 폭에 들어가는 가장 온전한 후보. 하나도 없으면 None."""
    for t, cut in cands:
        if cut and not allow_cut: continue
        pdf.f(pt, bold)
        if pdf.get_string_width(t) <= room_w:
            return t
    return None

def _aq_lbl_steps(hi, lo):
    out, v = [], math.floor(hi * 2) / 2.0
    while v >= lo - 1e-9:
        out.append(round(v, 2)); v -= 0.5
    return out

def _aq_pdf_box_label(pdf, bx, by, bwp, bhp, name, spec, tc, short=""):
    """상자 안에 품명(굵게)+규격 2줄을 그린다.
    우선순위 — ①12pt 이상을 확보한 채 **자르지 않은** 대표 명칭 ②12pt에서 줄임말
               ③그래도 안 들어가면 그때 비로소 글자 크기를 낮춘다(대표님 지시)."""
    nm_c = _aq_lbl_cands(name)
    if short:
        _sh = _aq_pr_clean(short)
        if _sh and _sh not in [t for t, _c in nm_c]:
            nm_c.insert(1, (_sh, False))     # 시트에 약칭이 있으면 온전한 후보로 우선 사용
    sp_c = _aq_lbl_spec_cands(spec) if str(spec or "").strip() else []
    if not nm_c: return
    room_w = bwp - 0.6
    if room_w <= 0.8 or bhp <= 0.8: return

    def _try(pt, lines, allow_cut):
        t1 = _aq_lbl_fit(pdf, nm_c, pt, True, room_w, allow_cut)
        if t1 is None: return None
        t2 = _aq_lbl_fit(pdf, sp_c, pt, False, room_w, allow_cut) if lines == 2 else None
        if lines == 2 and t2 is None: return None
        return t1, t2

    def _draw(pt, lines, t1, t2):
        lh = pt * 0.3528 * _AQ_LBL_K
        gp = pt * 0.3528 * _AQ_LBL_GAP
        y0 = by + max(0.0, (bhp - (lh * lines + gp * (lines - 1))) / 2.0)
        pdf.txt(bx + 0.3, y0, room_w, lh, t1, pt, bold=True, color=tc, align="C")
        if t2:
            pdf.txt(bx + 0.3, y0 + lh + gp, room_w, lh, t2, pt, color=tc, align="C")

    for lines in ((2, 1) if sp_c else (1,)):   # 규격은 되도록 품명과 함께 — 안 되면 그때 품명만
        cap = min(14.0, bhp / (0.3528 * (_AQ_LBL_K * lines + _AQ_LBL_GAP * (lines - 1))))
        if cap < AQ_LBL_PT_MIN: continue
        # ① 12pt 이상 구간에서 자르지 않은 대표 명칭 — 크기·뜻 둘 다 지키는 최선
        for pt in _aq_lbl_steps(cap, AQ_LBL_PT_HI):
            r = _try(pt, lines, False)
            if r: _draw(pt, lines, *r); return
        # ② 12pt(또는 상자가 허용하는 최대)에서 줄임말 허용
        _pt2 = min(math.floor(cap * 2) / 2.0, AQ_LBL_PT_HI)
        if _pt2 >= AQ_LBL_PT_MIN:
            r = _try(_pt2, lines, True)
            if r: _draw(_pt2, lines, *r); return
        # ③ 최후 — 크기를 낮춘다(10pt 하한을 넘겨야 할 때만 그 아래로)
        for pt in _aq_lbl_steps(min(cap, AQ_LBL_PT_HI) - 0.5, AQ_LBL_PT_MIN):
            r = _try(pt, lines, True)
            if r: _draw(pt, lines, *r); return

def _aq_pdf_rack(pdf, x, y, rk, inst_by, dims, info, sc):
    """랙 1대를 (x,y)에 배율 sc로 그린다 — 프레임·단선·상자(부속군색)·색상 자석테이프·라벨."""
    hs = list(rk.get("단높이") or [])
    t = int(rk.get("단두께") or 0)
    name = str(rk.get("명칭") or "")
    W, H = _aq_pdf_rack_wh(rk)
    pw, ph = W * sc, H * sc
    pdf.set_fill_color(250, 250, 247); pdf.set_draw_color(*pdf.BLACK)
    pdf.set_line_width(max(0.18, min(0.5, pw * 0.006)))
    pdf.rect(x, y, pw, ph, "DF")
    _ns = max(7.0, min(13.0, pw * 0.17))   # [V71] 섹션 이름도 상자 라벨(12pt급)에 맞춰 키움
    pdf.txt(x, y - _ns * 0.62 - 0.8, pw, _ns * 0.6, name, _ns, bold=True, color=pdf.DARK, align="C")
    y_real = 0
    for si, sh in enumerate(hs, 1):
        base = y + ph - y_real * sc          # 이 단의 바닥
        y_real += sh
        ytop = y + ph - y_real * sc          # 개구부 상단(=선반 판 윗면)
        pdf.set_draw_color(*pdf.BLACK); pdf.set_line_width(max(0.14, min(0.4, pw * 0.005)))
        pdf.line(x, ytop, x + pw, ytop)
        y_real += t
        ins = inst_by.get((name, si)) or []
        if not ins: continue
        cols, _unk = aq_inst_cols(ins, dims, int(rk.get("내측폭") or 0))   # [V70] 좌/우 정렬 반영
        # [V71] 색상 자석테이프 — 맨 아래 상자 라벨을 덮으므로 인쇄물에서는 얇게(구 1.4mm → 0.7mm).
        #  상자 자체가 이미 부속군 색이라 구분 기능은 그대로이고, 그만큼 라벨에 쓸 높이가 늘어난다.
        _tape_h = max(0.35, min(0.7, ph * 0.008))
        for cx, cw, stack in cols:
            ycum, tape_rgb = 0.0, None
            for li, (it, wh) in enumerate(stack):
                bw, bh = wh
                meta = info.get(str(it.get("code"))) or {}
                base_rgb = _aq_hexrgb(AQ_GROUP_COLORS.get(aq_grp_norm(meta.get("grp") or "")))
                if tape_rgb is None: tape_rgb = base_rgb
                rgb = _aq_pdf_blend(base_rgb)
                bx = x + AQ_PDF_FRAME_T * sc + cx * sc
                ycum += bh
                by = base - ycum * sc
                bwp, bhp = bw * sc, bh * sc
                pdf.set_fill_color(*rgb); pdf.set_draw_color(*pdf.BLACK); pdf.set_line_width(0.1)
                pdf.rect(bx, by, bwp, bhp, "DF")
                # [V71] 라벨 = 품명+규격 2줄 (12pt 지향·10pt 하한).
                #  맨 아래 상자는 하단이 색상 자석테이프에 덮이므로 그만큼 비우고 그 위에 앉힌다.
                _lbh9 = bhp - ((_tape_h + 0.15) if li == 0 else 0.0)
                if bwp >= 3.0 and _lbh9 >= 1.6:
                    _aq_pdf_box_label(pdf, bx, by, bwp, _lbh9,
                                      meta.get("name") or it.get("code"), meta.get("spec") or "",
                                      _aq_lum_txt(rgb), short=meta.get("short") or "")
            if tape_rgb:   # 색상 자석테이프(단 전면 하단 밴드) — 진열대 실물과 동일 표기
                pdf.set_fill_color(*tape_rgb)
                pdf.rect(x + AQ_PDF_FRAME_T * sc + cx * sc, base - _tape_h, cw * sc, _tape_h, "F")

def _aq_pdf_draw(pdf, x0, y0, racks, inst_by, dims, info, per, sc, align="C", area_w=0.0):
    """racks를 (x0,y0)에서 area_w 폭 안에 per개씩 줄지어 그린다(줄 안에서는 바닥 정렬).
    align: C=가운데 · L=왼쪽(펼침면 오른쪽 페이지) · R=오른쪽(펼침면 왼쪽 페이지). 반환: 사용 높이mm."""
    sizes = [_aq_pdf_rack_wh(rk) for rk in racks]
    y, i = y0, 0
    while i < len(racks):
        row = list(range(i, min(i + per, len(racks))))
        rw = sum(sizes[j][0] for j in row) + AQ_PDF_GAP_X * (len(row) - 1)
        rh = max(sizes[j][1] for j in row)
        if align == "R":   x = x0 + area_w - rw * sc
        elif align == "L": x = x0
        else:              x = x0 + (area_w - rw * sc) / 2.0
        for j in row:
            _aq_pdf_rack(pdf, x, y + (rh - sizes[j][1]) * sc, racks[j], inst_by, dims, info, sc)
            x += (sizes[j][0] + AQ_PDF_GAP_X) * sc
        y += rh * sc + AQ_PDF_GAP_Y * sc
        i += per
    return max(0.0, y - y0 - AQ_PDF_GAP_Y * sc)

def _aq_inst_by_shelf(instances):
    out = {}
    for it in instances:
        out.setdefault((str(it.get("rack") or ""), int(it.get("shelf") or 0)), []).append(it)
    return out

def aq_site_layout(site, recs=None, boxes=None):
    """[V69] 사이트의 랙 구성 + 상자 인스턴스 복원 — **가상랙(🅥) 제외**.
    저장 포맷 3종 호환: inst2(V68 압축) → instances(V67) → v1 assign/splits(패킹 1회 재현).
    반환 (rack_list, instances, dims, info)."""
    recs = recs if recs is not None else aq_load_items()
    boxes = boxes if boxes is not None else aq_load_boxes()
    by_code = {str(r.get("품목코드", "")).strip().zfill(5): r for r in recs}
    dims = aq_box_dims_map(boxes)
    racks_raw, plan = [], {}
    for srow in aq_load_sites():
        if str(srow.get("농협명", "")).strip() == str(site).strip():
            try: racks_raw = json.loads(str(srow.get("랙구성JSON") or "[]"))
            except Exception: racks_raw = []
            try: plan = json.loads(str(srow.get("배치JSON") or "{}"))
            except Exception: plan = {}
            break
    if not isinstance(plan, dict): plan = {}
    if not isinstance(racks_raw, list): racks_raw = []
    pit = plan.get("items") if isinstance(plan.get("items"), dict) else {}
    free = plan.get("free") if isinstance(plan.get("free"), dict) else {}
    for c, f in (free or {}).items():
        try:
            _w, _h = int(f.get("w") or 0), int(f.get("h") or 0)
            if _w > 0 and _h > 0: dims[f"자유:{c}"] = (_w, _h)
        except Exception:
            continue
    rack_list = []
    for r in racks_raw:
        if not isinstance(r, dict): continue
        nm = str(r.get("명칭") or "").strip()
        if not nm or nm.startswith("🅥"): continue        # 가상랙 = 임시 보관 공간 → 도면에서 제외
        try: wv = int(float(r.get("폭mm") or 0))
        except Exception: wv = 0
        try:
            hs = [int(float(x)) for x in str(r.get("단높이mm(콤마구분)") or "").split(",") if str(x).strip()]
        except Exception:
            hs = []
        try: tk = int(float(r.get("단두께mm") or 0))
        except Exception: tk = 0
        if wv > 0 and hs:
            rack_list.append({"명칭": nm, "내측폭": wv - 38, "단높이": hs, "단두께": tk})
    def _box_of(c):
        r0 = by_code.get(str(c), {}) or {}
        b0 = str(((pit or {}).get(str(c), {}) or {}).get("box") or r0.get("기본상자") or "").strip()
        if not b0 and f"자유:{c}" in dims: b0 = f"자유:{c}"
        return b0
    insts = []
    if isinstance(plan.get("inst2"), dict) and plan["inst2"]:
        insts = aq_inst_unpack(plan["inst2"], _box_of)
    elif isinstance(plan.get("instances"), list):
        for x in plan["instances"]:
            if not isinstance(x, dict): continue
            try:
                insts.append({"id": str(x.get("id") or ""), "code": str(x.get("code") or ""),
                              "box": str(x.get("box") or ""), "rack": str(x.get("rack") or ""),
                              "shelf": int(x.get("shelf") or 0),
                              "col": float(x.get("col") or 0), "layer": float(x.get("layer") or 0)})
            except Exception:
                continue
        aq_inst_normalize(insts)
    else:   # v1(assign/splits) — 종전 패킹 규칙으로 1회 재현
        asg = plan.get("assign") if isinstance(plan.get("assign"), dict) else {}
        spl = plan.get("splits") if isinstance(plan.get("splits"), dict) else {}
        seqs = {}
        def _add(c, rk, sh, n):
            b0 = _box_of(c); wh = dims.get(b0)
            if not wh: return
            g0 = str((by_code.get(str(c), {}) or {}).get("진열분류") or "(미지정)")
            for _ in range(max(1, int(n or 1))):
                seqs.setdefault((rk, sh), []).append((str(c), g0, b0, wh[0], wh[1], 1))
        for c, d in (asg or {}).items():
            if not isinstance(d, dict): continue
            try: _sh = int(d.get("shelf") or 0)
            except Exception: _sh = 0
            if str(d.get("rack") or "") and _sh > 0: _add(c, str(d["rack"]), _sh, d.get("n") or 1)
        for c, lst in (spl or {}).items():
            for e in (lst if isinstance(lst, list) else []):
                try: _add(c, str(e[0]), int(e[1]), int(e[2]))
                except Exception: continue
        for k in seqs: seqs[k] = aq_canon_seq(seqs[k])
        insts = aq_instances_from_seqs(seqs, rack_list)
    _rknames = {rk["명칭"] for rk in rack_list}
    insts = [x for x in insts if str(x.get("rack") or "") in _rknames]   # 가상랙·없는 랙 제외
    info = {}
    for x in insts:
        c = str(x.get("code"))
        if c in info: continue
        r0 = by_code.get(c, {}) or {}
        info[c] = {"name": _aq_pr_clean(r0.get("품목명_AQ") or c),
                   "spec": _aq_pr_clean(r0.get("규격_AQ") or ""),
                   # [V71] 시트에 약칭 컬럼이 있으면 배치도 상자 라벨의 줄임 후보로 우선 사용
                   "short": _aq_pr_clean(r0.get("약칭") or r0.get("표시명") or ""),
                   "grp": str(r0.get("진열분류") or "(미지정)")}
    return rack_list, insts, dims, info

def aq_layout_pdf_bytes(site, rack_list, instances, dims, info):
    """[V69] 배치도 1장 PDF(A4 가로·벡터) — 화면 캡처 대신 인쇄·문서 첨부용. 가상랙 제외본을 넘길 것."""
    pdf = _AqPrintPDF()
    pdf.add_page(orientation="L", format="A4")
    _today = datetime.date.today().strftime("%Y-%m-%d")
    pdf.txt(10, 7, 200, 9, f"{site} — 진열 배치도", 16, bold=True)
    pdf.txt(10, 16.5, 200, 5, f"실척 벡터 도면 · 부속군 색상 체계 · 가상랙 제외 · {_today}",
            8.5, color=pdf.INK500)
    pdf.set_draw_color(*pdf.BLACK); pdf.set_line_width(0.4); pdf.line(10, 23, 287, 23)
    ax, ay, aw, ah = 10.0, 30.0, 277.0, 168.0
    per, sc, _w9, _h9 = _aq_pdf_fit(rack_list, aw, ah)
    y0 = ay + max(0.0, (ah - _h9 * sc) / 2.0)
    _aq_pdf_draw(pdf, ax, y0, rack_list, _aq_inst_by_shelf(instances), dims, info,
                 per, sc, align="C", area_w=aw)
    pdf.txt(0, 202, 297, 4, f"Aqunaris · ShinJinChemTech · sjct.kr · 상자 {len(instances)}개 · {_today}",
            7, color=(168, 168, 168), align="C")
    return bytes(pdf.output())

# ══ [V71] 가이드북 배치도 펼침면 — 페이지당 6섹션(3열×2줄), 12섹션이 넘으면 다음 장으로 ══
#  대표님 지시: 책을 펼치면 4·5페이지가 함께 보인다 →
#    4p 상단 1·2·3 / 5p 상단 4·5·6 / 4p 하단 7·8·9 / 5p 하단 10·11·12,
#    15섹션이면 6페이지에 나머지 3개.
AQ_GB_LAY_PER_ROW = 3          # 페이지 한 줄에 놓는 랙 수
AQ_GB_LAY_ROWS = 2             # 페이지당 줄 수 → 페이지당 6랙 · 펼침면 12랙
AQ_GB_LAY_M, AQ_GB_LAY_TOP, AQ_GB_LAY_BOT = 10.0, 30.0, 18.0

def _aq_gb_layout_plan(rack_list):
    """랙 목록 → 페이지별 랙 리스트. 펼침면(12랙)을 왼쪽 면/오른쪽 면으로 갈라 담는다."""
    per_pg = AQ_GB_LAY_PER_ROW * AQ_GB_LAY_ROWS          # 6
    per_sp = per_pg * 2                                   # 12
    pages = []
    for i in range(0, len(rack_list), per_sp):
        ch = rack_list[i:i + per_sp]
        rows = [ch[r:r + AQ_GB_LAY_PER_ROW * 2] for r in range(0, len(ch), AQ_GB_LAY_PER_ROW * 2)]
        left = [rk for row in rows for rk in row[:AQ_GB_LAY_PER_ROW]]      # 1·2·3 · 7·8·9
        right = [rk for row in rows for rk in row[AQ_GB_LAY_PER_ROW:]]     # 4·5·6 · 10·11·12
        if left: pages.append(left)
        if right: pages.append(right)
    return pages

def _aq_gb_layout_scale(pages, aw, ah):
    """모든 배치도 페이지에 공통으로 쓸 배율 — 어느 페이지도 잘리지 않는 최대값."""
    sc = None
    for rks in pages:
        sizes = [_aq_pdf_rack_wh(rk) for rk in rks]
        rows = [sizes[i:i + AQ_GB_LAY_PER_ROW] for i in range(0, len(sizes), AQ_GB_LAY_PER_ROW)]
        w = max(sum(s[0] for s in r) + AQ_PDF_GAP_X * (len(r) - 1) for r in rows)
        h = sum(max(s[1] for s in r) for r in rows) + AQ_PDF_GAP_Y * (len(rows) - 1)
        if w <= 0 or h <= 0: continue
        s = min(aw / w, ah / h)
        sc = s if sc is None else min(sc, s)
    return sc or 0.0

def _aq_gb_layout_pages(pdf, site, pages, instances, dims, info, foot, gut):
    """배치도 페이지들을 그린다 — 전 페이지 같은 배율이라 랙 크기가 어디서나 동일."""
    if not pages or not instances: return False
    inst_by = _aq_inst_by_shelf(instances)
    M, TOP, BOT = AQ_GB_LAY_M, AQ_GB_LAY_TOP, AQ_GB_LAY_BOT
    aw, ah = 210 - M * 2, 297 - TOP - BOT
    sc = _aq_gb_layout_scale(pages, aw, ah)
    if sc <= 0: return False
    for pi, rks in enumerate(pages):
        pdf.add_page(); gut()
        # 제목은 **바깥쪽**(책 펼쳤을 때 페이지 가장자리)으로 — 제본선 가운데에 두 제목이 몰리지 않게
        _ta9 = "L" if (pdf.page_no() % 2 == 0) else "R"
        pdf.txt(M, 8, aw, 8, f"{site} 진열 배치도" + ("" if pi == 0 else f" ({pi + 1})"),
                15, bold=True, align=_ta9)
        pdf.txt(M, 17.5, aw, 4.5,
                "실척 도면 · 색상 = 부속군" + (" · 좌우 두 면이 이어집니다" if len(pages) > 1 else ""),
                8, color=pdf.INK500, align=_ta9)
        sizes = [_aq_pdf_rack_wh(rk) for rk in rks]
        _rows = [sizes[i:i + AQ_GB_LAY_PER_ROW] for i in range(0, len(sizes), AQ_GB_LAY_PER_ROW)]
        _h9 = sum(max(s[1] for s in r) for r in _rows) + AQ_PDF_GAP_Y * (len(_rows) - 1)
        y0 = TOP + max(0.0, (ah - _h9 * sc) / 2.0)
        _aq_pdf_draw(pdf, M, y0, rks, inst_by, dims, info, AQ_GB_LAY_PER_ROW, sc, align="C", area_w=aw)
        foot()
    return True

def aq_guidebook_pdf_bytes(recs, site, bc_mode, img_of=None):
    """가이드북 PDF → (bytes, 품목수, 확정배치사용여부). site='(전체 품목)'이면 진열분류 보유 전체."""
    assign = {}
    if site and site != "(전체 품목)":
        for srow in aq_load_sites():
            if str(srow.get("농협명", "")).strip() == site:
                try:
                    plan = json.loads(srow.get("배치JSON") or "{}")
                    assign = plan.get("assign", {}) if isinstance(plan, dict) else {}
                except Exception:
                    assign = {}
    use_assign = bool(assign)
    items = [_aq_pr_item(r) for r in recs]
    sel = []
    for it in items:
        if use_assign:
            a = assign.get(it["code"])
            if not isinstance(a, dict) or str(a.get("rack", "")).startswith("🅥"):
                continue   # 확정 배치 품목만(가상랙 보관 제외)
        elif not it["grp"]:
            continue
        sel.append(it)
    for it in items: it["grp"] = aq_grp_norm(it["grp"])   # [V59] 구군 명칭 정규화
    groups = [g for g in AQ_GROUP_COLORS if any(it["grp"] == g for it in sel)]
    groups += sorted({it["grp"] for it in sel} - set(groups))
    pdf = _AqPrintPDF()
    _today = datetime.date.today().strftime("%Y-%m-%d")

    def _foot():   # [V53] 푸터 — 페이지번호 + 보증 캡션 + 발행일 (디자인가이드 §5-2) — [V54] sjct.kr
        pdf.txt(0, 290.5, 210, 4, f"{pdf.page_no()}   ·   Aqunaris · ShinJinChemTech · sjct.kr   ·   {_today}",
                6.5, color=(168, 168, 168), align="C")

    # [V71] 제본 보정 — 표지 다음부터 짝수는 왼쪽·홀수는 오른쪽으로 AQ_GB_GUTTER만큼 밀어 그린다.
    def _gut():
        pdf.gutter(AQ_GB_GUTTER)

    def _page():   # 표지 이후 모든 페이지 = add_page + 제본 보정
        pdf.add_page(); _gut()

    # ── [V71] 배치도 데이터를 **먼저** 확보한다 — 목차(2페이지)에 실릴 페이지 번호를 미리 알아야 하므로 ──
    _lay9 = None
    if site and site != "(전체 품목)":
        try:
            _rk9, _in9, _dm9, _if9 = aq_site_layout(site, recs)
            if _rk9 and _in9:
                _lay9 = (_aq_gb_layout_plan(_rk9), _in9, _dm9, _if9)
            else:
                st.session_state["_aq_gb_layout_note"] = (
                    f"'{site}'의 저장된 배치·랙 구성이 없어 배치도 페이지는 생략했습니다 "
                    "(사이트 설계에서 배치 후 💾 저장하면 다음 생성부터 포함됩니다).")
        except Exception as _e9:
            st.session_state["_aq_gb_layout_note"] = f"배치도 페이지 생략 — {aq_err_str(_e9)}"
    _n_lay9 = len(_lay9[0]) if _lay9 else 0

    # ── [V71] 목차용 페이지 번호 사전 계산 — 1 표지 / 2 목차 / 3 색인 / 4~ 배치도 / 그 뒤 군별 카드 ──
    _P_IDX9 = 3                       # 부속군 색상 색인
    _P_LAY9 = 4                       # 진열 배치도 시작
    _toc9 = [("부속군 색상 색인", _P_IDX9, None)]
    if _n_lay9:
        _toc9.append((f"{site} 진열 배치도", _P_LAY9,
                      None if _n_lay9 == 1 else _P_LAY9 + _n_lay9 - 1))
    _pg9 = _P_LAY9 + _n_lay9          # 첫 카드 페이지
    for _g9 in groups:
        _cnt9 = sum(1 for it in sel if it["grp"] == _g9)
        if not _cnt9: continue
        _np9 = (_cnt9 + 7) // 8       # 카드 8장/페이지
        _toc9.append((_g9 or "(미지정)", _pg9, (_pg9 + _np9 - 1) if _np9 > 1 else None))
        _pg9 += _np9

    # ① 표지 — [V53] 화이트 기조 + Aqunaris 워드마크 + 부속군 색 스트립 + SJ 보증 로고 (§5-2, 옐로 전면 폐지)
    pdf.add_page(); pdf._dx = 0.0   # 표지는 제본 보정 제외(대표님 지시)
    try: pdf.set_char_spacing(-0.3)   # 워드마크 자간 -2% (§3 잠정 조판)
    except Exception: pass
    pdf.fx(54); pdf.set_text_color(*pdf.BLACK)
    pdf.sxy(0, 78); pdf.cell(210, 22, "Aqunaris", align="C")
    try: pdf.set_char_spacing(0)
    except Exception: pass
    pdf.txt(0, 106, 210, 12, "아쿠나리스 관수코너 가이드북", 20, bold=True, align="C")
    pdf.txt(0, 122, 210, 10, site or "", 15, align="C")
    pdf.txt(0, 134, 210, 7, f"바코드: {bc_mode}바코드 기준", 10, color=pdf.INK500, align="C")
    _cols_v = [_aq_hexrgb(v) for v in AQ_GROUP_COLORS.values()]   # 부속군 색 스트립 = 아쿠나리스 시그니처
    if _cols_v:
        _sx, _sw, _sh = 30, 150.0, 7.0
        _seg = _sw / len(_cols_v)
        for _i, _c in enumerate(_cols_v):
            pdf.set_fill_color(*_c); pdf.rect(_sx + _i * _seg, 156, _seg, _sh, "F")
        pdf.txt(_sx, 165.5, _sw, 4.5, "부속군 색상 체계 — 진열대 · 상자 스티커 · 가이드북 공통", 8, color=pdf.INK500, align="C")
    if not pdf.sj_logo(84, 238, 42):   # 보증 = SJ 로고 1개 (두 브랜드 텍스트 병렬 폐지)
        pdf.txt(0, 244, 210, 6, "Aqunaris · ShinJinChemTech", 10, color=pdf.INK500, align="C")
    pdf.txt(0, 284, 210, 6, f"{_today} · v1 · sjct.kr", 9, color=pdf.INK500, align="C", mono=True)

    # ② [V71] 목차 (2페이지) — 대표님 지시. 페이지 번호는 위에서 사전 계산한 값.
    _page()
    pdf.txt(15, 14, 180, 10, "목차", 18, bold=True)
    pdf.set_draw_color(*pdf.BLACK); pdf.set_line_width(0.5); pdf.line(15, 26, 195, 26)
    _ty9 = 36
    for _nm9, _p19, _p29 in _toc9:
        _chip9 = AQ_GROUP_COLORS.get(aq_grp_norm(_nm9))
        _tx9 = 15.0
        if _chip9:   # 부속군 항목은 색 칩을 앞에 — 색인·진열대 자석테이프와 같은 색
            pdf.set_fill_color(*_aq_hexrgb(_chip9)); pdf.rect(15, _ty9 + 1.0, 7, 5.6, "F")
            _tx9 = 25.0
        _pt9 = f"{_p19}" + (f"–{_p29}" if _p29 else "")
        pdf.txt(_tx9, _ty9, 130, 7.6, _nm9, 12, bold=not _chip9)
        pdf.f(12, bool(not _chip9))
        _lw9 = pdf.get_string_width(_nm9)
        _dx9, _dw9 = _tx9 + _lw9 + 3, 179 - 16 - (_tx9 + _lw9 + 3)   # 점선 리더 자리
        pdf.f(9, False)
        _u9 = pdf.get_string_width("·") or 1.9
        if _dw9 > _u9:
            pdf.txt(_dx9, _ty9, _dw9, 7.6, "·" * int(_dw9 / _u9), 9, color=(205, 205, 205))
        pdf.txt(179 - 16, _ty9, 16, 7.6, _pt9, 12, bold=True, align="R", mono=True)
        _ty9 += 9.6
    pdf.txt(15, min(_ty9 + 6, 276), 180, 6,
            "책자를 펼치면 왼쪽·오른쪽 두 면이 한 장의 배치도로 이어집니다.", 9, color=pdf.DARK)
    _foot()

    # ③ 부속군 색상 색인 (3페이지, +HEX 병기 §5-2)
    _page()
    pdf.txt(15, 14, 180, 10, "부속군 색상 색인", 18, bold=True)
    pdf.set_draw_color(*pdf.BLACK); pdf.set_line_width(0.5); pdf.line(15, 26, 195, 26)
    yy = 34
    for g in groups:
        _hex9 = str(AQ_GROUP_COLORS.get(aq_grp_norm(g)) or "#9AA0A6").upper()
        pdf.set_fill_color(*_aq_hexrgb(AQ_GROUP_COLORS.get(aq_grp_norm(g)))); pdf.rect(15, yy, 14, 9, "F")
        pdf.txt(33, yy, 95, 9, g or "(미지정)", 13, bold=True)
        pdf.txt(128, yy + 1.4, 30, 6, _hex9, 7.5, color=pdf.INK500, mono=True)
        pdf.txt(158, yy, 37, 9, f"{sum(1 for it in sel if it['grp'] == g)}품목", 11, align="R")
        yy += 13
    pdf.txt(15, yy + 6, 180, 6, "카드 테두리·진열대 색상 자석테이프·상자 스티커가 모두 같은 부속군 색을 씁니다.", 9, color=pdf.DARK)
    _foot()

    # ④ [V71] 진열 배치도 (4페이지~) — 펼침면 3열×2줄, 페이지당 6섹션
    if _lay9:
        _aq_gb_layout_pages(pdf, site, _lay9[0], _lay9[1], _lay9[2], _lay9[3], _foot, _gut)

    # ⑤ 부속군별 카드 (2열×4행) + 섹션 밴드(부속군명 병기)·푸터
    X0, Y0, CW, CH, GX, GY = 12, 22, 88, 62, 10, 4
    for g in groups:
        gi = [it for it in sel if it["grp"] == g]
        if not gi: continue
        rgb = _aq_hexrgb(AQ_GROUP_COLORS.get(aq_grp_norm(g)))
        k = 8
        for it in gi:
            if k == 8:
                _page()
                _dxb9 = pdf._dx; pdf._dx = 0.0   # [V71] 전폭 색 밴드는 제본 보정 제외(가장자리 흰 띠 방지)
                pdf.set_fill_color(*rgb); pdf.rect(0, 0, 210, 16, "F")
                pdf._dx = _dxb9
                pdf.txt(12, 3.5, 170, 9, g or "(미지정)", 15, bold=True, color=_aq_lum_txt(rgb))
                _foot()
                k = 0
            x = X0 + (k % 2) * (CW + GX)
            y = Y0 + (k // 2) * (CH + GY)
            bc = _aq_pr_bc(it, bc_mode)
            note = "※표준 폴백" if (bc_mode == "지역" and not it["bc_local"] and it["bc_std"]) else ""
            img = img_of(it["code"]) if img_of else None
            _aq_guide_card(pdf, x, y, it, rgb, bc, note, img)
            k += 1

    # ⑥ 뒷표지 — SJ 로고 + 문의(도메인만 — 문안은 의장 확정 대기, 가이드 §7-④)
    pdf.add_page(); pdf._dx = 0.0   # [V71] 표지·뒷표지는 제본 보정 제외
    if not pdf.sj_logo(80, 120, 50):
        pdf.txt(0, 130, 210, 8, "Aqunaris · ShinJinChemTech", 12, color=pdf.INK500, align="C")
    pdf.txt(0, 148, 210, 6, "sjct.kr", 11, color=pdf.INK500, align="C", mono=True)
    pdf.txt(0, 280, 210, 5, f"Aqunaris Guide Book · {_today}", 7, color=(168, 168, 168), align="C")
    return bytes(pdf.output()), len(sel), use_assign

@st.cache_data(ttl=86400, show_spinner=False)
def aq_iso_data_uri(file_id, max_px=240):
    """[V49] 등각(ISO) 이미지 → 흰배경 누끼(테두리 연결 플러드필, V37 방식) → PNG data URI (SVG 삽입용).
    실패 시 빈 문자열(호출측이 도형으로 폴백)."""
    img = download_image_by_id(file_id)
    if img is None: return ""
    try:
        from collections import deque
        img = img.convert("RGBA")
        img.thumbnail((max_px, max_px))
        px = img.load(); w, h = img.size
        thr = 232
        seen = [[False] * w for _ in range(h)]
        dq = deque()
        for x in range(w):
            dq.append((x, 0)); dq.append((x, h - 1))
        for y in range(h):
            dq.append((0, y)); dq.append((w - 1, y))
        while dq:
            x, y = dq.popleft()
            if x < 0 or y < 0 or x >= w or y >= h or seen[y][x]: continue
            seen[y][x] = True
            r, g, b, a = px[x, y]
            if r >= thr and g >= thr and b >= thr:
                px[x, y] = (r, g, b, 0)
                dq.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
        buf = io.BytesIO(); img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""
