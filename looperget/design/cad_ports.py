"""CAD 끼움 자리 참고 — 연결 사슬 이웃 부속이 맞물릴 「후보」인지 알려 준다 (2026-10-04 · 대표 A안).

데이터 = cad_ports.json (tools/cad_sync.py 가 설계 CAD my-product-cad 에서 만든 사본).
🔴 판정이 아니다. CAD 연결부속은 전부 status 추정(실측·승인 아님)이므로 여기 결과는
   connections.check_ports 의 확인됨/불일치/미확정을 바꾸지 않고, 화면 참고 문장으로만 쓴다.
규칙은 CAD 3D 뷰어(viewer.html IRRIGATION.compatible)와 같다 — 캠은 C–E 짝 + 중/소 일치,
나사는 암–수 + 호칭 일치여도 피치 미확인이라 「조건부」, 미늘·조임·캡·테이프는 관·호스를 받는 자리.
"""
from __future__ import annotations

import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cad_ports.json")
_DATA = None
CAM = {"camC": "C", "camE": "E"}
THREAD = {"male": "수", "female": "암"}
HOSE_SIDE = {"barb", "compression", "hosecap", "tape"}

MATCH, COND, CLASH, NONE = "결합 후보", "조건부 후보", "불일치 후보", "판단 자료 없음"


def _data():
    global _DATA
    if _DATA is None:
        try:
            with open(_PATH, encoding="utf-8") as fh:
                _DATA = json.load(fh)
        except (OSError, ValueError):
            _DATA = {"meta": {}, "parts": {}, "sku": {}}
    return _DATA


def ports_of(code):
    """판매 코드(또는 대표 코드) → {family, label, nominal, name, ports}. CAD 에 없으면 None."""
    d = _data()
    code = str(code or "").strip().zfill(5)
    sku = d["sku"].get(code)
    fam = sku["family"] if sku else code
    part = d["parts"].get(fam)
    if not part:
        return None
    return {"code": code, "family": fam, "label": (sku or {}).get("label"), "nominal": (sku or {}).get("nominal"),
            "name": part.get("name"), "ports": part.get("ports") or []}


def _pair(a, b, na, nb):
    ka, kb = a.get("kind"), b.get("kind")
    if ka in CAM and kb in CAM:
        sa, sb = a.get("cam_size"), b.get("cam_size")
        if CAM[ka] == CAM[kb]:
            return CLASH, f"같은 성(둘 다 {CAM[ka]})"
        if sa and sb and sa != sb:
            return CLASH, f"캠 크기 다름({sa}·{sb}) — 이경 부속 필요"
        return MATCH, f"C–E 짝 · 캠 {sa or '?'}"
    if ka in THREAD and kb in THREAD:
        if ka == kb:
            return CLASH, f"같은 {THREAD[ka]}나사"
        x, y = (a.get("nominal") if na is None else na), (b.get("nominal") if nb is None else nb)   # 0 = 비교 안 함
        if x and y and x != y:
            return CLASH, f"나사 호칭 다름({x:g}·{y:g})"
        return COND, "암–수 나사 · 피치·규격 미확인"
    return None


def _thread_nom(info, port):
    """판매 규격의 나사 호칭. 나사 끝이 한 호칭인 부속만 판매 라벨 호칭을 쓴다.
    이경(25↔20 등)인데 판매 코드가 대표형과 다르면 어느 끝이 몇인지 몰라 0(비교 안 함)."""
    noms = {p.get("nominal") for p in info["ports"] if p.get("kind") in THREAD}
    if len(noms) == 1:
        return info["nominal"] or port.get("nominal")
    return port.get("nominal") if info["code"] == info["family"] else 0


def pair_hint(code_a, code_b):
    """두 부속 사이 가장 나은 끼움 후보 한 개. 반환 {status, text}."""
    pa, pb = ports_of(code_a), ports_of(code_b)
    if not pa or not pb:
        miss = [c for c, p in ((code_a, pa), (code_b, pb)) if not p]
        return {"status": NONE, "text": "CAD 모델 없음: " + ", ".join(str(m) for m in miss)}
    found = []
    for a in pa["ports"]:
        for b in pb["ports"]:
            if a.get("kind") in THREAD and b.get("kind") in THREAD:
                r = _pair(a, b, _thread_nom(pa, a), _thread_nom(pb, b))
            else:
                r = _pair(a, b, None, None)
            if r:
                found.append(r)
    for want in (MATCH, COND, CLASH):
        hit = [t for s, t in found if s == want]
        if hit:
            return {"status": want, "text": hit[0]}
    hose = all(any(p.get("kind") in HOSE_SIDE for p in x["ports"]) for x in (pa, pb))
    return {"status": NONE, "text": "직접 끼우는 자리 없음" + (" — 관·호스를 사이에 두는 접속" if hose else "")}


def chain_hints(chains):
    """사슬마다 코드가 있는 이웃 부속 쌍의 참고 문장. 사슬 판정은 건드리지 않는다."""
    out = []
    for chain in chains or []:
        coded = [str(l.get("code")) for l in chain.get("links") or [] if l.get("code")]
        for a, b in zip(coded, coded[1:]):
            h = pair_hint(a, b)
            out.append(f"{chain.get('id', '')}: {a} → {b} · {h['status']} — {h['text']}")
    return out


def source_note():
    m = _data().get("meta") or {}
    return f"설계 CAD {m.get('catalog', '')} {m.get('catalog_date', '')} · {m.get('status', '자료 없음')}"
