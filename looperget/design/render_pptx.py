# -*- coding: utf-8 -*-
"""
looperget.design.render_pptx — 설계 요약(job) → 농업 제안서 PPTX (마스터 복제·치환).

정본
  · 형식 = 농업 제안서 마스터 28면 `_설계/_농업제안서_마스터/마스터_농업제안서_v1_20260824.pptx`
    (고정면은 그대로 재사용 — 디자인 정본 §7)
  · 지도면 문법 = 승인 배추밭 5필지 생성기(`20_생성기/_생성_숙진리.py` · `_생성_482_v4.py`)를
    **설계 JSON 입력형**으로 일반화 — 누적 레이어 · 지도 밖 지시 라벨(규칙 16) · 사선 분기 곡선(규칙 14)
    · 주배관 > 가지관 굵기(규칙 4) · 살수원 이중 원(10 m / 7 m)
  · 부속 소개 = 디자인 정본 v1 `_디자인정본/표준_pptx.py` 카드·칩·뱃지 (§5) — 세트명 병기(규칙 8·10)
  · 대표 계통도(규칙 7)는 meta.sketch_pages 로 받아 **그대로 옮긴다**(다시 그리지 않는다)

숫자는 전부 summary.build(job)에서 온다 — 이 파일은 값을 만들지 않는다.
"""
from __future__ import annotations

import copy
import io
import json
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Sequence, Tuple

from . import geom as G
from . import qr as QR
from .summary import spray_labels as _SL

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "_디자인정본")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import agri_overlay as ov                                             # noqa: E402
from agri_overlay import MapFrame, pipe, head_dot, spray_double, caption, leader, dim_chain, dim_side  # noqa: E402
import 표준_pptx as DS                                                # noqa: E402

# 🔵 [V117 · 3단계(b)] 마스터 = 원본이 있으면 원본(작업 PC), 없으면 **경량 사본**(배포 서버 · 16.5 MB · 구조 원본과 동일 검증
#    `작업/20260923_V117/p3a_경량마스터/검증결과.md` · 도구 `tools/make_slim_master.py`). 원본을 고치면 경량본을 다시 만든다 — master_status().
MASTER_FULL = os.path.join(ROOT, "_설계", "_농업제안서_마스터", "마스터_농업제안서_v1_20260824.pptx")
MASTER_SLIM = os.path.join(ROOT, "_설계", "_농업제안서_마스터", "마스터_농업제안서_v1_20260824_경량.pptx")


def pick_master() -> str:
    return MASTER_FULL if os.path.exists(MASTER_FULL) else MASTER_SLIM


MASTER = pick_master()
_SHA_CACHE: Dict[Tuple[str, int, float], str] = {}


def master_status() -> Dict:
    """→ {"path", "kind": 원본|경량본|없음, "warn"}. 원본과 경량본이 **둘 다** 있는 PC 에서 경량본 옆 보고 json 의
    src_sha256 이 지금 원본과 다르면 「경량본 다시 만들기」 경고(원본을 고쳤는데 서버는 옛 지면을 쓰게 된다)."""
    import hashlib
    kind = "원본" if MASTER == MASTER_FULL else ("경량본" if os.path.exists(MASTER) else "없음")
    out = {"path": MASTER, "kind": kind, "warn": ""}
    side = os.path.splitext(MASTER_SLIM)[0] + ".json"
    if os.path.exists(MASTER_FULL) and os.path.exists(MASTER_SLIM):
        try:
            want = json.load(open(side, encoding="utf-8")).get("src_sha256")
        except Exception:
            want = None
        st_ = os.stat(MASTER_FULL)
        key = (MASTER_FULL, st_.st_size, st_.st_mtime)
        if key not in _SHA_CACHE:
            h = hashlib.sha256()
            with open(MASTER_FULL, "rb") as f:
                for blk in iter(lambda: f.read(1 << 20), b""):
                    h.update(blk)
            _SHA_CACHE[key] = h.hexdigest()
        if not want:
            out["warn"] = "경량본 대조 정보(%s)가 없습니다 — 경량본 다시 만들기 권장(tools/make_slim_master.py)" % os.path.basename(side)
        elif want != _SHA_CACHE[key]:
            out["warn"] = ("원본 마스터가 경량본을 만든 뒤 바뀌었습니다 — 경량본 다시 만들기(tools/make_slim_master.py) · "
                           "배포 서버는 옛 지면으로 만듭니다")
    return out


R_NS ="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CAP_X, CAP_Y, CAP_W = 8.30, 1.45, 4.80                # 캡션 자리(승인 지면 실측)
W_MAIN, W_LAT, W_BURIED = DS.HOSE.MAIN_PT, DS.HOSE.BRANCH_PT, 1.6   # 규칙 4
GRN = RGBColor(0x00, 0xB0, 0x50)

# 총내역 고정면의 영세율 안내 — 견적서 비고와 **같은 문구**로 통일한다(마스터 원문은 손대지 않는다).
#  · 조특법 제105조는 「면제」가 아니라 **영세율** 조항이다(2026-08-31 확인, log). 마스터엔 「면제 대상」으로 적혀 있었다.
#  · 제출 서류명 = 「농업경영체 등록확인서」(농업회사법인은 사업자등록증) — 견적 비고·영세율 확인서와 일치.
#  · 조문 호수를 적을지는 열린 결정(세무대리인 확인). 줄 길이는 고정면이 wrap=False라 원문 길이를 넘기지 않는다.
# 영세율 안내는 **기본 off**다 (대표 결정 2026-09-04) — 우리가 법조문 근거로 입증해야 할 수 있어
# 위험부담이 있다. 「최소 200만원 이상 + 마케팅에 도움되는 경우」 등으로 **건별로 대표가 판단해 켠다**.
# 켜는 법 = job meta.quote.vat_zero = true. 끄면 합계 표기는 VAT_PLAIN.
VAT_ZERO_MIN_TOTAL = 2_000_000        # 대표 판단 기준선 — 이 아래면 켜져 있어도 경고한다
VAT_PLAIN = "※ 부가가치세 별도"       # 영세율 미적용 시 합계 표기(영세율 문구가 「10 %가 면제된 최종 금액」이므로 기본은 별도)
VAT_ZERO = [
    "[농업용 기자재 영세율(부가세0%) 적용 안내]",
    "적용 근거: 조세특례제한법 제105조 (농업용 스프링클러 설비 부가가치세 영세율 적용 대상)",
    "적용 혜택: 본 견적은 농가의 시설 투자 부담을 덜어드리기 위해 부가가치세를 영세율(0 %)로 적용한 최종 금액입니다.",
    "필수 협조사항: 영세율 적용·신고를 위해 결제 전 「농업경영체 등록확인서」(농업회사법인은 사업자등록증) 사본을 제출해 주시기 바랍니다.",
]
LINE2 = RGBColor(0xA6, 0x4B, 0xE8)                    # 둘째 줄(구역선) — 보라(승인 규약)
# [V114 · R06] 3구역부터 쓰는 색(1 노랑 · 2 보라는 승인 규약 그대로). 이름은 캡션 범례에 쓴다.
ZONE_PALETTE = [(RGBColor(0x1F, 0x77, 0xD0), "파랑"), (RGBColor(0xE0, 0x6C, 0x00), "주황"), (RGBColor(0x1B, 0x9E, 0x5A), "초록"),
                (RGBColor(0xC2, 0x18, 0x5B), "자주"), (RGBColor(0x00, 0x8C, 0x9E), "청록"), (RGBColor(0x7A, 0x5C, 0x2E), "갈색"),
                (RGBColor(0x55, 0x55, 0x55), "회색")]
BAD = RGBColor(0xD9, 0x2D, 0x20)                      # [V114] 급수 불가 열 — 빨강(커버율에서 뺀 열)
# 🔵 [계통도 · 2026-10-07] 인입관(급수 지점 → 매니폴드) 선 = 초록 계열 — 주배관(노랑)·구역선(보라 …)과 다른 색.
FEED = RGBColor(0x00, 0xA6, 0x51)
FEED_MIN_IN = 0.45                                    # 급수 지점이 밭에 너무 붙어 선이 안 보이면 표시만 이만큼 띄운다(좌표는 그대로)
# 물 공급 계통도 부속(대표 지정 · 관경별). 관경은 설계 main_mm 을 따른다 — 40·50 외에는 50 으로 그리고 기록한다.
# [2026-10-07 대표 교정] ① 첫 연결부 = 일자연결 세트(WF 4-1 + 호스밴드 + WF 4-2) · ③ 매니폴드 입구 = WF 4-2 → CCCT T
WD_BY_MM = {40: {"wf41": "00824", "e_valve": "01402", "wf42": "00826"},
            50: {"wf41": "00825", "e_valve": "01403", "wf42": "00827"}}
# 총 소요 내역 표 — 열 폭(사진 · 품목 · 규격 · 수량 · 단가 · 비고 = 6.05 in) · 사진 칸 때문에 행 최소 높이 0.30 · 한 단 최대 높이
BOM_COLS = (0.46, 1.74, 0.96, 0.62, 0.70, 1.57)
BOM_RMIN = 0.30
BOM_PAGE_H = 4.65
WD_COMMON = {"h20": "01920", "gauge": "01870", "ccct": "01201", "elbow": "00190", "band": "00278"}
WD_NAMES = {"00824": "WF 4-1", "00825": "WF 4-1", "00941": "WF 4-4", "00969": "WF 4-4", "01199": "WF 4-10", "00970": "WF 4-10", "01402": "E호스밸브", "01403": "E호스밸브",
            "00826": "WF 4-2", "00827": "WF 4-2", "01920": "루퍼젯 H20", "01870": "압력계", "01201": "CCCT 中",
            "00190": "변형 L보", "00278": "호스밴드"}

# 🔵 [V114 · 2단계 §3] 고정면 문구 교정 — **생성 시 치환**한다(마스터 원문은 손대지 않는다 · 롤백 = 이 표를 비우면 끝).
#    (면 번호는 마스터 1-base) 근거 없는 절대 표현은 계산 조건을 말하는 문장으로, 원시자료 확인 전 수치는 뺀다.
#    ⚠ 면23 문장 속 빈칸은 오탈자가 아니다 — 그 자리에 ↑·↓ 화살표 도형이 얹혀 있다. 빈칸은 그대로 둔다.
FIXED_TEXT_FIX = [
    (1, "관수 사각지대 원천 차단", "헤드 반경·간격 계산으로 살수 공백을 줄이는 배치"),
    (1, "지형 맞춤형 빈틈없는 관수", "지형 맞춤형 배관·살수 배치"),
    (22, "노란 표면은 태양광을 반사해 최고 15% 이상 표면온도 감소", "노란 표면은 태양광을 반사해 표면온도 상승을 줄입니다"),
    (22, "뜨거운 물 유입 방지로 작물 스트레스 완화.", ""),      # 표면온도를 작물 효과로 넓히지 않는다
    (22, "내부가 검정식이라", "내부가 검정색이라"),
    (22, "내1M마다", "1M마다"),
    (25, "PATENDED", "PATENTED"),
    (26, "꺽임", "꺾임"),
]
FIXED_DROP = [(22, "최대 15% 차이")]                   # 원시 측정자료 확인 전 수치 주장 — 고객 초안에서 뺀다(근거확인 대상)
FIXED_NAME_DROP = ("경기도 이천시", "도암리 인삼농장")      # [V117 · C] 마스터 도형 이름에 남은 다른 현장명(2·18면) — 생성 시 이름만 바꾼다
# 「루퍼젯+ AI」 — 상품·기능·지원 범위가 확인되기 전에는 기본 제안에서 뺀다(meta.options.ai = True 일 때만 남긴다).
AI_BLOCK = {"slide": 26, "texts": ("루퍼젯+ AI", "기후변화 시대에 최적화된"), "group_left_in": 9.88}
BURIED = RGBColor(0x9A, 0x9A, 0x9A)
P4_LOGO_Y = 6.70        # 면4 하단 고정 로고(레이아웃 그림 L0.68 T6.70 W1.25) — 이 위로만 쓴다
ov.FONT = DS.T.CAPTION                                # 생성 텍스트 서체 = 정본 §3 (고정면은 마스터 그대로)

# 마스터 면 지도 (0-base)
M = {"표지": 0, "장점": 1, "주의": 2, "상호확인": 3, "대상지": 4, "주배관": 5, "주배관상세": 6,
     "가지관": 7, "가지관상세": 8, "스프링클러": 9, "스프링클러상세": 10, "헤드성능": 11,
     "전체": 12, "구역": list(range(13, 21)), "총내역": 21, "꼬리": list(range(22, 28))}


def _grid_line(S):
    """[V114] 간격 문장 — 권장 격자와 같을 때만 「권장」이라고 쓴다(05 숙진리 10 m = 농가 요청 · 권장 14 m)."""
    from .layout import HEAD_PROFILES
    model = (S.get("spray") or {}).get("model", "427B")
    prof = HEAD_PROFILES.get(model) or {}
    rec = ("%.1f" % float(prof.get("S", 0))).rstrip("0").rstrip(".")
    same = str(S["head_gap"]) == rec and str(S["lat_gap"]) == rec
    return ("헤드 간격 %s m · 열 간격 %s m — %s 권장 격자(규칙 20)" % (S["head_gap"], S["lat_gap"], model) if same
            else "헤드 간격 %s m · 열 간격 %s m — 현장 조정(%s 권장 %s m)" % (S["head_gap"], S["lat_gap"], model, rec))


# ══════════════ 지면 조작 ══════════════
def _merge_parts(parts):
    """[V117 · C] 칩 목록 [(code, 이름, 규격)] → 같은 코드는 한 칩(규격 「×n」은 더하고, 아니면 「규격 ×개수」)."""
    order, got = [], {}
    for code, nm, sp in parts:
        if code not in got:
            order.append(code)
            got[code] = [nm, [], 0]
        got[code][1].append(str(sp))
        got[code][2] += 1
    out = []
    for code in order:
        nm, sps, k = got[code]
        if k == 1:
            out.append((code, nm, sps[0]))
        elif all(re.fullmatch(r"×\d+", s_) for s_ in sps):
            out.append((code, nm, "×%d" % sum(int(s_[1:]) for s_ in sps)))
        else:
            out.append((code, nm, "%s ×%d" % (sps[0], k)))
    return out


def wrap_em(text: str, box_in: float, pt: float, pad: float = 0.35) -> List[str]:
    """[V117 · C] 글자 폭(est_lines 와 같은 em 어림)으로 줄을 접는다 — 단어(공백) 경계 우선, 문장부호만 남는 줄 금지.
    textwrap(글자 수 66)은 한글 폭을 몰라 PowerPoint 가 한 번 더 접으면서 「미확인입니다 / .」처럼 끊겼다(23면)."""
    em = lambda s_: sum(1.0 if ord(c) > 0x2000 else (0.30 if c == " " else 0.52) for c in s_)
    cap = (box_in - pad) * 72.0 / pt
    out, cur = [], ""
    for word in str(text).split(" "):
        cand = (cur + " " + word) if cur else word
        if em(cand) <= cap or not cur:
            cur = cand
            while em(cur) > cap:                          # 공백 없이 긴 토막 — 글자 단위로 자른다
                k = len(cur)
                while k > 1 and em(cur[:k]) > cap:
                    k -= 1
                out.append(cur[:k])
                cur = cur[k:]
        else:
            out.append(cur)
            cur = word
    if cur or not out:
        out.append(cur)
    merged = []
    for ln in out:                                        # 문장부호만 남은 줄은 앞 줄에 붙인다
        if merged and re.fullmatch(r"[\s.,·:;!?)\]」』…—-]+", ln):
            merged[-1] += ln.strip()
        else:
            merged.append(ln)
    return merged


def chain_steps(chains, price_db=None, compatibility=(), log=None):
    """[V117 · K-06] 연결 사슬 → 도해 칸. 판정은 **엔진(connections.validate_chains)의 링크별·사슬별 결과** 그대로다.

    예전에는 도해가 check_ports 를 따로 불러(근거·코드·포트 ID·T 가지를 빼고) 엔진이 불일치로 본 사슬을 초록으로,
    근거가 있어 확인된 나사 이음을 「규격 확인 필요」로 그렸다(재검토 K-06). → [(원본 사슬, (칸들, 사슬 판정))]."""
    from . import connections as CN
    price_db = price_db or {}
    try:
        checked = CN.validate_chains(list(chains or []), compatibility)["chains"]
        pairs = list(zip(chains or [], checked))
    except ValueError:
        pairs = []                                        # 묶음 검사가 막히면(ID 중복 등) 사슬마다 따로
        for c in chains or []:
            try:
                pairs.append((c, CN.validate_chains([c], compatibility)["chains"][0]))
            except ValueError as e:
                if log is not None:
                    log.append("연결 도해 건너뜀 %s — %s" % ((c or {}).get("id"), e))
    out = []
    for raw, nc in pairs:
        steps = [{"name": str((nc.get("start") or {}).get("name") or "시작"), "code": "", "joint": None}]
        for link in nc.get("links") or []:
            code = str(link.get("code") or (link.get("pipe") or {}).get("code") or "")
            name = str(link.get("custom_name") or (price_db.get(code) or {}).get("name") or code or link.get("id"))
            if link.get("len_m"):
                name += " %s m" % link["len_m"]
            steps.append({"name": name, "code": code, "qty": link.get("qty", 1),
                          "joint": link.get("check") or {"status": CN.UNKNOWN, "issues": ["판정 없음"]}})
        out.append((raw, (steps, nc.get("check") or {"status": CN.UNKNOWN, "issues": []})))
    return out


def replace_text(slide, old, new):
    n = 0

    def walk(shapes):
        nonlocal n
        for sh in shapes:
            if sh.shape_type == 6:
                walk(sh.shapes)
                continue
            if not sh.has_text_frame:
                continue
            for para in sh.text_frame.paragraphs:
                runs = para.runs
                if any(old in r.text for r in runs):
                    for r in runs:
                        if old in r.text:
                            r.text = r.text.replace(old, new)
                            n += 1
                elif runs and old in "".join(r.text for r in runs):
                    runs[0].text = "".join(r.text for r in runs).replace(old, new)
                    for r in runs[1:]:
                        r._r.getparent().remove(r._r)
                    n += 1
    walk(slide.shapes)
    return n


