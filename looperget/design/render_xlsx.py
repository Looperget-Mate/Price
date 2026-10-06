# -*- coding: utf-8 -*-
"""
looperget.design.render_xlsx — 설계 요약 → 견적서 엑셀 (프로덕션 출력 엔진 서식 그대로).

`looperget.quote_docs.create_quote_excel`을 **직접 호출**한다 — 프로덕션 코드는 한 줄도 고치지 않는다.
app.py가 주입하던 Drive 함수 3개는 (1) 로컬 부속 이미지 캐시 → (2) 서비스계정 Drive 순으로 대체한다.
승인 통합 견적(08-28 v2)에서 대표가 확정한 손질을 그대로 잇는다:
  · 이미지 칸 20 chars × 84 pt · 알맹이만 잘라 넣기(autocrop) · 여백 3 px
  · 금액 = 수량×단가 **수식** · 합계 = SUM(첫 품목행 ~ 바로 윗줄) — 수량을 고치면 합계가 따라간다
  · 비고 열 = 어느 연결부·어느 세트·몇 개소인지(엔진 note)
"""
from __future__ import annotations

import base64
import io
import os
import types
from typing import Dict, List, Optional

import xlsxwriter
from PIL import Image, ImageChops

from .. import quote_docs

ROW0 = 9                                  # 엔진: 첫 품목 행(0-base) = 엑셀 10행
IMG_COL_CHARS, ROW_H_ITEM, IMG_PAD_PX, IMG_LONG_MAX = 20, 84, 3, 900
CELL_W_PX = IMG_COL_CHARS * 7 + 5         # 엑셀 환산: chars×7+5 px
CELL_H_PX = int(ROW_H_ITEM * 4 / 3)
CELL_W, CELL_H = CELL_W_PX - 2 * IMG_PAD_PX, CELL_H_PX - 2 * IMG_PAD_PX


# ══════════════ 이미지 ══════════════
def autocrop(im: Image.Image) -> Image.Image:
    bb = None
    if im.mode in ("RGBA", "LA"):
        b = im.getchannel("A").getbbox()
        if b and (b[2] - b[0]) * (b[3] - b[1]) > 0.02 * im.width * im.height:
            bb = b
    if bb is None:
        g = im.convert("RGB")
        white = Image.new("RGB", g.size, (255, 255, 255))
        bb = ImageChops.difference(g, white).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
    if bb and (bb[2] - bb[0]) > 8 and (bb[3] - bb[1]) > 8:
        im = im.crop(bb)
    return im


def fit_image(path: str):
    im = Image.open(path)
    if im.mode == "P":
        im = im.convert("RGBA")
    im = autocrop(im)
    long_side = max(im.width, im.height)
    if long_side > IMG_LONG_MAX:
        k = IMG_LONG_MAX / long_side
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    scale = min(CELL_W / im.width, CELL_H / im.height)
    w, h = im.width * scale, im.height * scale
    xo = IMG_PAD_PX + int((CELL_W - w) / 2)
    yo = IMG_PAD_PX + int((CELL_H - h) / 2)
    while xo + w > CELL_W_PX or yo + h > CELL_H_PX:
        scale *= 0.99
        w, h = im.width * scale, im.height * scale
        xo = IMG_PAD_PX + int((CELL_W - w) / 2)
        yo = IMG_PAD_PX + int((CELL_H - h) / 2)
    return buf, scale, xo, yo


class ImageSource:
    """품목코드 → data-URI. 로컬 캐시(부속이미지/{code}.png) 우선, 없으면 Drive(서비스계정)."""

    def __init__(self, img_dir: Optional[str], price_db: Dict, root: str, fetch=None):
        self.img_dir, self.price_db, self.root = img_dir, price_db, root
        self.fetch = fetch          # [V109] 앱이 주는 사진 공급자(code → data-URI). 서버엔 서비스계정 파일이 없다.
        self._cache: Dict[str, Optional[str]] = {}
        self._creds = None
        self.n_local = self.n_drive = 0

    def _token(self):
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import Request
        if self._creds is None:
            key = os.path.join(self.root, ".secrets", "service_account.json")
            self._creds = Credentials.from_service_account_file(
                key, scopes=["https://www.googleapis.com/auth/drive.readonly"])
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds.token

    def local_png(self, code: str) -> Optional[str]:
        if self.img_dir:
            p = os.path.join(self.img_dir, "%s.png" % code)
            if os.path.exists(p):
                return p
        return None

    def data_uri(self, code: str) -> Optional[str]:
        if code in self._cache:
            return self._cache[code]
        uri = None
        p = self.local_png(code)
        if p:
            uri = "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()
            self.n_local += 1
        elif self.fetch is not None:
            try:
                uri = self.fetch(code) or None
            except Exception:
                uri = None
            if uri:
                self.n_drive += 1
        else:
            # 세트 품목은 **구성 사진**을 쓴다 — Products 사진은 낱개 카플러 한 개라
            # 연결세트·마감세트가 거의 같아 보이고 세트에 무엇이 들었는지 안 보인다.
            # 정본 = Sets 시트 「이미지파일명」(대표가 갈아 끼우면 따라온다 · 2026-08-29 결정).
            # `_단가_DB.json`의 `img_set`은 그 파생본이다 — P2 재작성 때 이 경로가 빠졌었다(2026-09-04 복구).
            info = self.price_db.get(code, {})
            fid = str(info.get("img_set") or info.get("img", "") or "")
            if len(fid) >= 10:
                try:
                    import requests
                    r = requests.get("https://www.googleapis.com/drive/v3/files/%s?alt=media" % fid,
                                     headers={"Authorization": "Bearer %s" % self._token()}, timeout=30)
                    if r.status_code == 200:
                        uri = "data:image/png;base64," + base64.b64encode(r.content).decode()
                        self.n_drive += 1
                        if self.img_dir:
                            os.makedirs(self.img_dir, exist_ok=True)
                            open(os.path.join(self.img_dir, "%s.png" % code), "wb").write(r.content)
                except Exception:
                    uri = None
        self._cache[code] = uri
        return uri


