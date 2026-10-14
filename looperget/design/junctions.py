"""연결부 묶음 — 자리(N1~N7)마다 들어가는 부속 순서 (2026-10-08 · 결정 #102 B안 시범).

데이터 = junctions.json. 설계 CAD 3D 선택 화면(내보내기 = tools/junction_export.py)과 계통도(render_pptx)가 같은 파일을 읽는다.
  • 이음 판정은 connections.check_ports(기존 규칙) + coupler_specs(확인 사양) — 3D 형상은 판정 근거가 아니다(결정 #99 ②).
  • 순서 「미확정」 묶음은 계통도에 쓰지 않는다(내부 등록용 · 대표가 3D 화면에서 순서를 정해 등록).
  • 현장 선택 = site["junctions"] {자리: 묶음 id}. 없으면 defaults — 2026-10-07 계통도와 같은 부속.
"""
from __future__ import annotations

import json
import os

from . import cad_ports as CP
from . import connections as C
from . import coupler_specs as CS

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "junctions.json")
_DATA = None
HOSE = "호스 사이"                 # 판정 대상 아님(관·호스를 받는 자리)
LABEL = {C.CONFIRMED: "확인됨", C.MISMATCH: "불일치", C.UNKNOWN: "조건부"}


def _data():
    global _DATA
    if _DATA is None:
        with open(_PATH, encoding="utf-8") as fh:
            _DATA = json.load(fh)
    return _DATA


def template(tid):
    for t in _data()["templates"]:
        if t["id"] == tid:
            return t
    return None


def code_of(role, mm):
    """역할 이름(wf42 등) → 판매 코드. 숫자 코드는 그대로."""
    r = _data()["roles"]
    if str(role).isdigit():
        return str(role)
    return (r.get(str(mm)) or {}).get(role) or r["*"].get(role)


def _shape(t, nz):
    """묶음 → (rows {줄: [역할]}, joints, tee). 구역 수에 따라 모양이 다른 묶음(by_zones)은 2구역 이상 = "2"."""
    if "by_zones" in t:
        b = t["by_zones"]["1" if nz < 2 else "2"]
        return b["rows"], b.get("joints") or [], b.get("tee")
    return t["rows"], t.get("joints") or [], t.get("tee")


def _cam(code):
    """확인 사양의 카플러 끝 → [(성, 등급)] (C/E 부속은 두 끝)."""
    s = CS.spec_for(code)
    if not s or not s.get("등급"):
        return []
    sexes = ["C", "E"] if s["성"] == "C/E" else [s["성"]]
    return [(x, s["등급"]) for x in sexes]


def judge(code_a, code_b, how="direct"):
    """이웃 두 부속 이음 판정 {status, label, text}. 카플러 끝끼리는 check_ports 로, 그 밖은 근거 없음 = 조건부."""
    if how in ("clamp", "hose"):
        return {"status": HOSE, "label": HOSE, "text": "호스 위 고정 · 판정 대상 아님" if how == "clamp" else "호스를 사이에 둠"}
    ca, cb = _cam(code_a), _cam(code_b)
    if ca and cb:
        res = [C.check_ports({"kind": "coupler", "sex": a, "grade": g}, {"kind": "coupler", "sex": b, "grade": h})
               for a, g in ca for b, h in cb]
        best = next((r for r in res if r["status"] == C.CONFIRMED), None) or res[0]
        txt = "C–E 짝 · 등급 %s (확인 사양)" % ca[0][1] if best["status"] == C.CONFIRMED else " · ".join(best["issues"])
        return {"status": best["status"], "label": LABEL[best["status"]], "text": txt}
    if code_a in THREAD_ENDS or code_b in THREAD_ENDS:          # [결정 #109] 나사 끝 표가 있으면 끝끼리 규칙 판정
        pa, pb = _ports(code_a), _ports(code_b)
        if any(k in THREAD for _, k, _ in pa) and any(k in THREAD for _, k, _ in pb):
            return _joint(code_a, code_b, set(), set())[0]
    miss = [c for c, p in ((code_a, ca), (code_b, cb)) if not p]
    return {"status": C.UNKNOWN, "label": LABEL[C.UNKNOWN],
            "text": "끼움 자리 자료 없음(%s) — 나사 호칭·종류(상품 DB 열 · 결정 #103 ③)와 CAD 모델이 생기면 규칙 판정" % ", ".join(miss)}


