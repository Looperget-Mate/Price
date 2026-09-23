"""Connection chains v1: pure validation, quantity extraction and JSON interchange.

No product specifications are inferred from item names/codes. Coupler mating rule:
_세트재생성/S1_연결부_사양축_v1.json; nominal aliases and evidence boundaries:
10_프로매니저/사양_배관연결_세분화_v1.md. Quantities here are physical quantities;
the BOM owner applies existing packaging/spare rules exactly once.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import math
import re

CONFIRMED = "확인됨"
MISMATCH = "불일치"
UNKNOWN = "미확정"
NOMINAL_INCHES = {25: "1", 40: "1½", 50: "2"}
PARTS = {"A", "B", "C", "D", "E", "F"}


def _number(value, name, *, positive=False):
    if isinstance(value, bool):
        raise ValueError(f"{name}: 숫자가 필요합니다")
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name}: 숫자가 필요합니다") from None
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"{name}: 유한한 {'양수' if positive else '0 이상 수'}가 필요합니다")
    return number


def normalize_port(port):
    """Return a copy; mm are nominal aliases, never measured inch conversions."""
    if not isinstance(port, dict):
        raise ValueError("포트는 객체여야 합니다")
    result = deepcopy(port)
    kind = str(port.get("kind") or "").strip().lower()
    kind = {"카플러": "coupler", "나사": "thread", "호스": "hose"}.get(kind, kind)
    result["kind"] = kind
    sex = str(port.get("sex") or "").strip()
    aliases = ({"암": "C", "수": "E", "F": "C", "M": "E"} if kind == "coupler"
               else {"암": "F", "수": "M", "female": "F", "male": "M"})
    result["sex"] = aliases.get(sex, sex)
    mm = port.get("d_mm", port.get("size_mm"))
    if mm not in (None, ""):
        mm = _number(str(mm).lower().replace("mm", "").strip(), "호칭", positive=True)
        result["d_mm"] = int(mm) if mm.is_integer() else mm
    else:
        result["d_mm"] = None
    inch = str(port.get("size_in") or "").strip().lower()
    for token in ('"', '″', 'inches', 'inch', 'in'):
        inch = inch.replace(token, "")
    inch = inch.replace(" ", "")
    inch = {"1.0": "1", "1.5": "1½", "11/2": "1½", "2.0": "2"}.get(inch, inch)
    inverse = {v: k for k, v in NOMINAL_INCHES.items()}
    result.pop("nominal_conflict", None)
    if inch in inverse:
        if result["d_mm"] is not None and result["d_mm"] != inverse[inch]:
            result["nominal_conflict"] = True
        elif result["d_mm"] is None:
            result["d_mm"] = inverse[inch]
    result["size_in"] = inch or NOMINAL_INCHES.get(result["d_mm"], "")
    return result


def _result(status, issues=()):
    return {"status": status, "ok": status == CONFIRMED, "issues": list(issues)}


def _identity(port):
    p = normalize_port(port)
    return tuple(p.get(k) for k in ("kind", "sex", "grade", "d_mm", "size_in", "standard", "code", "port_id"))


def _evidence_matches(left, right, compatibility):
    for item in compatibility:
        if not isinstance(item, dict) or not all(item.get(k) for k in ("evidence", "date", "scope")):
            continue
        try:
            date.fromisoformat(str(item["date"]))
        except ValueError:
            continue
        # Evidence must identify the actual products/ports, not a generic nominal size.
        if not all(p.get("code") and p.get("port_id") for p in (left, right)):
            continue
        a, b = item.get("left", {}), item.get("right", {})
        if (_identity(left), _identity(right)) in ((_identity(a), _identity(b)), (_identity(b), _identity(a))):
            return True
    return False


def check_ports(left, right, compatibility=()):
    """Check mating ports. Confirmed thread pairs require scoped dated evidence."""
    a, b = normalize_port(left), normalize_port(right)
    if a.get("nominal_conflict") or b.get("nominal_conflict"):
        return _result(MISMATCH, ["mm 호칭과 인치 표기가 다릅니다"])
    if not a["kind"] or not b["kind"]:
        return _result(UNKNOWN, ["접속 종류 미확정"])
    if a["kind"] != b["kind"]:
        return _result(MISMATCH, ["접속 종류 불일치 — 양쪽 포트가 맞는 부속 필요"])
    if a["kind"] == "coupler":
        if a["sex"] not in ("C", "E") or b["sex"] not in ("C", "E") or not a.get("grade") or not b.get("grade"):
            return _result(UNKNOWN, ["카플러 성 또는 등급 미확정"])
        if a["sex"] == b["sex"]:
            return _result(MISMATCH, ["같은 성의 카플러는 연결할 수 없습니다"])
        if a["grade"] != b["grade"]:
            return _result(MISMATCH, ["카플러 등급 불일치 — 이경 부속 양쪽 포트를 확인하세요"])
        if a["grade"] not in ("大", "中", "小"):
            return _result(UNKNOWN, ["카플러 등급 근거 미확정"])
        return _result(CONFIRMED)
    if a["kind"] == "thread":
        if a["sex"] not in ("F", "M") or b["sex"] not in ("F", "M"):
            return _result(UNKNOWN, ["나사 암수 미확정"])
        if a["sex"] == b["sex"]:
            return _result(MISMATCH, ["같은 암수의 나사는 연결할 수 없습니다"])
        if a["d_mm"] is None or b["d_mm"] is None:
            return _result(UNKNOWN, ["나사 호칭 미확정"])
        if a["d_mm"] != b["d_mm"]:
            return _result(MISMATCH, ["나사 호칭 불일치"])
        if a.get("standard") and b.get("standard") and a["standard"] != b["standard"]:
            return _result(MISMATCH, ["나사 규격 불일치"])
        if _evidence_matches(a, b, compatibility):
            return _result(CONFIRMED)
        return _result(UNKNOWN, ["나사 취급 조합의 확인 범위·근거·일자 미확정"])
    if a["d_mm"] is not None and b["d_mm"] is not None and a["d_mm"] != b["d_mm"]:
        return _result(MISMATCH, ["접속 관경 불일치"])
    if _evidence_matches(a, b, compatibility):
        return _result(CONFIRMED)
    return _result(UNKNOWN, ["접속 방법 및 제품 근거 미확정"])


def _unique(value, seen, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: 안정된 ID가 필요합니다")
    if value in seen:
        raise ValueError(f"중복 {name}: {value}")
    seen.add(value)


def validate_chains(chains, compatibility=()):
    """Normalize and recheck chains; stale saved check/actual_end are never trusted.

    A chain owns one connection_id. Link IDs are unique within each chain; segment
    IDs are unique across chains. An end.port is a declaration of the actual end,
    not an extra mating component. Unused T ports require explicit mate evidence.
    """
    if not isinstance(chains, list):
        raise ValueError("chains는 배열이어야 합니다")
    normalized = deepcopy(chains)
    compatibility = list(compatibility) + [item for chain in normalized if isinstance(chain, dict)
                                           for item in chain.get("compatibility", [])]
    chain_ids, connection_ids, segments = set(), set(), set()
    all_issues, statuses = [], []
    for chain in normalized:
        if not isinstance(chain, dict):
            raise ValueError("사슬은 객체여야 합니다")
        _unique(chain.get("id"), chain_ids, "chain.id")
        _unique(chain.get("connection_id"), connection_ids, "connection_id")
        if chain.get("part") not in PARTS:
            raise ValueError("부위는 A~F여야 합니다")
        links = chain.get("links", [])
        if not isinstance(links, list):
            raise ValueError("links는 배열이어야 합니다")
        start = chain.get("start") or {}
        current = normalize_port(start.get("port") or {})
        chain["start"] = {**start, "port": current}
        checks, link_ids = [], set()
        if not links:
            checks.append(_result(UNKNOWN, ["사슬 부속이 없습니다"]))
        for link in links:
            if not isinstance(link, dict):
                raise ValueError("링크는 객체여야 합니다")
            _unique(link.get("id"), link_ids, "link.id")
            _number(link.get("qty", 1), "수량", positive=True)
            if link.get("segment_id") is not None:
                _unique(link["segment_id"], segments, "segment_id")
            if "pipe" in link:
                if not isinstance(link["pipe"], dict):
                    raise ValueError("pipe는 객체여야 합니다")
                _number(link.get("len_m"), "관 길이", positive=True)
                if not link.get("segment_id"):
                    raise ValueError("관 링크 segment_id가 필요합니다")
            raw_ports = link.get("ports") or {}
            if not isinstance(raw_ports, dict):
                raise ValueError("ports는 포트 ID별 객체여야 합니다")
            ports = {key: normalize_port({**value, "code": link.get("code") or (link.get("pipe") or {}).get("code"), "port_id": key}) for key, value in raw_ports.items()}
            link["ports"] = ports
            incoming, outgoing = link.get("in_port"), link.get("out_port")
            k0 = len(checks)                     # [V117 · K-06] 이 링크 몫의 판정(앞 이음·가지·T) — 도해가 링크별로 그린다
            if not incoming or not outgoing or incoming == outgoing or incoming not in ports or outgoing not in ports:
                checks.append(_result(UNKNOWN, [f"{link['id']}: 입구/출구 포트 ID 또는 근거 미확정"]))
                link["check"] = checks[-1]
                current = {}
                continue
            checks.append(check_ports(current, ports[incoming], compatibility))
            branches = link.get("branches") or {}
            for key in ports.keys() - {incoming, outgoing}:
                branch = branches.get(key) or {}
                if branch.get("state") not in ("connected", "capped"):
                    checks.append(_result(MISMATCH, [f"{link['id']}/{key}: 가지 포트 미연결·미마감"]))
                elif not branch.get("port"):
                    checks.append(_result(UNKNOWN, [f"{link['id']}/{key}: 가지 연결/마감 상대 포트 미확정"]))
                else:
                    checks.append(check_ports(ports[key], branch["port"], compatibility))
            if link.get("shape") in ("T", "tee") and len(ports) < 3:
                checks.append(_result(UNKNOWN, [f"{link['id']}: T 가지 포트 누락"]))
            mine = checks[k0:]
            link["check"] = _result(MISMATCH if any(c["status"] == MISMATCH for c in mine) else
                                    UNKNOWN if any(c["status"] == UNKNOWN for c in mine) else CONFIRMED,
                                    [i for c in mine for i in c["issues"]])
            current = ports[outgoing]
        chain["actual_end"] = deepcopy(current)
        declared = (chain.get("end") or {}).get("port")
        if declared:
            target = normalize_port(declared)
            for key in ("kind", "sex", "grade", "d_mm", "standard"):
                if target.get(key) not in (None, "") and target.get(key) != current.get(key):
                    checks.append(_result(MISMATCH, ["선언한 종단과 실제 마지막 링크 출력 포트가 다릅니다"]))
                    break
        if chain["part"] == "F" and current.get("kind") != "sprinkler":
            checks.append(_result(UNKNOWN, ["살수 세트의 실제 살수기 종단 미확정"]))
        status = MISMATCH if any(c["status"] == MISMATCH for c in checks) else UNKNOWN if any(c["status"] == UNKNOWN for c in checks) else CONFIRMED
        issues = [issue for check in checks for issue in check["issues"]]
        chain["check"] = _result(status, issues)
        chain["hydraulic_status"] = UNKNOWN
        statuses.append(status)
        all_issues.extend(f"{chain['id']}: {issue}" for issue in issues)
    status = MISMATCH if MISMATCH in statuses else UNKNOWN if UNKNOWN in statuses else CONFIRMED
    return {**_result(status, all_issues), "chains": normalized, "hydraulic_status": UNKNOWN}


def chain_bom(chains):
    """Extract physical quantities, retaining distinct physical locations.

    No implicit reducer, seal, spare, packaging or price is invented. Explicit
    consumables are separate rows with their declared sale unit. Price None means
    unknown (0 is a valid explicit price). This function does not access a catalog.
    """
    checked = validate_chains(chains)
    rows = []
    for chain in checked["chains"]:
        for link in chain.get("links", []):
            pipe = link.get("pipe")
            item = {**link, **(pipe or {})}
            qty = float(link["len_m"]) if pipe is not None else _number(link.get("qty", 1), "수량", positive=True)
            entries = [(item, qty, "m" if pipe is not None else item.get("unit", "개"))]
            for extra in link.get("consumables", []):
                if not extra.get("unit"):
                    raise ValueError("소모품 판매 단위가 필요합니다")
                entries.append((extra, _number(extra.get("qty"), "소모품 수량", positive=True), extra["unit"]))
            for entry, count, unit in entries:
                price = entry.get("price")
                if price is not None:
                    price = _number(price, "가격")
                    if not entry.get("price_basis") or not entry.get("unit", unit):
                        raise ValueError("대표 입력 가격에는 단위와 가격 기준이 필요합니다")
                code = str(entry.get("code") or "")
                temporary = bool(entry.get("temporary")) or not code
                label = entry.get("label") or entry.get("custom_name") or code
                if temporary and not label:
                    raise ValueError("임시 품목 이름이 필요합니다")
                if temporary and (not entry.get("material") or not entry.get("nominal_mm", entry.get("d_mm"))):
                    raise ValueError("임시 품목 재질과 호칭 규격이 필요합니다")
                if not code:
                    code = f"TEMP-{chain['id']}-{link['id']}"
                rows.append({"code": code, "qty": count, "base": count, "unit": unit,
                             "label": label, "custom_name": label, "price": price,
                             "material": entry.get("material"),
                             "nominal_mm": entry.get("nominal_mm", entry.get("d_mm")),
                             "price_basis": entry.get("price_basis"), "temporary": temporary,
                             "note": "대표 입력 · 임시 품목" if temporary else "연결 사슬",
                             "source": "chain", "part": chain["part"], "chain_id": chain["id"],
                             "connection_id": chain["connection_id"], "segment_id": link.get("segment_id"),
                             "link_id": link["id"], "is_pipe": pipe is not None and entry is item})
    return rows


def _precedent(document):
    if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document.get("schema_version") != 1:
        raise ValueError("지원하는 판례 schema_version은 1입니다")
    for key in ("id", "site", "created_at", "evidence_version", "confirmation_scope"):
        if not document.get(key):
            raise ValueError(f"판례 {key}가 필요합니다")
    try:
        date.fromisoformat(str(document["created_at"])[:10])
    except ValueError:
        raise ValueError("판례 작성일은 ISO 날짜여야 합니다") from None
    result = deepcopy(document)
    result.pop("check", None)
    result["chains"] = validate_chains(result.get("chains"))["chains"]
    result["reuse_requires_recalculation"] = True
    return result


def dumps_precedent(document):
    """Validate and export JSON; no server-local persistence claim is made."""
    return json.dumps(_precedent(document), ensure_ascii=False, indent=2, allow_nan=False)


def loads_precedent(text):
    """Load a candidate; remove historical price authority and recompute checks.

    Quantities/lengths remain editable candidate inputs, not calculated BOM output.
    The importing UI must obtain current-site acceptance before applying them.
    """
    try:
        document = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"잘못된 JSON 숫자: {value}")))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"판례 JSON 오류: {exc}") from None
    result = _precedent(document)
    for chain in result["chains"]:
        for link in chain.get("links", []):
            entries = [link, *link.get("consumables", [])]
            if isinstance(link.get("pipe"), dict):
                entries.append(link["pipe"])
            for entry in entries:
                if entry.get("price") is not None:
                    entry["historical_price"] = entry["price"]
                    entry["historical_price_basis"] = entry.get("price_basis")
                    entry["price"] = None
            link["requires_site_confirmation"] = True
    return result


def precedent_filename(document):
    """Relative recommended path; caller chooses local storage or JSON download."""
    item = _precedent(document)
    def safe(value):
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .") or "unnamed"
    parts = {chain["part"] for chain in item["chains"]}
    part = next(iter(parts)) if len(parts) == 1 else "복합"
    return f"_설계/판례/연결사슬/{part}/{safe(item['created_at'][:10])}_{safe(item['site'])}_{safe(item['id'])}.json"
