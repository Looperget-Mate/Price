# -*- coding: utf-8 -*-
"""[S1 · 2026-09-11] 아쿠나리스 재단 되먹임 — 「랙을 지우면 무슨 일이 생기나」.

근거: 결정 #88 · `_보고/2026-09-10_아쿠나리스_진열부속추천_검토.html` §3·§4.
금사농협 실측 — 재단은 **랙 단위**로 잘렸다(표준 12랙 → 섹션03~10). 대표가 이미 하는 조작
(표준 복제 → 랙 삭제 → 자동배치)에서 빠진 것은 「지우면 무엇이 갈 곳을 잃고, 남은 랙에 들어가나」를
말해 주는 부분뿐이다. 이 모듈은 그것만 한다.

  orphans(std_plan, rack_names, site_plan=None)  갈 곳 잃은 품목 — 지운 랙에 있던 것 (조회)
  headroom(racks, insts, dims)                   남은 랙의 단별 사용폭·여유폭·빈 칸·넘침
  fit(lost_rows, room_rows, box_of, dims)        갈 곳 잃은 상자가 빈 칸에 몇 개 들어가나 (개수만)
  diff_standard(site_plan, std_plan)             유지 / 옮김 / 뺌 / 추가
  group_keep(site_plan, std_plan, items)         부속군별 유지율

🔴 무엇을 뺄지·어디에 둘지는 정하지 않는다 — 판단은 사람, 자리는 기존 aq_auto_place(불변 원칙 1).
🔴 looperget(프로매니저 · 설계 개념)을 import 하지 않는다 — 진열 검토에 설계 개념을 섞지 않는다(대표 지시 · 시험으로 고정).
[2026-09-11] looperget/aq_fit.py → aqunaris/fit.py (앱 분리).
순수 모듈: streamlit·시트·파일 접근 없음. 입력은 AQ_Sites 의 랙구성JSON·배치JSON 을 json.loads 한 값.
"""
import math

from aqunaris.layout import aq_inst_cols, aq_inst_unpack

MAX_LAYERS = 3              # aq_pack_shelf_stacks 기본값 — 같은 상자끼리 3층까지
NO_STACK = ("루퍼젯팩",)     # [V61] 팩 제품은 쌓지 않는다
FREE_PREFIX = "자유:"        # 자유배치(여과기·지주대 등) 치수 키 — 칸으로 세지 않는다