CAM = {"camC": "C", "camE": "E"}
THREAD = {"female": "F", "male": "M"}
ENTRY_ORDER = ("saddle", "barb", "compression", "female", "male")   # saddle = 호스 타공홀에 얹는 H 계열(결정 #109)


# [2026-10-08 · 결정 #109] CAD 끼움 자리가 없는 부속의 나사 끝 — 상품 시트 「나사 호칭」「나사 종류」 열이 채워지면 그 값으로 바꾼다
THREAD_ENDS = {
    "01920": [("seat", "saddle", None), ("top", "female", 20)],   # 루퍼젯 H20 너트 상단 암나사 G3/4(=20A) — CAD 승인 사양 01_Specs/H20/h20_nut.md(2026-08-26 의장)
    "01870": [("p0", "male", 20)],      # 압력계 20mm 연결세트 — 대표 답 2026-10-08 「20A, 수나사」
}


def _ports(code):
    """부속의 끝 목록 [(id, kind)] — CAD 끼움 자리(cad_ports) 기준 · 없으면 THREAD_ENDS. 자료 없으면 []."""
    info = CP.ports_of(code)
    ps = [(p.get("id"), p.get("kind"), p.get("nominal")) for p in (info or {}).get("ports") or []]
    return ps or list(THREAD_ENDS.get(str(code), []))


def _joint(code_a, code_b, used_a, used_b):
    """[2026-10-08 · 결정 #103] 이미 쓴 끝을 뺀 나머지 끝끼리 판정 — 짝 판정(judge)만으로는 「4-10 의 C 를 4-4 가 쓰면
    남는 끝은 암나사」를 못 잡는다. 반환 (판정 dict, a 쓴 끝 id, b 쓴 끝 id)."""
    pa, pb = _ports(code_a), _ports(code_b)
    if not pa or not pb:
        r = judge(code_a, code_b)
        return r, None, None
    fa = [p for p in pa if p[0] not in used_a]
    fb = [p for p in pb if p[0] not in used_b]
    grade = lambda c: (CS.spec_for(c) or {}).get("등급")
    cams = [(x, y) for x in fa for y in fb if x[1] in CAM and y[1] in CAM]
    for x, y in cams:
        r = C.check_ports({"kind": "coupler", "sex": CAM[x[1]], "grade": grade(code_a)},
                          {"kind": "coupler", "sex": CAM[y[1]], "grade": grade(code_b)})
        if r["status"] == C.CONFIRMED:
            return {"status": r["status"], "label": LABEL[r["status"]], "text": "C–E 짝 · 등급 %s (확인 사양)" % grade(code_a)}, x[0], y[0]
    thr = [(x, y) for x in fa for y in fb if x[1] in THREAD and y[1] in THREAD]
    for x, y in thr:
        std = lambda c: "BSPT" if str(c) in THREAD_ENDS else None    # [결정 #109] 표에 든 나사 끝 = BSPT 계열(결정 #103 ② · H20 상단 G3/4 포함)
        r = C.check_ports({"kind": "thread", "sex": THREAD[x[1]], "d_mm": x[2], "standard": std(code_a)},
                          {"kind": "thread", "sex": THREAD[y[1]], "d_mm": y[2], "standard": std(code_b)})
        if r["status"] != C.MISMATCH:
            txt = ("같은 호칭 %sA · 암–수 반대 — 규칙 판정(결정 #103 ④)" % x[2]) if r["status"] == C.CONFIRMED \
                else "암–수 나사 · 나사 호칭·종류 자료(상품 DB 열 · 결정 #103 ③) 대기"
            return {"status": r["status"], "label": LABEL[r["status"]], "text": txt}, x[0], y[0]
    if cams:
        r = C.check_ports({"kind": "coupler", "sex": CAM[cams[0][0][1]], "grade": grade(code_a)},
                          {"kind": "coupler", "sex": CAM[cams[0][1][1]], "grade": grade(code_b)})
        return {"status": C.MISMATCH, "label": LABEL[C.MISMATCH], "text": " · ".join(r["issues"]) or "카플러 짝 불일치"}, None, None
    kinds = lambda ps: "·".join(dict.fromkeys(KIND_KO.get(k, k) for _, k, _ in ps)) or "없음"
    return {"status": C.MISMATCH, "label": LABEL[C.MISMATCH],
            "text": "남은 끝이 맞지 않음 — %s 남은 끝 %s ↔ %s 끝 %s" % (code_a, kinds(fa), code_b, kinds(fb))}, None, None