def clear_slide(slide, keep_top_in=1.0):
    for sh in list(slide.shapes):
        if not (sh.has_text_frame and sh.top is not None and sh.top < Inches(keep_top_in)):
            sh._element.getparent().remove(sh._element)


def est_lines(text, box_in, pt, pad=0.20):
    """텍스트가 몇 줄로 접히는지 어림 — 한글·한자 1.0 em · 공백 0.30 · 그 밖 0.52.
    실측 대조(면4 각주 12.1 in · 12 pt): 8.23 / 10.13 / 11.76 in 로 렌더 결과와 일치."""
    em = sum(1.0 if ord(c) > 0x2000 else (0.30 if c == " " else 0.52) for c in text)
    return max(1, int(-(-(em * pt / 72.0) // (box_in - pad))))


def set_paragraphs(shape, texts):
    """문단 텍스트 교체 — 첫 run 서식 유지. 문단이 모자라면 마지막 문단을 복제해 늘린다(줄이 사라지지 않게)."""
    tf = shape.text_frame
    while len(tf.paragraphs) < len(texts):
        last = tf.paragraphs[-1]._p
        last.addnext(copy.deepcopy(last))
    paras = tf.paragraphs
    for i, p in enumerate(paras):
        if i < len(texts):
            runs = p.runs
            if runs:
                runs[0].text = texts[i]
                for r in runs[1:]:
                    r._r.getparent().remove(r._r)
        else:
            p._p.getparent().remove(p._p)


def set_title(slide, text):
    for sh in slide.shapes:
        if sh.has_text_frame and sh.top is not None and sh.top < Inches(1.0) and sh.text_frame.text.strip():
            set_paragraphs(sh, [text])
            return True
    DS.title(slide, text)
    return False


def copy_shapes(dst, src_slide, dx_in=0.0, dy_in=0.0, skip_pred=None):
    """다른 파일의 슬라이드 도형을 dst에 복사(+오프셋). 이미지 파트는 blob 재등록, 비이미지 파트는 새 파트명."""
    same = src_slide.part.package is dst.part.package
    mapping = {}
    for rId, rel in src_slide.part.rels.items():
        if "notesSlide" in rel.reltype or "slideLayout" in rel.reltype:
            continue
        if rel.is_external:
            mapping[rId] = dst.part.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref)
        elif same:
            mapping[rId] = dst.part.relate_to(rel.target_part, rel.reltype)
        elif rel.reltype.endswith("/image"):
            _, mapping[rId] = dst.part.get_or_add_image_part(io.BytesIO(rel.target_part.blob))
        else:
            from pptx.opc.package import Part
            from pptx.opc.packuri import PackURI
            tp = rel.target_part
            stem = re.sub(r"\d+(?=\.\w+$)", "%d", str(tp.partname))
            pn = dst.part.package.next_partname(stem) if "%d" in stem else PackURI(str(tp.partname))
            mapping[rId] = dst.part.relate_to(Part(pn, tp.content_type, dst.part.package, tp.blob), rel.reltype)
    out, added = [], []
    for shp in src_slide.shapes:
        if skip_pred and skip_pred(shp):
            continue
        el = copy.deepcopy(shp._element)
        dst.shapes._spTree.append(el)
        added.append(el)
        new = dst.shapes[-1]
        try:
            new.left = Emu(int(new.left + Inches(dx_in)))
            new.top = Emu(int(new.top + Inches(dy_in)))
        except Exception:
            pass
        out.append(new)
    for root in added:                      # 새로 붙인 요소 안에서만 rId를 바꾼다
        for el in root.iter():
            for attr, val in list(el.attrib.items()):
                if attr.startswith("{%s}" % R_NS) and val in mapping:
                    el.set(attr, mapping[val])
    return out


def move_before(prs, slide, anchor):
    lst = prs.slides._sldIdLst
    ids = {prs.part.rels[e.get(qn("r:id"))].target_part: e for e in list(lst)}
    me, an = ids[slide.part], ids[anchor.part]
    lst.remove(me)
    lst.insert(list(lst).index(an), me)


def delete_slide(prs, slide):
    for sldId in list(prs.slides._sldIdLst):
        rId = sldId.get(qn("r:id"))
        if prs.part.rels[rId].target_part is slide.part:
            prs.part.drop_rel(rId)
            prs.slides._sldIdLst.remove(sldId)
            return


def new_slide_before(prs, anchor):
    s = prs.slides.add_slide(anchor.slide_layout)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    move_before(prs, s, anchor)
    return s


def label(slide, x, y, text, size=11, color=None, w=3.0, bold=True, align=PP_ALIGN.LEFT, wrap=True):
    return DS.text(slide, x, y, text, size=size, font=DS.T.HEAD if bold else DS.T.BODY,
                   color=color or DS.C.INK, w=w, h=0.28, bold=bold, align=align, wrap=wrap)


def bullets(slide, x, y, w, lines, size=11.5, gap=5, color=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.3))
    tf = tb.text_frame
    tf.word_wrap = True
    hang = int(Inches(0.02 * size))
    for i, t in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(gap)
        pPr = p._p.get_or_add_pPr()
        pPr.set("marL", str(hang))
        pPr.set("indent", str(-hang))
        r = p.add_run()
        r.text = "▷ " + t
        r.font.name = DS.T.BODY
        r.font.size = Pt(size)
        r.font.color.rgb = color or DS.C.INK700
    return tb


# ══════════════ 지도 ══════════════
class Map:
    """meta.map = {"png", "pic": {left_in, top_in, w_in, h_in, src}, "m_per_in"} — 승인본 좌표 계약.
    지도 위 미터 좌표 ↔ 위성 px 사상. P3 지도 어댑터(print_tile)가 이 블록을 채운다."""

    def __init__(self, meta_map: Dict, work_dir: str):
        self.png = meta_map["png"]
        self.img = Image.open(self.png).convert("RGB")
        self.PIC, self.MI = meta_map["pic"], float(meta_map["m_per_in"])
        self.work = work_dir
        os.makedirs(work_dir, exist_ok=True)

    def m2px(self, xm, ym):
        P = self.PIC
        return (P["src"][0] + (xm / self.MI - P["left_in"]) / P["w_in"] * P["src"][2],
                P["src"][1] + (ym / self.MI - P["top_in"]) / P["h_in"] * P["src"][3])

    def px2m(self, px, py):
        P = self.PIC
        return ((px / P["src"][2] * P["w_in"] + P["left_in"]) * self.MI,
                (py / P["src"][3] * P["h_in"] + P["top_in"]) * self.MI)

    def place(self, slide, crop_m, tag, left=0.9, top=1.25, max_w=7.2, max_h=5.4) -> MapFrame:
        x0, y0, x1, y1 = crop_m
        p0, p1 = self.m2px(x0, y0), self.m2px(x1, y1)
        px = [max(0, int(p0[0])), max(0, int(p0[1])), min(self.img.width, int(p1[0])), min(self.img.height, int(p1[1]))]
        fn = os.path.join(self.work, "_지도크롭_%s.png" % re.sub(r"\W+", "", tag))
        self.img.crop(px).resize(((px[2] - px[0]) * 3, (px[3] - px[1]) * 3), Image.LANCZOS).save(fn)
        xm0, ym0 = self.px2m(px[0], px[1])
        xm1, ym1 = self.px2m(px[2], px[3])
        ar = (xm1 - xm0) / (ym1 - ym0)
        w = min(max_w, max_h * ar)
        h = w / ar
        ox, oy = left + (max_w - w) / 2, top + (max_h - h) / 2
        slide.shapes.add_picture(fn, Inches(ox), Inches(oy), Inches(w), Inches(h))
        fr = MapFrame(ox, oy, w, h, xm0, ym0, xm1, ym1)
        fr.rect = (ox, oy, w, h)
        return fr


def place_leaders(slide, fr, marks, cap_x=CAP_X, gap=0.40, size=13):
    """지시 라벨을 지도 오른쪽 여백에 세로로 펼친다(규칙 16). marks = [(대상점 m, 글자, 이름)]"""
    L, T, W, H = fr.rect
    bx = L + W + 0.24
    tx = bx + 0.30
    tw = max(0.55, cap_x - 0.14 - tx)
    items = sorted([[Emu(fr.xy(*tgt)[1]).inches, tgt, ch, nm] for tgt, ch, nm in marks], key=lambda z: z[0])
    if not items:
        return []
    ys = [z[0] for z in items]
    # [V114] 표지가 많으면(9구역+ 밸브 번호 등) 간격을 지도 높이에 맞춘다 — 지면 아래로 넘치지 않게
    if len(ys) > 1:
        gap = min(gap, max(0.22, (H - 0.32) / (len(ys) - 1)))
    for i in range(1, len(ys)):
        if ys[i] - ys[i - 1] < gap:
            ys[i] = ys[i - 1] + gap
    over = ys[-1] - (T + H - 0.16)
    if over > 0:
        ys = [y - over for y in ys]
    if ys[0] < T + 0.16:
        ys = [y + (T + 0.16 - ys[0]) for y in ys]
    named = set()
    for y, (_, tgt, ch, nm) in zip(ys, items):
        lm = ((bx - fr.ox) / fr.s, (y - fr.oy) / fr.s)
        leader(slide, fr, tgt, lm, ch, size=size)
        # [V117 · C] 같은 기호·이름(말단 c 두 곳 등)은 이름을 한 번만 — 범례 「c 주배관 말단」 중복(7면)
        if nm and (ch, nm) not in named:
            label(slide, tx, y - 0.105, nm, size=8.0, color=DS.C.INK500, w=tw, bold=False)
            named.add((ch, nm))
    return items


# ══════════════ 렌더러 ══════════════
class Renderer:
    def __init__(self, job: Dict, summary: Dict, out_pptx: str, work_dir: Optional[str] = None, image_fetch=None):
        self.job, self.S, self.out = job, summary, out_pptx
        # [V117 · 3단계(b)] 부속 사진 공급자(code → data-URI) — 배포 서버엔 part_img_dir 이 없다(견적서와 같은 V109 image_fetch)
        self.image_fetch, self._fetched = image_fetch, {}
        self.site, self.design, self.meta = job["site"], job["design"], job.get("meta", {})
        self.work = work_dir or os.path.join(os.path.dirname(out_pptx), "_작업")
        self.map = Map(self.meta["map"], os.path.join(self.work, "지도크롭"))
        self.polys = [[tuple(p) for p in b["polygon"]] for b in self.site["blocks"]]
        self.routes = [dict(r, pts=[tuple(p) for p in r["pts"]]) for r in self.site["routes"]]
        self.lats = self.design["laterals"]
        self.tx = self.meta.get("texts", {})
        self.water = self.meta.get("water", {})
        self.img_dir = self.meta.get("part_img_dir")
        zones = [str(r.get("zone")) for r in self.routes if r.get("zone") is not None]
        self.zone_color = {}
        self.zone_cname = {}
        for i, z in enumerate(dict.fromkeys(zones)):
            col, nm = ((ov.PIPE_MAIN, "노랑") if i == 0 else (LINE2, "보라") if i == 1
                       else ZONE_PALETTE[(i - 2) % len(ZONE_PALETTE)])
            self.zone_color[z], self.zone_cname[z] = col, nm
        self.qr_dir = os.path.join(self.work, "_qr")
        try:
            from .publish import _price_db as _pdbf
            _pdb = _pdbf(self.meta)
        except Exception:
            _pdb = {}
        self.price_db = _pdb                    # [V116] 연결 도해의 품목 이름
        self.qr_links = QR.links(_pdb)          # {코드: 설치 영상 URL} — 정본 = AQ_Items `QR링크`
        self.log: List[str] = []
        # [V114] 구역 밸브 번호 = **구역당 하나**(V1 = 첫 구역 …). 자리 = 그 구역이 처음 나오는 분배점(headers · 규칙 21).
        #    한 구역이 T 로 두 갈래여도 번호는 하나다(05 숙진리 2구역 — 분배점 기준으로 세면 V3 이 생겼다 · 시각 검사).
        #    분배점에 없는 구역은 자리를 짓지 않는다(운전표 = [미확정]).
        self.valves, self.valve_of = [], {}
        first = {}
        for h in summary.get("headers") or []:
            for z in h.get("zones") or []:
                if z is not None and str(z) not in first:
                    first[str(z)] = h
        by_pt = {}
        for k, z in enumerate(summary.get("zones") or [], 1):
            zk = str(z["zone"])
            h = first.get(zk)
            self.valve_of[zk] = {"id": "V%d" % k, "pt": h["pt"] if h else None}
            if h:
                by_pt.setdefault(tuple(h["pt"]), []).append(("V%d" % k, zk))
        for pt, vz in by_pt.items():
            ids = [v for v, _ in vz]
            self.valves.append({"pt": list(pt), "mark": ids[0] if len(ids) == 1 else "%s~" % ids[0],
                                "names": "%s (%s)" % ("·".join(ids), "·".join(z if z.endswith("구역") else z + "구역" for _, z in vz))})

    # ── 그리기 층 ──
    def draw_field(self, s, fr, color=ov.DIM, w=2.2):
        for poly in self.polys:
            pipe(s, fr, poly + [poly[0]], color=color, weight=w, dash=MSO_LINE_DASH_STYLE.DASH)

    def draw_buried(self, s, fr, w=W_BURIED, pipes=True):
        if not self.water.get("buried"):
            return
        pipe(s, fr, [tuple(p) for p in self.water["buried"]], color=BURIED, weight=w, dash=MSO_LINE_DASH_STYLE.ROUND_DOT)
        if pipes:
            for pp in self.water.get("pipes", []):
                pipe(s, fr, [tuple(pp["tail"]), tuple(pp["tip"])], color=BURIED, weight=w + 0.8)
                head_dot(s, fr, pp["tip"][0], pp["tip"][1], r_in=0.035, color=BURIED)

    # ── [계통도] 인입관 · 급수 지점 · 압력계 세트 표식 ──
    def _feed_paths(self):
        """인입관 경로(m 좌표 목록). site 에 role=feeder 경로가 있으면 그것을, 없으면 급수원 → 가장 가까운 주배관 끝점을 잇는
        짧은 선 하나. **새 좌표를 만들지 않는다**(기존 점만 잇는다) — 매니폴드 위치 = 주배관 경로 끝점."""
        from .site import route_role
        fed = [[tuple(p) for p in r["pts"]] for r in self.routes if route_role(r) == "feeder" and len(r["pts"]) >= 2]
        if fed:
            return fed
        srcs = self.S.get("sources") or []
        mains = [r for r in self.routes if route_role(r) != "feeder" and r.get("pts")]
        if not srcs or not mains:
            return []
        src = tuple(srcs[0]["pt"])
        ends = [tuple(p) for r in mains for p in (r["pts"][0], r["pts"][-1])]
        tgt = min(ends, key=lambda q: (q[0] - src[0]) ** 2 + (q[1] - src[1]) ** 2)
        return [[src, tgt]] if (tgt[0] - src[0]) ** 2 + (tgt[1] - src[1]) ** 2 > 1e-8 else []

    @staticmethod
    def _poly_len(pts):
        return sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(pts, pts[1:]))

    @classmethod
    def _poly_mid(cls, pts):
        half, acc = cls._poly_len(pts) / 2.0, 0.0
        for a, b in zip(pts, pts[1:]):
            d = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            if d > 0 and acc + d >= half:
                t = (half - acc) / d
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            acc += d
        return tuple(pts[-1])

    def feed_geom(self, fr):
        """→ {"lines": [[pt…]…], "dot": 급수 지점 표시 좌표, "gauge": 압력계 표식 좌표|None, "displaced": 표시만 띄웠나}.
        급수 지점 쪽 끝에서 선이 화면 길이 FEED_MIN_IN 보다 짧으면 **표시만** 같은 방향으로 이어 띄운다(실제 좌표는 그대로 ·
        지도에서 밭에 붙은 초록 점이 선 없이 묻히던 문제)."""
        srcs = self.S.get("sources") or []
        src = tuple(srcs[0]["pt"]) if srcs else None
        paths = self._feed_paths()
        g = {"lines": [], "dot": src, "gauge": None, "displaced": False}
        if not paths:
            return g
        if src is None:
            src = paths[0][0]
        d2 = lambda a, b: (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
        pi, end = min(((i, e) for i, pts in enumerate(paths) for e in (0, -1)), key=lambda ie: d2(paths[ie[0]][ie[1]], src))
        line = list(paths[pi]) if end == 0 else list(reversed(paths[pi]))
        poly = ([src] if d2(src, line[0]) > 1e-4 else []) + line          # 급수원 점 → 인입관 시작(기존 점끼리)
        g["dot"] = poly[0]
        if self._poly_len(poly) * fr.s < FEED_MIN_IN:
            nxt = next((q for q in poly[1:] if d2(q, poly[0]) > 1e-8), None)
            if nxt is not None:
                d = d2(nxt, poly[0]) ** 0.5
                ext = (FEED_MIN_IN - self._poly_len(poly) * fr.s) / fr.s
                dot = (poly[0][0] + (poly[0][0] - nxt[0]) / d * ext, poly[0][1] + (poly[0][1] - nxt[1]) / d * ext)
                poly, g["dot"], g["displaced"] = [dot] + poly, dot, True
        g["lines"] = [poly] + [p for i, p in enumerate(paths) if i != pi]
        g["gauge"] = self._poly_mid(poly)
        return g

    def draw_feeder(self, s, fr, gauge=False, w=W_MAIN):
        """인입관(초록 선) + 급수 지점(초록 점) + [gauge] 압력계 세트 표식(작은 원 + 라벨). 선이 없어도 점은 그린다."""
        g = self.feed_geom(fr)
        for pts in g["lines"]:
            pipe(s, fr, pts, color=FEED, weight=w + 0.5)
        for k, src in enumerate(self.S.get("sources") or []):
            q = g["dot"] if (k == 0 and g["dot"] is not None) else src["pt"]
            head_dot(s, fr, q[0], q[1], r_in=0.07, color=GRN)
        if g["displaced"] and not getattr(self, "_disp_logged", False):
            self._disp_logged = True
            self.log.append("지도: 급수 지점이 밭에 붙어 있어 초록 점·인입관을 표시만 밭에서 띄움(실제 좌표 무변경)")
        if gauge and g["gauge"] is not None:
            gx, gy = fr.xy(*g["gauge"])
            r = 0.095
            ring = s.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(gx - Inches(r))), Emu(int(gy - Inches(r))), Inches(2 * r), Inches(2 * r))
            ring.fill.solid()
            ring.fill.fore_color.rgb = DS.C.WHITE
            ring.line.color.rgb = ov.DIM
            ring.line.width = Pt(2.0)
            ring.shadow.inherit = False
            tf = ring.text_frame
            tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
            tf.word_wrap = False
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            rr = p.add_run()
            rr.text = "P"
            rr.font.name, rr.font.size, rr.font.bold = DS.T.HEAD, Pt(7), True
            rr.font.color.rgb = ov.DIM
            tb = label(s, Emu(gx).inches - 0.84, Emu(gy).inches - 0.33, "압력계 세트", size=8.5, color=ov.DIM, w=0.70,
                       align=PP_ALIGN.RIGHT)
            tb.height = Inches(0.17)
            tb.text_frame.margin_right = Inches(0.03)
            tb.fill.solid()
            tb.fill.fore_color.rgb = DS.C.WHITE
        return g

    def draw_main(self, s, fr, w=W_MAIN, only=None, gauge=False):
        from .site import route_role
        for r in self.routes:
            if route_role(r) == "feeder":                    # 인입관은 아래 draw_feeder(초록)가 그린다
                continue
            z = None if r.get("zone") is None else str(r["zone"])
            col = ov.PIPE_MAIN if z is None else self.zone_color.get(z, ov.PIPE_MAIN)
            if only is not None and z is not None and z != only:
                col = ov.GREY
            pipe(s, fr, r["pts"], color=col, weight=w + (0.5 if z is None else 0))
        for p, _tag in self.S["tees"]:
            head_dot(s, fr, p[0], p[1], r_in=0.055, color=ov.INK)
        self.draw_feeder(s, fr, gauge=gauge, w=w)

    def draw_joints(self, s, fr, r_in=0.055):
        for j in (self.S["joints"] if len(self.S["joints"]) <= 4 else []):   # [R06] 많으면 점도 생략(캡션 수치)
            head_dot(s, fr, j["pt"][0], j["pt"][1], r_in=r_in, color=ov.DIM)

    def draw_lats(self, s, fr, w=W_LAT, ids=None):
        bad = set((self.S.get("unconnected") or {}).get("ids") or [])     # [V114 · F09] 급수 불가 열 = 빨강
        for l in self.lats:
            if ids is None or l["id"] in ids:
                pts = [tuple(q) for q in (l.get("path") or [l["p0"], l["p1"]])]
                pipe(s, fr, pts, color=(BAD if l["id"] in bad else ov.PIPE_SUB), weight=w)

    def draw_heads(self, s, fr, r_in=0.045, ids=None):
        for l in self.lats:
            if ids is None or l["id"] in ids:
                for hx, hy in l["heads"]:
                    head_dot(s, fr, hx, hy, r_in=r_in)

    def part_png(self, code):
        if self.img_dir:
            p = os.path.join(self.img_dir, "%s.png" % code)
            if os.path.exists(p):
                return p
        if self.image_fetch is not None:        # [V117 · 3단계(b)] 폴더에 없으면 앱의 드라이브 사진(견적서와 같은 공급자)
            if code not in self._fetched:
                self._fetched[code] = None
                try:
                    uri = self.image_fetch(code)
                    if uri:
                        import base64
                        raw = base64.b64decode(uri.split(",", 1)[1] if "," in uri else uri)
                        d = os.path.join(self.work, "_부속사진")
                        os.makedirs(d, exist_ok=True)
                        fn = os.path.join(d, "%s.png" % code)
                        Image.open(io.BytesIO(raw)).save(fn, "PNG")
                        self._fetched[code] = fn
                except Exception as e:
                    self.log.append("부속 사진 가져오기 실패 %s(%s)" % (code, type(e).__name__))
            if self._fetched.get(code):
                return self._fetched[code]
        self.log.append("부속 사진 없음 %s" % code)
        return None

    # ── 연결부 카드(정본 §5 카드+칩+뱃지) ──
    def set_card(self, s, x, y, w, ch, title, setname, parts, note, h=None):
        """parts = [(code, 이름, 규격)] — 부속은 전부 칩 안에(정본 §5-1)."""
        h = h or DS.CARD.H
        DS.card(s, x, y, w, h=h)                      # 세트명은 제목 아래 한 줄(겹침 금지)
        DS.badge(s, x + DS.BADGE.IN, y + DS.BADGE.IN, ch)
        label(s, x + DS.BADGE.IN + DS.BADGE.D + 0.10, y + DS.BADGE.IN, title, size=12, w=w - 0.9)
        DS.text(s, x + DS.BADGE.IN + DS.BADGE.D + 0.10, y + DS.BADGE.IN + 0.30, "세트  %s" % setname,
                size=9.5, font=DS.T.CAPTION, color=DS.C.INK500, w=w - 0.9, h=0.20)
        cx = x + 0.22
        cy = y + 0.78
        # [V117 · C] 칩 띠가 카드·지면 밖으로 나가면(8면 T분기 5칩 — 오른쪽 잘림) 같은 부속을 한 칩으로 묶는다(수량은 ×n).
        if cx + (len(parts) - 1) * DS.CHIP.PITCH_MIN + DS.CHIP.FRAME_W > min(x + w + 0.1, DS.SLIDE_W - 0.1):
            parts = _merge_parts(parts)
        pitch = min(DS.CHIP.PITCH_MAX, max(DS.CHIP.PITCH_MIN, (w - 0.44) / max(1, len(parts))))
        items = [(nm, sp, self.part_png(code)) for code, nm, sp in parts]
        DS.chip_row(s, cx, cy, items, pitch=pitch)
        for i, (_nm, _sp, png) in enumerate(items):          # [V114] 빈 사진 칸은 비워 두되 이유를 적는다
            if png is None:
                DS.text(s, cx + i * pitch, cy + DS.CHIP.FRAME_H * 0.38, "사진 미등록\n%s" % parts[i][0], size=8,
                        font=DS.T.CAPTION, color=DS.C.INK500, w=DS.CHIP.FRAME_W, h=0.4, align=PP_ALIGN.CENTER)
        DS.text(s, x + 0.22, y + h - 0.52, note, size=9.5, font=DS.T.BODY, color=DS.C.INK700, w=w - 0.44, h=0.48)

    # ── 부속 설치 영상 QR (대표 지시 2026-09-04) ──
    def video_page(self, prs, anchor, codes):
        """QR링크가 있는 부속만 모아 한 면에 세운다 — 낱개 칩 옆에 QR, 그림 자체에 하이퍼링크.

        지저분해지지 않게 **부속이 나오는 면마다 흩뿌리지 않고 한 면에 모은다**(대표 지시).
        QR 변 = 0.85 in ≈ 21.6 mm — 인쇄 정본 §5-1의 최소 15 mm 위. PDF에서는 눌러도 열린다.
        """
        rows = [(c, self.qr_links[c]) for c in codes if c in self.qr_links]
        if not rows:
            return None
        s = new_slide_before(prs, anchor)
        clear_slide(s, keep_top_in=0.0)
        DS.title(s, "부속 설치 영상",
                 "QR을 휴대폰 카메라로 비추면 설치 영상이 열립니다 — PDF로 보실 때는 QR을 그대로 누르셔도 됩니다")
        names = {b["code"]: (b.get("name", ""), b.get("spec", "")) for b in self.S["bom"]}
        NCOL, GAP = 4, 0.26
        cw = (DS.SLIDE_W - DS.G.MARGIN_L - DS.G.MARGIN_R - GAP * (NCOL - 1)) / NCOL
        qs = 0.85                                     # QR 변(in) — 21.6 mm
        y0, pitch_y = DS.G.ROW1_Y + 0.34, 2.30
        for i, (code, url) in enumerate(rows):
            x = DS.G.MARGIN_L + (i % NCOL) * (cw + GAP)
            y = y0 + (i // NCOL) * pitch_y
            nm_full, sp = names.get(code, ("", ""))
            nm = re.sub(r"\s*\(.*?\)", "", re.sub(r"^스마트카플러\s*", "", nm_full)).strip() or code
            DS.chip(s, x, y, nm, "", self.part_png(code))   # 규격은 아래 줄로 — 이름표 넘침 방지
            qx, qy = x + DS.CHIP.FRAME_W + 0.20, y + (DS.CHIP.FRAME_H - qs) / 2
            png = QR.png(url, self.qr_dir)
            if png:
                pic = s.shapes.add_picture(png, Inches(qx), Inches(qy), Inches(qs), Inches(qs))
                try:
                    pic.click_action.hyperlink.address = url      # PDF에서 눌러서 열기
                except Exception:
                    self.log.append("QR 하이퍼링크 실패 %s" % code)
            else:
                DS.text(s, qx, qy + qs * 0.35, "영상 준비중", size=9, font=DS.T.CAPTION,
                        color=DS.C.INK500, w=qs, h=0.24, align=PP_ALIGN.CENTER)
                self.log.append("QR 생성 실패 %s" % code)
            DS.text(s, qx, qy + qs + 0.06, "▶ 눌러서 보기", size=8.5, font=DS.T.CAPTION,
                    color=DS.C.INK500, w=qs + 0.3, h=0.20)
            DS.text(s, x, y + DS.CHIP.FRAME_H + DS.CHIP.GAP_BELOW + DS.CHIP.NAME_H + 0.06,
                    "%s  ·  %s%s" % (code, nm_full, ("  ·  " + sp) if sp else ""),
                    size=8.5, font=DS.T.CAPTION, color=DS.C.INK500, w=cw, h=0.34)
        caption(s, DS.G.MARGIN_L, y0 + ((len(rows) - 1) // NCOL) * pitch_y + 1.86,
                DS.SLIDE_W - DS.G.MARGIN_L - DS.G.MARGIN_R,
                "설치 영상 %d편 — 스마트카플러 · 조임식 연결구" % len(rows),
                ["영상은 부속 조립 순서만 보여줍니다 — 배관 경로·헤드 자리는 앞의 지면을 따르십시오",
                 "인쇄본에서는 QR을 찍으시고, 화면(PDF)에서는 QR을 누르시면 같은 영상이 열립니다"])
        self.log.append("설치 영상 면 %d개소" % len(rows))
        return s

    # ── [계통도] 물 공급 계통도 지면 — 대표 작도(sketch_pages)가 없을 때 코드로 그린다 ──
    def _water_diagram(self, prs, anchor):
        """오른쪽 펌프(고객 보유)·여과기 → 노란 송수호스 → ① 첫 연결부(WF 4-1 + 호스밴드 + WF 4-2 = 일자연결 세트) → 인입관 위 ② 압력계 세트
        (루퍼젯 H20 + 압력계) → ③ 매니폴드(CCCT T + E호스밸브 = 1구역 / 변형 L보 + E호스밸브 = 2구역). 구역 1개면 밸브 1개.
        부속 코드 = 대표 지정표(WD_BY_MM · WD_COMMON · 관경은 설계 main_mm). 사진이 없으면 「사진 없음」 칸(빈칸 금지)."""
        S = self.S
        mm = int(S.get("main_mm") or 50)
        if mm not in WD_BY_MM:
            self.log.append("계통도: 주배관 %s mm 부속 대응 없음 — 50 mm 부속으로 그림(확인 필요)" % mm)
            mm = 50
        K = dict(WD_COMMON, **WD_BY_MM[mm])
        zn = [str(z["zone"]) for z in (S.get("zones") or [])] or [z for z in self.zone_color] or ["1"]
        nz = len(zn)
        bom_codes = {str(b.get("code")) for b in S.get("bom") or []}
        miss = [c for c in ("wf41", "wf42", "h20", "gauge", "e_valve") if K[c] not in bom_codes]
        if miss:
            self.log.append("계통도 부속 중 견적(BOM)에 없는 것: %s — 그림에는 표시(급수 계통 품목 여부 확인)"
                            % " · ".join("%s %s" % (WD_NAMES.get(K[c], c), K[c]) for c in miss))
        s = new_slide_before(prs, anchor)
        DS.title(s, "물 공급 계통도", "펌프에서 매니폴드까지 — 오른쪽에서 왼쪽으로 물이 지나는 순서입니다 · 주배관 %d mm 기준" % mm)
        RED = ov.DIM
        W_, H_ = DS.CHIP.FRAME_W, DS.CHIP.FRAME_H
        CH = H_ + DS.CHIP.GAP_BELOW + DS.CHIP.NAME_H
        PITCH, PAD, GAP = 0.93, 0.12, 0.62
        yA = 2.0 if nz >= 2 else 2.55                                         # 구역 1개면 밸브 한 줄이라 지면 가운데 쪽으로
        ycA = yA + H_ / 2
        yB = yA + CH + 0.34
        ycB = yB + H_ / 2
        # 가로 배치 — 오른쪽(펌프)에서 왼쪽으로
        PX = DS.SLIDE_W - DS.G.MARGIN_R - 1.59
        r1 = PX - GAP
        x1 = [r1 - PAD - W_ - PITCH * i for i in range(3)]                    # WF 4-1 · 호스밴드 · WF 4-2 (일자연결 세트)
        l1 = x1[-1] - PAD
        r2 = l1 - GAP
        x2 = [r2 - PAD - W_ - PITCH * i for i in range(2)]                    # H20 · 압력계
        l2 = x2[-1] - PAD
        r3 = l2 - GAP
        n3 = 3 if nz >= 2 else 2
        x3 = [r3 - PAD - W_ - PITCH * i for i in range(n3)]                   # WF 4-2 · T · E호스밸브 (구역 1개면 WF 4-2 · E호스밸브)
        l3 = min(x3[-1] - PAD, r3 - 2.35)                                      # 묶음 이름표(「③ 매니폴드(구역 밸브 N)」)가 들어가는 폭

        # 노란 송수호스 · 인입관 — 사진 칸 뒤로 지나간다
        BAR = 0.16
        hose = lambda xa, ya, xb, yb: DS._rect(s, MSO_SHAPE.RECTANGLE, min(xa, xb), min(ya, yb), abs(xb - xa) or BAR, abs(yb - ya) or BAR,
                                               fill=ov.PIPE_MAIN)
        hose(x3[-1] + W_ / 2, ycA - BAR / 2, PX, ycA + BAR / 2)
        if nz >= 2:
            tcx = x3[1] + W_ / 2
            hose(tcx - BAR / 2, ycA, tcx + BAR / 2, ycB)                       # T 에서 아래로 — 2구역 쪽
            hose(x3[2] + W_ / 2, ycB - BAR / 2, tcx, ycB + BAR / 2)
        # 펌프·여과기 — 고객 보유(사진 없음 · 이름 박스)
        pump_nm = str((self.site.get("pump") or {}).get("model") or "").strip()
        pump_nm = "" if (pump_nm in ("없음", "미정", "[미확정]") or len(pump_nm) > 14) else pump_nm     # 긴 설명문은 박스에 안 넣는다
        for (bx, by, bw, bh, t1, t2) in ((PX, ycA - 0.45, 1.59, 0.90, "펌프", "(고객 보유)" + (" · %s" % pump_nm if pump_nm else "")),
                                         (PX + 0.20, ycA - 0.45 - 0.78, 1.19, 0.52, "여과기", "(급수원 쪽)")):
            DS._rect(s, MSO_SHAPE.ROUNDED_RECTANGLE, bx, by, bw, bh, fill=RGBColor(0xF4, 0xF4, 0xF0), line=DS.C.CARD_LINE, line_pt=1.0)
            DS.text(s, bx, by + 0.07, t1, size=11, font=DS.T.HEAD, color=DS.C.INK, w=bw, h=0.22, bold=True, align=PP_ALIGN.CENTER)
            DS.text(s, bx, by + 0.30, t2, size=9, font=DS.T.CAPTION, color=DS.C.INK500, w=bw, h=0.40, align=PP_ALIGN.CENTER)
        DS._rect(s, MSO_SHAPE.RECTANGLE, PX + 0.20 + 1.19 / 2 - 0.02, ycA - 0.45 - 0.26, 0.04, 0.26, fill=DS.C.BURIED)
        # 호스 이름표 — 칸 사이 틈
        for gx, tx_ in ((r1, "송수호스"), (r2, "인입관"), (r3, "인입관")):
            DS.text(s, gx, ycA - BAR / 2 - 0.27, tx_, size=9, font=DS.T.CAPTION, color=DS.C.INK500,
                    w=GAP if tx_ != "송수호스" else PX - r1, h=0.2, align=PP_ALIGN.CENTER)

        def part(x, y, code, name=None, spec=None):
            png = self.part_png(code)
            DS.chip(s, x, y, name or WD_NAMES.get(code, code), spec or code, png)
            if png is None:                                     # 빈칸 금지 — 사진이 없으면 그 자리에 이유를 적는다
                DS.text(s, x, y + H_ * 0.34, "사진 없음", size=8.5, font=DS.T.CAPTION, color=DS.C.INK500, w=W_, h=0.3, align=PP_ALIGN.CENTER)

        part(x1[0], yA, K["wf41"])
        part(x1[1], yA, K["band"])
        part(x1[2], yA, K["wf42"])
        part(x2[0], yA, K["h20"])
        part(x2[1], yA, K["gauge"])
        zc = lambda i: (self.zone_color.get(zn[i]) if self.zone_color.get(zn[i]) else (ov.PIPE_MAIN, LINE2)[min(i, 1)])

        def ztag(x, y, i):
            col = zc(i)
            lum = 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]
            nm = zn[i] if zn[i].endswith("구역") else zn[i] + "구역"
            sh = DS._rect(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, W_, 0.24, fill=col)
            DS.text(s, x, y + 0.035, nm + " 밸브", size=9, font=DS.T.HEAD, color=(DS.C.WHITE if lum < 140 else DS.C.INK),
                    w=W_, h=0.2, bold=True, align=PP_ALIGN.CENTER)
        part(x3[0], yA, K["wf42"])                                     # 인입관 → 매니폴드 입구
        if nz >= 2:
            part(x3[1], yA, K["ccct"], spec="01201 · T")
            part(x3[2], yA, K["e_valve"])
            ztag(x3[2], yA - 0.30, 0)
            part(x3[1], yB, K["elbow"])
            part(x3[2], yB, K["e_valve"])
            ztag(x3[2], yB - 0.30, 1)
        else:
            part(x3[1], yA, K["e_valve"])
            ztag(x3[1], yA - 0.30, 0)
        # 빨간 둥근 테두리 + 번호·이름 라벨 — ① ② ③ 묶음
        top = yA - 0.31
        for (lx, rx, bot, nm) in ((l1, r1, yA + CH + 0.16, "① 첫 연결부(일자연결 세트)"), (l2, r2, yA + CH + 0.16, "② 압력계 설치"),
                                  (l3, r3, (yB + CH + 0.16) if nz >= 2 else (yA + CH + 0.16), "③ 매니폴드(구역 밸브 %d)" % nz)):
            sh = DS._rect(s, MSO_SHAPE.ROUNDED_RECTANGLE, lx, top, rx - lx, bot - top, fill=None, line=RED, line_pt=2.25)
            try:
                sh.adjustments[0] = 0.07
            except Exception:
                pass
            DS.text(s, lx, top - 0.38, nm, size=13, font=DS.T.HEAD, color=RED, w=max(rx - lx, 2.4), h=0.28, bold=True, wrap=False)
        # 한 줄 설명 + 각주
        yb = (yB + CH + 0.36) if nz >= 2 else (yA + CH + 0.55)
        DS._rect(s, MSO_SHAPE.ROUNDED_RECTANGLE, DS.G.MARGIN_L, yb, DS.SLIDE_W - DS.G.MARGIN_L - DS.G.MARGIN_R, 0.50, fill=RGBColor(0xF4, 0xF4, 0xF0))
        DS.text(s, DS.G.MARGIN_L + 0.2, yb + 0.12, "첫 연결부 → 매니폴드 사이가 인입관 · 압력계는 인입관 위에 · 구역 전환은 매니폴드 밸브로",
                size=13, font=DS.T.HEAD, color=DS.C.INK, w=DS.SLIDE_W - 2 * DS.G.MARGIN_L - 0.4, h=0.3, bold=True)
        notes = ["노란 선 = 송수호스·인입관 · 부속 코드는 주배관 %d mm 기준 — 지도의 초록 선이 이 인입관입니다" % mm]
        if nz >= 3:
            notes[0] += " · 구역 %d개 — 3구역째부터의 매니폴드 구성은 [미확정](그림은 2구역 기준)" % nz
        for i, t in enumerate(notes):
            DS.text(s, DS.G.MARGIN_L + 0.2, yb + 0.62 + i * 0.24, t, size=10, font=DS.T.CAPTION, color=DS.C.INK500,
                    w=DS.SLIDE_W - 2 * DS.G.MARGIN_L - 0.4, h=0.22)
        self.log.append("물 공급 계통도 면 추가(코드 작도 · %d mm · %d구역)" % (mm, nz))
        return s

    # ── 지면 ──
    def build(self) -> str:
        S, meta, tx = self.S, self.meta, self.tx
        os.makedirs(os.path.dirname(self.out), exist_ok=True)
        shutil.copy(MASTER, self.out)
        prs = Presentation(self.out)
        sl = list(prs.slides)
        P = {k: (sl[v] if isinstance(v, int) else [sl[i] for i in v]) for k, v in M.items()}
        fmt_n = lambda v: format(v, ",")

        self._fix_fixed(sl)

        # 01 표지 — [V117 · 2단계] 관급·건설은 「발주처 · 현장명 · 담당」(design.segments) · 농업은 현행 그대로
        from . import segments as _SG
        _qh = meta.get("quote") or {}
        _hd = _SG.head_line(_SG.profile(self.site), _qh.get("recipient", ""), S["name"], _qh.get("manager", ""))
        replace_text(P["표지"], "{{대상지}}", _hd or "%s · %s" % (meta.get("site_short", S["site_label"]), S["name"]))
        # [V114 · F06] 관문 표지 — 정상 초안이 아니면 표지에 적는다(발행 전 대표가 지운다 · 조용히 완성처럼 두지 않는다).
        g = S.get("gate") or {}
        if g.get("level") and g["level"] != "ok":
            label(P["표지"], 7.6, 6.72, "● " + g["label"], size=11,
                  color=(BAD if g["level"] == "blocked" else DS.C.INK500), w=5.2, align=PP_ALIGN.RIGHT)

        # 04 상호 확인사항
        s = P["상호확인"]
        est = lambda texts: 0.20 + sum(-(-len(t) // 52) for t in texts) * 0.34     # 문단 높이 어림(in)
        # 🔴 [V114 · F04] 급수원·공급 범위는 **입력된 사실**(summary.scope)만 쓴다 — 모르면 「확인 필요」.
        #    예전 기본값 「고객 보유 — 펌프 토출측 여과기부터」는 입력이 없어도 사실처럼 나갔다.
        SC = S.get("scope") or {}
        water_texts = [self.water.get("start_line") or SC.get("start_line", "급수원 [확인 필요]")]
        water_texts += list(tx.get("topo", [])) or [SC.get("buried", "매설·기설 배관 — 입력 없음 [현장 확인]")]
        # [V114 · F02] 「한 구역 최대 25두 이내」 고정 문구 폐기 — 구역 두수는 설계값, 가동 가능 여부는 급수 조건이 정한다.
        water_texts.append("헤드 간격 %s m · 총 %d두 · %d구역(%s두) — 구역별 필요 유량·압력은 부록 「급수·연결 조건」"
                           % (S["head_gap"], S["n_heads"], len(S["zones"]),
                              " · ".join(str(z["n_heads"]) for z in S["zones"]) or "-"))
        filt_texts = tx.get("filter_note") or ["스프링클러 설치 시, 반드시 여과기를 설치해야 합니다",
                                              SC.get("filter", "여과기 설치 여부를 확인해 주세요"),
                                              "여과기 미설치·미청소로 인한 피해에 대해 당사에게 책임을 물을 수 없음"]
        y_water, y_filt = 1.30, 1.30 + est(water_texts) + 0.22
        for sh in s.shapes:
            if not sh.has_text_frame:
                continue
            t = sh.text_frame.text
            if "설계 제안" in t:
                set_paragraphs(sh, water_texts)
                sh.height = Inches(est(water_texts))
            elif "여과기를 설치" in t:
                set_paragraphs(sh, filt_texts)
                sh.top, sh.height = Inches(y_filt), Inches(est(filt_texts))
            elif t.strip() == "여과기":
                sh.top = Inches(y_filt)
        y_note = y_filt + est(filt_texts) + 0.25
        SP = S.get("spray") or {"r_out": 10.0, "r_in": 7.0, "p_bar": 1.5, "basis": ""}
        UN = S.get("unconnected") or {"rows": 0, "heads": 0}
        # 🔴 [V114 · F02] 「끝까지 물이 갑니다」 → 계산 조건을 말하는 문장. 커버율 = 연결된 헤드 · 설계 반경 · 배치상 범위.
        RD = _SL(SP)                                  # [V117 · K-07] R·Ø 표기 = 한 값·한 규칙(summary.spray_labels)
        lines = [(ov.DIM, "※ 살수 반경 %s m — %s. 급수원이 그 압력을 낼 때의 배치상 범위입니다(현장 실측 아님)"
                  % (RD["r_out"], SP["basis"] or "설계 말단압 기준")),
                 (DS.C.INK500, "   두둑과 나란히 가지관을 눕혀 배치상 커버율 %.0f %% · 헤드–경계 %.1f m 이상 — 열 끝은 간격을 좁혀 헤드를 하나 더 넣었습니다(규칙 11)"
                  % (S["cover"] * 100, S["edge_min_m"]))]
        if UN["rows"]:
            lines.append((BAD, "※ 주배관에 닿지 않는 가지관 %d열 · %d두 — 급수 불가(커버율에서 뺐습니다). 경로를 고치기 전에는 설치할 수 없습니다"
                          % (UN["rows"], UN["heads"])))
        if S.get("supply"):
            lines.append((DS.C.INK500, "※ 급수원 정보와 무관하게 구역별 필요 유량·압력을 계산했습니다. 부록 ‘급수·연결 조건’을 확인하세요."))
        elif S["hydro"]:
            worst = min(S["hydro"], key=lambda r: r["p_end"])
            pump = worst.get("pump", "[미확정]")
            if "need_hp" in worst:
                lines.append((DS.C.INK500, "※ 펌프 [미확정] — 최대 구역 %d두 요구 = %d L/분 @ %d m (축동력 %.1f HP 이상)"
                              % (worst["heads"], worst["Q"], worst["need_head_m"], worst["need_hp"])))
            else:
                lines.append((DS.C.INK500, "※ 펌프 %s 1대(농가 보유) — 최대 구역 %d두 말단 %.2f bar · 살수 반경 %.1f m → %s"
                              % (pump, worst["heads"], worst["p_end"], worst["radius_end"],
                                 ("목표 1.50 bar(반경 10 m)에 %.2f bar 부족 — %d두로 줄이면 맞습니다" % (1.5 - worst["p_end"], worst.get("cap_15bar", worst["heads"])))
                                 if worst["p_end"] < 1.5 else "목표(1.50 bar · 반경 10 m) 만족. 구역별 운전점은 살수 예시 면에")))
        y_foot = max(4.45, y_note)
        tb = s.shapes.add_textbox(Inches(0.6), Inches(y_foot), Inches(12.1), Inches(1.9))
        tb.text_frame.word_wrap = True
        for i, (col, t) in enumerate(lines):
            p = tb.text_frame.paragraphs[0] if i == 0 else tb.text_frame.add_paragraph()
            r = p.add_run()
            r.text = t
            r.font.name = DS.T.HEAD
            r.font.size = Pt(12.0)
            r.font.bold = True
            r.font.color.rgb = col
            p.space_after = Pt(4)
        # 각주 아래 빈자리 — 면19 표가 길면 「다음 단계」가 여기로 내려온다
        self.p4_free_y = y_foot + 0.05 + sum(est_lines(t, 12.10, 12.0) for _, t in lines) * 0.255

        # 05 대상지 개요
        s = P["대상지"]
        clear_slide(s)
        set_title(s, "대상지 개요")
        fr = self.map.place(s, meta["map"]["wide_m"], "전체", left=0.8, top=1.2, max_w=7.6, max_h=5.9)
        self.draw_field(s, fr, ov.DIM, 2.5)
        self.draw_buried(s, fr, 2.0)
        _fg = self.draw_feeder(s, fr, gauge=True, w=2.5)        # [계통도] 인입관(초록 선) · 급수 지점 · 압력계 세트 표식
        caption(s, 8.7, 1.45, 4.3, S["name"], [
            "살수 면적 약 %s ㎡ (약 %s 평)" % (fmt_n(S["area_m2"]), fmt_n(S["area_py"])),
            tx.get("size_txt", "블록 %d개" % len(self.polys)),
            "빨간 점선 = 이번 제안 대상지",
            # [V114 · F04] 매설관 입력이 없으면 「없음」이 아니라 「입력 없음 — 현장 확인」이다.
            tx.get("wide_note", ("회색 점선 = 기설 매설 배관 %.0f m (농가)" % self.water["buried_len_m"])
                   if self.water.get("buried") else SC.get("buried", "매설·기설 배관 — 입력 없음 [현장 확인]")),
            "초록 점 = %s" % self.water.get("start_kind", SC.get("start_kind", "급수 시작점")),
        ] + (["초록 선 = 인입관 · P = 압력계 세트"] if _fg["lines"] else []), title_color=ov.DIM)

        # 05-a 현장 사진(당사 현장답사 · V116) — 실제 파일만. 자리가 있으면 대상지 지도에 같은 번호를 단다.
        self._photo_pages(prs, P["주배관"], s, fr)

        # 05-c 연결 사슬 도해(V116 · 견적 포함 · 예시) — 연결부 상세 면들 뒤, 헤드 성능 면 앞
        self._chain_pages(prs, P["헤드성능"])

        # 05-b 대표 계통도 지면 (규칙 7 — 그대로 옮긴다)
        for sp in meta.get("sketch_pages", []):
            src = Presentation(sp["pptx"])
            ns = new_slide_before(prs, P["주배관"])
            copy_shapes(ns, src.slides[sp["slide"]], dx_in=sp.get("dx_in", 0.0), dy_in=sp.get("dy_in", 0.0))
            for old, new in sp.get("replace", []):
                replace_text(ns, old, new)
            self._scan_copied(ns, sp["title"][:12])
            label(ns, 0.62, 0.42, sp["title"], size=24, w=11.5)
            cx, cy, cw = sp.get("cap_xy", (8.75, 1.30, 4.2))
            ts, bs = sp.get("cap_size", (16, 11.5))
            caption(ns, cx, cy, cw, sp["cap_title"], sp["cap_lines"], title_size=ts, size=bs)

        # 05-b' 물 공급 계통도(코드 작도) — 대표 작도가 없을 때만. 대표 작도가 있으면 위 경로가 그대로 쓴다.
        if not meta.get("sketch_pages") and meta.get("water_diagram", True):
            self._water_diagram(prs, P["주배관"])

        # 06 주배관 연결
        s = P["주배관"]
        clear_slide(s)
        fr = self.map.place(s, meta["map"]["crop_m"], "주배관")
        self.draw_field(s, fr)
        self.draw_buried(s, fr)
        self.draw_main(s, fr, gauge=True)
        _fd = self.feed_geom(fr)
        marks = [(tuple(_fd["dot"] or src["pt"]), "a", self.water.get("a_name", "시작부")) for src in S["sources"][:1]]
        if S["n_tees"] and meta.get("tee_panel", True) and len(S["tees"]) <= 4:   # [R06] 5곳 이상은 캡션 수치로만
            for p, tag in S["tees"]:
                marks.append((tuple(p), "d", "T분기"))
        for p in (S["ends"] if len(S["ends"]) <= 4 else []):      # [R06] 5곳 이상이면 캡션 수치로만
            marks.append((tuple(p), "c", "주배관 말단"))
        for j in (S["joints"] if len(S["joints"]) <= 4 else []):   # [R06] 5곳 이상은 캡션 수치로만
            marks.append((tuple(j["pt"]), "b", "롤 이음"))
        # 🔵 [V114 · 2단계] 구역 밸브 번호 — 운전표와 **같은 번호**를 지도에 단다. 자리 = 엔진의 분배점(규칙 21).
        # 밸브가 3곳 이하면 지시선, 그보다 많으면 **지도 위 제자리에 번호**(지시선 기둥이 캡션과 부딪힌다 · 9구역 시각 검사)
        on_map = len(self.valves) > 3
        for v in ([] if on_map else self.valves):
            marks.append((tuple(v["pt"]), "V", "구역 밸브 %s" % v["names"]))
        if len(marks) > 10:          # 너무 많으면 말단·롤 이음 지시선은 빼고 캡션 수치로만 둔다(겹침 방지)
            marks = [m for m in marks if m[1] not in ("b", "c")]
            self.log.append("주배관 면: 지시선 과다 — 말단·롤 이음 표지는 캡션 수치로만")
        place_leaders(s, fr, marks)
        if on_map:
            for v in self.valves:
                vx, vy = fr.xy(*v["pt"])
                label(s, Emu(vx).inches + 0.05, Emu(vy).inches - 0.30, v["mark"].rstrip("~"), size=9.5,
                      color=ov.INK, w=0.5, bold=True)
        self.draw_joints(s, fr)
        n_line = len(S["zones"]) or sum(1 for r in self.routes if r.get("zone") is not None)
        cap = list(tx.get("main_cap", []))
        if not cap:
            cap = ["a  %s" % self.water.get("start_kind", "급수 시작점")]
            if _fd["lines"]:
                cap.append("초록 선 = 인입관 · P = 압력계 세트" + (" · 급수 지점 표시만 띄움" if _fd["displaced"] else ""))
            _zl = [(z["zone"], sum(r["len_m"] for r in self.design["mainline"]["routes"] if r["name"] in z["routes"]), z["n_heads"])
                   for z in S["zones"]]
            if len(_zl) <= 4:
                for zn, zm, zh in _zl:
                    cap.append("%s — 주배관 %.0f m · %d두" % (zn, zm, zh))
            else:                                                   # [R06] 5구역 이상 — 한 줄로
                cap.append("%d구역 · 주배관 %.0f~%.0f m · %d~%d두 — 구역별은 「구역별 운전·확인표」"
                           % (len(_zl), min(x[1] for x in _zl), max(x[1] for x in _zl),
                              min(x[2] for x in _zl), max(x[2] for x in _zl)))
            if S["n_joints"]:
                cap.append("b  일자연결 세트 %s — 50 m를 넘는 지점 %d개소" % (S["sets"]["join50"], S["n_joints"]))
            cap.append("c  E호스밸브 마감세트 %d개소 — 세척·월동 배수 때 밸브만 엽니다" % S["n_ends"])
            if S["n_tees"]:
                cap.append("d  T분기 세트 %s %d개소" % (S["sets"]["tee50"], S["n_tees"]))
            _elb = [j for j in (self.design.get("mainline") or {}).get("junctions") or [] if j.get("kind") == "elbow"]
            cap.append("꺾임은 모두 45° 이내 — 현장에서 호스를 굽힙니다(꺾임부 부속 없음)" if not _elb else
                       "45°를 넘는 꺾임 %d곳 — 부속 [미확정](호스는 T 양쪽 · 파이프는 엘보)" % len(_elb))
            if len(self.zone_color) > 1:
                cap.append(" · ".join("%s = %s" % (self.zone_cname.get(z, "색"), z) for z in self.zone_color))
            v = max((r["v50"] for r in S["hydro"]), default=0)
            if v > 2.0:
                cap.append("주배관 유속 %.2f m/s(권장 2.0 초과) — 급수·정지는 밸브를 천천히(수격 방지)" % v)
            if self.valves:
                cap.append("V = 구역 밸브 — 번호는 뒤의 「구역별 운전·확인표」와 같습니다")
        # [V114 · F01] 관경은 엔진이 확정한 호칭(summary.main_mm = BOM 과 같은 출처)
        caption(s, CAP_X, CAP_Y, CAP_W, "주배관 %d mm · %d줄 · %d m" % (S.get("main_mm", 50), n_line, S["main_total_m"]), cap)

        # 07-a 매니폴드 상세 (대표 작도 · 규칙 7) — 있으면 주배관 상세 앞에
        mf = meta.get("manifold")
        if mf:
            ns = new_slide_before(prs, P["주배관상세"])
            src = Presentation(mf["pptx"])
            copy_shapes(ns, src.slides[mf["slide"]], dx_in=mf.get("dx_in", 0.0), dy_in=mf.get("dy_in", 0.0),
                        skip_pred=(lambda sh: sh.shape_type != 6) if mf.get("groups_only") else None)
            for old, new in mf.get("replace", []):
                replace_text(ns, old, new)
            for lb in mf.get("labels", []):
                x, y, txt = lb[0], lb[1], lb[2]
                label(ns, x, y, txt, size=10.5, w=lb[3] if len(lb) > 3 else 1.6,
                      align=PP_ALIGN.RIGHT if len(lb) > 4 and lb[4] == "r" else PP_ALIGN.LEFT)
            self._scan_copied(ns, "매니폴드")
            label(ns, 0.62, 0.42, mf["title"], size=24, w=11.5)
            cx, cy, cw = mf.get("cap_xy", (8.75, 1.30, 4.2))
            caption(ns, cx, cy, cw, mf["cap_title"], mf["cap_lines"])

        # 07 주배관 연결부 상세 — 카드 3장(c 말단 · b 일자 · d T) 규칙 8·10
        s = P["주배관상세"]
        clear_slide(s, keep_top_in=0.0)
        DS.title(s, "주배관 연결, 연결부 상세")
        y0 = DS.G.ROW1_Y + 0.15
        if tx.get("start_on_prev"):
            label(s, DS.G.MARGIN_L, y0, tx["start_on_prev"], size=11.5, color=DS.C.INK500, w=12.0, bold=False)
            y0 += 0.45
        # 🔴 [V114 · F01] 부속 코드·규격·세트명 = **확정된 관경의 BOM 규칙**(summary.fittings · summary.sets).
        #    예전에는 02051·01403·00825·00827·「50 mm」가 고정이라 40 mm 설계에도 50 mm 부속 사진이 나갔다.
        FT, mm = S.get("fittings") or {"hose": "02051", "e_valve": "01403", "wf41": "00825", "wf42": "00827"}, S.get("main_mm", 50)
        mms = "%d mm" % mm
        cards = []
        cards.append(("c", "주배관 말단 마감 세트 — %d개소" % S["n_ends"],
                      "%s  E호스밸브 마감세트 %d (%s + 호스밴드 2)" % (S["sets"]["end50"], mm, FT["e_valve"]),
                      [(FT["hose"], "송수호스", mms), ("00278", "호스밴드", "2¼″ ×2"), (FT["e_valve"], "E호스밸브", mms)],
                      "밸브로 막습니다 — 관 세척·월동 배수 때 밸브만 열면 주배관 안의 물이 빠집니다. 1개소 = E호스밸브 1 + 호스밴드 2."))
        if S["n_joints"]:
            cards.append(("b", "주배관 일자연결 세트 — %d개소" % S["n_joints"], S["sets"]["join50"],
                          [("00278", "호스밴드", "×2"), (FT["wf41"], "WF 4-1", str(mm)), (FT["wf42"], "WF 4-2", str(mm)), ("00278", "호스밴드", "×2")],
                          "50 m 롤을 잇는 자리입니다. 꺾임에는 부속을 쓰지 않습니다 — 호스가 유연해 45° 이내는 현장에서 굽힙니다. 1개소 = WF 4-1 + WF 4-2 + 호스밴드 4."))
        # 🔴 [V117 · C] T 들어오는 쪽(WF 4-4 · 규칙 8-1) 문구는 **실제 조건일 때만** — 매니폴드 면이 있을 때만 「매니폴드 면에 계상」,
        #    급수 계통 품목(water_items)에 있으면 그대로 1개소 구성, 둘 다 없으면 [미확정](관문 확인 항목과 짝).
        #    용산리 원본은 매니폴드 면도 WF 4-4 도 없는데 「매니폴드 면에 계상했습니다」가 나갔다.
        _ti = S.get("tee_inlet") or ("manifold" if meta.get("manifold") else "missing")
        _tee_note = {"manifold": "1개소 = CCCT 中 1 + 나가는 쪽 WF 4-2 2 + 들어오는 쪽 WF 4-4 1 + 호스밴드 6 "
                                 "(들어오는 쪽은 급수 계통 규격을 따르므로 매니폴드 면에 계상했습니다).",
                     "quote": "1개소 = CCCT 中 1 + 나가는 쪽 WF 4-2 2 + 들어오는 쪽 WF 4-4 1 + 호스밴드 6.",
                     }.get(_ti, "1개소 = CCCT 中 1 + 나가는 쪽 WF 4-2 2 + 호스밴드 4 · 들어오는 쪽 부속 [미확정].")
        _tee_row = {"manifold": "CCCT 中 1 + 나가는 쪽 WF 4-2 2 + 호스밴드 4 (들어오는 쪽 WF 4-4 1·밴드 2 = 매니폴드)",
                    "quote": "CCCT 中 1 + 나가는 쪽 WF 4-2 2 + 호스밴드 4 (들어오는 쪽 WF 4-4 1·밴드 2 = 급수 계통 품목)",
                    }.get(_ti, "CCCT 中 1 + 나가는 쪽 WF 4-2 2 + 호스밴드 4 (들어오는 쪽 부속 [미확정])")
        if S["n_tees"] and meta.get("tee_panel", True):
            cards.append(("d", "주배관 T분기 세트 — %d개소" % S["n_tees"], S["sets"]["tee50"],
                          [("00278", "호스밴드", "×2"), (FT["wf42"], "WF 4-2", str(mm)), ("01201", "CCCT 中", "T"), (FT["wf42"], "WF 4-2", str(mm)), ("00278", "호스밴드", "×2")],
                          "한 줄이 여기서 양쪽으로 갈라집니다 — 되돌이(헤어핀) 배관을 만들지 않으려고 T를 씁니다. " + _tee_note))
        _unreg = sorted({c["label"] for c in S.get("connections") or [] if not c["registered"]})
        if _unreg:
            self.log.append("미등록 세트 — %s (구성은 BOM 기준 · 이름·사진 확인 필요)" % " · ".join(_unreg))
        n = len(cards)
        cw = (DS.SLIDE_W - DS.G.MARGIN_L - DS.G.MARGIN_R - 0.3 * (n - 1)) / n if n <= 2 else 4.0
        for i, (ch, title, setname, parts, note) in enumerate(cards):
            if n <= 2:
                x, y = DS.G.MARGIN_L + i * (cw + 0.3), y0
            else:
                x, y = DS.G.MARGIN_L + (i % 3) * (cw + 0.28), y0 + (i // 3) * (DS.CARD.H + 0.3)
            self.set_card(s, x, y, cw, ch, title, setname, parts, note, h=DS.CARD.H + 0.62)
        y_tab = y0 + DS.CARD.H + 0.62 + (0 if n <= 3 else DS.CARD.H + 0.3) + 0.22
        label(s, DS.G.MARGIN_L, y_tab, "연결부 요약 — 세트 · 개소 · 낱개 부속 (세트 단위로 받으시고, 낱개 수량은 검수용입니다)", size=12, w=9.0)
        rows = [["연결부", "세트", "개소", "부속 (1개소당)", "합계 수량"]]
        if tx.get("start_on_prev"):
            rows.append(["a  시작부", "앞 면 참조", "-", "밭 입구 매니폴드 · 급수 계통 면", "-"])
        else:
            # [R05] BOM 이 세는 것 = 시작 E호스밸브 1 + 호스밴드(급수점 입력). 급수 쪽 카플러는 계통 품목(규칙 7)
            rows.append(["a  시작부", S["sets"]["inlet50"], "1",
                         "E호스밸브 1 + 호스밴드 2 (급수 쪽 카플러는 급수 계통 품목)", "E호스밸브 1 · 밴드 2"])
        if S["n_joints"]:
            rows.append(["b  일자연결", S["sets"]["join50"], str(S["n_joints"]), "WF 4-1 1 + WF 4-2 1 + 호스밴드 4",
                         "WF 4-1 %d · WF 4-2 %d · 밴드 %d" % (S["n_joints"], S["n_joints"], 4 * S["n_joints"])])
        rows.append(["c  말단 마감", S["sets"]["end50"], str(S["n_ends"]), "E호스밸브 1 + 호스밴드 2",
                     "E호스밸브 %d · 밴드 %d" % (S["n_ends"], 2 * S["n_ends"])])
        if S["n_tees"]:
            rows.append(["d  T분기", S["sets"]["tee50"], str(S["n_tees"]), _tee_row,
                         "CCCT %d · WF 4-2 %d · 밴드 %d" % (S["n_tees"], 2 * S["n_tees"], 4 * S["n_tees"])])
        rows.append(["가지관 분기 · 말단", "%s / %s" % (S["sets"]["branch25"], S["sets"]["end25"]), str(S["n_lats"]),
                     "루퍼젯 H25 1 + 지관 밸브 1 + 25 mm 마감 1 (열마다)",
                     "H25 %d · 밸브 %d · 마감 %d" % (S["n_lats"], S["n_lats"], S["n_lats"])])
        self._table(s, DS.G.MARGIN_L, y_tab + 0.32, [1.55, 2.05, 0.7, 4.3, 3.5], rows, head_h=0.26, row_h=0.22, size=9.5)

        # 08 부속 설치 영상 QR — 대표 지시 2026-09-04 (연결부 상세 바로 뒤)
        self.video_page(prs, P["가지관"], [b["code"] for b in S["bom"]])

        # 09 가지관 연결
        s = P["가지관"]
        clear_slide(s)
        fr = self.map.place(s, meta["map"]["crop_m"], "가지관")
        self.draw_field(s, fr)
        self.draw_main(s, fr)
        self.draw_lats(s, fr)
        self._dims(s, fr, heads=False)
        _LL = sorted(l["len_m"] for l in self.lats)
        _LN = sorted(l["n_heads"] for l in self.lats)
        lat_cap = ["두둑(재배 열)과 평행 · 열 간격 %s m (직각)" % S["lat_gap"],
                   "열 길이 %.0f~%.0f m · 열별 %d~%d두 — 긴 열부터 100 m 롤을 잘라 이어 씁니다"
                   % (_LL[0], _LL[-1], _LN[0], _LN[-1]),
                   "열마다 밸브 1개 — 부분 관수·수리 시 개별 차단 · 분기 세트 %s" % S["sets"]["branch25"],
                   "한 열 최대 %d두 (25 mm 한계 7두)" % S["lat_max_heads"],
                   "말단 %s 마감 %d개소" % (S["sets"]["end25"], S["n_lats"])]
        if S["curved_n"]:
            lat_cap.append("사선 분기 %d열 — 주배관에서 직각으로 뺀 뒤 둥글게 돌립니다(분기 부속 H25 목 보호 · 직각 이탈 최대 %.0f°)" % (S["curved_n"], S["dev_max"]))
        lat_cap.append("흰 치수선 = 블록마다 한 줄 — 열 사이 간격과 **밭 경계까지의 이격**을 모두 적었습니다"
                       .replace("**", ""))
        caption(s, CAP_X, CAP_Y, CAP_W, "가지관 25 mm · %d열 · %d m" % (S["n_lats"], S["lat_total_m"]), lat_cap)

        # 11 스프링클러 연결
        s = P["스프링클러"]
        clear_slide(s)
        fr = self.map.place(s, meta["map"]["crop_m"], "헤드")
        self.draw_field(s, fr)
        self.draw_main(s, fr)
        self.draw_lats(s, fr)
        self.draw_heads(s, fr, 0.05)
        self._dims(s, fr, heads=True)
        # [V109] 간격·헤드 구성은 summary(정책·head_kit)에서 — 「10 m」·「01998」 고정 문구를 없앴다.
        _kit = S["head_kit"]
        # [V117 · K-04] _kit = BOM 이 실제로 쓰는 헤드 구성(summary.head_kit_used) — 견적과 같은 물건을 말한다
        caption(s, CAP_X, CAP_Y, CAP_W, "스프링클러 %d두 · %s" % (S["n_heads"], _kit["short"]), [_x for _x in [
            "헤드 간격 %s m · 첫 헤드 %.1f~%.1f m (기준 5)" % (S["head_gap"], S["off_min"], S["off_max"]),
            "경계 이격 %.1f m 이상 · 밭 커버율 %.0f %%" % (S["edge_min_m"], S["cover"] * 100),
            ("열별 구성 — 「스프링클러 연결, 연결부 상세」 면 참조" if _kit.get("key") == "mixed"
             else "%s — %s" % (S["sets"]["head"], _kit["label"].split(" — ", 1)[-1])),
            ("지관 15 mm 타공 · 케이블타이 140 mm 헤드당 2개 — 북주기·철거 때 호스가 당겨져도 루퍼젯이 버팁니다"
             if _kit["key"] == "01998" else _kit["hose_note"]),
            "흰 치수선 = 가운데 대표 열 한 줄 — 첫 헤드까지 여백, 그 뒤로 헤드 사이 실측 간격 (다른 열도 같은 방식입니다)",
        ] if _x])                                         # [V117 · K-04] 구성 설명이 빈 kit([미확정])이면 빈 줄을 두지 않는다

        # 🔴 [V114 · F05] 고정 상세면의 **적용 조건** — 면10(가지관 상세)·면11(스프링클러 상세)은 01998 세트 도해다.
        #    다른 헤드 구성(이동식·열별 혼합)에 그 도해를 그대로 두면 본문·BOM 과 다른 물건을 보여 준다.
        self._head_detail(P["가지관상세"], P["스프링클러상세"], _kit)

        # 12 헤드 성능표 — 고정면 + 본 설계 반경 캡션
        s = P["헤드성능"]
        for sh in list(s.shapes):
            if sh.has_text_frame and "촘촘 살수" in sh.text_frame.text:
                sh._element.getparent().remove(sh._element)
        # 🔵 [V117 · C] 고정 살수 도해의 숫자(마스터 「14m」·「26m」·「최대 14m 간격」 · 가지관 상세 「간격 최대 14m」)는
        #    이 설계와 다른 값이었다(용산리 Ø24/Ø14 · 간격 10 m). **생성 시 설계값으로 치환**한다(마스터 무수정 · 결정 #95).
        #    제조사 성능표(표 · 「최대 살수 직경 23~26m」)는 제조사 값이라 그대로 둔다.
        self._fix_spray_figure(s, P["가지관상세"], RD, S["head_gap"])
        # [V114 · F02] 반경은 설계 말단압에서 계산(summary.spray) — 「바깥 10 m · 안쪽 7 m」 고정 폐기
        caption(s, 9.1, 6.30, 4.0, "본 설계 살수 원 (R 반경 · Ø 지름)",
                ["바깥 R %s m · Ø %s m — 말단 %.1f bar" % (RD["r_out"], RD["d_out"], SP["p_bar"]),
                 "안쪽 R %s m · Ø %s m — 귀환 살수" % (RD["r_in"], RD["d_in"])]
                + (["필요 공급조건은 급수 부록 참조 · 실제 말단압은 현장 확인"] if S.get("supply") else
                   (["말단 압력 %s bar — 현장 압력계로 확인" % " · ".join("%.2f" % h["p_end"] for h in S["hydro"])] if S["hydro"] else [])),
                title_size=12, size=10, title_color=GRN)

        # 14~ 구역 살수 예시 ×Z + 전체
        live = {l["id"] for l in self.lats if l["id"] not in set(UN.get("ids") or [])}

        def spray_page(slide, title_new, ids, cap_title, cap_lines, only=None):
            clear_slide(slide)
            set_title(slide, title_new)
            fr = self.map.place(slide, meta["map"]["crop_m"], title_new[:10])
            self.draw_field(slide, fr)
            for l in self.lats:
                if l["id"] in ids and l["id"] in live:          # [V114 · F09] 급수 불가 열에는 살수원을 그리지 않는다
                    for hx, hy in l["heads"]:
                        spray_double(slide, fr, hx, hy, SP["r_out"], SP["r_in"])
            self.draw_main(slide, fr, only=only)
            self.draw_lats(slide, fr)
            self.draw_heads(slide, fr, 0.04)
            caption(slide, CAP_X, CAP_Y, CAP_W, cap_title, cap_lines)

        zs = S["zones"] if len(S["zones"]) > 1 else []
        # 🔴 [V114 · F07] 마스터 구역 면은 8장이다. 9구역부터는 **같은 레이아웃의 면을 새로 만든다** —
        #    예전에는 k=8 에서 IndexError 로 제안서 전체가 멈췄다(감사 F07 · 실측).
        zpages = list(P["구역"])
        while len(zpages) < len(zs):
            zpages.append(new_slide_before(prs, P["전체"]))
            self.log.append("구역 면 추가 — %d구역(마스터 8면 초과)" % len(zpages))
        for k, z in enumerate(zs):
            v = self.valve_of.get(str(z["zone"]))
            v = v if (v and v.get("pt")) else None
            spray_page(zpages[k], "%s 살수 예시 (%d두)" % (z["zone"], z["n_heads"]), set(z["lat_ids"]),
                       "%s · %d두" % (z["zone"], z["n_heads"]), [
                           "계획 가동 %d두 — 필요 유량·압력은 「구역별 운전·확인표」" % z["n_heads"],
                           z["how"] or (("%s 밸브만 엽니다" % v["id"]) if v else "이 구역 밸브만 엽니다 — 밸브 위치 [미확정]"),
                           "가지관 %d열" % len(z["lat_ids"]),
                           "바깥 원 = 설계 말단압 %.1f bar일 때 반경 R %s m(지름 Ø %s m · 배치상 범위)"
                           % (SP["p_bar"], RD["r_out"], RD["d_out"]),
                       ] + (["실제 가동 여부는 급수원 성능 확인 후 결정"] if S.get("supply") else []),
                       only=z["zone"])
        for k in range(len(zs), len(zpages)):
            delete_slide(prs, zpages[k])
        for k in range(len(zs)):                      # 구역 예시 → 전체 예시 순(승인 지면 순서)
            move_before(prs, zpages[k], P["전체"])
        full_lines = ["%d구역 %s가동" % (len(S["zones"]), "순차 " if len(S["zones"]) > 1 else "동시 "),
                      "두둑과 평행 · %s m 간격 — 원이 겹치도록 배치" % S["head_gap"],
                      "배치상 커버율 약 %.0f %% (연결된 헤드 · 반경 %s m)" % (S["cover"] * 100, RD["r_out"])]
        if UN["rows"]:
            full_lines.append("빨간 열 %d열 = 주배관에 닿지 않음(급수 불가) — 살수원을 그리지 않았습니다" % UN["rows"])
        spray_page(P["전체"], "전체 살수 예시 (%d두)" % S["n_heads"], set(l["id"] for l in self.lats),
                   "전체 %d두 살수 범위" % S["n_heads"], full_lines + self._runtime_lines())

        # [V114 · 2단계] 현장 요약(상호 확인사항 뒤) · 구역별 운전·확인표(전체 살수 뒤)
        self._site_summary(prs, P["대상지"])
        self._zone_table(prs, P["총내역"])

        # 17 총 소요 내역
        s = P["총내역"]
        for sh in list(s.shapes):
            if sh.shape_type == 6 or (sh.has_text_frame and "촘촘" in sh.text_frame.text):
                sh._element.getparent().remove(sh._element)
        _bpages = self._bom_pages(S["bom"])                      # [계통도 · 사진 열] 사진 칸으로 행이 높아져 넘치면 면을 나눈다
        self._bom_tables(s, S["bom"], _bpages[0])
        # 🔴 [V114 · F03] 합계 = 비용 구조의 합계(자재 + 수기 비용 줄) — 견적서(XLSX)와 같은 수다.
        C = S.get("cost") or {"grand": S["total"], "priced": True, "svc": [], "material": S["total"],
                              "basis_note": "자재 포함 · 배송비·설치 인건비 별도", "missing": []}
        grand = C["grand"] if C.get("priced") else None
        if not replace_text(s, "₩{{합계금액}} 원", ("%s 원" % fmt_n(grand)) if grand is not None else "미확정"):
            replace_text(s, "{{합계금액}}", fmt_n(grand) if grand is not None else "미확정")
        parts = ["자재 %s" % (fmt_n(C["material"]) if C.get("material") is not None else "미확정")]
        parts += ["%s %s" % (x["항목"], fmt_n(x["금액"])) for x in C.get("svc") or [] if x["금액"]]
        brk = " + ".join(parts)
        if C.get("missing") and C.get("priced"):
            brk += " · 단가 없는 %d품목 제외(가격 확정 품목 소계)" % len(C["missing"])
        vat0 = bool(self.meta.get("quote", {}).get("vat_zero"))   # 기본 off — 대표가 건별로 켠다
        for sh in list(s.shapes):                                 # 고정면 영세율 안내 = 견적 비고와 통일
            if not sh.has_text_frame:
                continue
            t = sh.text_frame.text
            if "영세율" in t and "적용 안내" in t:
                if vat0:
                    set_paragraphs(sh, VAT_ZERO)
                else:
                    sh._element.getparent().remove(sh._element)   # 안내 자체를 뺀다(마스터 원문은 무수정)
            elif t.strip() == "※ 영세율 적용 금액" and not vat0:
                set_paragraphs(sh, [VAT_PLAIN])
        tot = grand or 0
        if vat0 and tot < VAT_ZERO_MIN_TOTAL:
            self.log.append("영세율 안내 ON인데 합계 %s원 < 기준 %s원 — 대표 판단 확인 요"
                            % (fmt_n(tot), fmt_n(VAT_ZERO_MIN_TOTAL)))
        elif not vat0 and tot >= VAT_ZERO_MIN_TOTAL:
            self.log.append("영세율 안내 OFF · 합계 %s원(기준 이상) — 적용 여부는 대표 판단(meta.quote.vat_zero)"
                            % fmt_n(tot))
        if S.get("won_per_py") and C.get("priced"):
            label(s, 8.6, 6.38, "평당 약 %s원 (%s평)" % (fmt_n(S["won_per_py"]), fmt_n(S["area_py"])), size=10.5,
                  color=DS.C.INK500, w=2.15, align=PP_ALIGN.RIGHT)
        _l, _r = _bpages[0]
        h_left, h_right = self._bom_table_h(_l), self._bom_table_h(_r)
        col_x = 0.6 if h_left <= h_right else 6.85                # 짧은 쪽 표 아래에 놓는다
        y_next = 1.1 + min(h_left, h_right) + 0.18
        # [V114 · F04] 「설치 지원 인력」은 약정됐을 때만 쓴다 — 기본은 협의.
        SCs = (S.get("scope") or {})
        steps = meta.get("next_steps") or [
            "현장 실측 — 위성 축척으로 잡은 치수를 줄자로 확인합니다(호스는 롤 단위라 여유가 있습니다)",
            "급수 연결부 규격 확정 — 매설관·파이프 구경을 보고 카플러·밸브 규격을 정합니다",
            ("시공 일정 — 자재 배송 뒤 현장 설치 지원 인력과 날짜를 잡습니다" if SCs.get("install_support") is True
             else "시공 방법 — 자가 시공 또는 설치 지원 여부를 정한 뒤 일정을 잡습니다"),
        ]
        # 아래 고정 블록(영세율 안내, y 5.71)은 옮기지 않는다 — 그 밑에 로고·각주가 있다. 넘치면 글자만 줄이고,
        # 그래도 자리가 없으면 「다음 단계」를 면4(상호 확인사항) 각주 아래로 내린다(대표 폴백).
        y_fixed = min([Emu(sh.top).inches for sh in s.shapes
                       if sh.has_text_frame and "영세율" in sh.text_frame.text and "적용 안내" in sh.text_frame.text] or [5.71])
        size, gap, line_h = 9.5, 2, 0.19
        if y_next + 0.28 + len(steps) * line_h + 0.05 > y_fixed:
            size, gap, line_h = 8.5, 1, 0.17
        if y_next + 0.28 + len(steps) * line_h + 0.05 > y_fixed:
            if self._steps_on_p4(P["상호확인"], steps):
                self.log.append("면19: 표가 길어(BOM %d행) 「다음 단계」를 면4 상호 확인사항 아래로 내림" % len(S["bom"]))
                steps = None
            elif getattr(self, "summary_slide", None) is not None:
                # [V114] 면4에도 자리가 없으면 현장 요약 면 왼쪽 아래로 — 영세율 안내와 겹치던 자리(05 시각 검사)
                label(self.summary_slide, DS.G.MARGIN_L, 5.30, "다음 단계", size=11.5, w=3.0, color=ov.DIM)
                bullets(self.summary_slide, DS.G.MARGIN_L, 5.58, 6.2, steps, size=9.5, gap=2)
                self.log.append("면19: 표가 길어(BOM %d행) 「다음 단계」를 현장 요약 면으로 옮김" % len(S["bom"]))
                steps = None
            else:
                self.log.append("면19: 다음 단계가 영세율 안내와 겹침(표가 김) — BOM %d행 · 면4에도 자리 없음" % len(S["bom"]))
        if steps:
            label(s, col_x, y_next, "다음 단계", size=11.5, w=3.0, color=ov.DIM)
            bullets(s, col_x, y_next + 0.28, 5.9, steps, size=size, gap=gap)
        label(s, 3.2, 6.84, "%s · %s · 여분(세트 3 %%·자재 5 %%·롤 여유 12 %%) 포함 · %s"
              % (brk, S["tier"], C.get("basis_note", "")),
              size=9.5, color=(BAD if not C.get("priced") else DS.C.INK500), w=9.7, align=PP_ALIGN.RIGHT)
        # [계통도 · 사진 열] 행이 많아 한 면에 안 들어가면 이어지는 면(합계·다음 단계는 첫 면에 그대로)
        if len(_bpages) > 1:
            self.log.append("총 소요 내역 %d면으로 나눔 — 사진 칸으로 행이 높아져(BOM %d행) 한 면에 안 들어감" % (len(_bpages), len(S["bom"])))
        for k, pg in enumerate(_bpages[1:], 2):
            _cs = new_slide_before(prs, P["꼬리"][0])
            DS.title(_cs, "총 소요 내역 (%d/%d)" % (k, len(_bpages)))
            self._bom_tables(_cs, S["bom"], pg)

        # 🔴 [V109] 안전망 — 지면 밖으로 멀리 나간 도형은 지우고 기록한다. PowerPoint 는 좌표가 ±2^31 EMU 를 넘는
        #    파일을 **열지 않는다**(09-15 실사고). 원인은 위(_lat_dims)에서 고쳤지만, 다른 작도가 같은 사고를 내도
        #    파일만은 열리게 한다. 지운 것은 render_log 에 남아 §9 점검과 함께 보인다.
        self._supply_appendix(prs)
        self._prune_offpage(prs)
        self._renumber_slides(prs)
        prs.save(self.out)
        return self.out

    # ── [V114] 고정면 교정 · 상세면 적용 조건 · 현장 요약 · 운전표 ──
    def _fix_fixed(self, sl):
        """FIXED_TEXT_FIX/FIXED_DROP/AI_BLOCK — 마스터 복사본에만 적용한다(원본 무수정)."""
        # [V117 · C] 도형 **이름**(PowerPoint 선택 창에 보이는 이름)에 남은 다른 현장명 — 화면 글자는 아니지만 고객이 열면 보인다.
        nfix = 0

        def _walk(shapes):
            nonlocal nfix
            for sh in shapes:
                if any(k in (sh.name or "") for k in FIXED_NAME_DROP):
                    sh.name = "텍스트 %d" % sh.shape_id
                    nfix += 1
                if sh.shape_type == 6:
                    _walk(sh.shapes)
        for s_ in sl:
            _walk(s_.shapes)
        if nfix:
            self.log.append("고정면 도형 이름 정리 %d개(다른 현장명)" % nfix)
        for i, old, new in FIXED_TEXT_FIX:
            if i < len(sl) and replace_text(sl[i], old, new):
                self.log.append("고정면%d 교정: 「%s」" % (i + 1, old[:18]))
        for i, t in FIXED_DROP:
            for sh in list(sl[i].shapes) if i < len(sl) else []:
                if sh.has_text_frame and sh.text_frame.text.strip() == t:
                    sh._element.getparent().remove(sh._element)
                    self.log.append("고정면%d: 근거확인 전 수치 「%s」 제외" % (i + 1, t))
        if 22 < len(sl):
            for sh in list(sl[22].shapes):          # 「저감 ➡ (작물 스트레스 완화)」의 화살표 — 뒤 문장을 뺐으니 함께 뺀다
                if sh.shape_type == 1 and abs(Emu(sh.left or 0).inches - 10.33) < 0.05 and abs(Emu(sh.top or 0).inches - 1.55) < 0.05:
                    sh._element.getparent().remove(sh._element)
            DS.text(sl[22], 7.9, 6.86, "※ 자사 측정(2024년 8월) — 측정 조건·원자료 확인 중인 참고 그래프입니다", size=8.5,
                    font=DS.T.CAPTION, color=DS.C.INK500, w=4.6, h=0.25)
        if not (self.meta.get("options") or {}).get("ai"):
            i = AI_BLOCK["slide"]
            if i < len(sl):
                n = 0
                for sh in list(sl[i].shapes):
                    t = sh.text_frame.text if sh.has_text_frame else ""
                    grp = sh.shape_type == 6 and abs(Emu(sh.left or 0).inches - AI_BLOCK["group_left_in"]) < 0.05
                    if grp or any(t.startswith(k) for k in AI_BLOCK["texts"]):
                        sh._element.getparent().remove(sh._element)
                        n += 1
                if n:
                    self.log.append("고정면27: 「루퍼젯+ AI」 제외(상품·지원 범위 미확인 — meta.options.ai 로 켬)")

    def _fix_spray_figure(self, head_perf, lat_detail, RD, gap):
        """[V117 · C] 고정 도해의 지름·간격 글자 → 이 설계값. 글자 도형만 바꾼다(그림 속 숫자는 없다 — 마스터 실측)."""
        want = {"26m": "%sm" % RD["d_out"], "14m": "%sm" % RD["d_in"]}   # 바깥·안쪽 원 지름 도형(이름·글자 = 마스터 그대로)
        hit = []

        def walk(shapes):
            for sh in shapes:
                if sh.shape_type == 6:
                    walk(sh.shapes)
                elif sh.has_text_frame and sh.text_frame.text.strip() in want:
                    old = sh.text_frame.text.strip()
                    set_paragraphs(sh, [want[old]])
                    hit.append("%s→%s" % (old, want[old]))
        walk(head_perf.shapes)
        n = replace_text(head_perf, "최대 14m 간격", "간격 %sm" % gap)
        n += replace_text(lat_detail, "간격 최대 14m", "간격 %sm" % gap)
        self.log.append("고정 살수 도해 설계값 치환: %s · 간격 %d곳" % (" · ".join(hit) or "지름 도형 없음(마스터 확인)", n))

    def _head_detail(self, lat_slide, head_slide, kit):
        if kit.get("key") == "01998":
            return
        if kit.get("key") == "unknown":              # [V117 · K-04] BOM 에 헤드 구성이 없다 — 도해·카드를 짓지 않는다
            clear_slide(head_slide, keep_top_in=0.0)
            DS.title(head_slide, "스프링클러 연결, 연결부 상세 — [미확정]", kit.get("label", "[미확정] 헤드 구성"))
            self.log.append("면12: 헤드 구성 [미확정] — BOM 에 헤드 품목 없음")
            return
        replace_text(lat_slide, "루퍼젯+ 스프링클러세트", kit.get("short", "헤드 구성"))
        clear_slide(head_slide, keep_top_in=0.0)
        DS.title(head_slide, "스프링클러 연결, 연결부 상세 — %s" % kit.get("short", ""),
                 "이 구성의 조립 도해는 아직 등록되지 않았습니다 — 아래 부속과 수량은 견적(BOM)과 같습니다")
        names = {b["code"]: (b.get("name", ""), str(b.get("spec", ""))) for b in self.S["bom"]}
        groups = self.S.get("head_groups") or [{"kit": kit, "heads": self.S["n_heads"], "rows": []}]
        y = DS.G.ROW1_Y + 0.25
        if len(groups) > 3:
            DS.text(head_slide, DS.G.MARGIN_L, 6.35, "외 %d구성 — 열별 구성은 견적(BOM)과 부록 「급수·연결 조건」 참조" % (len(groups) - 3),
                    size=10, font=DS.T.BODY, color=DS.C.INK500, w=12.0, h=0.3)
        for g in groups[:3]:
            k = g["kit"]
            parts = [(c, re.sub(r"\s*\(.*?\)", "", names.get(c, (c, ""))[0])[:20] or c,
                      "두당 %d" % q) for c, q in k["recipe"].items()]
            title = "%s — %d두" % (k.get("short", k.get("label", "")), g["heads"])
            if g.get("rows"):
                title += " · 열 %s" % ", ".join(map(str, g["rows"][:12]))
            self.set_card(head_slide, DS.G.MARGIN_L, y, 12.0, "H", title, k.get("set", "[세트 미등재]"), parts,
                          "%s  ·  조립 순서·타공 치수는 설치 전 확인 [미확정]" % (k.get("hose_note") or k.get("label", "")),
                          h=DS.CARD.H + 0.85)
            y += DS.CARD.H + 1.05
        self.log.append("면11: %s 구성 — 01998 도해 대신 실제 구성 카드(도해 미등록)" % kit.get("short", ""))

    def _site_summary(self, prs, anchor):
        """[V114 · 2단계 §1] 현장 한 장 요약 — 입력·엔진 값만. 채울 수 없는 칸은 [확인 필요]로 둔다."""
        S, SC, C = self.S, self.S.get("scope") or {}, self.S.get("cost") or {}
        s = new_slide_before(prs, anchor)
        clear_slide(s, keep_top_in=0.0)
        DS.title(s, "현장 요약", "이 밭에 무엇을, 왜, 얼마에 — 한 장으로 먼저 보시고 뒤의 지면에서 자리를 확인하십시오")
        self.summary_slide = s
        fmt = lambda v: format(v, ",") if isinstance(v, (int, float)) else "[미확정]"
        crops = sorted({b.get("crop") for b in self.site.get("blocks") or [] if b.get("crop")})
        kit = S["head_kit"]
        left = [
            ("대상지", "%s · %s ㎡(약 %s평) · 밭 %d개%s" % (S["name"], fmt(S["area_m2"]), fmt(S["area_py"]),
                                                 len(self.polys), (" · " + "·".join(crops)) if crops else "")),
            ("목적", "노지 스프링클러 관수 — 427B 헤드 %d두 · %s" % (
                S["n_heads"], ("%d구역 순차 운전" % len(S["zones"])) if len(S["zones"]) > 1 else "한 번에 전체 운전")),
            ("제안 범위", SC.get("start_line", "[확인 필요]")),
            ("기설·매설", SC.get("buried", "[현장 확인]")),
            ("여과기·계측", SC.get("filter", "[확인 필요]")),
            ("설치", SC.get("install", "협의 필요")),
        ]
        why = ["주배관 %d mm — %s" % (S.get("main_mm", 50), (self.design.get("main_mm_source") or "엔진 선정")[:70]),
               _grid_line(S),
               "가지관은 두둑과 나란히 %d열 · %d m — 열마다 밸브로 부분 관수" % (S["n_lats"], S["lat_total_m"]),
               "살수 반경 %s m(설계 말단압 %.1f bar) · 배치상 커버율 %.0f %%" % (_SL(S.get("spray"))["r_out"],
                                                              (S.get("spray") or {}).get("p_bar", 0), S["cover"] * 100)]
        # [V114 · 축5] 고객 말로 — 이 배치가 농가에 주는 것(설계 사실에서만 뽑는다)
        good = ["줄마다 밸브가 있어 필요한 줄만 물을 줄 수 있습니다"]
        if len(S["zones"]) > 1:
            good.append("%d구역을 밸브(V1~V%d)로 하나씩 돌려 한 번에 필요한 물을 줄였습니다" % (len(S["zones"]), len(S["zones"])))
        if not [j for j in (self.design.get("mainline") or {}).get("junctions") or [] if j.get("kind") == "elbow"]:
            good.append("주배관은 45° 이내로 굽혀 깔아 꺾임 부속이 없습니다")
        why = good + why
        if C.get("priced"):
            money = "합계 %s원 (%s · %s)" % (fmt(C.get("grand")), C.get("basis_note", ""), C.get("vat", ""))
            if C.get("won_per_py"):
                money += " · 평당 약 %s원" % fmt(C["won_per_py"])
        else:
            money = "금액 [미확정] — 단가 연결 뒤 산출 (물량은 총 소요 내역 면)"
        ask = []
        if SC.get("ownership") == "미확정":
            ask.append("급수원(%s)을 누가 갖추는지 — 고객 보유 / 당사 공급 / 별도 업체" % SC.get("source_kind", "급수원"))
        sup = S.get("supply") or {}
        if sup.get("mode") == "demand_only":
            ask.append("펌프·관정의 성능(유량과 그때의 압력) — 부록 요구조건과 맞는지 확인")
        if "입력 없음" in SC.get("buried", ""):
            ask.append("밭까지 묻힌 관·기존 시설이 있는지")
        if SC.get("install_support") is None:
            ask.append("설치를 직접 하실지, 설치 지원이 필요한지")
        ask.append("밭 치수 — 위성 축척으로 잡았으니 현장 실측으로 확인")
        y = DS.G.ROW1_Y + 0.15
        for k, v in left:
            label(s, DS.G.MARGIN_L, y, k, size=11, color=ov.DIM, w=1.35)
            DS.text(s, DS.G.MARGIN_L + 1.40, y, v, size=10.5, font=DS.T.BODY, color=DS.C.INK700, w=5.0, h=0.5)
            y += 0.24 * max(1, est_lines(v, 5.0, 10.5)) + 0.30
        x2 = 7.25
        label(s, x2, DS.G.ROW1_Y + 0.15, "핵심 선택과 이유", size=12, color=ov.DIM, w=5.5)
        bullets(s, x2, DS.G.ROW1_Y + 0.48, 5.6, why, size=10.5, gap=3)
        label(s, x2, 3.72, "비용", size=12, color=ov.DIM, w=5.5)
        bullets(s, x2, 4.02, 5.6, [money], size=10.5, gap=3)
        label(s, x2, 4.72, "고객께서 확인해 주실 것", size=12, color=ov.DIM, w=5.5)
        bullets(s, x2, 5.02, 5.6, ask[:5], size=10, gap=2)
        return s

    def _zone_table(self, prs, anchor):
        """[V114 · 2단계 §2] 구역별 운전·확인표 — 밸브 번호 = 주배관 면의 V 번호. 밸브 정보가 없으면 순서를 짓지 않는다."""
        S = self.S
        zs = S["zones"]
        if not zs:
            return None
        s = new_slide_before(prs, anchor)
        clear_slide(s, keep_top_in=0.0)
        DS.title(s, "구역별 운전·확인표", "한 번에 한 구역만 엽니다 — 밸브 번호는 「주배관 연결」 지도의 V 번호와 같습니다")
        sup = {str(z.get("zone")): z for z in (S.get("supply") or {}).get("zones") or []}
        from .supply_docs import STATUS
        rows = [["구역", "밸브", "열 것 / 닫을 것", "두수 · 열", "필요 유량", "필요 압력(양정)", "판정 · 기준"]]
        for z in zs:
            zk = str(z["zone"])
            v = self.valve_of.get(zk)
            v = v if (v and v.get("pt")) else None
            others = [self.valve_of[str(o["zone"])]["id"] for o in zs
                      if str(o["zone"]) != zk and (self.valve_of.get(str(o["zone"])) or {}).get("pt")]
            if v:
                how = "%s 열기%s" % (v["id"], (" / %s 닫기" % "·".join(others)) if others else "")
            else:
                how = "밸브 위치 [미확정] — 운전 순서를 정하지 않았습니다"
            d = sup.get(zk) or {}
            q, p, hm = d.get("required_flow_lpm"), d.get("required_pressure_bar"), d.get("required_head_m")
            rows.append([zk, v["id"] if v else "[미확정]", how, "%d두 · %d열" % (z["n_heads"], len(z["lat_ids"])),
                         ("%.0f L/분" % q) if q is not None else "[미확정]",
                         ("%.2f bar (%.1f m)" % (p, hm)) if p is not None else "[미확정]",
                         ("급수 불가 — 관이 급수원에 닿지 않음" if (zk in set(S.get("dead_zones") or []) or not z["n_heads"])
                          else STATUS.get(d.get("status"), "급수원 확인 필요"))])
        self._table(s, DS.G.MARGIN_L, DS.G.ROW1_Y + 0.25, [0.7, 0.8, 2.75, 1.25, 1.2, 1.6, 3.8], rows,
                    head_h=0.32, row_h=0.30, size=10)
        sp = S.get("spray") or {}
        y = DS.G.ROW1_Y + 0.25 + 0.32 + 0.30 * len(zs) + 0.30
        caption(s, DS.G.MARGIN_L, min(y, 5.2), 12.0, "기준 · 가정 · 확인할 것", [
            "필요 압력 = 가장 먼 헤드에서 %.1f bar(반경 %s m)를 내기 위한 급수 지점 압력 · 여과기·부속 여유 2 m 포함" % (sp.get("p_bar", 0), _SL(sp)["r_out"]),
            "유량과 압력을 **동시에** 확보해야 합니다 — 정지압·최대양정만으로 판단하지 않습니다".replace("**", ""),
            "지형 높낮이·펌프 흡상은 계산에 넣지 않았습니다(평탄 가정) — 차이가 있으면 다시 계산합니다",
            "운전 중 급수 지점 압력계로 표의 압력이 나오는지 확인하십시오",
        ] + (["실물 밸브(카플러·싱글밸브 등)는 「밭 입구 매니폴드」 면의 이름을 따릅니다 — V 번호는 구역 순서입니다"]
             if self.meta.get("manifold") else []))
        return s

    def _renumber_slides(self, prs):
        """[V114 · F11] 슬라이드 파트 이름을 순서대로 다시 매긴다 — 면 추가·삭제가 섞이면 같은 이름이 두 번
        저장돼(zip 중복 항목 · `slide22.xml` 실측) PowerPoint 가 복구를 묻거나 면을 잃는다."""
        from pptx.opc.packuri import PackURI
        for i, s in enumerate(prs.slides, 1):
            s.part.partname = PackURI("/ppt/slides/_tmp_%d.xml" % i)
        for i, s in enumerate(prs.slides, 1):
            s.part.partname = PackURI("/ppt/slides/slide%d.xml" % i)

    def _chain_pages(self, prs, anchor):
        """[V116] 연결 사슬 → 흐름 도해 한 면씩(시작 → 부속 … → 끝). 이음마다 판정(확인됨·미확정·불일치)을 단다.

        🔴 판정은 connections.check_ports 가 한다 — 도해가 짓지 않는다. 미확정 이음은 「규격 확인 필요」로 그리고
           확정 조합처럼 보이게 두지 않는다. site.chains = 견적 포함 · site.connection_examples = 예시(견적 미포함).
        """
        from . import connections as CN
        col = {CN.CONFIRMED: GRN, CN.UNKNOWN: DS.C.INK500, CN.MISMATCH: BAD}
        word = {CN.CONFIRMED: "이음 확인됨", CN.UNKNOWN: "규격 확인 필요", CN.MISMATCH: "맞지 않음"}
        compat = list(self.site.get("connection_compatibility") or [])
        groups = []
        for lst, quoted in ((self.S.get("chains") or [], True), (self.S.get("connection_examples") or [], False)):
            for chain, res in chain_steps(lst, self.price_db, compat, self.log):
                groups.append((chain, quoted, res))
        for chain, quoted, (steps, chk) in groups:
            s = new_slide_before(prs, anchor)           # 연결부 상세 뒤 · 헤드 성능 면 앞(면 번호 고정 없음)
            head = "연결 %s — %s · %s" % (chain.get("title") or chain.get("connection_id") or chain.get("id"),
                                        "견적 포함" if quoted else "예시 · 견적 미포함", word.get(chk["status"], chk["status"]))
            label(s, 0.6, 0.45, head, size=22, w=12.1, color=(BAD if chk["status"] == CN.MISMATCH else None))
            n = len(steps)
            per_row = min(n, 5)
            bw, gap = 2.05, 0.42
            for i, st_ in enumerate(steps):
                r, c = divmod(i, per_row)
                x, y = 0.6 + c * (bw + gap), 1.35 + r * 2.75
                box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(bw), Inches(2.0))
                box.fill.solid()
                box.fill.fore_color.rgb = DS.C.WHITE
                box.line.color.rgb = DS.C.CARD_LINE
                img = self.part_png(st_["code"]) if st_["code"] else None
                if img:
                    s.shapes.add_picture(img, Inches(x + 0.45), Inches(y + 0.1), Inches(1.15), Inches(1.15))
                label(s, x + 0.05, y + (1.28 if img else 0.35), st_["name"], size=10.5, w=bw - 0.1,
                      bold=True, align=PP_ALIGN.CENTER)
                if st_["code"]:
                    label(s, x + 0.05, y + 1.66, "%s × %s" % (st_["code"], st_.get("qty", 1)), size=9, w=bw - 0.1,
                          bold=False, color=DS.C.INK500, align=PP_ALIGN.CENTER)
                j = st_["joint"]
                if j is not None:                        # 앞 칸과의 이음 — 같은 줄이면 사이, 줄이 바뀌면 칸 위
                    jc = col.get(j["status"], DS.C.INK500)
                    jx, jy = (x - gap - 0.02, y + 0.85) if c else (x + 0.2, y - 0.42)
                    label(s, jx, jy, "→", size=16, w=0.5, color=jc)
                    if j["status"] != CN.CONFIRMED:
                        label(s, x, y + 2.02, ("규격 확인 필요 — " if j["status"] == CN.UNKNOWN else "맞지 않음 — ")
                              + "; ".join(j.get("issues") or [])[:60], size=8.5, w=bw, bold=False, color=jc)
            label(s, 0.6, 6.05, "→ 초록 = 이음 확인됨 · 회색 = 규격(나사·암수·직경) 확인 필요 · 빨강 = 맞지 않음. "
                  "확인되지 않은 이음은 확정 조합이 아닙니다." + ("" if quoted else " 이 면의 부속은 견적에 들어 있지 않습니다."),
                  size=10, w=12.1, bold=False, color=DS.C.INK500)
            self.log.append("연결 도해 %s (%s)" % (chain.get("id"), "견적" if quoted else "예시"))

    def _supply_appendix(self, prs):
        """Paged requirement/connection appendix generated from the same summary as HTML."""
        from .supply_docs import lines
        if not self.S.get("supply"):
            return
        import textwrap
        content = list(lines(self.S))
        for chain in self.S.get("chains") or []:
            path = " → ".join(str(link.get("custom_name") or link.get("code") or link.get("id"))
                              for link in chain.get("links") or [])
            content.append("연결 %s · %s: %s" % (chain.get("part"), chain.get("connection_id"), path))
        for group in self.S.get("head_groups") or []:
            content.append("열 %s · %s두: %s" % (", ".join(map(str, group["rows"])), group["heads"], group["kit"]["label"]))
        content += ["공구 제외 %s: %s" % (t["code"], t["reason"]) for t in self.S.get("excluded_tools") or []]
        content += list(self.S.get("warnings") or [])
        content = [str(c).replace("**", "") for c in content]
        # [V117 · C] 글자 수(66)가 아니라 글자 폭으로 접는다 — 문장부호만 남는 줄(「미확인입니다 / .」) 금지
        wrapped = [part for line in content for part in wrap_em(line, 11.9, 13.0)]
        for offset in range(0, len(wrapped), 15):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            # [V117 · C] 「빈 화면」 레이아웃은 마스터의 큰 Looperget·루퍼젯 표지 그림을 그대로 보여 본문 글자를 덮었다
            #    (용산리 23면 실측) — 이 부록 면만 마스터 그림을 숨긴다(배경·글자 자리는 그대로).
            slide._element.set("showMasterSp", "0")
            label(slide, .6, .45, "급수·연결 조건 — %d" % (offset // 15 + 1), size=24, w=12, bold=True)
            for i, line in enumerate(wrapped[offset:offset + 15]):
                label(slide, .7, 1.15 + i * .34, line, size=13, w=11.9)
            label(slide, .7, 6.75, "설계 초안 · 필요한 운전 유량과 압력을 동시에 확보해야 합니다.", size=11, w=11.9)

    def _prune_offpage(self, prs, margin_in: float = 3.0):
        W, H, lim = int(prs.slide_width), int(prs.slide_height), int(Inches(margin_in))
        for i, s in enumerate(prs.slides, 1):
            bad = []
            for sh in list(s.shapes):
                try:
                    l, t, w, h = int(sh.left or 0), int(sh.top or 0), int(sh.width or 0), int(sh.height or 0)
                except Exception:
                    continue
                if (l + w < -lim or t + h < -lim or l > W + lim or t > H + lim
                        or max(abs(l), abs(t), abs(l + w), abs(t + h)) > 2 ** 31 - 1):
                    bad.append(sh)
            for sh in bad:
                sh._element.getparent().remove(sh._element)
            if bad:
                self.log.append("면%d: 지면 밖 도형 %d개 삭제(좌표 이상) — 치수·경계 작도를 확인하세요" % (i, len(bad)))

    def _steps_on_p4(self, slide, steps):
        """면19 표가 길어 자리가 없을 때 「다음 단계」를 면4(상호 확인사항)로 내린다.
        아래는 고정 로고(T6.70) · 위는 각주 — 그 사이에 들어갈 때만 놓고, 못 놓으면 False."""
        n = len(steps)
        for size, lh in ((9.5, 0.20), (8.5, 0.18)):
            y = P4_LOGO_Y - 0.08 - n * lh                      # 로고 위에 바닥 정렬
            if y >= getattr(self, "p4_free_y", 6.10) + 0.12:
                label(slide, 0.60, y, "다음 단계", size=11.0, w=1.15, color=ov.DIM)
                bullets(slide, 1.80, y, 10.90, steps, size=size, gap=1)
                return True
        return False

    def _photo_pages(self, prs, anchor, map_slide, fr):
        """meta.photos → 「현장 사진」 면(한 면 두 장). 면 번호를 고정하지 않고 anchor(주배관 면) 앞에 끼운다."""
        from . import photos as PH
        items = list(self.meta.get("photos") or [])
        for m in self.meta.get("photo_missing") or []:
            self.log.append("현장 사진 누락: " + m)
        if not items:
            return
        for it in items:                                   # 대상지 지도 위 번호 — 캡션과 같은 번호
            if it.get("pt"):
                x, y = fr.xy(*it["pt"])
                d = 0.30
                dot = map_slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(x - Inches(d / 2))), Emu(int(y - Inches(d / 2))),
                                                 Inches(d), Inches(d))
                dot.fill.solid()
                dot.fill.fore_color.rgb = DS.C.NAVY
                dot.line.color.rgb = DS.C.WHITE
                tf = dot.text_frame
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                r = tf.paragraphs[0].add_run()
                r.text = str(it["n"])
                r.font.size, r.font.bold, r.font.name = Pt(11), True, DS.T.HEAD
                r.font.color.rgb = DS.C.WHITE
                tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        if any(it.get("pt") for it in items):
            label(map_slide, 8.7, 6.55, "숫자 = 현장 사진 번호(다음 면)", size=11, color=DS.C.INK500, w=4.3)
        work = os.path.join(self.work, "사진")
        # [V117 · 3차 검토 D5] 「당사 현장답사」 화자는 관급 규칙(결정 #98 ①) — 농업·건설은 기존 중립 표현 「현장 사진」만
        from . import segments as _SG
        _ptitle = "현장 사진 — 당사 현장답사" if _SG.segment_of(self.site) == "관급" else "현장 사진"
        for k in range(0, len(items), PH.PER_PAGE):
            ns = new_slide_before(prs, anchor)
            label(ns, 0.62, 0.42, _ptitle, size=24, w=11.5)
            page = items[k:k + PH.PER_PAGE]
            box_w, box_h, top = 5.9, 4.6, 1.35
            for j, it in enumerate(page):
                left = 0.62 + j * (box_w + 0.35) if len(page) > 1 else 0.62 + (box_w + 0.35) / 2
                try:                                       # [V117 · K-01] 안전망 — publish 가 렌더 전에 확인했지만 발행 전체를 멈추지 않는다
                    fn, ar = PH.fit(it["path"], work)
                except Exception as e:
                    self.log.append("현장 사진 %s 렌더 실패(%s) — 관문 확인 필요" % (it.get("n"), type(e).__name__))
                    continue
                w = min(box_w, box_h * ar)
                h = w / ar
                ns.shapes.add_picture(fn, Inches(left + (box_w - w) / 2), Inches(top + (box_h - h) / 2), Inches(w), Inches(h))
                label(ns, left, top + box_h + 0.12, "%d. %s" % (it["n"], it["caption"] or "[설명 없음]"), size=13,
                      w=box_w, bold=False)
        self.log.append("현장 사진 %d장 · %d면" % (len(items), -(-len(items) // PH.PER_PAGE)))

    def _scan_copied(self, slide, tag):
        """대표 작도 복사면의 「n두」가 이 설계의 두수(전체·구역·열)와 다르면 기록한다 — 죽은 숫자 방지(P4)."""
        allowed = {self.S["n_heads"]} | {z["n_heads"] for z in self.S["zones"]} | {l["n_heads"] for l in self.lats}

        def walk(shapes):
            for sh in shapes:
                if sh.shape_type == 6:
                    walk(sh.shapes)
                elif sh.has_text_frame:
                    for m in re.finditer(r"(\d+)\s*두", sh.text_frame.text):
                        if int(m.group(1)) not in allowed:
                            self.log.append("복사면 %s: '%s' — 이 설계 두수와 다름(meta.replace 필요)" % (tag, m.group(0)))
        walk(slide.shapes)

    def _runtime_lines(self):
        """살수강도와 운전 시간 — 10 mm는 **예시 기준**이다(조건 병기). 구역별 헤드 토출로 계산한다.

        대표 확인 2026-09-04: **작물별 관수 기준 정본은 없다 — 농가·지역마다 방식이 다르다.**
        그래서 「배추는 몇 mm」로 쓰지 않고, 살수강도(mm/h)를 내고 10 mm를 예시로 환산해 보여 준다.
        고객이 자기 기준(mm)을 대면 그 자리에서 시간을 다시 낼 수 있게 강도를 함께 적는 것이 요점이다."""
        if self.S.get("supply"):
            return ["관수 시간은 급수원 확인 후 실제 토출량과 농가의 목표 관수량으로 정합니다."]
        H = self.S["hydro"]
        if not H:
            return []
        rates = [h["q_head"] * 60 / 100 for h in H]                  # mm/h (헤드 10×10 m 격자)
        per = [10.0 / r * 60 for r in rates]                            # 10 mm에 드는 분
        tot = sum(per)
        return ["살수강도 약 %.1f mm/h (구역별 %s)" % (sum(rates) / len(rates), " · ".join("%.1f" % r for r in rates)),
                "예시로 10 mm를 주려면 구역당 약 %d분 · %d구역 순차 약 %d시간 %d분 "
                "— 관수량 기준은 농가·지역·작물 상태에 따라 다르므로 위 살수강도로 환산해 쓰십시오"
                % (round(sum(per) / len(per)), len(H), int(tot // 60), int(round(tot % 60)))]

    # ── 치수(간격 표시 — 익산 정본식) ──
    def _dims(self, s, fr, heads: bool):
        """치수는 **적게 · 서로 멀리 · 이름을 달아** 놓는다 (대표 체크 2026-09-04).
        여러 열에 나눠 찍으면 사선 열에서 치수선이 서로 겹쳐 무엇을 재는지 알 수 없다.
          · 가지관 면 = 첫 여백 1곳 + 열 간격 1곳 (헤드 간격은 스프링클러 면의 몫)
          · 스프링클러 면 = **가운데 대표 열 한 줄**에 첫 여백 + 헤드 간격 전부. 열 간격은 찍지 않는다.
        대표 열 = 헤드가 가장 많은 열들 중 가운데 — 그 열이 이 밭의 표준 배치다."""
        lats = [l for l in self.lats if l["heads"]]
        if not lats:
            return
        n1 = lambda v: ("%.1f" % v).rstrip("0").rstrip(".")
        mx = max(len(l["heads"]) for l in lats)
        cand = [i for i, l in enumerate(lats) if len(l["heads"]) == mx]
        mi = cand[len(cand) // 2]
        mid = lats[mi]
        hs = [tuple(h) for h in mid["heads"]]

        if heads:                                   # 면13 — 대표 열 한 줄에 끝까지
            # [V109] 헤드 사이 간격은 **실측**한다 — 「10」 고정은 균등 정렬·열당 두수 지정에서 틀린 값이었다.
            dim_chain(s, fr, [tuple(mid["p0"])] + hs,
                      ["첫 %s" % n1(mid["off"])] + [n1(G.dist(hs[i], hs[i + 1])) for i in range(len(hs) - 1)],
                      off_m=3.2, side=-1)
            return
        self._lat_dims(s, fr, lats)

    def _lat_dims(self, s, fr, lats):
        """면11 — **블록마다 한 줄**로 「경계 → 열 → … → 열 → 경계」를 전부 잰다 (대표 지시 2026-09-04).
        첫 헤드 여백은 여기 없다 — 그건 스프링클러 설치의 초기 간격이라 면13의 몫이다.
        블록마다 축이 다르므로(a = p·n, n = perp(u)) 블록별로 자기 축 위에 놓는다."""
        n1 = lambda v: ("%.1f" % v).rstrip("0").rstrip(".")
        for blk in self.site.get("blocks", []):
            rows = [l for l in lats if l.get("block") == blk.get("name")]
            poly = [tuple(q) for q in (blk.get("polygon") or [])]
            if not rows or len(poly) < 3:
                continue
            u = G.unit(tuple(blk["u"]))
            nv = G.perp(u)
            # 🔴 [V109] 열 위치는 **p0 로 다시 잰다.** job 의 `a` 는 배치기 좌표계(북쪽 +y)의 값이라 지면(아래쪽 +y)으로
            #    뒤집힌 p0·u 와 부호가 반대다. 그 값을 폴리곤 경계와 섞으면 치수·경계 표시가 수백 km 밖(±21억 EMU 초과)에
            #    찍혀 **PowerPoint 가 파일을 열지 못했다**(유촌리·용산리 2026-09-15). P2 는 원점이 밭 곁이라 드러나지 않았다.
            ra = {id(r): G.dot(tuple(r["p0"]), nv) for r in rows}
            rows.sort(key=lambda r: ra[id(r)])
            av = [G.dot(q, nv) for q in poly]
            a_lo, a_hi = min(av), max(av)
            # 치수선을 놓을 열 방향 위치 = 열 길이의 3/4 지점(말단 쪽) — 주배관·분기 표기에서 멀어진다
            t = sum(G.dot(r["p0"], u) + 0.75 * (G.dot(r["p1"], u) - G.dot(r["p0"], u))
                    for r in rows) / len(rows)
            xy = lambda a: (a * nv[0] + t * u[0], a * nv[1] + t * u[1])
            aa = [a_lo] + [ra[id(r)] for r in rows] + [a_hi]
            pts = [xy(a) for a in aa]
            # 경계 이격은 라벨이 길다 — 열 간격과 **반대쪽**에 놓아 서로 덮지 않게 한다
            for i in range(len(aa) - 1):
                d = aa[i + 1] - aa[i]
                edge = i in (0, len(aa) - 2)
                dim_side(s, fr, pts[i], pts[i + 1],
                         ("경계 %s" % n1(d)) if edge else n1(d),
                         off_m=0.0, side=(-1 if edge else 1), serif_m=1.4, size=9.0)

    def _table(self, slide, left, top, widths, rows, head_h=0.36, row_h=0.32, size=11.5):
        tb = slide.shapes.add_table(len(rows), len(widths), Inches(left), Inches(top),
                                    Inches(sum(widths)), Inches(head_h + row_h * (len(rows) - 1)))
        t = tb.table
        t.first_row = True
        for i, w in enumerate(widths):
            t.columns[i].width = Inches(w)
        for r, row in enumerate(rows):
            t.rows[r].height = Inches(head_h if r == 0 else row_h)
            for c, v in enumerate(row):
                cell = t.cell(r, c)
                cell.margin_left = cell.margin_right = Inches(0.06)
                cell.margin_top = cell.margin_bottom = Inches(0.02)
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string("EFEDE4") if r == 0 else DS.C.WHITE
                p = cell.text_frame.paragraphs[0]
                p.alignment = PP_ALIGN.LEFT if c in (0, 1, 3, 4) else PP_ALIGN.CENTER
                run = p.add_run()
                run.text = str(v)
                run.font.name = DS.T.CAPTION
                run.font.size = Pt(size)
                run.font.bold = (r == 0)
                run.font.color.rgb = DS.C.INK
        return t

    @staticmethod
    def _bom_row_h(r, rh=0.24, rmin=BOM_RMIN):
        """표 한 행의 높이(in). 분류 머리행 = rh · 품목 행 = 줄 수 어림, 단 **사진 칸이 있어** 최소 rmin.
        [계통도 · 사진 열] 칸 폭이 사진 열만큼 좁아져 글자 수/줄을 낮췄다(품목 17 · 규격 9 · 비고 15)."""
        if "_group" in r:
            return rh
        q = "%s %s" % (r.get("qty", ""), r.get("unit", ""))           # 수량 칸(0.62 in)은 글자 폭 약 4.2 em(실측: 「17 미확정」 4.4 em 이 접힘) — 「17 미확정」은 두 줄로 접힌다
        q_em = sum(1.0 if ord(c) > 0x2000 else (0.30 if c == " " else 0.55) for c in q)
        lines = max(-(-len(str(r["name"])) // 17), -(-len(str(r["spec"])) // 9), -(-len(str(r["note"])) // 15),
                    int(-(-q_em // 4.2)), 1)
        return max(rmin, 0.10 + 0.105 * lines)

    @staticmethod
    def _bom_table_h(rows, rh=0.24, rmin=BOM_RMIN):
        """표 높이 어림 — 규격·비고가 접히면 PowerPoint가 행을 늘리므로 줄 수를 세어 더한다.
        실측(8/7.5/7 pt · 05 숙진리): 1줄 0.24 · 2줄 0.31 · 3줄 0.41 in. 사진 칸이 있는 행은 최소 rmin(0.30)."""
        return rh + sum(Renderer._bom_row_h(r, rh, rmin) for r in rows)

    # ── BOM 표(2단) ──
    @staticmethod
    def _bom_lines(bom):
        """표 행 목록 — 분류가 바뀌는 자리에 머리행(group)을 끼운다."""
        lines, g = [], None
        for r in bom:
            if r.get("group") != g:
                g = r.get("group")
                lines.append({"_group": r.get("group_label", g or "")})
            lines.append(r)
        return lines

    @staticmethod
    def _split_lines(lines):
        """두 단으로 가른다 — 분류 머리행이 단 끝에 홀로 남지 않게."""
        half = -(-len(lines) // 2)
        while half < len(lines) and "_group" in lines[half - 1]:
            half -= 1
        return lines[:half], lines[half:]

    def _bom_pages(self, bom, page_h=BOM_PAGE_H):
        """→ [(왼쪽 단 행들, 오른쪽 단 행들), …]. 한 면에 들어가면(기존 반분 그대로) 1쪽, 사진 칸으로 행이 높아져 넘치면
        단마다 page_h 까지 채우고 다음 단·다음 면으로 넘긴다(분류 머리행이 단 끝에 홀로 남지 않게 · 이어지면 「(이어서)」)."""
        lines = self._bom_lines(bom)
        lft, rgt = self._split_lines(lines)
        if max(self._bom_table_h(lft), self._bom_table_h(rgt)) <= page_h:
            return [(lft, rgt)]
        cols, cur, cur_h, pend, grp = [], [], 0.24, None, None
        for ln in lines:
            if "_group" in ln:
                pend, grp = ln, ln["_group"]
                continue
            hh = self._bom_row_h(ln)
            add = hh + (0.24 if pend else 0.0)
            if cur and cur_h + add > page_h:
                cols.append(cur)
                cur, cur_h = [], 0.24
                if pend is None and grp is not None:
                    pend = {"_group": "%s (이어서)" % grp}
                add = hh + (0.24 if pend else 0.0)
            if pend:
                cur.append(pend)
                pend = None
            cur.append(ln)
            cur_h += add
        if cur:
            cols.append(cur)
        return [(cols[i], cols[i + 1] if i + 1 < len(cols) else []) for i in range(0, len(cols), 2)]

    def _bom_thumb(self, code):
        """표 안 사진 — 원본(수백 px)을 128 px 로 줄여 쓴다(제안서 용량 · 같은 코드는 한 번만)."""
        png = self.part_png(code) if code else None
        if not png:
            return None
        d = os.path.join(self.work, "_bom썸네일")
        fn = os.path.join(d, "%s.png" % code)
        if not os.path.exists(fn):
            try:
                os.makedirs(d, exist_ok=True)
                im = Image.open(png)
                im.thumbnail((128, 128), Image.LANCZOS)
                im.save(fn, "PNG")
            except Exception as e:
                self.log.append("표 사진 축소 실패 %s(%s)" % (code, type(e).__name__))
                return png
        return fn

    def _bom_cell_img(self, th, rh, bg):
        """썸네일을 **칸 비율의 캔버스**(행 높이 · 칸 배경색)에 비율 유지로 앉힌다 — 표 칸 그림 채우기로 쓴다.
        그림이 칸에 묶여 있어 PowerPoint 가 행을 조금 키워도 사진이 행과 어긋나지 않는다(떠 있는 그림은 누적해서 밀렸다)."""
        d = os.path.join(self.work, "_bom썸네일")
        fn = os.path.join(d, "%s_%d_%02X%02X%02X.png" % (os.path.splitext(os.path.basename(th))[0], int(rh * 100), bg[0], bg[1], bg[2]))
        if not os.path.exists(fn):
            im = Image.open(th).convert("RGBA")
            W, H = int(BOM_COLS[0] * 200), int(rh * 200)
            sc = min((W - 10) / im.width, (H - 10) / im.height)
            im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.LANCZOS)
            cv = Image.new("RGB", (W, H), tuple(bg))
            cv.paste(im, ((W - im.width) // 2, (H - im.height) // 2), im)
            cv.save(fn, "PNG")
        return fn

    @staticmethod
    def _cell_blip(slide, cell, png):
        """표 칸 배경을 그림(blipFill · 늘이기)으로 — 칸 채우기 자리(도형 채우기 다음 · 머리글 앞)에 넣는다."""
        from pptx.oxml import parse_xml
        _ip, rid = slide.part.get_or_add_image_part(png)
        tcPr = cell._tc.get_or_add_tcPr()
        for tag in ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"):
            for el in tcPr.findall(qn(tag)):
                tcPr.remove(el)
        tcPr.append(parse_xml('<a:blipFill xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                              'xmlns:r="%s"><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></a:blipFill>' % (R_NS, rid)))

    def _bom_tables(self, slide, bom, pair=None):
        PANEL = RGBColor(0xF4, 0xF4, 0xF0)
        GROUP_BG = RGBColor(0xFB, 0xF4, 0xC6)
        NOPHOTO = RGBColor(0xEA, 0xEA, 0xEA)
        pair = pair if pair is not None else self._bom_pages(bom)[0]
        for pi, part in enumerate(pair):
            if not part:
                continue
            heights = [0.24] + [self._bom_row_h(r) for r in part]
            gf = slide.shapes.add_table(len(part) + 1, 6, Inches(0.6 + pi * 6.25), Inches(1.1),
                                        Inches(6.05), Inches(sum(heights)))
            t = gf.table
            t.first_row = False
            t.horz_banding = False
            for w, col in zip(BOM_COLS, t.columns):
                col.width = Inches(w)

            def put(cell, text, size=8, bold=False, align=PP_ALIGN.LEFT, color=DS.C.INK, wrap=False):
                tf = cell.text_frame
                tf.margin_left = tf.margin_right = Pt(3)
                tf.margin_top = tf.margin_bottom = Pt(0.5)
                tf.word_wrap = wrap
                p = tf.paragraphs[0]
                p.alignment = align
                r = p.add_run()
                r.text = text
                r.font.name = DS.T.CAPTION
                r.font.size = Pt(size)
                r.font.bold = bold
                r.font.color.rgb = color
                p._p.get_or_add_endParaRPr().set("sz", str(int(size * 100)))   # 빈 칸(규격 없음 등)이 기본 18 pt 로 행을 키우지 않게
            for c, tt in enumerate(["사진", "품목", "규격", "수량", "단가", "비고"]):
                cell = t.cell(0, c)
                cell.fill.solid()
                cell.fill.fore_color.rgb = DS.C.INK
                put(cell, tt, size=9, bold=True, color=DS.C.WHITE, align=PP_ALIGN.CENTER if c != 1 else PP_ALIGN.LEFT)
            for ri, row in enumerate(part, 1):
                rh = heights[ri]
                if "_group" in row:
                    cell = t.cell(ri, 0)
                    cell.merge(t.cell(ri, 5))
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = GROUP_BG
                    put(cell, row["_group"], size=8, bold=True)
                    continue
                for c in range(6):
                    cell = t.cell(ri, c)
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = DS.C.WHITE if ri % 2 else PANEL
                    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                th = self._bom_thumb(row.get("code"))
                if th is None:                                    # 사진이 없으면 빈 칸이 아니라 회색 「사진 없음」
                    t.cell(ri, 0).fill.fore_color.rgb = NOPHOTO
                    put(t.cell(ri, 0), "사진 없음", size=6, align=PP_ALIGN.CENTER, color=DS.C.INK500, wrap=True)
                else:
                    # 빈 칸의 기본 글자 크기(18 pt)가 행을 0.40 in 이상으로 키운다 — 끝 문단 크기를 6 pt 로 낮춘다
                    t.cell(ri, 0).text_frame.paragraphs[0]._p.get_or_add_endParaRPr().set("sz", "600")
                    try:
                        bg = DS.C.WHITE if ri % 2 else PANEL
                        self._cell_blip(slide, t.cell(ri, 0), self._bom_cell_img(th, rh, (bg[0], bg[1], bg[2])))
                    except Exception as e:
                        self.log.append("표 사진 넣기 실패(%s)" % type(e).__name__)
                        put(t.cell(ri, 0), "사진 없음", size=6, align=PP_ALIGN.CENTER, color=DS.C.INK500, wrap=True)
                put(t.cell(ri, 1), row["name"], size=8, wrap=True)
                put(t.cell(ri, 2), str(row["spec"]), size=7.5, color=DS.C.INK500, wrap=True)
                put(t.cell(ri, 3), "%s %s" % (format(row["qty"], ","), row["unit"]), size=8, align=PP_ALIGN.CENTER)
                # [V114 · F08] 단가 없음 = 「미확정」(0원으로 보이지 않게)
                put(t.cell(ri, 4), format(row["price"], ",") if row["price"] is not None else "미확정",
                    size=8, align=PP_ALIGN.RIGHT)
                put(t.cell(ri, 5), row["note"], size=7, color=DS.C.INK500, wrap=True)
            for r_, hh in zip(t.rows, heights):
                r_.height = Inches(hh)


# ══════════════ 후처리 (PowerPoint COM — 선택) ══════════════
def export_pdf(pptx_path: str, pdf_path: Optional[str] = None) -> str:
    import win32com.client
    src = os.path.abspath(pptx_path)
    dst = os.path.abspath(pdf_path or os.path.splitext(src)[0] + ".pdf")
    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(src, WithWindow=False)
    try:
        pres.SaveAs(dst, 32)
    finally:
        pres.Close()
        app.Quit()
    return dst


def export_png(pptx_path: str, out_dir: str, width: int = 1600) -> List[str]:
    import win32com.client
    src = os.path.abspath(pptx_path)
    os.makedirs(out_dir, exist_ok=True)
    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(src, WithWindow=False)
    out = []
    try:
        for i in range(1, pres.Slides.Count + 1):
            p = os.path.join(os.path.abspath(out_dir), "s%02d.png" % i)
            pres.Slides(i).Export(p, "PNG", width, int(width * 9 / 16))
            out.append(p)
    finally:
        pres.Close()
        app.Quit()
    return out


def check_pages(pptx_path: str) -> Dict[int, List[str]]:
    """정본 §9 기계 점검(표준_pptx.check_slide) — 지면별 위반 목록."""
    prs = Presentation(pptx_path)
    return {i: DS.check_slide(s, i) for i, s in enumerate(prs.slides, 1) if DS.check_slide(s, i)}


__all__ = ["Renderer", "Map", "export_pdf", "export_png", "check_pages", "MASTER"]
