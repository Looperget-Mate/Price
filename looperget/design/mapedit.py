# -*- coding: utf-8 -*-
"""지도 조작의 순수 계산과 Leaflet ↔ Streamlit 전달. 외부 저장소 접근 없음."""
from copy import deepcopy
import hashlib
import json
import math

from . import geom as G, mapsrc, site
from .layout import RowPolicy, rows_from_polygon

HANDLE = "looperget_lateral"


def map_policy(policy=None):
    """신규 현장 지도: 표시한 첫 여백을 주배관 교점부터 적용. 승인본 엔진 기본값은 유지."""
    out = {"S": 14.0, "lat_gap": 14.0, "std": 7.0, "maxm": 8.0}
    out.update(policy or {})
    out.update(off_fixed=float(out["std"]), start_ref="main")
    out["maxm"] = max(float(out["maxm"]), float(out["std"]) + 1.0)
    return out


def revision(blocks, routes):
    return hashlib.sha256(json.dumps([blocks, routes], sort_keys=True,
                                    ensure_ascii=False).encode("utf-8")).hexdigest()[:20]


def design_blocks(blocks):
    """설계 전달 시 간격·수동 열·두둑을 빠뜨리지 않고 독립된 복사본으로 넘긴다."""
    keys = ("name", "polygon", "u", "policy", "bars", "crop")
    return [deepcopy({k: b[k] for k in keys if k in b}) for b in blocks]


def handles(preview, origin, rev):
    out = []
    for block in preview.get("blocks", []):
        for i, row in enumerate(block.get("row_details", [])):
            xy = [(a + b) / 2 for a, b in zip(row["p0"], row["p1"])]
            lon, lat = mapsrc.from_local_m([xy], origin)[0]
            out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {"kind": HANDLE, "revision": rev,
                                       "block_index": block["block_index"], "row_index": i,
                                       "xy": xy}})
    return out


def move_rows(blocks, routes, preview, features, origin, rev):
    """옮긴 손잡이를 고랑 직각 방향으로 투영. 성공 시 복사본, 실패/무변경 시 None + 안내."""
    out = deepcopy(blocks)
    changes = {}
    details = {b["block_index"]: b.get("row_details", []) for b in preview.get("blocks", [])
               if "block_index" in b}
    try:
        for feature in features:
            prop = feature.get("properties") or {}
            if prop.get("kind") != HANDLE or prop.get("revision") != rev:
                continue
            bi, ri = int(prop["block_index"]), int(prop["row_index"])
            rows = details[bi]
            row = rows[ri]
            old_xy = [(a + b) / 2 for a, b in zip(row["p0"], row["p1"])]
            xy = mapsrc.to_local_m([feature["geometry"]["coordinates"]], origin)[0]
            n = G.perp(G.unit(tuple(out[bi].get("u") or (1, 0))))
            delta = G.dot(G.sub(xy, old_xy), n)
            if not math.isfinite(delta):
                raise ValueError("올바르지 않은 지도 좌표입니다")
            if abs(delta) < 0.2:
                continue
            specs = changes.setdefault(bi, [{"a": r["a"], "deg": r["deg"]} for r in rows])
            specs[ri]["a"] = row["a"] + delta
        mains = [r["pts"] for r in routes if site.route_role(r) == "main"]
        for bi, specs in changes.items():
            block = out[bi]
            policy = map_policy(block.get("policy"))
            policy["manual_rows"] = specs
            rows = rows_from_polygon(block["polygon"], tuple(block.get("u") or (1, 0)),
                                     RowPolicy(**policy), bars=block.get("bars"), mains=mains)
            moved = {i for i, spec in enumerate(specs) if abs(spec["a"] - details[bi][i]["a"]) >= 0.2}
            for i in moved:
                if any(i != j and G.seg_seg_dist(rows[i].p0, rows[i].p1, r.p0, r.p1)
                       < policy.get("min_sep", 6.0) - 0.1 for j, r in enumerate(rows)):
                    raise ValueError("이웃 가지관에 너무 가깝거나 교차합니다. 간격을 더 벌려 주세요.")
            block["policy"] = policy
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return None, str(exc)
    return (out, "") if changes else (None, "")