KIND_KO = {"camC": "C(암)", "camE": "E(수)", "female": "암나사", "male": "숫나사", "barb": "호스미늘", "compression": "조임식"}


def resolve(tid, mm, nz=2):
    """묶음 하나를 현장 관경·구역 수로 풀어 {id, label, order, rows{줄:[코드]}, tee, joints[{a,b,codes,판정}]}."""
    t = template(tid)
    if t is None:
        raise KeyError("등록되지 않은 연결부 묶음: %s" % tid)
    mm = int(t.get("mm_fixed") or mm)
    rows, joints, tee = _shape(t, nz)
    codes = {k: [code_of(r, mm) for r in v] for k, v in rows.items()}
    at = lambda ref: codes[ref[0]][int(ref[1:])]
    used = {k: set() for k, v in codes.items() for k in ["%s%d" % (k, i) for i in range(len(v))]}
    first = _ports(codes["A"][0]) if codes.get("A") else []
    ent = next((p for want in ([t["entry"]] if t.get("entry") else []) + list(ENTRY_ORDER) for p in first if p[1] == want), None)
    if ent:
        used["A0"].add(ent[0])                                   # 들어오는 끝(호스·농수관·나사) — 다음 이음에 못 씀
    js = []
    for j in joints:
        a, b, how = at(j["a"]), at(j["b"]), j.get("how", "direct")
        if how in ("clamp", "hose"):
            js.append(dict(j, codes=[a, b], **judge(a, b, how)))
            continue
        r, ua, ub = _joint(a, b, used[j["a"]], used[j["b"]])
        if ua:
            used[j["a"]].add(ua)
        if ub:
            used[j["b"]].add(ub)
        js.append(dict(j, codes=[a, b], **r))
    return {"id": tid, "node": t["node"], "name": t["name"], "label": t["label"].replace("{nz}", str(nz)),
            "order": t["order"], "source": t["source"], "mm": mm, "rows": codes, "roles": rows, "tee": tee, "joints": js}


def selection(site):
    """현장 선택 {자리: 묶음 id} — site["junctions"] 가 기본값 위에 얹힌다(자리 키 N1~N7 만 · 선택 사항은 option())."""
    sel = dict(_data()["defaults"])
    sel.update({k: v for k, v in ((site or {}).get("junctions") or {}).items() if v and k in _data()["nodes"]})
    return sel


def option(site, key):
    """묶음 선택 사항(예: "N4.elbow_deg" = 0·45·90) — 허용 값이 아니면 None."""
    v = ((site or {}).get("junctions") or {}).get(key)
    allowed = ((_data().get("options") or {}).get(key) or {}).get("values") or []
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if v in allowed else None


def water_layout(site, mm, nz):
    """계통도 ①②③ 에 쓸 묶음 셋 + 알림(log). 순서 미확정·등록 안 된 묶음은 기본 묶음으로 그리고 알린다."""
    sel, log, out = selection(site), [], {}
    for node in ("N2", "N3", "N4"):
        tid = sel.get(node)
        t = template(tid)
        if t is None or t["node"] != node or t["order"] != "확정":
            why = "등록 안 됨" if t is None else ("자리 다름" if t["node"] != node else "순서 미확정")
            log.append("연결부 %s 「%s」 %s — 기본 묶음 %s 로 그림" % (node, tid, why, _data()["defaults"][node]))
            tid = _data()["defaults"][node]
        out[node] = resolve(tid, mm, nz)
        for j in out[node]["joints"]:
            if j["status"] in (C.MISMATCH, C.UNKNOWN):
                log.append("연결부 %s %s→%s %s — %s" % (node, j["codes"][0], j["codes"][1], j["label"], j["text"]))
    return out, log


def matrix(codes):
    """부속 목록 안의 모든 짝 판정 — 3D 화면 「순서 정하기」가 이 표만 본다(판정을 두 번 구현하지 않음)."""
    codes = sorted(set(codes))
    return {a + ">" + b: judge(a, b) for a in codes for b in codes}
