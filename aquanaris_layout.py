# -*- coding: utf-8 -*-
# [V66] 아쿠나리스 배치 엔진 — app.py에서 분리(2026-07-23). 동작 불변.
#  ⚠ 배포 시 app.py와 함께 이 파일도 반드시 GitHub에 올릴 것(하나만 올리면 import 오류로 앱이 죽음).
#  순수 모듈: streamlit 미사용, app.py 함수 미호출(표준상수·패킹·자동배치·SVG 렌더러·hover HTML).
import json
import datetime

# 렌더러가 쓰는 색상 헬퍼(app.py에도 동일 정의가 있으나 순수함수라 모듈 자체 보유)
def _aq_hexrgb(h):
    h = (h or "#9AA0A6").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def _aq_lum_txt(rgb):
    r, g, b = rgb
    return (25, 20, 20) if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else (255, 255, 255)

# ── [V44] 표준 시스템(Aqunaris V1) — 도면 1:7.5 역산 상수 + 재현 검증 엔진 ──
#  근거: Aqunaris V1.ai 벡터 실측(2026-07-18). 상자 개수 91/54/53/38 = 구매수량과 정확 일치.
#  검증 모델: 층수 = floor(단높이/상자높이), Σ(상자폭÷층수) ≤ 내측폭 862 → V1 실배치 51/51단 적합.
AQ_STD_SITE = "표준(Aqunaris V1)"
AQ_STD_INNER = 1162         # [V55] 랙 W1200 - 기둥(19×2) — 대표님 실측 정정(구: W900/862, V1 도면 축척 역산 오차)
# [V60] 대표님 실측 도면 정정(2026-07-23): 랙 총높이 2400 · 단두께 40 · 단별 개구부(아래→위).
#  표기 없는 개구부(꼭대기 또는 바닥)는 Σ단높이 = 2400 − 40×(단수−1) 잔여로 산정 — 랙 검증식과 정합.
#  (구 값은 V1 도면 1:7.5 축척 역산 근사 — 단높이가 실제보다 작아 3호·6호 2층 적층이 잘려 나가던 원인)
AQ_STD_TOTAL_H = 2400
AQ_STD_SHELF_T = 40
AQ_STD_RACK_H = {
    "01": [1350, 1010], "02": [500, 550, 500, 730], "03": [350, 400, 1570],
    "04": [500, 450, 400, 930], "05": [450, 450, 450, 930], "06": [450, 500, 450, 880],
    "07": [890, 350, 350, 350, 300], "08": [890, 350, 350, 350, 300],
    "09": [890, 350, 350, 350, 300], "10": [890, 350, 350, 350, 300],
    "11": [890, 350, 350, 350, 300], "12": [890, 350, 350, 350, 300],
}
# [V58] V1 도면의 랙 나열 순서 재현 — 도면 윗줄 = 섹션12→07(우측 벽 반전), 아랫줄 = 섹션01→06
AQ_STD_RACK_ORDER = [f"섹션{s}" for s in ("12", "11", "10", "09", "08", "07",
                                          "01", "02", "03", "04", "05", "06")]
# [V58] 표준 자유배치 존 — V1 도면 섹션01 랙: 위 단(727)=여과기 3×2 적층, 아래 단(1042)=지주대 3분할
#  (개별 지주대를 그리지 않고 '영역+수량'으로만 표시 — 대표님 지시 2026-07-23. 수량 기본값=AQ_Items 기본수량)
AQ_STD_FREE = {
    "00527": {"shape": "사각", "w": 380, "h": 340,  "qty": 6,  "rack": "섹션01", "shelf": 2, "n": 6},
    "01016": {"shape": "사각", "w": 380, "h": 1300, "qty": 10, "rack": "섹션01", "shelf": 1, "n": 1},
    "01889": {"shape": "사각", "w": 380, "h": 1300, "qty": 10, "rack": "섹션01", "shelf": 1, "n": 1},
    "01854": {"shape": "사각", "w": 380, "h": 1300, "qty": 10, "rack": "섹션01", "shelf": 1, "n": 1},
    # 연결호스 코일(도면 섹션02 단4 좌측 호스 뭉치) — 원형 3단 적층 영역
    "01547": {"shape": "원", "w": 405, "h": 160, "qty": 6, "rack": "섹션02", "shelf": 4, "n": 3},
}

def aq_std_free_of(code):
    """[V58] 코드의 표준 자유배치 정의 (5자리 패딩 양쪽 매칭)."""
    c = str(code or "").strip()
    return AQ_STD_FREE.get(c) or AQ_STD_FREE.get(c.zfill(5))

# [V59] 표준 전면 상자수(n) — V1 도면 실측: 루퍼젯팩 P25·H25·P13B = 2팩 나란히, P20·H20 = 1팩
AQ_STD_N = {"01923": 2, "01924": 2, "01926": 2}

def aq_std_n_of(code):
    """[V59] 코드의 표준 전면 상자수 힌트 (자유배치 n 포함)."""
    c = str(code or "").strip().zfill(5)
    if c in AQ_STD_N: return AQ_STD_N[c]
    return (aq_std_free_of(c) or {}).get("n", 1)

def aq_box_dims_map(boxes):
    """AQ_Boxes → {상자종류: (폭mm, 높이mm)} (치수 있는 것만)."""
    out = {}
    for b in boxes:
        name = str(b.get("상자종류", "")).strip()
        try:
            w = int(float(str(b.get("폭mm") or 0))); h = int(float(str(b.get("높이mm") or 0)))
        except Exception:
            continue
        if name and w > 0 and h > 0: out[name] = (w, h)
    return out

def aq_box_depth_map(boxes):
    """[V49] AQ_Boxes → {상자종류: 깊이mm} (깊이 있는 것만) — 탑뷰(줄수) 계산용."""
    out = {}
    for b in boxes:
        name = str(b.get("상자종류", "")).strip()
        try: d = int(float(str(b.get("깊이mm") or 0)))
        except Exception: continue
        if name and d > 0: out[name] = d
    return out

def aq_capacity_rows(aq_items, plan_items, box_dims, rack_h_by_sec, inner=AQ_STD_INNER, inner_by_sec=None):
    """표준 위치(섹션-단) 기반 단별 용량 검증. plan_items의 상자 오버라이드 반영.
    반환: [{섹션,단,단높이,품목수,사용폭,판정,미지정}]"""
    shelf = {}
    for r in aq_items:
        sec = str(r.get("섹션", "")).strip()
        dan = str(r.get("단", "")).strip()
        if not sec or not dan: continue
        code = r["품목코드"]
        ov = plan_items.get(code, {}) if isinstance(plan_items, dict) else {}
        box = str((ov.get("box") if isinstance(ov, dict) else "") or r.get("기본상자") or "").strip()
        shelf.setdefault((sec, dan), []).append(box)
    rows = []
    for (sec, dan), boxes_on in sorted(shelf.items()):
        hs = rack_h_by_sec.get(sec, [])
        try: dan_h = hs[int(dan) - 1] if 0 < int(dan) <= len(hs) else 0
        except Exception: dan_h = 0
        used = 0.0; unknown = 0
        for bx in boxes_on:
            if bx not in box_dims:
                unknown += 1; continue
            w, h = box_dims[bx]
            layers = max(1, dan_h // h) if dan_h else 1
            used += w / layers
        _inner = (inner_by_sec or {}).get(sec, inner)
        rows.append({"섹션": sec, "단": dan, "단높이": dan_h, "품목수": len(boxes_on),
                     "사용폭": int(round(used)), "내측폭": _inner,
                     "판정": "✓ 적합" if used <= _inner else "⚠ 초과", "미지정": unknown})
    return rows

def aq_std_payload(aq_items):
    """표준 사이트의 랙구성·배치 JSON 생성 (AQ_Items 기본값 기반)."""
    plan_items, groups = {}, set()
    for r in aq_items:
        box = str(r.get("기본상자", "")).strip()
        try: qty = int(float(str(r.get("기본수량") or 0)))
        except Exception: qty = 0
        g = str(r.get("진열분류", "")).strip()
        if g: groups.add(g)
        if box or qty:
            plan_items[r["품목코드"]] = {"box": box, "qty": qty, "ori": "세로"}
    racks = []
    for s in sorted(AQ_STD_RACK_H):
        racks.append({"명칭": f"섹션{s}", "폭mm": 1200, "깊이mm": 450, "단수": len(AQ_STD_RACK_H[s]),   # [V55] 실측 1200
                      "총높이mm": AQ_STD_TOTAL_H, "단두께mm": AQ_STD_SHELF_T,   # [V60] 실측 — 검증식 정합
                      "단높이mm(콤마구분)": ",".join(str(x) for x in AQ_STD_RACK_H[s]),
                      "단깊이mm(콤마구분)": "", "비고": "표준(실측 2026-07-23)"})
    # [V58] 표준 자유배치 존(섹션01 여과기·지주대) + 도면 랙 순서를 배치JSON에 포함
    #  [V61] assign은 넣지 않는다 — 불러오기 = 빈 랙, ⚡자동배치 한 번으로 전 품목(여과기·루퍼젯 포함) 배치
    #  (여과기 존은 free 기본값+표준 위치(pre)+표준 상자수(aq_std_n_of)로 자동 재현됨)
    free_std = {}
    for r in aq_items:
        c = str(r.get("품목코드", "")).strip()
        fd = aq_std_free_of(c)
        if fd:
            free_std[c] = {"shape": fd["shape"], "w": fd["w"], "h": fd["h"], "qty": fd["qty"]}
    plan = {"groups": sorted(groups), "items": plan_items,
            "free": free_std, "rack_order": list(AQ_STD_RACK_ORDER),
            "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M") + " (표준)"}
    return racks, plan

