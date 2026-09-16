"""V110 chain/legacy ownership adapter. Pure; never writes production products."""
from copy import deepcopy
import math


def prepare(site):
    from .connections import validate_chains, chain_bom
    normalized = validate_chains(site.get("chains") or [], site.get("connection_compatibility") or [])
    chains = normalized["chains"]
    result = deepcopy(site)
    warnings = list(normalized.get("issues") or [])
    ids = {c["connection_id"] for c in chains}
    result["water_items"] = [w for w in result.get("water_items", []) if w.get("connection_id") not in ids]
    replaced = [c["replace_source"] for c in chains if c.get("replace_source")]
    known_sources = {s["name"] for s in result.get("sources", [])}
    if len(replaced) != len(set(replaced)) or set(replaced) - known_sources:
        raise ValueError("시작부 밴드 대체 급수점이 중복되거나 존재하지 않습니다")
    for source in result.get("sources", []):
        if source["name"] in replaced:
            source["start_bands"] = 0
    rows = chain_bom(chains)
    routes = {r["name"]: r for r in site.get("routes", [])}
    links = {(c["connection_id"], l["id"]): l for c in chains for l in c.get("links", [])}
    extra, hydraulic_missing, roll_groups = [], [], {}
    for row in rows:
        link = links[(row["connection_id"], row["link_id"])]
        if row.get("is_pipe"):
            segment = link.get("segment_id")
            if segment in routes:
                # One physical pipe: quantities/lengths/hydraulics remain owned by routes.
                from .geom import dist
                route = routes[segment]
                from .pipes import PIPES
                pipe = link["pipe"]
                registered = next((p for p in PIPES if p["code"] == row["code"]), None)
                expected = "hose%d" % registered["nominal_mm"] if registered else pipe.get("material")
                if expected != route.get("material", "hose50"):
                    raise ValueError("사슬 관과 지도 경로 재질·호칭이 다릅니다: " + segment)
                if not registered:
                    diameter = pipe.get("id_mm")
                    if diameter is None or route.get("d_mm") is None or abs(float(diameter) - float(route["d_mm"])) > .01:
                        raise ValueError("사슬 관과 지도 경로 내경 확인이 필요합니다: " + segment)
                length = sum(dist(a, b) for a, b in zip(route["pts"], route["pts"][1:]))
                if abs(float(link.get("len_m", 0)) - length) > 0.11:
                    raise ValueError("사슬 관 길이와 지도 경로 길이가 다릅니다: " + segment)
                continue
            hydraulic_missing.append(segment or link["id"])
            from .pipes import PIPES
            registered = next((p for p in PIPES if p["code"] == row["code"]), None)
            roll_m = (registered or {}).get("roll_m") or (link.get("pipe") or {}).get("roll_m")
            if roll_m:
                roll_m = float(roll_m)
                if not math.isfinite(roll_m) or roll_m <= 0:
                    raise ValueError("관의 롤 길이가 올바르지 않습니다")
                sale_unit = "롤" if registered else (link.get("pipe") or {}).get("unit", link.get("unit", "롤"))
                group = roll_groups.setdefault(row["code"], {"row": row, "length": 0, "roll_m": roll_m, "unit": sale_unit})
                if group["roll_m"] != roll_m or group["unit"] != sale_unit:
                    raise ValueError("같은 관 품목의 롤 길이가 다릅니다")
                if any(group["row"].get(k) != row.get(k) for k in ("price", "price_basis", "custom_name", "temporary")):
                    raise ValueError("같은 관 품목의 이름·단가·가격 기준이 다릅니다")
                group.setdefault("segments", []).append({"connection_id": row["connection_id"], "segment_id": segment,
                                                          "link_id": row["link_id"], "length_m": link["len_m"]})
                group["length"] += float(link["len_m"])
                continue
            declared_unit = (link.get("pipe") or {}).get("unit", link.get("unit", "m"))
            if declared_unit not in ("m", "M", "미터"):
                raise ValueError("관 판매단위가 m가 아니면 roll_m(판매단위당 길이)을 입력하세요")
            # Standalone pipes remain an explicit purchasing quantity. Never assume a roll size.
            if row.get("unit") == "m":
                row["qty"] = row["base"] = float(link.get("len_m", row["qty"]))
        extra.append(row)
    for group in roll_groups.values():
        from .bom import ROLL_SLACK
        length, roll_m, row = group["length"], group["roll_m"], group["row"]
        rolls = math.ceil(length / roll_m - 1e-9)
        reserve = int(rolls * roll_m - length <= ROLL_SLACK * roll_m)
        row.update(qty=rolls + reserve, base=rolls, unit=group["unit"],
                   note="연결 사슬 관 %.1f m → %d%s + 여분 %d (지도 경로와 별도 절단)" % (length, rolls, group["unit"], reserve))
        row["segments"] = group["segments"]
        extra.append(row)
    if chains and any(not w.get("connection_id") for w in result.get("water_items", [])):
        warnings.append("기존 급수 품목에 접점 ID가 없습니다 — 사슬과 중복인지 확인하세요(자동 삭제하지 않음)")
    if hydraulic_missing:
        warnings.append("사슬 관의 수리계산 미반영: " + ", ".join(hydraulic_missing))
    result["chains"] = chains
    return result, extra, {**normalized, "issues": warnings, "hydraulic_missing": hydraulic_missing}


