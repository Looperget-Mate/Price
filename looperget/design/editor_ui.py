"""P3 connection/supply editors. UI only; engineering decisions stay in engines."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid
from datetime import datetime

import pandas as pd
import streamlit as st


def invalidate():
    for key in ("p3_result", "p3_pub", "p3_site"):
        st.session_state.pop(key, None)


SITE_FIELDS = ("chains", "supply", "row_kits", "tool_items", "link_intent", "photos", "connection_examples",
               "contact")   # [V117 · 2-C] 연락처·회신 기한(매번 수동 · 빈칸 허용)


def sync_site_fields(pins, drawn):
    """[V117 · K-02] 현장마다 다른 입력(사슬·급수 성능·열별 세트·공구·접점 의도·사진·연결 예시)은 **목록(pins)이 정본**이다.
    drawn 은 그대로 따라 쓴다 — 목록에 없으면 drawn 에서도 뺀다. 예전엔 「있으면 복사」만 해서 「🗑 목록 전부 비우기」·
    새 현장 뒤에도 옛 현장의 접점 의도·사진이 drawn → site(엔진 입력)에 남았다(재검토 K-02)."""
    if not isinstance(drawn, dict):
        return drawn
    for field in SITE_FIELDS:
        if field in (pins or {}):
            drawn[field] = copy.deepcopy(pins[field])
        else:
            drawn.pop(field, None)
    return drawn


def clear_site_fields(drawn):
    """[V117 · K-02] 「🗑 목록 전부 비우기」 — drawn 의 현장별 입력도 함께 비운다."""
    if isinstance(drawn, dict):
        for field in SITE_FIELDS:
            drawn.pop(field, None)
    return drawn


def invalidate_changed_inputs():
    pins = st.session_state.get("p3_pins") or {}
    drawn = st.session_state.get("p3_drawn")
    sync_site_fields(pins, drawn)
    keys = ("p3_answers", "p3_waived", "p3_pins", "p3_drawn")
    sig = hashlib.sha256(json.dumps({k: st.session_state.get(k) for k in keys},
                                   ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    if st.session_state.get("p3_input_signature") != sig:
        invalidate()
        st.session_state.p3_input_signature = sig


def _save(pins):
    st.session_state.p3_pins = pins
    invalidate()
    st.session_state.p3_connection_epoch = st.session_state.get("p3_connection_epoch", 0) + 1
    st.rerun()


def _records(value):
    return value.where(pd.notnull(value), None).to_dict("records") if isinstance(value, pd.DataFrame) else value


def _number_or_none(value):
    return None if value in (None, "") else float(value)


def _ports_editor(ports, key):
    fields = ("id", "kind", "sex", "grade", "d_mm", "standard", "code", "port_id", "evidence")
    rows = [dict(id=k, **{f: v.get(f) for f in fields if f != "id"}) for k, v in ports.items()]
    edited = st.data_editor(pd.DataFrame(rows, columns=fields), hide_index=True, num_rows="dynamic", key=key,
                           column_config={"kind": st.column_config.SelectboxColumn("종류", options=["unknown", "coupler", "thread", "hose", "socket"]),
                                          "d_mm": st.column_config.NumberColumn("호칭 mm", min_value=0),
                                          "sex": st.column_config.TextColumn("성 C/E 또는 male/female"),
                                          "evidence": st.column_config.TextColumn("제품·확인 근거")})
    result = {}
    for row in _records(edited):
        pid = str(row.pop("id", "") or "").strip()
        if pid:
            if pid in result:
                raise ValueError("포트 ID가 겹칩니다: " + pid)
            result[pid] = dict(ports.get(pid) or {})
            for k, v in row.items():
                result[pid].pop(k, None)
                if v not in (None, ""):
                    result[pid][k] = v
    return result


def render_connections(pins, products, site_name="현장"):
    from . import connections as C
    with st.expander("🔗 A 시작부 · B 물공급부 · C 인입부 연결 사슬", expanded=bool(pins.get("chains"))):
        st.caption("부품은 물이 흐르는 순서로 추가합니다. 포트 정보가 없으면 미확정으로 저장합니다. "
                   "25 mm(1″) · 40 mm(1½″) · 50 mm(2″). 카플러 C/E와 나사 암수는 별개입니다.")
        chains = copy.deepcopy(pins.get("chains") or [])
        part = st.selectbox("사슬 부위", ["A", "B", "C"], format_func=lambda x: {"A": "A 시작부", "B": "B 물공급부", "C": "C 인입부"}[x])
        if st.button("이 부위에 사슬 추가", key="p3_chain_add"):
            cid = part + "-" + uuid.uuid4().hex[:10]
            chains.append({"id": cid, "part": part, "connection_id": cid, "start": {"port": {}}, "links": []})
            pins["chains"] = chains
            _save(pins)
        selected = [i for i, c in enumerate(chains) if c.get("part") == part]
        epoch = st.session_state.get("p3_connection_epoch", 0)
        if selected:
            idx = st.selectbox("편집할 사슬", selected, format_func=lambda i: chains[i]["id"], key=f"chain_pick_{part}_{epoch}")
            chain = chains[idx]
            key = f"ch_{chain['id']}_{epoch}"
            with st.form(key + "_boundary"):
                chain["connection_id"] = st.text_input("물리 접점 ID (경계에서 같은 접점은 하나만)", chain.get("connection_id", ""))
                source_names = [""] + [s.get("name", "") for s in pins.get("sources", [])]
                old = chain.get("replace_source", "")
                if old not in source_names:
                    source_names.append(old)
                chain["replace_source"] = st.selectbox("기존 시작 호스밴드를 이 사슬로 대체할 급수원", source_names,
                                                       index=source_names.index(old), format_func=lambda v: v or "대체하지 않음")
                route_names = [r["name"] for r in pins.get("routes", [])]
                chain["replace_route_joints"] = st.multiselect("이 사슬이 롤 이음 부속·밴드를 전부 맡을 경로", route_names,
                    default=[n for n in chain.get("replace_route_joints", []) if n in route_names])
                st.caption("선택 경로의 기존 롤 이음 부속과 밴드를 제외합니다. 사슬에 필요한 이음 전부를 입력하세요.")
                st.caption("시작 포트는 펌프 또는 실제 급수원 출구입니다. 끝 포트는 마지막 부품에서 도출합니다.")
                try:
                    ports = _ports_editor({"source": (chain.get("start") or {}).get("port") or {}}, key + "_source")
                except ValueError as exc:
                    st.error(str(exc)); ports = None
                if st.form_submit_button("시작 포트·접점 저장") and ports is not None:
                    chain["start"] = {"port": ports.get("source", {})}
                    pins["chains"] = chains
                    _save(pins)
            if st.button("마지막에 부품 추가", key=key + "_add"):
                chain["links"].append({"id": "link-" + uuid.uuid4().hex[:10], "qty": 1,
                                       "in_port": "in", "out_port": "out", "ports": {"in": {}, "out": {}}})
                pins["chains"] = chains
                _save(pins)
            links = chain.get("links") or []
            if links:
                li = st.selectbox("부품 순서", list(range(len(links))),
                                  format_func=lambda i: f"{i+1}. {links[i].get('code') or links[i].get('custom_name') or '미입력'}", key=key + "_link")
                link = links[li]
                with st.form(key + "_item_" + link["id"]):
                    catalog = {str(p.get("code", "")).zfill(5): p for p in products if p.get("code")}
                    codes = [""] + sorted(catalog)
                    current = str(link.get("code") or "")
                    if current and current not in codes:
                        codes.append(current)
                    link["code"] = st.selectbox("등록 품목 (직접 입력은 빈 선택)", codes, index=codes.index(current),
                                                 format_func=lambda c: (c + " · " + catalog.get(c, {}).get("name", "")) if c else "직접 입력 임시 품목")
                    link["custom_name"] = st.text_input("임시 품목명 / 보충 설명", link.get("custom_name", ""))
                    link["material"] = st.text_input("임시 품목 재질", link.get("material", ""))
                    link["nominal_mm"] = st.number_input("임시 품목 호칭 mm", min_value=0.0, value=_number_or_none(link.get("nominal_mm")))
                    link["qty"] = st.number_input("수량", min_value=0.0, value=float(link.get("qty", 1)))
                    link["unit"] = st.text_input("판매 단위", link.get("unit", "EA"))
                    link["price"] = st.number_input("대표 입력 단가 (비우면 미확정)", min_value=0.0, value=_number_or_none(link.get("price")), step=1.0)
                    link["price_basis"] = st.text_input("가격 기준 (소비자가·부가세 등)", link.get("price_basis", ""))
                    directions = ["수평", "상", "하", "좌", "우"]
                    link["direction"] = st.selectbox("시공 방향", directions, index=directions.index(link.get("direction", "수평")) if link.get("direction", "수평") in directions else 0)
                    st.caption("포트 ID는 in/out 외에 T의 branch 등도 추가 가능합니다. 미확인 상세 규격은 빈칸으로 둡니다.")
                    try:
                        ports = _ports_editor(link.get("ports") or {"in": {}, "out": {}}, key + "_ports_" + link["id"])
                    except ValueError as exc:
                        st.error(str(exc)); ports = None
                    link["in_port"] = st.text_input("입구 포트 ID", link.get("in_port", "in"))
                    link["out_port"] = st.text_input("출구 포트 ID", link.get("out_port", "out"))
                    shape = st.checkbox("T 부속 (가지 포트 연결·마감 확인)", value=link.get("shape") == "T")
                    branch_id = st.text_input("가지 포트 ID", next(iter(link.get("branches") or {}), "branch"))
                    branch = (link.get("branches") or {}).get(branch_id) or {}
                    state = st.selectbox("가지 처리", ["미확정", "connected", "capped"], index={"connected": 1, "capped": 2}.get(branch.get("state"), 0))
                    st.caption("T 가지가 있으면 아래에 연결 부속 또는 마개 상대 포트를 적습니다.")
                    try:
                        branch_ports = _ports_editor({"mate": branch.get("port") or {}}, key + "_branch_" + link["id"])
                    except ValueError as exc:
                        st.error(str(exc)); branch_ports = None
                    link["segment_id"] = st.text_input("지도와 같은 관 구간 ID (경로 이름)", link.get("segment_id", ""))
                    link["len_m"] = st.number_input("길이 있는 관 길이(m)", min_value=0.0, value=float(link.get("len_m") or 0))
                    material = st.text_input("관 재질 모델 (확인한 모델 키)", (link.get("pipe") or {}).get("material", ""))
                    pipe_id = st.number_input("관 실측 내경 mm (모르면 빈칸)", min_value=0.0, value=_number_or_none((link.get("pipe") or {}).get("id_mm")))
                    roll_m = st.number_input("판매단위당 길이 m (롤·본 판매일 때)", min_value=0.0, value=_number_or_none((link.get("pipe") or {}).get("roll_m")))
                    if st.form_submit_button("부품 저장") and ports is not None and branch_ports is not None:
                        link["ports"] = ports
                        link["temporary"] = not bool(link.get("code"))
                        if shape:
                            link["shape"] = "T"
                            link["branches"] = {branch_id: {"state": state, "port": branch_ports.get("mate", {})}}
                        else:
                            link.pop("shape", None)
                            link.pop("branches", None)
                        if material or link["len_m"]:
                            link["pipe"] = dict(link.get("pipe") or {}, material=material, code=link.get("code"),
                                                id_mm=pipe_id, roll_m=roll_m, unit=link["unit"])
                        pins["chains"] = chains
                        _save(pins)
                cols = st.columns(3)
                if cols[0].button("앞으로 이동", disabled=li == 0, key=key + "_up"):
                    links[li-1], links[li] = links[li], links[li-1]
                    pins["chains"] = chains; _save(pins)
                if cols[1].button("부품 삭제", key=key + "_delete"):
                    links.pop(li); pins["chains"] = chains; _save(pins)
            if st.button("선택 사슬 삭제", key=key + "_remove"):
                chains.pop(idx); pins["chains"] = chains; _save(pins)
        try:
            checked = C.validate_chains(pins.get("chains") or [])
            st.write("연결 검사: **" + checked["status"] + "** · 수리 검사: **" + checked["hydraulic_status"] + "**")
            for issue in checked.get("issues", []):
                st.warning(str(issue))
        except ValueError as exc:
            st.error("사슬 입력 오류: " + str(exc))
        # [2026-10-04 · 대표 A안] 설계 CAD 끼움 자리 참고 — 위 판정을 바꾸지 않는다(CAD 부속 = 추정 형상)
        from . import cad_ports as CP
        _cad_hints = CP.chain_hints(pins.get("chains") or [])
        if _cad_hints:
            with st.expander(f"🧩 CAD 참고 — 이웃 부속 끼움 후보 {len(_cad_hints)}건 (판정 아님)", expanded=False):
                st.caption(CP.source_note() + " · 확정은 위 연결 검사와 대표 확인으로만 합니다.")
                for _h in _cad_hints:
                    st.caption("• " + _h)
        if any(link.get("requires_site_confirmation") for chain in pins.get("chains", []) for link in chain.get("links", [])):
            st.warning("불러온 판례의 수량·길이는 과거 현장 값입니다. 현재 현장에 맞게 수정하고 확인해 주세요. 단가는 다시 입력해야 합니다.")
            if st.button("현재 현장의 수량·길이·사용 맥락 확인", key="p3_chain_confirm_site"):
                for chain in pins["chains"]:
                    for link in chain.get("links", []):
                        link["requires_site_confirmation"] = False
                _save(pins)
        st.caption("기존 급수 계통 품목은 그대로 유지됩니다. 같은 물리 부품을 양쪽에 중복 입력하지 마세요.")
        if selected:
            st.caption("나사·호스 등 확인된 취급 조합은 양쪽 제품 코드·포트 ID가 있는 경우에만 재사용합니다.")
            confirmed_pair = st.text_area("확인된 접속 근거 JSON (선택)",
                                         json.dumps(chain.get("compatibility", []), ensure_ascii=False, indent=2), key=key + "_compat")
            st.caption('형식: [{"left": {포트 속성}, "right": {포트 속성}, "evidence": "대표 확인", "date": "2026-09-16", "scope": "해당 두 제품 접점"}]')
            if st.button("접속 근거 저장", key=key + "_compat_save"):
                try:
                    proof = json.loads(confirmed_pair)
                    if not isinstance(proof, list):
                        raise ValueError("근거는 목록이어야 합니다")
                    chain["compatibility"] = proof
                    C.validate_chains(chains)
                    pins["chains"] = chains
                    _save(pins)
                except (ValueError, TypeError) as exc:
                    st.error(str(exc))
        scope = st.text_input("판례 확인 범위·근거", value="미확정", key="p3_chain_scope")
        evidence = st.text_input("품목·포트 근거 버전", value="미확정", key="p3_chain_evidence")
        if pins.get("chains"):
            doc = {"schema_version": 1, "id": st.session_state.setdefault("p3_precedent_id", uuid.uuid4().hex),
                   "site": site_name, "created_at": datetime.now().isoformat(timespec="seconds"),
                   "evidence_version": evidence, "confirmation_scope": scope, "chains": pins["chains"]}
            try:
                st.download_button("연결 판례 JSON 내려받기", C.dumps_precedent(doc), file_name=f"연결사슬_{doc['id']}.json", mime="application/json")
            except ValueError as exc:
                st.warning("내보내기: " + str(exc))
        st.caption("내려받은 파일을 _설계/판례/연결사슬/{부위}/ 에 보관하세요. 서버 임시 파일은 영구 보관이 아닙니다.")
        uploaded = st.file_uploader("연결 판례 JSON 불러오기", type="json", key="p3_chain_upload")
        if st.button("선택 판례로 사슬 교체", disabled=uploaded is None):
            try:
                doc = C.loads_precedent(uploaded.getvalue().decode("utf-8-sig"))
                pins["chains"] = doc["chains"]
                _save(pins)
            except (ValueError, UnicodeError) as exc:
                st.error("판례를 불러오지 못했습니다: " + str(exc))


def render_supply(pins, preview):
    from .supply import design_capacity
    if st.session_state.pop("p3_supply_reload", False):
        for key in list(st.session_state):
            if key.startswith("p3_supply_"):
                st.session_state.pop(key, None)
    with st.expander("💧 펌프·관정 성능과 가동 가능 범위", expanded=True):
        old = pins.get("supply") or {}
        kinds = {"unknown": "정보 없음", "pump": "펌프", "well": "관정 + 펌프", "mains": "상수도·기타 급수"}
        kind = st.selectbox("급수원 종류", list(kinds), index=list(kinds).index(old.get("kind")) if old.get("kind") in kinds else 0, format_func=kinds.get, key="p3_supply_kind")
        supply = {"kind": kind}
        if kind != "unknown":
            modes = ["동시 유량·잔압", "성능곡선", "등록 펌프 곡선"]
            method = st.radio("확보한 성능 자료", modes, index=2 if old.get("model") else (1 if old.get("curve") else 0), horizontal=True, key="p3_supply_method")
            st.caption("최대유량과 최대양정은 동시 운전점이 아닙니다. 설치 상태에서 같은 운전점의 유량·잔압을 입력합니다.")
            if method == modes[0]:
                point = old.get("operating_point") or {}
                a, b = st.columns(2)
                q = a.number_input("동시 측정 유량 L/분", min_value=0.0, value=_number_or_none(point.get("flow_lpm")), key="p3_supply_q")
                p = b.number_input("그 유량에서 잔압 bar", min_value=0.0, value=_number_or_none(point.get("pressure_bar")), key="p3_supply_p")
                supply["operating_point"] = {"flow_lpm": q, "pressure_bar": p}
            elif method == modes[1]:
                frame = pd.DataFrame(old.get("curve") or [], columns=["flow_lpm", "head_m"])
                curve = st.data_editor(frame, num_rows="dynamic", hide_index=True, key="p3_supply_curve", column_config={"flow_lpm": st.column_config.NumberColumn("유량 L/분", min_value=0), "head_m": st.column_config.NumberColumn("가용 양정 m", min_value=0)})
                supply["curve"] = [[r["flow_lpm"], r["head_m"]] for r in _records(curve)]
            else:
                from .hydro_zone import PUMP_CURVES
                models = list(PUMP_CURVES)
                model = st.selectbox("확인된 펌프 모델", models, index=models.index(old["model"]) if old.get("model") in models else 0, key="p3_supply_model")
                cases = list(PUMP_CURVES[model])
                case = st.selectbox("펌프 곡선 측정 조건", cases, index=cases.index(old["case"]) if old.get("case") in cases else 0, key="p3_supply_case")
                supply.update(model=model, case=case, curve=[list(p) for p in PUMP_CURVES[model][case]])
                st.caption("등록 곡선은 표시된 측정 조건 기준입니다. 실제 동수위·흡상 및 출구 가용성능이 다르면 직접 성능자료를 입력하세요.")
            if kind == "well":
                supply["sustainable_flow_lpm"] = st.number_input("관정 지속 취수 가능 유량 L/분 (모르면 빈칸)", min_value=0.0, value=_number_or_none(old.get("sustainable_flow_lpm")), key="p3_supply_well")
            supply["conditions_confirmed"] = st.checkbox("현재 설치조건·동수위/흡상손실을 반영한 급수원 출구 성능이며 지형은 평탄 모델 적용 가능", value=bool(old.get("conditions_confirmed")), key="p3_supply_confirmed")
        if old != supply:
            pins["supply"] = supply
            invalidate()
        if not preview.get("n_heads"):
            st.info("밭을 그리면 입력한 성능으로 가동 가능 두수를 계산합니다. 정보 없이도 설계를 진행할 수 있습니다.")
            return
        if not pins.get("routes") or not pins.get("sources"):
            st.info("관 경로와 급수점을 입력하면 실제 관경·길이를 반영한 가동 수량을 표시합니다.")
            return
        try:
            from . import design, intake, mapedit
            drawn = copy.deepcopy(pins)
            drawn["blocks"] = mapedit.design_blocks(pins["blocks"])
            drawn["supply"] = supply
            live_site = intake.to_site(st.session_state.get("p3_answers") or {}, drawn)
            signature = hashlib.sha256(json.dumps(live_site, sort_keys=True, default=str).encode()).hexdigest()
            cached = st.session_state.get("p3_supply_live") or {}
            if cached.get("signature") != signature:
                answer = design(live_site)
                cached = {"signature": signature, "answer": answer, "capacity": design_capacity(answer, live_site)}
                st.session_state.p3_supply_live = cached
            render_supply_result(cached["answer"])
            check = cached["answer"].get("connections") or {}
            if check.get("hydraulic_missing") or (check and check.get("status") != "확인됨"):
                st.warning("사슬의 연결 또는 수리계산이 미확정이므로 가동 수량을 확정하지 않습니다.")
            else:
                for result in cached["capacity"].get("zones", []):
                    if result.get("heads_cap") is not None:
                        st.write("구역", result.get("zone"), "·", result.get("candidate_label", "동시 가동 후보"),
                                 ":", result["heads_cap"], "두 · 분할 구역 후보:", result.get("zones_min") or "추가 확인")
                    for note in result.get("errors", []) + result.get("notes", []):
                        st.caption(str(note))
            st.caption("지도의 실제 관경·인입관·구역 경로 기준입니다. 배치를 바꾸면 다시 계산합니다.")
        except (ValueError, TypeError, KeyError) as exc:
            st.warning("성능 입력 미확정: " + str(exc))


def render_row_kits(pins, preview):
    from . import heads
    with st.expander("🎯 열별 연결 세트 선택 (살수기종·운전조건 동일)"):
        rows = []
        for block in preview.get("blocks", []):
            for i, row in enumerate(block.get("row_details", [])):
                rid = heads.row_key(dict(row, block=block.get("name")))
                rows.append({"열 ID": rid, "밭": block.get("name"), "열": i + 1, "헤드 수": row.get("n_heads"),
                             "세트": (pins.get("row_kits") or {}).get(rid, pins.get("head_kit") or heads.DEFAULT)})
        if not rows:
            st.caption("밭을 그리면 열마다 연결 세트를 고를 수 있습니다."); return
        frame = st.data_editor(pd.DataFrame(rows), hide_index=True, disabled=["열 ID", "밭", "열", "헤드 수"],
                               column_config={"세트": st.column_config.SelectboxColumn(options=list(heads.KITS), required=True)}, key="p3_row_kit_editor")
        valid = {r["열 ID"] for r in rows}
        stale = set(pins.get("row_kits") or {}) - valid
        if stale:
            st.warning("배치 변경으로 연결되지 않는 열 세트가 있습니다. 새 배치의 선택을 확인하고 적용해 주세요.")
        if st.button("열별 세트 적용", key="p3_row_kits_apply"):
            pins["row_kits"] = {r["열 ID"]: r["세트"] for r in _records(frame)}
            _save(pins)


def render_tools(pins):
    with st.expander("🛠 현장 공구 (기본 포함 · 제외 이유 기록)"):
        rows = pins.get("tool_items")
        if rows is None:
            rows = [{"code": "01909", "qty": 1, "include": True, "reason": ""},
                    {"code": "20002", "qty": 1, "include": True, "reason": ""}]
            pins["tool_items"] = rows
        st.caption("H25 분기용 20 mm 펀치(01909), H20 살수용 15 mm 펀치(20002)를 기본 포함합니다. 보유·시공자 제공이면 포함을 해제하고 이유를 적으세요.")
        frame = pd.DataFrame(rows, columns=["code", "qty", "include", "reason"])
        edited = st.data_editor(frame, num_rows="dynamic", hide_index=True, key="p3_tools_editor", column_config={"include": st.column_config.CheckboxColumn("포함", default=True), "qty": st.column_config.NumberColumn("수량", min_value=1, default=1), "code": st.column_config.TextColumn("공구 품목코드"), "reason": st.column_config.TextColumn("제외 이유")})
        if st.button("공구 적용", key="p3_tools_apply"):
            values = [dict(r, include=r.get("include") is not False, qty=r.get("qty") or 1) for r in _records(edited) if r.get("code")]
            if any(not r["include"] and not r.get("reason") for r in values):
                st.error("공구를 제외하려면 고객 보유·시공자 제공 등의 이유를 적어 주세요.")
            else:
                pins["tool_items"] = values
                _save(pins)


def render_supply_result(result):
    report = result.get("supply") or {}
    if not report:
        return
    st.markdown("##### 💧 구역별 필요 유량·급수원 압력")
    labels = {"conditional": "입력 조건 내 후보", "insufficient": "입력 성능 부족", "unverified": "급수원 미확정"}
    rows = [{"구역": z.get("zone"), "필요 유량 L/분": z.get("required_flow_lpm"),
             "필요 압력 bar": z.get("required_pressure_bar"), "필요 양정 m": z.get("required_head_m"),
             "비교": labels.get(z.get("status"), z.get("status"))} for z in report.get("zones", [])]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    for note in report.get("notes", []) + report.get("errors", []):
        st.caption(str(note))
    for zone in report.get("zones", []):
        for note in zone.get("notes", []):
            st.caption(f"구역 {zone.get('zone', '')}: {note}")


def link_intent_update(links, table_rows, geo_site):
    """[V117 · K-03·K-08] 화면 표 → 저장할 site.link_intent (순수 함수 · 시험 대상).

    · 의도마다 **도장**(접점 좌표·관 모양 지문 — summary.intent_entry)을 함께 적는다. 관을 다시 그리면 도장이 달라져
      그 의도는 쓰이지 않는다(관문 차단 + 재확인).
    · 쌍은 목록(pair)으로 적는다 — 관 이름에 「↔」가 있어도 쪼개지지 않는다.
    · 지금 접점 목록에 없는 옛 키는 버린다(현재 링크에 없는 의도 정리).
    geo_site = 접점 목록을 만든 그 site(발행에 쓴 모양) — 도장은 그 모양에서 찍는다."""
    from .summary import LINK_INTENTS, intent_entry, link_key
    back = {v: k for k, v in LINK_INTENTS.items()}
    pairs = {link_key(x[0], x[1]): (x[0], x[1]) for x in links or []}
    new = {}
    for r in table_rows or []:
        k, v = r.get("접점"), back.get(r.get("의도"))
        if k in pairs and v:
            new[k] = intent_entry(geo_site, pairs[k][0], pairs[k][1], v)
    return new


def render_link_intent(pins, links, site=None):
    """[V116] 엔진이 연결로 계산하지 않은 관 접점마다 대표가 의도를 적는다(site.link_intent).

    좌표만으로는 「같은 길로 따로 깐 관」과 「실제로 잇는 자리」를 가를 수 없다. 값은 관문만 바꾼다 —
    잇는 자리의 T·수리는 여전히 엔진이 계산하지 못하므로 「잇는 자리」는 차단으로 남는다(선을 끊어 다시 그리기).
    [V117] 도장(접점 좌표·관 모양)과 함께 저장 — site = 접점 목록을 만든 발행 site(없으면 목록 pins).
    """
    from .summary import LINK_INTENTS, link_key, intent_status
    if not links:
        return
    geo = site or pins
    opts = ["미확인"] + list(LINK_INTENTS.values())
    with st.expander("🔗 관 접점 확인 — %d곳 (따로 깐 관인지, 잇는 자리인지)" % len(links), expanded=True):
        st.caption("엔진은 이 자리를 연결로 계산하지 않았습니다. 「따로 깐 관」이면 그대로 진행하고, "
                   "「잇는 자리」면 T·부속·수리가 빠져 있어 발송할 수 없습니다 — 그 자리에서 관을 끊어 다시 그려 주세요. "
                   "서로 다른 급수원의 관이 닿은 자리는 「따로 깐 관」을 고르기 전까지 차단됩니다. "
                   "고른 의도는 지금 관 모양에 묶입니다 — 관을 다시 그리면 다시 골라야 합니다.")
        rows = []
        cur_site = dict(geo, link_intent=pins.get("link_intent") or {})
        for x in links:
            k = link_key(x[0], x[1])
            it, stt = intent_status(cur_site, x[0], x[1])
            rows.append({"접점": k, "두 급수원": "예" if len(x) > 2 and x[2] else "",
                         "의도": LINK_INTENTS.get(it, "미확인") if stt == "ok" else "미확인",
                         "상태": {"stale": "관 모양 바뀜 — 다시 고르기", "legacy": "옛 형식 — 다시 고르기"}.get(stt, "")})
        frame = st.data_editor(pd.DataFrame(rows), hide_index=True, disabled=["접점", "두 급수원", "상태"],
                               column_config={"의도": st.column_config.SelectboxColumn(options=opts, required=True)},
                               key="p3_link_intent_editor")
        if st.button("접점 의도 적용", key="p3_link_intent_apply"):
            pins["link_intent"] = link_intent_update(links, _records(frame), geo)
            _save(pins)


def photo_dir_info():
    """[V117 · K-11] 현장 사진 저장 폴더와 그 성격 → {"dir", "persistent", "why"}.

    폴더 = publish.ROOT(프로젝트 폴더) 아래 `_제안/_현장사진` — 예전엔 dirname 을 4번 올라가 프로젝트 **밖**
    (…/AI/Agent/_제안)을 잡았다. 배포 서버(Streamlit Cloud `/mount/src/…`)는 쓰기가 되더라도 재시작하면 사라진다 —
    쓰기가 막히면 임시 폴더다. 둘 다 persistent=False 로 화면에 알린다."""
    import os
    import tempfile
    from .publish import ROOT
    d = os.path.join(ROOT, "_제안", "_현장사진")
    server = ROOT.replace("\\", "/").startswith("/mount/")
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, "_쓰기시험")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return {"dir": d, "persistent": not server,
                "why": "배포 서버 폴더 — 앱이 다시 시작되면 사진이 사라집니다" if server else ""}
    except Exception:
        d = os.path.join(tempfile.gettempdir(), "looperget_현장사진")
        os.makedirs(d, exist_ok=True)
        return {"dir": d, "persistent": False, "why": "저장소 폴더에 쓸 수 없어 임시 폴더에 둡니다 — 앱이 다시 시작되면 사라집니다"}


def photo_dir():
    """현장 사진 저장 폴더 — 로컬은 `_제안/_현장사진`(재열기 가능), 쓰기 막힌 서버는 임시 폴더."""
    return photo_dir_info()["dir"]


def render_photos(pins, site):
    """[V116] 당사 현장답사 사진 — 올리기 · 설명 · 지도 자리. 파일명만 적는 칸은 두지 않는다(실제 사진만)."""
    import os
    from . import photos as PH
    info = photo_dir_info()
    d = info["dir"]
    items = list(pins.get("photos") or [])
    with st.expander("📷 현장 사진 (당사 현장답사) — %d장" % len(items), expanded=bool(items)):
        st.caption("올린 사진이 제안서 「현장 사진」 면(대상지 개요 다음)에 그대로 들어갑니다. 한 면에 두 장. "
                   "지도 자리를 고르면 대상지 지도에 같은 번호가 찍힙니다. 빠진 사진을 다른 사진으로 채우지 않습니다.")
        if not info["persistent"]:                      # [V117 · K-11] 휘발 폴더면 그 사실을 화면에
            st.warning("📷 %s. 제안서를 만들면 사진 축소본이 job(_job.json)에 함께 실립니다 — job 을 내려받아 두세요. "
                       "(저장 폴더: `%s`)" % (info["why"], d))
        ups = st.file_uploader("사진 올리기 (JPG·PNG · 여러 장)", type=["jpg", "jpeg", "png"],
                               accept_multiple_files=True, key="p3_photo_up_%d" % st.session_state.get("p3_photo_epoch", 0))
        if ups and st.button("올린 사진 추가", key="p3_photo_add"):
            have = {x.get("file") for x in items}
            for u in ups:
                fn = PH.store(u.getvalue(), u.name, d)
                if fn not in have:
                    items.append({"file": fn, "caption": os.path.splitext(u.name)[0], "at": ""})
                    have.add(fn)
            pins["photos"] = items
            st.session_state.p3_photo_epoch = st.session_state.get("p3_photo_epoch", 0) + 1
            _save(pins)
        if not items:
            return
        opts = PH.anchors(site or {})
        rows = [{"번호": i + 1, "있음": "✅" if os.path.isfile(os.path.join(d, x.get("file", ""))) else "❌ 파일 없음",
                 "설명": x.get("caption", ""), "지도 자리": opts.get(x.get("at", ""), opts[""]), "빼기": False}
                for i, x in enumerate(items)]
        frame = st.data_editor(pd.DataFrame(rows), hide_index=True, disabled=["번호", "있음"],
                               column_config={"지도 자리": st.column_config.SelectboxColumn(options=list(opts.values()), required=True)},
                               key="p3_photo_editor")
        cols = st.columns(min(4, len(items)))
        for i, x in enumerate(items[:8]):
            p = os.path.join(d, x.get("file", ""))
            if os.path.isfile(p):
                cols[i % len(cols)].image(p, caption="%d. %s" % (i + 1, x.get("caption", "")), use_container_width=True)
        if any(r["있음"] != "✅" for r in rows):
            st.warning("파일이 없는 사진이 있습니다 — 다시 올리거나 「빼기」로 지워 주세요. 제안서에는 빠진 채로 확인 항목에 남습니다.")
        if st.button("사진 설명·자리 적용", key="p3_photo_apply"):
            back = {v: k for k, v in opts.items()}
            new = []
            for x, r in zip(items, _records(frame)):
                if not r.get("빼기"):
                    new.append({"file": x["file"], "caption": str(r.get("설명") or "").strip(),
                                "at": back.get(r.get("지도 자리"), "")})
            pins["photos"] = new
            _save(pins)


def contact_update(values):
    """[V117 · 2-C] 화면 칸 → 저장할 contact(순수 · 시험 대상). 빈칸은 빈 글자로 둔다(지어내지 않는다). 전부 비면 None."""
    from .customer import CONTACT_FIELDS
    out = {k: str((values or {}).get(k) or "").strip() for k, _lab in CONTACT_FIELDS}
    return out if any(out.values()) else None


def render_contact(pins):
    """[V117 · 2-C] 제안서 연락처·회신 기한 — 선택 입력(매번 수동 · 빈칸 허용 · 결정 #98 ②).
    고객 전달본 현장 요약 면에 한 줄로 들어간다(비면 손으로 적을 밑줄). 저장하면 작도 결과·site JSON 에 함께 남는다."""
    from .customer import CONTACT_FIELDS
    cur = dict(pins.get("contact") or {})
    with st.expander("📞 연락처·회신 기한 (선택 · 고객 전달본에 한 줄)", expanded=bool(cur)):
        cols = st.columns(len(CONTACT_FIELDS))
        vals = {k: cols[i].text_input(lab, value=str(cur.get(k) or ""), key="p3_ct_" + k)
                for i, (k, lab) in enumerate(CONTACT_FIELDS)}
        if st.button("연락처 저장", key="p3_ct_save"):
            new = contact_update(vals)
            if new:
                pins["contact"] = new
            else:
                pins.pop("contact", None)
            _save(pins)