def _layers(box, box_h, shelf_h):
    """한 단에 같은 상자를 몇 층 쌓나 — aq_pack_shelf_stacks 규칙 그대로(3층 · 루퍼젯팩 1층 · 0이면 못 들어감)."""
    if box_h <= 0 or shelf_h <= 0:
        return 0
    n = min(MAX_LAYERS, int(shelf_h // box_h))
    return min(n, 1) if box in NO_STACK else n


def rack_list(records):
    """랙구성JSON(records) → [{명칭, 내측폭, 단높이}] — app.py 배치부(_rk_list)와 같은 규칙.
    내측폭 = 폭mm − 38(기둥 19×2) · 단높이 = '단높이mm(콤마구분)'(단1 = 맨 아래). 폭·단높이 없는 랙은 뺀다."""
    out = []
    for r in records or []:
        if not isinstance(r, dict):
            continue
        nm = str(r.get("명칭") or "").strip()
        if not nm:
            continue
        try:
            w = int(float(r.get("폭mm") or 0))
        except (TypeError, ValueError):
            w = 0
        try:
            hs = [int(float(x)) for x in str(r.get("단높이mm(콤마구분)") or "").split(",") if str(x).strip()]
        except ValueError:
            hs = []
        if w > 0 and hs:
            out.append({"명칭": nm, "내측폭": w - 38, "단높이": hs})
    return out


def box_resolver(plan, items=None):
    """코드 → 상자명. app.py `_box_of0` 와 같은 순서: 배치 items.box → AQ_Items 기본상자 → 자유배치('자유:코드').
    저장본(inst2)에는 상자명이 없어서([V68]) 이렇게 되짚는다."""
    plan = plan if isinstance(plan, dict) else {}
    pitems = plan.get("items") if isinstance(plan.get("items"), dict) else {}
    free = plan.get("free") if isinstance(plan.get("free"), dict) else {}
    by = {str(r.get("품목코드") or "").strip(): r for r in (items or []) if isinstance(r, dict)}

    def box_of(code):
        c = str(code)
        ov = pitems.get(c) if isinstance(pitems.get(c), dict) else {}
        b = str(ov.get("box") or (by.get(c) or {}).get("기본상자") or "").strip()
        if not b and c in free:
            b = FREE_PREFIX + c
        return b
    return box_of


def dims_with_free(box_dims, plan):
    """상자 치수 {상자: (폭, 높이)} + 자유배치 치수('자유:코드') — app.py 배치부와 같다."""
    d = dict(box_dims or {})
    free = (plan or {}).get("free") if isinstance((plan or {}).get("free"), dict) else {}
    for c, fc in free.items():
        try:
            d[FREE_PREFIX + str(c)] = (int(fc["w"]), int(fc["h"]))
        except (KeyError, TypeError, ValueError):
            pass
    return d


def instances(plan, box_of=None):
    """배치JSON → 상자 인스턴스 [{code, box, rack, shelf, col, layer}] — app.py 로드와 같은 우선순위.
    ① inst2(정식 · 좌표 그대로) ② instances(schema 2 초기) ③ assign·splits(v1 · 좌표 없음).
    ③은 상자마다 제 열을 준다(쌓지 않음) — 여유를 **적게** 보는 안전측. 연습 사이트(신규농협1·2)가 이 형식이다."""
    plan = plan if isinstance(plan, dict) else {}
    bo = box_of or (lambda c: "")
    packed = plan.get("inst2")
    if isinstance(packed, dict) and packed:
        return aq_inst_unpack(packed, bo)
    raw = plan.get("instances")
    if isinstance(raw, list):
        out = []
        for x in raw:
            if not isinstance(x, dict):
                continue
            try:
                e = {"code": str(x.get("code") or ""), "box": str(x.get("box") or bo(x.get("code"))),
                     "rack": str(x.get("rack") or ""), "shelf": int(x.get("shelf") or 0),
                     "col": float(x.get("col") or 0), "layer": float(x.get("layer") or 0)}
            except (TypeError, ValueError):
                continue
            if e["code"] and e["rack"] and e["shelf"] > 0:
                out.append(e)
        return out
    out, nxt = [], {}
    asg = plan.get("assign") if isinstance(plan.get("assign"), dict) else {}
    spl = plan.get("splits") if isinstance(plan.get("splits"), dict) else {}

    def _add(c, rack, shelf, n):
        try:
            sh, n = int(shelf or 0), int(n or 1)
        except (TypeError, ValueError):
            return
        if not rack or sh <= 0:
            return
        for _ in range(max(1, n)):
            k = (str(rack), sh)
            out.append({"code": str(c), "box": str(bo(c)), "rack": k[0], "shelf": sh,
                        "col": nxt.get(k, 0), "layer": 0})
            nxt[k] = nxt.get(k, 0) + 1
    for c, d in asg.items():
        if isinstance(d, dict):
            _add(c, d.get("rack"), d.get("shelf"), d.get("n"))
    for c, rest in spl.items():
        for e in rest if isinstance(rest, list) else []:
            if isinstance(e, (list, tuple)) and len(e) >= 3:
                _add(c, e[0], e[1], e[2])
    return out


def placements(plan):
    """배치JSON → {코드: {(랙, 단): 상자수}}."""
    out = {}
    for it in instances(plan):
        d = out.setdefault(str(it["code"]), {})
        k = (str(it["rack"]), int(it["shelf"]))
        d[k] = d.get(k, 0) + 1
    return out


def _main(locs):
    """본 자리 = 상자가 가장 많은 단(같으면 앞선 자리) — aq_inst_derive_assign 과 같은 뜻."""
    return max(sorted(locs), key=lambda k: locs[k])


def _rack_key(order):
    pos = {n: i for i, n in enumerate(order or [])}
    return lambda n: (pos.get(n, len(pos)), n)


def orphans(std_plan, rack_names, site_plan=None):
    """갈 곳 잃은 품목 — 표준에서 **지운 랙**(rack_names 에 없는 랙)에 상자가 있던 품목. 계산이 아니라 조회.

    rows[] = {code, lost[(랙, 단, 상자수)], lost_n, std_n, whole(전부 잃음), status}
      site_plan 없음: status = '갈 곳 없음'(전부 잃음) · '일부 남음'(남은 랙에도 있음)
      site_plan 있음: status = '다시 놓음'(매장 배치에 있음) · '빠짐'(없음) + now[(랙, 단, 상자수)]
    ⚠ 랙은 **이름**으로 맞춘다 — 표준 복제본에서 랙 이름을 바꾸면 지운 랙으로 보인다."""
    std = placements(std_plan)
    keep = {str(n) for n in rack_names or []}
    rkey = _rack_key((std_plan or {}).get("rack_order"))
    removed = sorted({r for locs in std.values() for (r, _s) in locs if r not in keep}, key=rkey)
    site = placements(site_plan) if site_plan is not None else None
    rows = []
    for code in sorted(std):
        locs = std[code]
        lost = sorted(((r, s, n) for (r, s), n in locs.items() if r not in keep),
                      key=lambda t: (rkey(t[0]), t[1]))
        if not lost:
            continue
        lost_n, std_n = sum(t[2] for t in lost), sum(locs.values())
        row = {"code": code, "lost": lost, "lost_n": lost_n, "std_n": std_n, "whole": lost_n == std_n,
               "need_n": lost_n}
        if site is None:
            row["status"] = "갈 곳 없음" if row["whole"] else "일부 남음"
        else:
            now = site.get(code) or {}
            row["now"] = sorted(((r, s, n) for (r, s), n in now.items()), key=lambda t: (rkey(t[0]), t[1]))
            # 다시 놓은 상자 = 표준의 남은 자리를 넘어선 상자 — 원래 남은 랙에 있던 상자는 세지 않는다
            extra = sum(max(0, n - locs.get(k, 0)) for k, n in now.items())
            row["need_n"] = max(0, lost_n - extra)
            row["status"] = ("빠짐" if not now else "다시 놓음" if extra >= lost_n
                             else "일부 다시 놓음" if extra else "남은 자리만")
        rows.append(row)
    return {"removed": removed, "rows": rows}


def headroom(racks, insts, dims, boxes=None):
    """남은 랙의 단별 여유 — 좌표 기반(aq_inst_cols · aq_inst_validate 와 같은 폭 계산).

    racks = rack_list() 결과 · insts = instances()(상자명 채운 것) · dims = dims_with_free().
    빈 칸 = 위_빈칸(기존 열 위 · 같은 상자 · 층수 한도 안) + 새_빈칸(여유 폭에 새 열 × 층수).
    🔴 새_빈칸은 상자 종류마다 **같은 여유 폭을 나눠 쓰는 대안**이다 — 종류끼리 더하지 않는다(나눠 쓰기는 fit).
    boxes = 빈 칸을 셀 상자 종류(기본 = dims 의 상자 전부, 자유배치 제외)."""
    kinds = [b for b in (boxes or dims) if b in dims and not str(b).startswith(FREE_PREFIX)]
    by = {}
    for it in insts:
        by.setdefault((str(it.get("rack") or ""), int(it.get("shelf") or 0)), []).append(it)
    rows = []
    for rk in racks:
        inner = rk["내측폭"]
        for si, sh in enumerate(rk["단높이"], 1):
            lst = by.get((rk["명칭"], si), [])
            cols, unknown = aq_inst_cols(lst, dims, inner)
            used = sum(cw for _x, cw, _s in cols)
            free = max(0, inner - used)
            top = {}
            for _x, _cw, stack in cols:
                bxs = {str(it.get("box") or "") for it, _wh in stack}
                if len(bxs) != 1:
                    continue
                b = bxs.pop()
                if b.startswith(FREE_PREFIX) or b not in dims:
                    continue
                room = _layers(b, dims[b][1], sh) - len(stack)
                if room > 0:
                    top[b] = top.get(b, 0) + room
            new = {b: (free // dims[b][0]) * _layers(b, dims[b][1], sh) for b in kinds}
            rows.append({"랙": rk["명칭"], "단": si, "단높이": sh, "내측폭": inner,
                         "상자수": len(lst), "사용폭": used, "여유폭": free,
                         "점유율": round(100.0 * used / inner, 1) if inner else 0.0,
                         "넘침": max(0, used - inner), "위_빈칸": top, "새_빈칸": new,
                         "미지정": len(unknown)})
    return rows


def fit(lost_rows, room_rows, box_of, dims):
    """갈 곳 잃은 상자가 남은 랙의 빈 칸에 **몇 개** 들어가나 — 개수만 센다(자리는 정하지 않는다).

    수요 = 각 행의 need_n — 매장 배치가 없으면 지운 랙에 있던 상자 수, 있으면 그중 아직 못 놓은 수.
    채우는 법(어림 · 탐욕): 폭 넓은 상자부터 ① 기존 열 위 빈 칸 ② 여유 폭 큰 단부터 새 열. 여유 폭은 종류끼리 나눠 쓴다.
    🔴 부속군 구획(색 자석테이프 · 결정 #11)은 보지 않는다 — 물리적으로 들어가나만. 실제 자리는 aq_auto_place.
    자유배치·치수 미등록 상자는 칸으로 셀 수 없어 unknown 으로 따로 낸다(조용히 빼지 않는다).
    반환 {need, fit, short: {상자: n}, unknown: [(코드, 상자, n)], 넘침%}"""
    need, unknown = {}, []
    for r in lost_rows:
        n = int(r.get("need_n", r["lost_n"]))
        if n <= 0:
            continue
        b = str(box_of(r["code"]) or "")
        if not b or b.startswith(FREE_PREFIX) or b not in dims:
            unknown.append((r["code"], b, n))
            continue
        need[b] = need.get(b, 0) + n
    pool = [{"여유폭": r["여유폭"], "단높이": r["단높이"], "위": dict(r.get("위_빈칸") or {})} for r in room_rows]
    got = {}
    for b in sorted(need, key=lambda k: (-dims[k][0], k)):
        w, h = dims[b]
        left = need[b]
        for p in pool:
            k = min(p["위"].get(b, 0), left)
            if k:
                p["위"][b] -= k
                left -= k
        for p in sorted(pool, key=lambda q: -q["여유폭"]):
            if left <= 0:
                break
            L = _layers(b, h, p["단높이"])
            if L < 1 or w <= 0:
                continue
            ncol = min(p["여유폭"] // w, math.ceil(left / L))
            if ncol <= 0:
                continue
            p["여유폭"] -= ncol * w
            left -= min(left, ncol * L)
        got[b] = need[b] - left
    short = {b: need[b] - got[b] for b in need if need[b] > got[b]}
    tot = sum(need.values())
    return {"need": need, "fit": got, "short": short, "unknown": unknown,
            "넘침%": round(100.0 * sum(short.values()) / tot, 1) if tot else 0.0}


def diff_standard(site_plan, std_plan):
    """표준 대비 — 유지(본 자리 같음) · 옮김(다른 본 자리) · 뺌(매장에 없음) · 추가(표준에 없음). 코드 목록."""
    std, site = placements(std_plan), placements(site_plan)
    out = {"유지": [], "옮김": [], "뺌": [], "추가": []}
    for c in sorted(set(std) | set(site)):
        if c not in site:
            out["뺌"].append(c)
        elif c not in std:
            out["추가"].append(c)
        elif _main(site[c]) == _main(std[c]):
            out["유지"].append(c)
        else:
            out["옮김"].append(c)
    return out


def group_keep(site_plan, std_plan, items):
    """부속군(AQ_Items 진열분류)별 유지율 — 표준 품목 중 매장 배치에 남은 비율. 표준 품목 수가 많은 군부터."""
    grp = {str(r.get("품목코드") or "").strip(): str(r.get("진열분류") or "").strip()
           for r in (items or []) if isinstance(r, dict)}
    std, site = placements(std_plan), placements(site_plan)
    acc = {}
    for c in std:
        g = grp.get(c) or "(미지정)"
        a = acc.setdefault(g, {"부속군": g, "표준": 0, "유지": 0})
        a["표준"] += 1
        a["유지"] += 1 if c in site else 0
    rows = sorted(acc.values(), key=lambda a: (-a["표준"], a["부속군"]))
    for a in rows:
        a["유지율"] = round(100.0 * a["유지"] / a["표준"], 1)
    return rows