def main_for_bom(main, site):
    """Explicit whole-route roll-joint replacement, never silently infer ownership."""
    result = deepcopy(main)
    replaced = [name for c in site.get("chains") or [] for name in c.get("replace_route_joints") or []]
    routes = {r["name"]: r for r in result["routes"]}
    if len(replaced) != len(set(replaced)) or set(replaced) - routes.keys():
        raise ValueError("롤 이음 대체 경로가 중복되거나 존재하지 않습니다")
    for name in replaced:
        count = int(routes[name].get("joints") or 0)
        result["joints"] -= count
        routes[name]["joints"] = 0
    # A chain carrying a route's roll-joining fittings must explicitly own those joints.
    joint_codes = {"00824", "00825", "00826", "00827", "00278", "01999"}
    for c in site.get("chains") or []:
        referenced = {l.get("segment_id") for l in c.get("links", [])} & routes.keys()
        if any(l.get("code") in joint_codes for l in c.get("links", [])):
            ambiguous = [name for name in referenced if main["routes"] and
                         next(r for r in main["routes"] if r["name"] == name).get("joints", 0) and name not in replaced]
            if ambiguous:
                raise ValueError("사슬과 기존 롤 이음의 담당이 겹칩니다. 경로 이음 대체 여부를 지정하세요: " + ", ".join(ambiguous))
    return result


def merge(base, extra, tools=()):
    """Keep component provenance even when purchase codes are consolidated."""
    rows = deepcopy(base)
    tool_map, excluded = {}, []
    for tool in tools:
        code = str(tool.get("code") or "").strip()
        qty = float(tool.get("qty", 1))
        if not code or not math.isfinite(qty) or qty <= 0 or not qty.is_integer():
            raise ValueError("공구 코드·수량을 확인하세요")
        if not tool.get("include", True):
            reason = str(tool.get("reason") or "").strip()
            if not reason:
                raise ValueError("공구 제외 이유를 입력하세요")
            excluded.append({"code": code, "reason": reason})
            continue
        tool_map[code] = max(int(qty), tool_map.get(code, 0))
    rows.extend(deepcopy(extra))
    # An explicit customer-owned/provider-supplied choice overrides duplicate defaults.
    for item in excluded:
        tool_map.pop(item["code"], None)
    for code, qty in tool_map.items():
        rows.append(dict(code=code, qty=qty, base=qty, note="현장 공구 — 기본 포함", source="tool"))
    merged = {}
    for row in rows:
        evidence = {k: row[k] for k in ("source", "part", "connection_id", "segment_id", "link_id", "qty", "note", "segments") if k in row}
        evidence.setdefault("source", "legacy")
        code = row["code"]
        if code not in merged:
            merged[code] = dict(row, provenance=[evidence])
        else:
            target = merged[code]
            if row.get("is_pipe") and not row.get("temporary") and row.get("unit") != "롤":
                raise ValueError("등록 관의 판매단위를 확인하세요: " + code)
            if row.get("temporary") or target.get("temporary"):
                if any(row.get(k) != target.get(k) for k in ("price", "unit", "custom_name")):
                    raise ValueError("같은 임시품목 코드의 가격·단위·이름이 다릅니다: " + code)
            target["qty"] += row["qty"]
            target["base"] += row.get("base", row["qty"])
            target["note"] += " · " + row.get("note", "")
            target["provenance"].append(evidence)
    return list(merged.values()), excluded


def required_tools(bom, selected):
    """S0 H25=20mm/H20=15mm; S1 01909=20mm, 20002=15mm punch.

    Applies only to V110 opt-in tool_items. Legacy jobs remain unchanged.
    Other fitting families require a confirmed mapping, never guessed tools.
    """
    codes = {r["code"] for r in bom if r.get("qty", 0) > 0}
    required = []
    if "01924" in codes:
        required.append("01909")
    if {"01920", "01998"} & codes:
        required.append("20002")
    explicit = {str(t.get("code")) for t in selected}
    return list(selected) + [dict(code=c, qty=1, include=True, reason="") for c in required if c not in explicit]