# ── [V45] 단(선반) 중심 배치 — 섹션 개념은 표준 참고로만, 배치의 단위는 '단' ──
#  철학(박 대표님): 용도군별로 단 단위 군집 배치 + 단 아래 색상 자석테이프로 영역 표시.
#  섹션(세로 열) 고정 개념은 유동성을 죽임(신규 추가·변경 불가) → 폐기, 표준화 참고 전용.
#  [V49] 색상 = V1 실측 확정 팔레트 v1 (2026-07-21, 아쿠나리스_부속군_색상팔레트_v1_확정.md).
#  ⚠ 군 명칭(키)은 현행 9군 유지 — 10군 재편(노지SP 분리·미니SP→시설관수)은 AQ_Items 재분류와 함께 후속(§3·§4).
# [V59] 부속군 10군 재편 — 팔레트 v1 확정(아쿠나리스_부속군_색상팔레트_v1_확정.md §1·§3)
#  9군→10군: 여과기·스프링클러지주 → 여과기+노지SP 분리 / 미니스프링클러·분수부속 → 시설관수+분수호스 분리.
#  AQ_Items 진열분류도 10군 부속군코드로 재지정(NAS `배치` 정본 + 재지정 17건, tools/aq_regroup_10.py).
AQ_GROUP_COLORS = {
    "루퍼젯": "#F4D624", "송수호스": "#68258A", "조임식": "#938073",
    "나사식": "#231F20", "시설관수": "#1A2989", "점적": "#00923A",
    "노지SP": "#EA5516", "분수호스": "#EC008C", "물호스": "#00A7EA",
    "여과기": "#A1A2A2", "(미지정)": "#9AA0A6",
}
AQ_GROUP_LEGACY = {   # 구 9군 명칭 → 신 부속군코드 (저장된 배치JSON groups 등 하위호환)
    "스마트카플러": "송수호스", "조임식부속": "조임식", "나사식부속": "나사식",
    "퀸밸브": "시설관수", "새들·점적스타트": "점적", "물호스·연질부속": "물호스",
    "루퍼젯·공구": "루퍼젯",
    "미니스프링클러·분수부속": "시설관수",   # 분리군 — 대표 케이스는 품목 재지정으로 해소, 폴백만 시설관수
    "여과기·스프링클러지주": "여과기",       # 분리군 — 폴백만 여과기
}

def aq_grp_norm(g):
    """[V59] 진열분류(부속군) 정규화 — 구 9군 명칭이 남아 있으면 신 10군 코드로."""
    g = str(g or "").strip() or "(미지정)"
    return AQ_GROUP_LEGACY.get(g, g)

AQ_COL_ORD = {"좌": 0, "중": 1, "우": 2}   # [V58] AQ_Items '열' → 단 내 좌우 순서 (V1 도면 재현)

def aq_canon_seq(seq, group_order=None, colmap=None):
    """단 패킹의 정준 정렬: ([V58]열힌트, 분류 군집순, 높이↓, 폭↓, 상자, 코드) — 편집표 순서와 무관하게 동일 결과.
    [V49] 상자명 정렬 추가 — 같은 상자끼리 인접해야 스택(동일상자 적층) 열을 공유한다.
    [V58] colmap={코드: 0|1|2} — 표준 위치(그 단이 품목의 표준 섹션·단일 때)의 '열'(좌0/중1/우2)을
    최우선 정렬 키로 써서 V1 도면의 좌우 배치 순서를 재현한다. 힌트 없는 품목은 중(1) 취급."""
    gp = {g: i for i, g in enumerate(group_order or [])}
    cm = colmap or {}
    def _col(t):   # 열 힌트: colmap > 튜플 6번째 원소(있으면) > 중(1)
        return cm.get(t[0], t[5] if len(t) > 5 else 1)
    return sorted(seq, key=lambda t: (_col(t), gp.get(t[1], 99), -t[4], -t[3], t[2], t[0]))