# ══════════════ 엔진 워크북 대역 — 이미지 다듬기 + 후처리 ══════════════
class _WS:
    def __init__(self, ws):
        self._ws = ws
        self.n_img = 0

    def __getattr__(self, k):
        return getattr(self._ws, k)

    def insert_image(self, row, col, path, opts=None):
        try:
            data, scale, xo, yo = fit_image(path)
        except Exception:
            return self._ws.insert_image(row, col, path, opts or {})
        self.n_img += 1
        return self._ws.insert_image(row, col, path, {
            "image_data": data, "x_scale": scale, "y_scale": scale,
            "x_offset": xo, "y_offset": yo, "object_position": 2, "url": None})


class _WB:
    def __init__(self, wb):
        self._wb, self.last = wb, None

    def __getattr__(self, k):
        return getattr(self._wb, k)

    def add_worksheet(self, name=None):
        self.last = _WS(self._wb.add_worksheet(name))
        return self.last

    def close(self):
        pass


def build(summary: Dict, out_path: str, *, date: str, label: str, buyer: Dict, remarks: str,
          svc: Optional[List[Dict]] = None, price_db: Optional[Dict] = None,
          img_dir: Optional[str] = None, root: Optional[str] = None,
          fetch=None, tier2: Optional[str] = None, head_labels=None, site_name: str = "",
          hide_code: bool = False, tier3: Optional[List[str]] = None) -> Dict:
    """→ {"path", "n_items", "n_img", "total", "total_row"}

    [V109] `tier2` 를 주면 **시공업체용 두 단가 양식**(엔진 profit 양식) — 왼쪽 = tier2(대리점가1 등) · 오른쪽 =
    summary tier(소비자가) · 이익율. 단가는 price_db[code][tier2] 에서 읽고 없으면 0 + `missing2`.
    [V117 · 2단계] head_labels = (발주처, 현장명, 담당) — 관급·건설 머리글(design.segments · 수신/참조/담당자 칸 라벨) ·
    hide_code = 품목정보 칸의 품목 코드 줄 숨김(관급 고객본). 기본값이면 예전과 같은 파일이다.
    [2026-10-07] `tier3` = [매입가 열, 중간업체가 열] → **내부 검토 세 단가 양식**(매입 · 중간업체 · 소비자 · 이익율).
    tier2 와 함께 주지 않는다(tier3 가 우선).
    """
    if tier3:
        tier2 = None
    root = root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = ImageSource(img_dir, price_db or {}, root, fetch=fetch)
    tier = summary.get("tier", "소비자가")
    missing2: List[str] = []
    quote_docs.bind(get_drive_file_map_deep=lambda: {},
                    get_best_image_id=lambda code, db_img, fmap: code,
                    download_image_by_id=src.data_uri)
    real = xlsxwriter.Workbook(out_path)
    proxy = _WB(real)
    saved = quote_docs.xlsxwriter
    quote_docs.xlsxwriter = types.SimpleNamespace(Workbook=lambda *a, **k: proxy)
    try:
        items = []
        for r in summary["bom"]:
            it = {"코드": r["code"], "품목": r["name"], "규격": r["spec"], "단위": r["unit"],
                  "수량": r["qty"], "price_1": r["price"] or 0, "image_data": r["code"]}
            if tier2:
                p2 = (price_db or {}).get(r["code"], {}).get(tier2)
                if p2 is None:
                    missing2.append(r["code"])
                it["price_1"], it["price_2"] = int(p2 or 0), r["price"] or 0
            if tier3:
                _pp = (price_db or {}).get(r["code"], {})
                pb, pm = _pp.get(tier3[0]), _pp.get(tier3[1])
                if pb is None or pm is None:
                    missing2.append(r["code"])
                it["price_1"], it["price_2"], it["price_3"] = int(pb or 0), int(pm or 0), r["price"] or 0
            items.append(it)
        svc = svc or []
        form = "tier3" if tier3 else ("profit" if tier2 else "basic")
        quote_docs.create_quote_excel(items, svc, label, date, form,
                                      ([{"대리점가1": "중간업체가"}.get(tier3[0], tier3[0]), {"대리점가1": "중간업체가"}.get(tier3[1], tier3[1]), tier] if tier3 else ([tier2, tier] if tier2 else [tier])),
                                      buyer, remarks)
        ws = proxy.last
        n = len(items)
        total_row = ROW0 + n + (1 + len(svc) if svc else 0)          # 0-base 「자재비 합계」 행
        F = lambda **k: real.add_format(dict({"font_name": "맑은 고딕", "valign": "vcenter", "border": 1}, **k))
        f_amt = F(align="right", font_size=14, num_format="#,##0", shrink=True)
        f_tot = F(bold=True, bg_color="#E6E6E6", align="right", font_size=16, num_format="#,##0", shrink=True)
        f_rmk = F(align="left", font_size=9, text_wrap=True)
        f_qty = F(align="right", font_size=14, num_format="0.###")
        # Legacy quote template coerces quantities to int. Restore physical metres here.
        for i, row in enumerate(summary["bom"]):
            ws.write_number(ROW0 + i, 3, float(row["qty"]), f_qty)
        ws.write(0, 0, "견 적 서    —    %s" % label,
                 real.add_format({"font_name": "맑은 고딕", "valign": "vcenter", "bold": True,
                                  "font_size": 20, "align": "center"}))
        ws.set_column(0, 0, IMG_COL_CHARS)
        total = summary["total"] + sum(int(s["금액"]) for s in svc)
        total_text = None
        total2 = None
        if tier3:
            # 세 단가: D 수량 · E 매입 F 금액 · G 중간업체 H 금액 · I 소비자 J 금액 · K 이익율(소비자 대비 매입)
            f_pct = F(align="center", font_size=14, num_format="0.0%", shrink=True)
            total2 = 0
            for i, it in enumerate(items):
                ws.set_row(ROW0 + i, ROW_H_ITEM)
                er = ROW0 + i + 1
                q_ = float(it["수량"])
                a1, a2, a3 = (round(int(it[k]) * q_) for k in ("price_1", "price_2", "price_3"))
                total2 += a1
                for col, a, let in ((5, a1, "E"), (7, a2, "G"), (9, a3, "I")):
                    ws.write_formula(ROW0 + i, col, "=D%d*%s%d" % (er, let, er), f_amt, a)
                ws.write_formula(ROW0 + i, 10, "=IF(J%d>0,(J%d-F%d)/J%d,0)" % (er, er, er, er), f_pct,
                                 ((a3 - a1) / a3) if a3 else 0)
                if it["코드"] in missing2:
                    for col in (4, 5, 6, 7, 10):
                        ws.write(ROW0 + i, col, "미확정", f_rmk)
                if summary["bom"][i]["price"] is None:
                    for col in (8, 9, 10):
                        ws.write(ROW0 + i, col, "미확정", f_rmk)
            if summary["bom"] and all(r["price"] is None for r in summary["bom"]):
                ws.write(total_row, 9, "미확정", f_tot)
                total_text = "미확정"
            else:
                ws.write_formula(total_row, 9, "=SUM(J$%d:INDEX(J:J,ROW()-1))" % (ROW0 + 1), f_tot, total)
            if svc:
                ws.write(total_row, 0, "합계 (자재 + %s)" % " · ".join(str(s["항목"]) for s in svc),
                         F(bold=True, bg_color="#E6E6E6", align="center", font_size=14))
        elif not tier2:
            ws.set_column(6, 6, 34)
            for i, r in enumerate(summary["bom"]):
                ws.set_row(ROW0 + i, ROW_H_ITEM)
                er = ROW0 + i + 1
                ws.write_formula(ROW0 + i, 5, "=D%d*E%d" % (er, er), f_amt, r["amount"] or 0)
                if r["price"] is None:
                    ws.write(ROW0 + i, 4, "미확정", f_rmk)
                    ws.write(ROW0 + i, 5, "미확정", f_rmk)
                ws.write(ROW0 + i, 6, r["note"], f_rmk)
            # [R03] 전 품목 단가가 없으면 합계는 **미확정**(식이 「미확정」 글자를 0 으로 더하지 않게)
            if summary["bom"] and all(r["price"] is None for r in summary["bom"]):
                ws.write(total_row, 5, "미확정", f_tot)
                total_text = "미확정"
            else:
                ws.write_formula(total_row, 5, "=SUM(F$%d:INDEX(F:F,ROW()-1))" % (ROW0 + 1), f_tot, total)
            # [R04] 추가 비용 줄이 있으면 「자재비 합계」가 아니다
            if svc:
                ws.write(total_row, 0, "합계 (자재 + %s)" % " · ".join(str(s["항목"]) for s in svc),
                         F(bold=True, bg_color="#E6E6E6", align="center", font_size=14))
        else:
            # profit 양식: D 수량 · E 단가1(tier2) · F 금액1 · G 단가2(tier) · H 금액2 · I 이익율. 비고 열은 없다.
            f_pct = F(align="center", font_size=14, num_format="0.0%", shrink=True)
            total2 = 0
            for i, it in enumerate(items):
                ws.set_row(ROW0 + i, ROW_H_ITEM)
                er = ROW0 + i + 1
                a1, a2 = round(int(it["price_1"]) * float(it["수량"])), round(int(it["price_2"]) * float(it["수량"]))
                total2 += a1
                ws.write_formula(ROW0 + i, 5, "=D%d*E%d" % (er, er), f_amt, a1)
                ws.write_formula(ROW0 + i, 7, "=D%d*G%d" % (er, er), f_amt, a2)
                ws.write_formula(ROW0 + i, 8, "=IF(H%d>0,(H%d-F%d)/H%d,0)" % (er, er, er, er), f_pct,
                                 ((a2 - a1) / a2) if a2 else 0)
                if it["코드"] in missing2:
                    ws.write(ROW0 + i, 4, "미확정", f_rmk)
                    ws.write(ROW0 + i, 5, "미확정", f_rmk)
                    ws.write(ROW0 + i, 8, "미확정", f_rmk)
                if summary["bom"][i]["price"] is None:
                    ws.write(ROW0 + i, 6, "미확정", f_rmk)
                    ws.write(ROW0 + i, 7, "미확정", f_rmk)
                    ws.write(ROW0 + i, 8, "미확정", f_rmk)
            # [V115 · C03] 두 단가 양식도 같은 정책 — 전 품목 단가가 없으면 합계 칸은 0 이 아니라 **미확정**.
            if summary["bom"] and all(r["price"] is None for r in summary["bom"]):
                ws.write(total_row, 7, "미확정", f_tot)
                total_text = "미확정"
            else:
                ws.write_formula(total_row, 7, "=SUM(H$%d:INDEX(H:H,ROW()-1))" % (ROW0 + 1), f_tot, total)
            if svc:
                ws.write(total_row, 0, "합계 (자재 + %s)" % " · ".join(str(s["항목"]) for s in svc),
                         F(bold=True, bg_color="#E6E6E6", align="center", font_size=14))
        if summary.get("missing") or missing2:
            ws.write(0, 0, "견 적 서 — %s (%s)" % (label, "단가 미확정 — 물량만" if total_text == "미확정"
                                                     else "가격 확정 품목 소계 · 미확정 별도"),
                     real.add_format({"font_name": "맑은 고딕", "bold": True, "font_size": 16}))
        lines = sum(max(1, -(-len(t) // 56)) for t in remarks.split("\n"))
        ws.set_row(total_row + 3, max(20 * lines + 12, 44))
        if head_labels:          # [V117 · 2단계] 관급·건설 머리글 — 엔진 양식의 칸 자리 그대로(수신 A3 · 참조 A4/B4 · 담당자 C6)
            f_lbl = F(bold=True, bg_color="#F0F0F0", align="center", font_size=11)
            ws.write(2, 0, head_labels[0], f_lbl)
            ws.write(3, 0, head_labels[1], f_lbl)
            ws.write(3, 1, site_name or "/", F(align="left", font_size=11))
            ws.write(5, 2, head_labels[2], f_lbl)
        if hide_code:            # [V117 · 2단계] 관급 고객본 — 품목정보 칸 「이름 · 규격」만(코드 줄 숨김 · 사진은 코드로 그대로 찾는다)
            f_it = F(bold=True, align="left", font_size=12, text_wrap=True)
            for i, r in enumerate(summary["bom"]):
                ws.write(ROW0 + i, 1, "%s\n%s" % (r["name"], r["spec"]), f_it)
    finally:
        quote_docs.xlsxwriter = saved
        real.close()
    return {"path": out_path, "n_items": len(items), "n_img": ws.n_img, "total": total, "total_text": total_text,
            "total_row": total_row + 1, "img_local": src.n_local, "img_drive": src.n_drive,
            "tier": tier, "tier2": tier2, "tier3": tier3, "total2": total2, "missing2": missing2}


__all__ = ["build", "ImageSource", "autocrop", "fit_image"]
