# -*- coding: utf-8 -*-
"""
looperget.design.qr — 부속 설치 영상 QR (segno · 가드 임포트).

링크 정본은 **`Looperget_DB` AQ_Items 시트의 `QR링크` 열**이다(제품 사용법 쇼츠).
설계 파이프라인은 오프라인으로 돌기 때문에 `_단가_DB.json`의 `qr` 필드를 **파생본**으로 읽는다 —
`img`(드라이브 파일 id)와 같은 취급이다. 갱신은 `tools/qr_sync.py`.

    links(price_db)              → {code: url}  (빈 값·공백 제거)
    png(url, cache_dir)          → QR PNG 경로 (없거나 segno 미설치면 None)

인쇄 최소 크기 = **15 mm**(인쇄 정본 §5-1). PDF에서는 그림에 하이퍼링크를 걸어 눌러서도 열리게 한다.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Dict, Optional

QR_MIN_MM = 15.0                      # 인쇄 정본 §5-1 — 이보다 작게 놓지 않는다
QR_MIN_IN = QR_MIN_MM / 25.4


def links(price_db: Optional[Dict]) -> Dict[str, str]:
    """단가 파생본 → {품목코드: 영상 URL}. `qr`가 비었거나 없는 품목은 빠진다."""
    out: Dict[str, str] = {}
    for code, v in (price_db or {}).items():
        u = str((v or {}).get("qr") or "").strip()
        if u.startswith("http"):
            out[str(code).zfill(5)] = u
    return out


def png(url: str, cache_dir: str, px: int = 600) -> Optional[str]:
    """URL → QR PNG(정사각·여백 2모듈). 실패하면 None — 호출자가 자리를 비운다."""
    if not url:
        return None
    try:
        import segno
    except Exception:
        return None
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    p = os.path.join(cache_dir, "qr_%s.png" % key)
    if os.path.exists(p):
        return p
    try:
        q = segno.make(url, error="m")
        q.save(p, scale=max(1, px // (q.symbol_size(1)[0] or 25)), border=2)
    except Exception:
        return None
    return p if os.path.exists(p) else None


def short_label(url: str) -> str:
    """캡션용 짧은 표기 — `youtube.com/shorts/<id>`."""
    m = re.search(r"shorts/([A-Za-z0-9_-]+)", url or "")
    return "youtube.com/shorts/" + m.group(1) if m else (url or "")


__all__ = ["links", "png", "short_label", "QR_MIN_MM", "QR_MIN_IN"]