def aq_pack_shelf_stacks(box_seq, inner, shelf_h, max_layers=3, force=None):
    """[V49] 단 내부 스택(열) 패킹 — 플라스틱 상자 물리 규칙(박 대표님 지시 2026-07-21):
      ① 적층은 '같은 상자'끼리만(아래 상자에 윗 상자가 끼워짐 — 다른 상자를 위에 못 올림)
      ② 적층 높이 ≤ 단높이 (층수 = min(3, 단높이//상자높이), 0층이면 그 단에 못 들어감)
      ③ 상자는 반드시 바로 아래 상자 위에 — 붕 뜬 배치 구조적으로 불가(열 단위 적층)
    box_seq=[(코드,분류,상자,폭,높이)] (정준 정렬 가정) — 같은 (분류,상자,치수) 연속 구간이 열을 공유.
    [V64] force={코드: 열그룹키} — 그 코드는 물리 한도·루퍼젯팩 잠금·열 분리를 우회해 같은 열그룹키끼리 한 열에 적층.
     (열그룹키가 같으면 서로 다른 품목이라도 한 열에 쌓임 — B를 A 위에 올린 수동 적층 재현.)
    반환: (cols, fitted, rejected) — cols=[(x오프셋, 폭, [아래→위 items])]."""
    if force is None: force = {}
    if isinstance(force, (set, frozenset)): force = {c: c for c in force}   # 하위호환(구 set 형태)
    cols, fitted, rejected = [], [], []
    x = 0
    runs = []
    _fruns = {}   # [V64] 열그룹키 → 병합 run(비연속 항목도 한 열로)
    for it in box_seq:
        # [V58] 열 힌트(튜플 6번째, 좌0/중1/우2)가 다르면 다른 열 — V1 도면의 나란히 배치 재현
        # [V60] 분류는 키에서 제외 — 도면 실측: 적층은 '같은 상자'끼리면 분류가 달라도 위아래로 쌓는다
        #  (예: 섹션02 압력계(루퍼젯)+이경부싱(나사식)+물호스밸브소켓(물호스) 3호 3층 스택)
        _fk = force.get(str(it[0]))
        if _fk is not None:   # [V64] 수동 고정 → 열그룹키로 병합(비연속도 한 열)
            key = ("__FORCE__", str(_fk))
            if key in _fruns:
                _fruns[key].append(it); continue
            _fruns[key] = [it]; runs.append((key, _fruns[key])); continue
        else:
            key = (it[2], it[3], it[4], it[5] if len(it) > 5 else 1)
        if runs and runs[-1][0] == key:
            runs[-1][1].append(it)
        else:
            runs.append((key, [it]))
    for _key, items in runs:
        w, h = items[0][3], items[0][4]
        _forced = (isinstance(_key, tuple) and len(_key) == 2 and _key[0] == "__FORCE__")
        if _forced:   # [V64] 수동 고정 — 한 열에 전부 적층(물리 한도·루퍼젯팩·열 규칙 우회, 안전 상한 12)
            _flim = int(shelf_h // h) if h > 0 else 0   # [V65] 단높이 지킴 — 물리 층수까지만(떠오름 방지, 더 쌓으려면 단높이↑)
            layers = max(1, min(len(items), _flim or 1))
        else:
            layers = min(max_layers, int(shelf_h // h)) if h > 0 else 0
            if items[0][2] == "루퍼젯팩":   # [V61] 팩 제품은 적층하지 않고 나란히(도면 실측·낱개 이동)
                layers = min(layers, 1)
        if layers < 1 or w > inner:
            rejected.extend(items); continue
        cur = None
        for it in items:
            if cur is None or len(cur[2]) >= layers:
                if x + w > inner:
                    rejected.append(it); cur = None; continue
                cur = (x, w, [])
                cols.append(cur); x += w
            cur[2].append(it); fitted.append(it)
    return cols, fitted, rejected

def aq_auto_place(rack_list, items_seq, box_dims, group_order=None, pre=None, center_codes=None, colhint=None, n_of=None):
    """단 중심 자동배치(군집): 랙 순서·단은 아래→위, 품목은 분류 군집 순서 그대로 채움.
    rack_list=[{명칭,내측폭,단높이:[...]}], items_seq=[(코드,분류,상자)] (분류별 연속 정렬).
    패킹은 정준 정렬(aq_canon_seq) 기준 — 편집표 재검증과 동일 결과 보장.
    [V53] pre={코드:(랙명,단번호)} = 표준 위치 우선 배치(표준 실측 검증 근거로 존중) /
          center_codes = 루퍼젯 본품 등 → 가운데 랙의 중앙 단부터 우선 배치.
    [V59] colhint(code, rack, shelf)→열힌트 — 렌더 패킹과 동일한 런 분할로 시험 배치(불일치 방지).
    반환: (assign={코드:(랙명,단번호)}, unplaced=[코드...])"""
    shelves, shelf_by = [], {}
    for rk in rack_list:
        for si, h in enumerate(rk["단높이"], 1):
            s = {"rack": rk["명칭"], "no": si, "h": h, "inner": rk["내측폭"], "seq": []}
            shelves.append(s); shelf_by[(rk["명칭"], si)] = s
    pre = pre or {}
    center_codes = set(center_codes or [])
    _ch = colhint or (lambda c, rk, sh: 1)
    _nf = n_of or (lambda c: 1)
    def _t6(t, s):   # 시험 대상 단(s)에 맞는 열힌트를 6번째 원소로
        return (t[0], t[1], t[2], t[3], t[4], _ch(t[0], s["rack"], s["no"]))
    def _seq6(s, t):
        # [V59] 전면 상자수(n)만큼 복제해 시험 — 렌더 패킹과 동일한 폭 소모(여과기 3×2 등)
        return aq_canon_seq([_t6(x, s) for x in s["seq"]] + [_t6(t, s)] * max(1, int(_nf(t[0]) or 1)),
                            group_order)
    assign, unplaced = {}, []
    rest = []
    for code, grp, box in items_seq:
        wh = box_dims.get(box)
        if not wh:
            unplaced.append(code); continue
        t = (code, grp, box, wh[0], wh[1])
        tgt = pre.get(code)
        if tgt and tgt in shelf_by:                          # ① [V53] 표준 위치 우선
            s = shelf_by[tgt]
            s["seq"] = _seq6(s, t)
            assign[code] = tgt
            continue
        rest.append(t)
    if center_codes and rack_list:                            # ② [V53] 루퍼젯 본품 → 가운데 랙 중앙 단부터
        mid_rk = rack_list[len(rack_list) // 2]
        n_sh = len(mid_rk["단높이"])
        mid = (n_sh + 1) // 2
        order_sh = [mid]
        for d in range(1, n_sh + 1):
            if mid + d <= n_sh: order_sh.append(mid + d)
            if mid - d >= 1: order_sh.append(mid - d)
        still = []
        for t in rest:
            if t[0] not in center_codes:
                still.append(t); continue
            placed = False
            for no in order_sh:
                s = shelf_by[(mid_rk["명칭"], no)]
                trial = _seq6(s, t)
                if not aq_pack_shelf_stacks(trial, s["inner"], s["h"])[2]:
                    s["seq"] = trial; assign[t[0]] = (s["rack"], s["no"]); placed = True; break
            if not placed:
                still.append(t)
        rest = still
    cur = 0                                                   # ③ 나머지 그리디(기존 로직)
    for code, grp, box, w, h in rest:
        placed = False
        i = cur
        while i < len(shelves):
            s = shelves[i]
            trial = _seq6(s, (code, grp, box, w, h))
            _cols, fitted, rej = aq_pack_shelf_stacks(trial, s["inner"], s["h"])   # [V49] 스택 패킹
            if not rej:
                s["seq"] = trial
                assign[code] = (s["rack"], s["no"])
                cur = i
                placed = True
                break
            i += 1
        if not placed:
            unplaced.append(code)
    return assign, unplaced

def _aq_esc(s):
    """[V49] SVG/HTML 속성용 이스케이프."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))

_AQ_CW = {   # [V57] 문자별 폭(em) — 크롬 sans-serif(Arial+맑은고딕) 실측 보정
    "m": 0.89, "M": 0.90, "w": 0.75, "W": 0.95, "i": 0.25, "l": 0.25, "j": 0.25, "t": 0.30,
    "f": 0.30, "r": 0.36, " ": 0.35, ".": 0.30, ",": 0.30, "*": 0.45, "~": 0.72, "/": 0.30,
    "-": 0.36, "(": 0.36, ")": 0.36, "·": 0.36, "'": 0.20, ":": 0.30,
}

def _aq_txt_w(s, fs=1.0):
    """[V57] SVG text 근사 폭(px). 한글·전각=1.0em · 숫자 0.57 · 대문자 0.62 · 소문자 0.52(표 우선).
    실측(크롬) 대비 5% 여유를 둬 '박스 밖으로 나가는' 오차 방향을 차단한다."""
    w = 0.0
    for ch in str(s):
        if ord(ch) > 0x2E80: w += 1.0
        elif ch in _AQ_CW:   w += _AQ_CW[ch]
        elif ch.isdigit():   w += 0.57
        elif ch.isupper():   w += 0.62
        else:                w += 0.52
    return w * fs * 1.05

def _aq_strip_paren(s):
    """[V57] 괄호부 제거 — '밸브바디(조임식연결구)' → '밸브바디'. 괄호만 남으면 원문 유지."""
    t, out, depth = str(s), [], 0
    for ch in t:
        if ch in "(（[": depth += 1
        elif ch in ")）]":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    r = "".join(out).strip(" ·-/,")
    return r or t.strip()

def _aq_fit_label(s, max_px, fs, min_fs=2.4):
    """[V57] 박스 폭 안에 들어가도록 (텍스트, 폰트크기) 조정.
    ① 괄호부 제거 ② 폰트 축소(min_fs까지) ③ 그래도 넘치면 말줄임(…). 안 들어가면 ('', fs)."""
    t = str(s).strip()
    if not t or max_px <= 1: return "", fs
    if _aq_txt_w(t, fs) > max_px:
        t2 = _aq_strip_paren(t)
        if t2 and _aq_txt_w(t2, fs) < _aq_txt_w(t, fs): t = t2
    w1 = _aq_txt_w(t, 1.0) or 1.0
    if w1 * fs > max_px:
        fs = max(min_fs, max_px / w1)
    fs = int(fs * 10) / 10.0 or min_fs     # SVG에 소수 1자리로 찍히므로 내림 = 반올림 확대 방지
    if _aq_txt_w(t, fs) > max_px:          # 최소 폰트에서도 넘침 → 말줄임
        while t and _aq_txt_w(t + "…", fs) > max_px:
            t = t[:-1]
        t = (t + "…") if t else ""
    return t, fs

def _aq_hover_attrs(it, info):
    """[V49] 상자 rect의 호버 툴팁 데이터 속성. info={코드:{name,spec,box,cap,...}} 없으면 빈 문자열."""
    if not info: return ""
    meta = info.get(it[0])
    if not meta: return ""
    return (f' class="aqbox" data-name="{_aq_esc(meta.get("name") or it[0])}"'
            f' data-spec="{_aq_esc(meta.get("spec") or "")}"'
            f' data-box="{_aq_esc(meta.get("box") or it[2])}"'
            f' data-cap="{_aq_esc(meta.get("cap") or "")}"')

def _aq_rack_parts(out, x0, y0, rack_name, inner, shelf_hs, shelf_seqs, frame_t=19, scale=0.22, show_dims=True, info=None, shelf_t=0, force=None):
    """(x0,y0) 기준으로 랙 1대의 SVG 요소들을 out 리스트에 추가. 반환: (폭px, 높이px).
    [V49] 스택 패킹 렌더(동일상자 열 적층) + info 있으면 호버 데이터 속성 + 도형/이미지(자유 배치) 지원.
    [V62] shelf_t = 단(선반 판) 두께 — 단높이(개구부)는 총높이−단두께×(단수−1)이라, 판 두께를
          높이·단 바닥 y에 더해야 단수가 달라도 랙 총높이가 동일하게(=실제) 그려진다."""
    W = inner + frame_t * 2
    _nsh = len(shelf_hs)
    H = sum(shelf_hs) + shelf_t * max(0, _nsh - 1) + frame_t   # [V62] 단두께 반영
    pw, ph = W * scale, H * scale
    _virt9 = str(rack_name).startswith("🅥")   # [V53] 가상랙 = 점선 프레임 + 연노랑 배경으로 구분
    _dash9 = ' stroke-dasharray="7,4"' if _virt9 else ''
    _fill9 = "#FFFBEB" if _virt9 else "#FAFAF7"
    out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{pw:.1f}" height="{ph:.1f}" fill="{_fill9}" stroke="#191414" stroke-width="1.6"{_dash9}/>')
    # [V55] 랙 이름 = 랙 순서 드래그 핸들 (≡ 표시)
    out.append(f'<text class="aqrackhandle" data-rack="{_aq_esc(rack_name)}" x="{x0:.1f}" y="{y0 - 4:.1f}" '
               f'font-size="11" fill="#8C8681">≡ {_aq_esc(rack_name)}</text>')
    y_real = 0
    for si, sh in enumerate(shelf_hs, 1):
        base = y0 + ph - y_real * scale          # [V62] 이 단 바닥(아래 판 두께 누적 반영)
        y_real += sh
        y_px = y0 + ph - y_real * scale           # 이 단 개구부 상단 = 선반 판 윗면
        out.append(f'<line x1="{x0:.1f}" y1="{y_px:.1f}" x2="{x0 + pw:.1f}" y2="{y_px:.1f}" stroke="#191414" stroke-width="1.6"/>')
        if show_dims:
            out.append(f'<text x="{x0 + 2:.1f}" y="{y_px + 9:.1f}" font-size="7" fill="#B9B3AD">{si}·{sh}</text>')
        # [V51] 드래그 드롭존(투명) — 빈 단도 드롭 대상이 되도록 항상 추가
        out.append(f'<rect class="aqshelf" data-rack="{_aq_esc(rack_name)}" data-shelf="{si}" '
                   f'x="{x0 + frame_t*scale:.1f}" y="{y_px:.1f}" width="{inner*scale:.1f}" height="{sh*scale:.1f}" '
                   f'fill="none" stroke="none"/>')
        y_real += shelf_t                          # [V62] 다음 단은 선반 판 두께만큼 위 (빈 단도 누적되도록 continue 앞)
        seq = shelf_seqs.get((rack_name, si)) or shelf_seqs.get(si) or []
        if not seq: continue
        cols_p, fitted, rej = aq_pack_shelf_stacks(seq, inner, sh, force=force)   # [V64] 수동 적층 고정
        tape = []
        for cx, cw, stack in cols_p:
            for li, it in enumerate(stack):
                bw, bh = it[3], it[4]
                col = AQ_GROUP_COLORS.get(aq_grp_norm(it[1]), "#9AA0A6")
                bx = x0 + frame_t * scale + cx * scale
                by = base - (li + 1) * bh * scale
                attrs = _aq_hover_attrs(it, info)
                if attrs:   # [V51] 드래그·더블클릭용 위치 데이터
                    attrs += f' data-code="{_aq_esc(it[0])}" data-rack="{_aq_esc(rack_name)}" data-shelf="{si}"'
                meta = (info or {}).get(it[0]) or {}
                shape = meta.get("shape") or ""
                if shape == "원":
                    out.append(f'<ellipse cx="{bx + bw*scale/2:.1f}" cy="{by + bh*scale/2:.1f}" rx="{bw*scale/2:.1f}" ry="{bh*scale/2:.1f}" '
                               f'fill="{col}" fill-opacity="0.72" stroke="#191414" stroke-width="0.6"{attrs}/>')
                elif shape == "이미지" and meta.get("img"):
                    out.append(f'<image x="{bx:.1f}" y="{by:.1f}" width="{bw*scale:.1f}" height="{bh*scale:.1f}" '
                               f'href="{meta["img"]}" preserveAspectRatio="xMidYMid meet"{attrs}/>')
                else:
                    out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" '
                               f'width="{bw*scale:.1f}" height="{bh*scale:.1f}" fill="{col}" fill-opacity="0.72" stroke="#191414" stroke-width="0.6"{attrs}/>')
                _tag9 = str(meta.get("tag") or "")   # [V53] 루퍼젯 본품 뒷표기(P13B/P20/P25/H20/H25) — 옐로 위 블랙
                _cx9 = bx + bw * scale / 2
                _bwin9 = max(2.0, bw * scale - 2.4)   # [V57] 좌우 여백 제외한 실제 쓸 수 있는 폭
                # 아래쪽은 맨 밑 상자만 색상 자석테이프(3.4px)·단 구분선(1.6px)에 가려지므로 그만큼 더 비운다
                _rb9 = 4.0 if li == 0 else 0.9
                _bhin9 = max(2.0, bh * scale - 0.9 - _rb9)
                _cy9 = by + 0.9 + _bhin9 / 2          # 글자 세로 기준선 = 가려지지 않는 영역의 중심
                if _tag9:   # [V57] 평소(비전체화면) 뒷표기 — 전체화면에서는 aqlbl 라벨로 교체(JS가 숨김)
                    _tg9t, _tg9f = _aq_fit_label(_tag9, _bwin9,
                                                 max(4.5, min(9.0, bw * scale * 0.30, _bhin9 * 0.62)), min_fs=3.2)
                    if _tg9t:
                        out.append(f'<text class="aqtag" x="{_cx9:.1f}" y="{_cy9 + _tg9f*0.36:.1f}" '
                                   f'font-size="{_tg9f:.1f}" text-anchor="middle" font-weight="bold" '
                                   f'fill="#191414" pointer-events="none">{_aq_esc(_tg9t)}</text>')
                if attrs:   # [V56] 전체화면 라벨(품목명·규격) — 평소 숨김, ⛶ 진입 시 JS가 표시
                    #        [V57] 상자 안에 반드시 들어가도록 폭·높이 기준 자동 축소 + 괄호부 제거 + 말줄임
                    _lume9 = _aq_lum_txt(_aq_hexrgb(AQ_GROUP_COLORS.get(aq_grp_norm(it[1]))))
                    _lfill9 = f"rgb({_lume9[0]},{_lume9[1]},{_lume9[2]})"
                    _sp9l = str(meta.get("spec") or "")
                    _base9 = max(2.6, min(7.0, bw * scale * 0.16))
                    _l1s9 = _base9 * (1.3 if _tag9 else 1.0)   # 루퍼젯 본품은 뒷표기를 조금 크게
                    _l2s9 = _base9 * 0.88 if _sp9l else 0.0
                    # 실측(크롬) 글자 상자 = 위 1.16em · 아래 0.30em · 줄간격 0.22em → 상자 높이를 넘으면 비례 축소
                    if _l2s9:
                        _ink9 = 1.16 * _l1s9 + 0.22 * _l1s9 + 1.30 * _l2s9
                        if _ink9 > _bhin9:
                            _k9 = _bhin9 / _ink9
                            if _l1s9 * _k9 < 2.4:   # 두 줄이면 너무 작아짐 → 규격 생략하고 한 줄을 크게
                                _sp9l, _l2s9 = "", 0.0
                            else:
                                _l1s9, _l2s9 = _l1s9 * _k9, _l2s9 * _k9
                    if not _l2s9 and 1.46 * _l1s9 > _bhin9:
                        _l1s9 = _bhin9 / 1.46
                    if _tag9:   # 루퍼젯 본품 = 뒷표기(굵게) + 규격 — 큰 글씨 겹침 제거
                        _l1t9, _l1f9 = _aq_fit_label(_tag9, _bwin9, _l1s9, min_fs=1.8)
                        _l1w9 = "bold"
                        _l1c9 = "#191414"   # 옐로 상자 위 블랙 유지
                    else:
                        _l1t9, _l1f9 = _aq_fit_label(str(meta.get("name") or it[0]), _bwin9, _l1s9, min_fs=1.8)
                        _l1w9, _l1c9 = "normal", _lfill9
                    _l2t9, _l2f9 = _aq_fit_label(_sp9l, _bwin9, _l2s9, min_fs=1.8) if _sp9l else ("", 0.0)
                    _gap9 = _l1f9 * 0.22
                    _tot9 = 1.16 * _l1f9 + ((_gap9 + 1.30 * _l2f9) if _l2t9 else 0.30 * _l1f9)
                    _y19 = _cy9 - _tot9 / 2 + 1.16 * _l1f9
                    if _l1t9:
                        out.append(f'<text class="aqlbl" x="{_cx9:.1f}" y="{_y19:.1f}" '
                                   f'font-size="{_l1f9:.1f}" text-anchor="middle" fill="{_l1c9}" '
                                   f'font-weight="{_l1w9}" pointer-events="none" style="display:none">{_aq_esc(_l1t9)}</text>')
                    if _l2t9:
                        out.append(f'<text class="aqlbl" x="{_cx9:.1f}" y="{_y19 + _gap9 + _l2f9:.1f}" '
                                   f'font-size="{_l2f9:.1f}" text-anchor="middle" fill="{_lfill9}" '
                                   f'pointer-events="none" style="display:none">{_aq_esc(_l2t9)}</text>')
            tape.append((cx, cx + cw, AQ_GROUP_COLORS.get(aq_grp_norm(stack[0][1]), "#9AA0A6")))
        for tx0, tx1, col in tape:   # 색상 자석테이프(단 전면 하단 밴드)
            out.append(f'<rect class="aqtape" x="{x0 + frame_t*scale + tx0*scale:.1f}" y="{base - 3:.1f}" width="{(tx1-tx0)*scale:.1f}" height="3.4" fill="{col}"/>')
    return pw, ph

def aq_rack_svg(rack_name, inner, shelf_hs, shelf_seqs, frame_t=19, scale=0.22, info=None):
    """랙 1대 정면 SVG (실척)."""
    pad = 16
    out = []
    pw, ph = _aq_rack_parts(out, pad, pad, rack_name, inner, shelf_hs, shelf_seqs, frame_t, scale, info=info)
    return (f'<svg width="{pw + pad*2:.0f}" height="{ph + pad*2 + 14:.0f}" xmlns="http://www.w3.org/2000/svg">'
            + "".join(out) + '</svg>')

def aq_racks_svg_all(rack_list, seq_by_shelf, per_row=6, scale=None, info=None, mstack=None):
    """[V47] 전체 배치 뷰 — V1 도면처럼 랙들을 줄당 per_row대씩 나란히 렌더.
    rack_list=[{명칭,내측폭,단높이}], seq_by_shelf={(랙명,단):[...]}. [V49] info=호버 툴팁 데이터.
    [V64] mstack=수동 적층 고정 코드 집합(렌더 전용 — 검증·견적 패킹엔 미적용)."""
    if not rack_list: return ""
    if scale is None:
        n = len(rack_list)
        scale = 0.22 if n <= 2 else (0.16 if n <= 4 else 0.105)
    pad, gap_x, gap_y = 16, 12, 26
    rows = [rack_list[i:i + per_row] for i in range(0, len(rack_list), per_row)]
    out, y = [], pad + 4
    total_w = 0
    for row in rows:
        x = pad
        row_h = 0
        for rk in row:
            _parts9 = []   # [V55] 랙 단위 <g> 그룹 — 랙 전체 드래그(순서 변경)용
            pw, ph = _aq_rack_parts(_parts9, x, y + 10, rk["명칭"], rk["내측폭"], rk["단높이"], seq_by_shelf,
                                    scale=scale, show_dims=(scale >= 0.15), info=info,
                                    shelf_t=int(rk.get("단두께") or 0),   # [V62] 단 판 두께 반영
                                    force=mstack)   # [V64] 수동 적층 고정
            out.append(f'<g class="aqrackg" data-rack="{_aq_esc(rk["명칭"])}">' + "".join(_parts9) + '</g>')
            x += pw + gap_x
            row_h = max(row_h, ph)
        total_w = max(total_w, x)
        y += row_h + gap_y
    return (f'<svg width="{total_w + pad:.0f}" height="{y + pad:.0f}" xmlns="http://www.w3.org/2000/svg">'
            + "".join(out) + '</svg>')

def aq_shelf_top_svg(rack_name, shelf_no, inner, shelf_h, depth, seq, rows_by_code=None, box_depths=None, info=None, scale=0.5):
    """[V49] 단 탑뷰 — 위에서 내려다본 배치. 전면 x좌표는 정면 패킹과 동일, 깊이 방향 줄수 표시.
    depth=단 깊이mm · rows_by_code={코드:줄수} · box_depths={상자:깊이mm}(미등록 상자는 1줄 전체깊이).
    아래쪽 = 매장 전면(정면도에서 보이는 줄)."""
    pad = 18
    cols_p, fitted, rej = aq_pack_shelf_stacks(seq, inner, shelf_h)
    pw, ph = inner * scale, depth * scale
    out = [f'<rect x="{pad}" y="{pad}" width="{pw:.1f}" height="{ph:.1f}" fill="#FAFAF7" stroke="#191414" stroke-width="1.6"/>']
    for cx, cw, stack in cols_p:
        it = stack[0]
        code, grp, box = it[0], it[1], it[2]
        try: d = int(float((box_depths or {}).get(box) or 0))
        except Exception: d = 0
        try: n_rows = int((rows_by_code or {}).get(code) or 1)
        except Exception: n_rows = 1
        if d <= 0:
            d, n_rows = depth, 1          # 깊이 미등록 → 1줄 전체 깊이로 표시
        n_max = max(1, int(depth // d))
        n_rows = max(1, min(n_rows, n_max))
        col = AQ_GROUP_COLORS.get(aq_grp_norm(grp), "#9AA0A6")
        attrs = _aq_hover_attrs(it, info)
        for j in range(n_rows):
            y = pad + ph - (j + 1) * d * scale
            out.append(f'<rect x="{pad + cx*scale:.1f}" y="{y:.1f}" width="{cw*scale:.1f}" height="{d*scale:.1f}" '
                       f'fill="{col}" fill-opacity="{max(0.25, 0.78 - j*0.18):.2f}" stroke="#191414" stroke-width="0.7"{attrs}/>')
        if len(stack) > 1:   # 정면 기준 적층 수 표기
            out.append(f'<text x="{pad + (cx + cw/2)*scale:.1f}" y="{pad + ph - d*scale/2 + 3:.1f}" '
                       f'font-size="9" text-anchor="middle" fill="#191414">×{len(stack)}층</text>')
    out.append(f'<text x="{pad}" y="{pad - 5}" font-size="11" fill="#8C8681">'
               f'{_aq_esc(rack_name)} 단{shelf_no} 탑뷰 — 내측 {inner}×깊이 {depth}mm · 아래쪽=전면</text>')
    return (f'<svg width="{pw + pad*2:.0f}" height="{ph + pad*2:.0f}" xmlns="http://www.w3.org/2000/svg">'
            + "".join(out) + '</svg>')

def aq_svg_hover_html(svg, interactive=False, nonce="", boxes=None, committed_ts=0):
    """[V49] SVG를 호버 툴팁(품목명 크게·규격·상자·최대수량)과 함께 iframe HTML로 래핑.
    반환: (html, 권장 iframe 높이px). components.html로 렌더해야 JS 툴팁이 동작.
    [V51] interactive=True → 드래그 이동(같은 품목 묶음)·더블클릭 복제/삭제·전체화면/줌 툴바.
    조작은 부모 localStorage 'AQ_OPS'({nonce,ts,ops})에 기록 → 파이썬 브리지가 적용."""
    h = 400
    try:
        _i = svg.index('height="')
        h = int("".join(ch for ch in svg[_i + 8:_i + 16] if ch.isdigit()) or 400)
    except Exception:
        pass
    _btn = ('margin-left:4px;padding:3px 9px;border:1px solid #B9B3AD;background:#FFFFFF;'
            'border-radius:6px;cursor:pointer;font-size:12px;')
    tools = ''
    js_int = ''
    if interactive:
        tools = (
            '<div style="position:absolute;top:4px;right:8px;z-index:60;font-family:sans-serif;">'
            '<span id="aqst" style="font-size:11px;color:#8C8681;margin-right:8px;"></span>'
            f'<button onclick="aqZoom(1.25)" style="{_btn}">＋</button>'
            f'<button onclick="aqZoom(0.8)" style="{_btn}">－</button>'
            f'<button onclick="aqZreset()" style="{_btn}">1:1</button>'
            f'<button onclick="aqFull()" style="{_btn}">⛶ 전체화면</button></div>')
        js_int = """
<script>
var AQN="__NONCE__", AQB=__BOXES__, aqOps=[], aqZ=1, aqDrag=null, aqMenu=null, aqSeq=0;
var AQCT=__COMMITTED_TS__;   /* [V63] 서버가 마지막으로 반영한 조작 payload의 ts — 자가치유 기준 */
var aqSel=[], aqBand=null;   /* [V58] 다중선택(러버밴드+Shift) */
var aqBoxes=[].slice.call(document.querySelectorAll('.aqbox[data-code]'));
var aqZones=[].slice.call(document.querySelectorAll('.aqshelf'));
var aqSvg=document.querySelector('#aqzoom svg');
function aqTexts(el){var r=[],n=el.nextElementSibling;   /* 상자에 딸린 라벨 텍스트들 */
 while(n&&n.tagName==='text'){r.push(n);n=n.nextElementSibling;}return r;}
function aqOff(el){return {x:parseFloat(el.dataset.ox||0),y:parseFloat(el.dataset.oy||0)};}
function aqSetT(el,x,y){el.dataset.ox=x;el.dataset.oy=y;   /* 누적 오프셋 — 미반영 이동 위에 추가 이동 가능 */
 if(x||y)el.setAttribute('transform','translate('+x+','+y+')');else el.removeAttribute('transform');}
function aqSelHas(el){return aqSel.indexOf(el)>-1;}
function aqSelMark(el,on){
 if(on){el.setAttribute('stroke','#F4D624');el.setAttribute('stroke-width','2.6');}
 else{el.setAttribute('stroke','#191414');el.setAttribute('stroke-width','0.6');}}
function aqSelSet(arr){aqSel.forEach(function(b){aqSelMark(b,false);});
 aqSel=arr.slice();aqSel.forEach(function(b){aqSelMark(b,true);});aqStat();}
function aqSelClear(){aqSelSet([]);}
function aqStat(txt){var s=document.getElementById('aqst');if(!s)return;
 if(txt!==undefined){s.textContent=txt;return;}
 var p=[];if(aqSel.length)p.push('✓ 선택 '+aqSel.length+'상자 (Delete=삭제 · 드래그=이동)');
 if(aqOps.length)p.push('미반영 '+aqOps.length+'건');
 s.textContent=p.join(' · ');}
function aqZoom(f){aqZ=Math.max(0.3,Math.min(4,aqZ*f));document.getElementById('aqzoom').style.transform='scale('+aqZ+')';}
function aqZreset(){aqZ=1;document.getElementById('aqzoom').style.transform='';}
function aqFull(){var w=document.getElementById('aqwrap');
 if(document.fullscreenElement){document.exitFullscreen();return;}
 if(w.requestFullscreen){w.requestFullscreen().catch(function(){aqNewTab();});}else{aqNewTab();}}
function aqNewTab(){var t=window.open('','_blank');if(!t)return;
 t.document.write('<html><head><title>Aqunaris 배치</title></head><body style="background:#fff;">'
 +document.getElementById('aqzoom').innerHTML
 +'<script>[].slice.call(document.querySelectorAll(".aqlbl")).forEach(function(x){x.style.display="block";});'
 +'[].slice.call(document.querySelectorAll(".aqtag")).forEach(function(x){x.style.display="none";});<\\/script>'
 +'</body></html>');t.document.close();}
var aqZpre=null;
function aqFitZoom(){/* [V57] 전체화면 진입 시 화면에 꽉 차게 자동 확대 — 작은 라벨도 읽히게 */
 var zw=document.getElementById('aqzoom'),s=zw.firstElementChild;if(!s)return;
 var w=parseFloat(s.getAttribute('width'))||zw.scrollWidth,h=parseFloat(s.getAttribute('height'))||zw.scrollHeight;
 if(!w||!h)return;
 var f=Math.min((window.innerWidth-14)/w,(window.innerHeight-40)/h);
 aqZ=Math.max(1,Math.min(4,f));zw.style.transform='scale('+aqZ+')';}
document.addEventListener('fullscreenchange',function(){
 var on=!!document.fullscreenElement;
 [].slice.call(document.querySelectorAll('.aqlbl')).forEach(function(x){x.style.display=on?'block':'none';});
 [].slice.call(document.querySelectorAll('.aqtag')).forEach(function(x){x.style.display=on?'none':'block';});
 var zw=document.getElementById('aqzoom');
 if(on){aqZpre=aqZ;aqFitZoom();}
 else{aqZ=(aqZpre==null?1:aqZpre);aqZpre=null;zw.style.transform=(aqZ===1?'':'scale('+aqZ+')');
  if(aqOps.length){clearTimeout(window.__aqap);window.__aqap=setTimeout(aqApply,900);}}});   /* [V58] 종료 시 일괄 반영 — [V62] 전체화면 종료 리플로우/리사이즈가 가라앉은 뒤 커밋 */
function aqGrp(el){return aqBoxes.filter(function(b){return b.dataset.code===el.dataset.code
 &&b.dataset.rack===el.dataset.rack&&b.dataset.shelf===el.dataset.shelf;});}
function aqPush(op){op.id=Date.now()+'-'+(++aqSeq);aqOps.push(op);
 try{window.parent.localStorage.setItem('AQ_OPS',JSON.stringify({nonce:AQN,ts:Date.now(),ops:aqOps}));}catch(e){}
 aqSchedule();}
/* [V58] 버퍼링 개선 — 조작마다 리런하지 않고 그림에 즉시(낙관) 반영해 두고,
   4초간 추가 조작이 없을 때 한 번에 서버 반영. 전체화면 중에는 종료 시 일괄 반영. */
function aqSchedule(){clearTimeout(window.__aqap);
 if(document.fullscreenElement){aqStat('미반영 '+aqOps.length+'건 — 전체화면 종료 시 일괄 반영');return;}
 window.__aqap=setTimeout(aqApply,4000);
 aqStat('미반영 '+aqOps.length+'건 — 4초 뒤 일괄 반영(계속 조작하면 연장)');}
function aqApply(){if(!aqOps.length)return;
 if(document.fullscreenElement)return;
 if(aqDrag||aqRDrag||aqBand){clearTimeout(window.__aqap);window.__aqap=setTimeout(aqApply,1500);return;}
 aqStat('반영 중… ('+aqOps.length+'건)');
 /* [V62] 커밋 직전 새 ts로 재기록 → streamlit_js_eval이 값 변경을 확실히 감지해 적용 리런이 반드시 발생
    (전체화면 종료 시 옛 값 반환으로 복구 리런이 안 뜨던 경합 차단 · 중복은 op id 디둡으로 무해) */
 try{window.parent.localStorage.setItem('AQ_OPS',JSON.stringify({nonce:AQN,ts:Date.now(),ops:aqOps}));}catch(e){}
 try{var bs=window.parent.document.querySelectorAll('button');
 for(var i=0;i<bs.length;i++){if((bs[i].innerText||'').indexOf('배치 조작 반영')>-1){bs[i].click();
  clearTimeout(window.__aqap);window.__aqap=setTimeout(aqApply,3000);return;}}}catch(e){}
 clearTimeout(window.__aqap);window.__aqap=setTimeout(aqApply,3000);}   /* 실패 시 재시도(성공하면 iframe 교체됨) */
function aqZoneAt(x,y){for(var i=0;i<aqZones.length;i++){var r=aqZones[i].getBoundingClientRect();
 if(x>=r.left&&x<=r.right&&y>=r.top&&y<=r.bottom)return aqZones[i];}return null;}
function aqDragStart(el,ev){   /* [V58] 선택된 상자를 잡으면 선택 전체가 함께 이동
   [V61] 선택이 없으면 잡은 상자 1개만(낱개) — 루퍼젯 2팩 등도 하나씩 옮긴다 */
 var els,one=false;
 if(aqSelHas(el)&&aqSel.length>1){els=aqSel.slice();}
 else{aqSelClear();els=[el];one=(aqGrp(el).length>1);}
 aqDrag={one:one,items:els.map(function(b){
   var o=aqOff(b);
   return {b:b,bx:o.x,by:o.y,ts:aqTexts(b).map(function(t){var q=aqOff(t);return {n:t,bx:q.x,by:q.y};})};}),
  el:el,sx:ev.clientX,sy:ev.clientY,moved:false,raised:false};}
function aqDragRaise(d){if(d.raised)return;d.raised=true;   /* z-order: 실제 이동 시작 때만 랙 <g> 밖으로
 (mousedown에서 재부모화하면 크롬이 dblclick을 만들지 않음) */
 d.items.forEach(function(it){aqSvg.appendChild(it.b);
  it.ts.forEach(function(t){aqSvg.appendChild(t.n);});});}
aqBoxes.forEach(function(el){
 el.addEventListener('mousedown',function(ev){if(ev.button!==0)return;
  ev.preventDefault();ev.stopPropagation();
  if(ev.shiftKey){   /* Shift+클릭 = (같은 품목 묶음) 선택 토글 — PPT 방식 */
   var g=aqGrp(el);
   if(g.some(aqSelHas)){aqSelSet(aqSel.filter(function(b){return g.indexOf(b)<0;}));}
   else{aqSelSet(aqSel.concat(g));}
   return;}
  aqDragStart(el,ev);});
 el.addEventListener('dblclick',function(ev){aqMenuShow(el,ev);ev.preventDefault();});
});
document.addEventListener('mousemove',function(ev){if(!aqDrag)return;
 var dx=(ev.clientX-aqDrag.sx)/aqZ,dy=(ev.clientY-aqDrag.sy)/aqZ;
 if(Math.abs(dx)+Math.abs(dy)>3){aqDrag.moved=true;aqDragRaise(aqDrag);}
 aqDrag.items.forEach(function(it){aqSetT(it.b,it.bx+dx,it.by+dy);
  it.ts.forEach(function(t){aqSetT(t.n,t.bx+dx,t.by+dy);});});
 if(typeof tip!=='undefined')tip.style.display='none';
 var z=aqZoneAt(ev.clientX,ev.clientY);
 aqZones.forEach(function(r){var on=(r===z);
  r.setAttribute('stroke',on?'#F4D624':'none');r.setAttribute('stroke-width',on?'3':'0');
  r.setAttribute('fill',on?'#F4D624':'none');r.setAttribute('fill-opacity',on?'0.12':'0');});
});
function aqNudge(b,dx,dy){var o=aqOff(b);aqSetT(b,o.x+dx/aqZ,o.y+dy/aqZ);
 aqTexts(b).forEach(function(t){var q=aqOff(t);aqSetT(t,q.x+dx/aqZ,q.y+dy/aqZ);});}
function aqSnapBox(b,z,skip){/* [V60] 드롭 스냅 — 단 바닥/동일상자 위 적층 + 이웃·기둥에 딱 붙이기 */
 var rb=b.getBoundingClientRect(),zr=z.getBoundingClientRect();
 var others=aqBoxes.filter(function(x){
  if(x===b||skip.indexOf(x)>-1||x.style.display==='none')return false;
  if(x.dataset.rack!==z.dataset.rack||x.dataset.shelf!==z.dataset.shelf)return false;
  return x.getBoundingClientRect().width>0;});
 var cx=rb.left+rb.width/2,dy=null;
 var unders=others.filter(function(x){var r=x.getBoundingClientRect();   /* 드롭 지점 아래 동일 상자 → 위에 적층 */
  return x.dataset.box===b.dataset.box&&r.left<cx&&cx<r.right;});
 if(unders.length){var top=Math.min.apply(null,unders.map(function(x){return x.getBoundingClientRect().top;}));
  if(top-rb.height>=zr.top-2)dy=top-rb.bottom;}
 if(dy===null)dy=zr.bottom-rb.bottom;   /* 그 외 → 단 바닥에 밀착 */
 var dx=0,best=14;   /* 14px 이내면 이웃 상자·랙 기둥에 흡착 */
 others.forEach(function(x){var r=x.getBoundingClientRect();
  if(Math.abs(r.right-rb.left)<best){best=Math.abs(r.right-rb.left);dx=r.right-rb.left;}
  if(Math.abs(r.left-rb.right)<best){best=Math.abs(r.left-rb.right);dx=r.left-rb.right;}});
 if(Math.abs(zr.left-rb.left)<best){best=Math.abs(zr.left-rb.left);dx=zr.left-rb.left;}
 if(Math.abs(zr.right-rb.right)<best){best=Math.abs(zr.right-rb.right);dx=zr.right-rb.right;}
 aqNudge(b,dx,dy);}
document.addEventListener('mouseup',function(ev){if(!aqDrag)return;
 var d=aqDrag;aqDrag=null;
 aqZones.forEach(function(r){r.setAttribute('stroke','none');r.setAttribute('fill','none');});
 function rev(it){aqSetT(it.b,it.bx,it.by);it.ts.forEach(function(t){aqSetT(t.n,t.bx,t.by);});}
 if(!d.moved){d.items.forEach(rev);return;}
 var z=aqZoneAt(ev.clientX,ev.clientY);
 if(!z){d.items.forEach(rev);return;}
 var zr=z.getBoundingClientRect();   /* [V59] 드롭한 좌우 위치를 배치 순서에 반영 */
 var xr=Math.max(0,Math.min(1,(ev.clientX-zr.left)/Math.max(1,zr.width)));
 var done={};
 function aqOnBox(b,ev){   /* [V64] 대상 단에서 다른 상자 위(바닥에서 떠서)에 떨어뜨렸으면 그 상자 code 반환(적층 고정) */
  for(var i=0;i<aqBoxes.length;i++){var x=aqBoxes[i];
   if(x===b||x.style.display==='none')continue;
   if(d.items.some(function(it){return it.b===x;}))continue;
   if(x.dataset.rack!==z.dataset.rack||x.dataset.shelf!==z.dataset.shelf)continue;
   var r=x.getBoundingClientRect();
   if(r.width>0&&r.left<ev.clientX&&ev.clientX<r.right&&ev.clientY<r.bottom-4)return x.dataset.code;}
  return null;}
 d.items.forEach(function(it){var b=it.b;
  var k=b.dataset.code+'|'+b.dataset.rack+'|'+b.dataset.shelf;
  if(!done[k]){done[k]=true;
   if(z.dataset.rack!==b.dataset.rack||z.dataset.shelf!==b.dataset.shelf||d.moved){
    var _onto=aqOnBox(b,ev);   /* [V64] 위에 올린 대상 상자 code(있으면 그 열그룹에 합쳐 적층) */
    var op={t:'move',code:b.dataset.code,rack:b.dataset.rack,shelf:parseInt(b.dataset.shelf),
            track:z.dataset.rack,tshelf:parseInt(z.dataset.shelf),xr:Math.round(xr*1000)/1000,
            stack:_onto?1:0};   /* 1=상자 위 적층 고정 / 0=바닥 → 고정 해제 */
    if(_onto)op.onto=_onto;
    if(d.one)op.one=1;   /* [V61] 낱개 이동 → 서버가 분할 진열로 처리 */
    aqPush(op);}}
  b.dataset.rack=z.dataset.rack;b.dataset.shelf=z.dataset.shelf;});
 var rem=d.items.map(function(it){return it.b;});   /* [V60] 드롭 즉시 스냅 — 먼저 놓인 것부터 이웃이 됨 */
 d.items.forEach(function(it){rem.shift();aqSnapBox(it.b,z,rem.slice());});
});
function aqDelOne(b){aqPush({t:'del',code:b.dataset.code,rack:b.dataset.rack,shelf:parseInt(b.dataset.shelf)});
 b.style.display='none';aqTexts(b).forEach(function(t){t.style.display='none';});}
function aqSelDel(){var sel=aqSel.slice();aqSelClear();sel.forEach(aqDelOne);}   /* [V58] 선택 일괄 삭제 */
function aqMenuShow(el,ev){aqMenuHide();
 var m=document.createElement('div');aqMenu=m;m.id='aqmenu';
 m.style.cssText='position:fixed;z-index:120;background:#191414;border:2px solid #F4D624;'
  +'border-radius:8px;padding:8px;font-family:sans-serif;left:'+(ev.clientX+6)+'px;top:'+(ev.clientY+6)+'px;';
 var nm=el.getAttribute('data-name')||el.dataset.code;
 var t=document.createElement('div');
 t.style.cssText='color:#F4D624;font-weight:700;font-size:12px;margin-bottom:6px;';
 t.textContent=nm; m.appendChild(t);
 var b1=document.createElement('button');b1.textContent='⧉ 복제(+1상자)';
 var b2=document.createElement('button');b2.textContent='🗑 삭제(−1상자)';
 var b3=document.createElement('button');b3.textContent='✕';
 var bs4=[b1,b2,b3];
 var b4=null;
 if(aqSel.length>1&&aqSelHas(el)){b4=document.createElement('button');
  b4.textContent='🗑 선택 '+aqSel.length+'상자 삭제';bs4=[b1,b2,b4,b3];}
 bs4.forEach(function(b){b.style.cssText='margin-right:6px;padding:4px 8px;border:1px solid #F4D624;'
  +'background:#191414;color:#FFFFFF;border-radius:6px;cursor:pointer;font-size:12px;';m.appendChild(b);});
 b1.onclick=function(){aqPush({t:'dup',code:el.dataset.code,rack:el.dataset.rack,
  shelf:parseInt(el.dataset.shelf)});
  var g=aqGrp(el),last=g[g.length-1];   /* [V58] 반영 전에도 보이게 유령 복제 */
  try{var c=last.cloneNode(false);c.removeAttribute('class');c.setAttribute('pointer-events','none');
   var o=aqOff(last),hh=(last.getBBox?last.getBBox().height:12)||12;
   aqSvg.appendChild(c);aqSetT(c,o.x,o.y-hh);}catch(e){}
  aqMenuHide();};
 b2.onclick=function(){var g=aqGrp(el);aqDelOne(g[g.length-1]||el);aqMenuHide();};
 if(b4)b4.onclick=function(){aqSelDel();aqMenuHide();};
 b3.onclick=aqMenuHide;
 if(AQB&&AQB.length){var bt=document.createElement('div');
  bt.style.cssText='color:#CFC9C3;font-size:10px;margin:7px 0 3px 0;';bt.textContent='📦 상자 변경';m.appendChild(bt);
  var bw=document.createElement('div');bw.style.cssText='max-width:230px;';
  AQB.forEach(function(bn){if(bn===el.getAttribute('data-box'))return;
   var bb=document.createElement('button');bb.textContent=bn;
   bb.style.cssText='margin:0 4px 4px 0;padding:3px 7px;border:1px solid #8C8681;'
    +'background:#2B2626;color:#FFFFFF;border-radius:5px;cursor:pointer;font-size:11px;';
   bb.onclick=function(){aqPush({t:'box',code:el.dataset.code,rack:el.dataset.rack,
    shelf:parseInt(el.dataset.shelf),box:bn});aqMenuHide();};
   bw.appendChild(bb);});
  m.appendChild(bw);}
 document.getElementById('aqwrap').appendChild(m);}   /* [V58] 전체화면(#aqwrap) 안에서도 메뉴 표시 */
function aqMenuHide(){if(aqMenu&&aqMenu.parentNode)aqMenu.parentNode.removeChild(aqMenu);aqMenu=null;}
document.addEventListener('mousedown',function(ev){if(aqMenu&&!aqMenu.contains(ev.target))aqMenuHide();},true);
/* [V58] 러버밴드 다중선택 — 빈 곳 드래그로 영역 안 상자 전부 선택(랙은 선택 안 됨), Shift=추가 */
document.addEventListener('mousedown',function(ev){
 if(ev.button!==0||aqDrag||aqRDrag||aqBand)return;
 var t=ev.target;
 if(t.closest&&(t.closest('#aqmenu')||t.closest('button')||t.closest('#aqtip')))return;
 if(t.classList&&(t.classList.contains('aqbox')||t.classList.contains('aqrackhandle')))return;
 aqBand={x:ev.clientX,y:ev.clientY,add:ev.shiftKey,el:null,rect:null};});
document.addEventListener('mousemove',function(ev){if(!aqBand)return;
 if(!aqBand.el){var dv=document.createElement('div');aqBand.el=dv;
  dv.style.cssText='position:fixed;z-index:110;border:1.5px dashed #C7A500;'
   +'background:rgba(244,214,36,0.12);pointer-events:none;';
  document.getElementById('aqwrap').appendChild(dv);}
 var x1=Math.min(ev.clientX,aqBand.x),y1=Math.min(ev.clientY,aqBand.y);
 var w=Math.abs(ev.clientX-aqBand.x),h=Math.abs(ev.clientY-aqBand.y);
 var s=aqBand.el.style;s.left=x1+'px';s.top=y1+'px';s.width=w+'px';s.height=h+'px';
 aqBand.rect={l:x1,t:y1,r:x1+w,b:y1+h};
 if(typeof tip!=='undefined')tip.style.display='none';});
document.addEventListener('mouseup',function(ev){if(!aqBand)return;
 var b=aqBand;aqBand=null;
 if(b.el&&b.el.parentNode)b.el.parentNode.removeChild(b.el);
 if(!b.rect||(b.rect.r-b.rect.l)+(b.rect.b-b.rect.t)<8){if(!b.add)aqSelClear();return;}
 var hit=aqBoxes.filter(function(x){
  if(x.style.display==='none')return false;
  var r=x.getBoundingClientRect();
  return r.left<b.rect.r&&r.right>b.rect.l&&r.top<b.rect.b&&r.bottom>b.rect.t;});
 aqSelSet(b.add?aqSel.concat(hit.filter(function(x){return !aqSelHas(x);})):hit);});
document.addEventListener('keydown',function(ev){
 if((ev.key==='Delete'||ev.key==='Backspace')&&aqSel.length){aqSelDel();ev.preventDefault();}
 else if(ev.key==='Escape'&&aqSel.length){aqSelClear();}});
var aqRDrag=null;
[].slice.call(document.querySelectorAll('.aqrackhandle')).forEach(function(h){
 h.style.cursor='grab';
 h.addEventListener('mousedown',function(ev){if(ev.button!==0)return;
  aqRDrag={g:(h.closest?h.closest('g.aqrackg'):null),rack:h.getAttribute('data-rack'),
           sx:ev.clientX,sy:ev.clientY,moved:false};
  ev.preventDefault();ev.stopPropagation();});
});
document.addEventListener('mousemove',function(ev){if(!aqRDrag)return;
 var dx=(ev.clientX-aqRDrag.sx)/aqZ,dy=(ev.clientY-aqRDrag.sy)/aqZ;
 if(Math.abs(dx)+Math.abs(dy)>4)aqRDrag.moved=true;
 if(aqRDrag.g)aqRDrag.g.setAttribute('transform','translate('+dx+','+dy+')');
 if(typeof tip!=='undefined')tip.style.display='none';});
document.addEventListener('mouseup',function(ev){if(!aqRDrag)return;
 var d=aqRDrag;aqRDrag=null;
 if(!d.moved){if(d.g)d.g.removeAttribute('transform');return;}
 var best=null,bd=1e12;
 [].slice.call(document.querySelectorAll('g.aqrackg')).forEach(function(g){
  if(d.g&&g===d.g)return;
  var r=g.getBoundingClientRect(),cx=r.left+r.width/2,cy=r.top+r.height/2;
  var dist=(cx-ev.clientX)*(cx-ev.clientX)+(cy-ev.clientY)*(cy-ev.clientY);
  if(dist<bd){bd=dist;best={g:g,cx:cx};}});
 if(best){aqPush({t:'rord',rack:d.rack,target:best.g.getAttribute('data-rack'),after:ev.clientX>best.cx});}
 else if(d.g){d.g.removeAttribute('transform');}
});
/* [V63] 자가치유 — iframe이 재생성될 때 localStorage에 '서버가 아직 반영 안 한' 조작(ts>AQCT)이
   남아 있으면 재반영을 예약한다. 비동기 브리지 읽기 레이스(bump 리런의 빈 읽기 → 편집前 재생성)로
   조작이 유실·초기화되던 것을 복구한다. move는 목적 단 위로 시각 이동해 스냅백(깜빡임)도 줄인다. */
(function(){try{
 var _p=JSON.parse(window.parent.localStorage.getItem('AQ_OPS')||'{}');
 if(_p&&_p.nonce===AQN&&_p.ops&&_p.ops.length&&((+_p.ts||0)>(+AQCT||0))){
  aqOps=_p.ops.slice(); aqSeq=aqOps.length;
  _p.ops.forEach(function(op){try{if(op.t==='move'&&op.track){
    var bx=document.querySelector('.aqbox[data-code="'+op.code+'"]');
    var zn=document.querySelector('.aqshelf[data-rack="'+op.track+'"][data-shelf="'+op.tshelf+'"]');
    if(bx&&zn){var br=bx.getBoundingClientRect(),zr=zn.getBoundingClientRect();
     aqSvg.appendChild(bx);
     aqSetT(bx,(zr.left+zr.width/2)-(br.left+br.width/2),(zr.top+zr.height*0.72)-(br.top+br.height/2));}
  }}catch(e){}});
  clearTimeout(window.__aqap); window.__aqap=setTimeout(aqApply,700);
  aqStat('미반영 '+aqOps.length+'건 — 재반영 중');
 }}catch(e){}})();
</script>""".replace("__NONCE__", str(nonce).replace('"', '')).replace(
            "__COMMITTED_TS__", str(int(float(committed_ts or 0)))).replace(
            "__BOXES__", json.dumps([str(b) for b in (boxes or [])], ensure_ascii=False))
    html = (
        '<div id="aqwrap" style="position:relative;font-family:sans-serif;background:#FFFFFF;overflow:auto;">'
        + tools + '<div id="aqzoom" style="transform-origin:0 0;">' + svg + '</div>' +
        '<div id="aqtip" style="display:none;position:fixed;z-index:99;pointer-events:none;'
        'background:#191414;color:#FFFFFF;border:2px solid #F4D624;border-radius:8px;'
        'padding:10px 14px;max-width:320px;box-shadow:0 4px 14px rgba(0,0,0,.35);">'
        '<div id="aqtip-name" style="font-size:19px;font-weight:800;color:#F4D624;line-height:1.25;"></div>'
        '<div id="aqtip-spec" style="font-size:13px;margin-top:3px;"></div>'
        '<div id="aqtip-cap" style="font-size:13px;margin-top:2px;color:#CFC9C3;"></div>'
        '</div>'
        '<script>'
        'var tip=document.getElementById("aqtip");'
        'function aqShow(el,ev){'
        ' document.getElementById("aqtip-name").textContent=el.getAttribute("data-name")||"";'
        ' document.getElementById("aqtip-spec").textContent=el.getAttribute("data-spec")||"";'
        ' var b=el.getAttribute("data-box")||"", c=el.getAttribute("data-cap")||"";'
        ' var ctxt=c?(c==="\\uc5c6\\uc74c"?" \\u00B7 \\uc218\\ub7c9\\uc815\\ubcf4 \\uc5c6\\uc74c":(" \\u00B7 \\ucd5c\\ub300 "+c+"\\uac1c")):"";'
        ' document.getElementById("aqtip-cap").textContent=(b?("\\uD83D\\uDCE6 "+b):"")+ctxt;'
        ' tip.style.display="block"; aqMove(ev);}'
        'function aqMove(ev){'
        ' var x=ev.clientX+14,y=ev.clientY+14;'
        ' var r=tip.getBoundingClientRect();'
        ' if(x+r.width>window.innerWidth-8)x=ev.clientX-r.width-10;'
        ' if(y+r.height>window.innerHeight-8)y=ev.clientY-r.height-10;'
        ' tip.style.left=x+"px"; tip.style.top=y+"px";}'
        'document.querySelectorAll(".aqbox").forEach(function(el){'
        ' el.addEventListener("mouseenter",function(ev){aqShow(el,ev);});'
        ' el.addEventListener("mousemove",aqMove);'
        ' el.addEventListener("mouseleave",function(){tip.style.display="none";});'
        ' el.style.cursor="pointer";});'
        '</script>' + js_int + '</div>')
    return html, h + 10

# [V66] app.py가 `from aquanaris_layout import *`로 가져갈 이름 — aq_/AQ_/_aq_/_AQ_ 전부(색상헬퍼 제외)
__all__ = [n for n in list(globals())
           if (n.startswith('aq_') or n.startswith('AQ_') or n.startswith('_aq_') or n.startswith('_AQ_'))
           and n not in ('_aq_hexrgb', '_aq_lum_txt')]