def merge_routes(existing, features, origin, default_role="main"):
    """재반영해도 사용자가 정한 역할·관경·구역을 보존. 신규 선만 추가한다."""
    out = deepcopy(existing)
    for f in features:
        pts = mapsrc.to_local_m(f["geometry"]["coordinates"], origin)
        prop = f.get("properties") or {}
        draw_id = prop.get("draw_id")
        match = next((r for r in out if (draw_id and r.get("draw_id") == draw_id)
                      or (len(r.get("pts", [])) == len(pts)
                          and all(math.dist(a, b) < 0.15 for a, b in zip(r["pts"], pts)))), None)
        if match is not None:
            match["pts"] = pts
            if draw_id:
                match["draw_id"] = draw_id
            continue
        role = prop.get("role", default_role)
        role = "feeder" if role == "feeder" else "main"
        num = 1
        ids = {r.get("id") for r in out}
        while "R%d" % num in ids:
            num += 1
        zone = max([int(r.get("zone") or 0) for r in out] or [0]) + 1
        out.append({"id": "R%d" % num, "name": "R%d" % num, "role": role,
                    "zone": None if role == "feeder" else zone,
                    "material": "hose50" if role == "feeder" else None, "d_mm": None,
                    "pts": pts, "by_ceo": True, "draw_id": draw_id})
    return out


def draw_bridge(draw, handle_features, role="main", drafts=None):
    """일반 마커 드래그를 draw:edited 이벤트로 전달; 손잡이는 급수원과 구별한다."""
    from branca.element import MacroElement, Template
    bridge = MacroElement()
    bridge.draw = draw
    payload = json.dumps({"handles": handle_features, "role": role, "drafts": drafts or []},
                         ensure_ascii=False).replace("<", "\\u003c")
    bridge._template = Template(r"""
{% macro script(this, kwargs) %}
(function(){
 const map = {{this._parent.get_name()}}, group = drawnItems_{{this.draw.get_name()}};
 const data = __PAYLOAD__;
 data.drafts.forEach(function(f){
   L.geoJSON(f, {style: function(x){return {color: x.geometry.type==='Polygon'?'#ffd600':
     ((x.properties||{}).role==='feeder'?'#ffa040':'#ff4b4b'), weight:4};}})
    .eachLayer(function(layer){group.addLayer(layer);});
 });
 map.on('draw:created', function(e){
   e.layer.feature = e.layer.feature || {type:'Feature', properties:{}};
   const p = e.layer.feature.properties;
   p.draw_id = p.draw_id || String(Date.now())+'-'+String(Math.random()).slice(2);
   if(e.layerType==='polyline'){
     p.role=data.role;
     e.layer.setStyle({color:data.role==='feeder'?'#ffa040':'#ff4b4b',
                       dashArray:data.role==='feeder'?'12,8':null});
   }
 });
 data.handles.forEach(function(f){
   const xy=f.geometry.coordinates;
   const marker=L.marker([xy[1],xy[0]], {draggable:true,
     icon:L.divIcon({className:'p3-row-handle',iconSize:[26,26],iconAnchor:[13,13],
       html:'<div style="background:#063e35;color:white;border:2px solid #a7ffdd;border-radius:50%;text-align:center;line-height:22px;font-size:18px;cursor:grab">↔</div>'})});
   marker.feature=f;
   marker.bindTooltip('가지관 '+(f.properties.row_index+1)+' — 잡고 옆으로 이동');
   marker.on('dragend', function(){map.fire('draw:edited',{layer:marker,layers:L.featureGroup([marker])});});
   marker.addTo(map);  // 점 편집/지우기의 대상은 사용자가 그린 도형만
 });
})();
{% endmacro %}
""".replace("__PAYLOAD__", payload))
    return bridge
