# -*- coding: utf-8 -*-
"""
looperget.design.photos — 현장 사진(당사 현장답사) 입력 · 저장 · 재열기 · 지면 배치 (V116).

Codex 인계 20260922 「원본 파일명 대신 실제 사진」:
  · JPG **파일명 목록**을 사진 면으로 취급하지 않는다 — 실제 이미지 파일이 있어야 면이 생긴다.
  · 사진이 없거나 못 열면 **다른 현장 사진으로 채우지 않는다** — 빠진 것은 편집 화면에 드러낸다.
  · 특정 면 번호를 고정하지 않는다 — 렌더러가 「대상지 개요」 뒤에 끼운다.

입력(pins·site) = `photos: [{"file": 저장 이름, "caption": str, "at": ""|"source:0"|"block:이름"}]`
  · file 은 내용 해시 이름(sha256 앞 16자 + 확장자)이라 세션이 바뀌어도 같은 사진은 같은 이름이다.
  · at 은 지도 위 자리 — 급수원 번호·밭 이름. 좌표를 사람이 적지 않는다(엔진이 그린 자리에서 찾는다).
출력(job.meta) = `photos: [{"path", "caption", "pt": [x,y]|None, "n", "b64"?}]` + `photo_missing: [문구]`.
  · [V117] n = 화면 순번(빠진 사진이 있어도 당기지 않는다 · K-09) · b64 = job 에 실은 축소본(서버 job → 작업 PC · K-01).
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Dict, List, Optional, Tuple

EXT = (".jpg", ".jpeg", ".png")
PER_PAGE = 2                                          # 한 면에 두 장 — 캡션을 읽을 수 있는 크기


def store(data: bytes, name: str, photo_dir: str) -> str:
    """올린 사진을 내용 해시 이름으로 저장 → 저장 이름. 같은 사진을 두 번 올려도 한 파일이다."""
    ext = os.path.splitext(str(name))[1].lower()
    if ext not in EXT:
        raise ValueError("사진은 JPG·PNG만 받습니다: %s" % name)
    fn = hashlib.sha256(data).hexdigest()[:16] + (".jpg" if ext == ".jpeg" else ext)
    os.makedirs(photo_dir, exist_ok=True)
    path = os.path.join(photo_dir, fn)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return fn


def anchors(site: Dict) -> Dict[str, str]:
    """지도 자리 보기 → {값: 화면 이름}. 급수원 번호 · 밭 이름(엔진이 그린 자리)."""
    out = {"": "지도 표시 없음"}
    for i, s in enumerate(site.get("sources") or []):
        out["source:%d" % i] = "급수원 %d — %s" % (i + 1, s.get("name") or "")
    for b in site.get("blocks") or []:
        if b.get("name"):
            out["block:%s" % b["name"]] = "밭 — %s" % b["name"]
    return out


def anchor_pt(site: Dict, at: str) -> Optional[Tuple[float, float]]:
    """자리 → 지도 좌표(site 좌표계 그대로 · publish 가 뒤집은 site 를 넘기면 뒤집힌 좌표)."""
    at = str(at or "")
    m = re.fullmatch(r"source:(\d+)", at)
    if m:
        src = site.get("sources") or []
        k = int(m.group(1))
        return tuple(src[k]["pt"]) if k < len(src) else None
    if at.startswith("block:"):
        for b in site.get("blocks") or []:
            if b.get("name") == at[6:] and b.get("polygon"):
                P = b["polygon"]
                return (sum(p[0] for p in P) / len(P), sum(p[1] for p in P) / len(P))
    return None


def resolve(items: Optional[List[Dict]], photo_dir: Optional[str], site: Dict) -> Tuple[List[Dict], List[str]]:
    """pins.photos → (지면에 넣을 사진, 빠진 사진 문구). 파일을 실제로 열어 본다 — 이름만 있는 것은 사진이 아니다."""
    from PIL import Image
    ok, missing = [], []
    for i, it in enumerate(items or []):
        cap = str(it.get("caption") or "").strip()
        fn = str(it.get("file") or "")
        path = os.path.join(photo_dir, fn) if (photo_dir and fn) else ""
        why = ""
        if not path or not os.path.isfile(path):
            why = "파일 없음"
        else:
            try:
                with Image.open(path) as im:
                    im.verify()
            except Exception:
                why = "이미지로 열 수 없음"
        if why:
            missing.append("사진 %d(%s) — %s. 다시 올려 주세요(다른 사진으로 채우지 않습니다)" % (i + 1, cap or fn or "이름 없음", why))
            continue
        pt = anchor_pt(site, it.get("at"))
        # [V117 · K-09] 번호 = 화면 순번 그대로(i+1). 앞 사진이 빠져도 당기지 않는다 — 편집 화면·확인 항목과 같은 번호.
        ok.append({"path": path, "caption": cap, "pt": list(pt) if pt else None, "n": i + 1})
    return ok, missing


def embed(items: List[Dict], max_px: int = 1200, quality: int = 85) -> int:
    """[V117 · K-01] 지면에 넣을 사진을 **job 안에 싣는다**(축소본 base64 · 위성 그림 png_b64 와 같은 방식).
    서버에서 만든 job 을 작업 PC 에서 발행하면 서버 경로의 파일이 없다 — 그때 localize 가 이것을 푼다. → 실은 장 수."""
    import base64
    import io
    from PIL import Image, ImageOps
    n = 0
    for it in items or []:
        p = it.get("path")
        if it.get("b64") or not p or not os.path.isfile(p):
            continue
        try:
            with Image.open(p) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((max_px, max_px), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=quality)
            it["b64"] = base64.b64encode(buf.getvalue()).decode("ascii")
            n += 1
        except Exception:
            continue
    return n


def localize(items: Optional[List[Dict]], work_dir: str) -> Tuple[List[Dict], List[str]]:
    """[V117 · K-01] job 의 사진 → 이 PC 에서 열리는 사진만 (지면용, 누락 문구). **발행 전에** 부른다(관문에 들어가게).

    경로의 파일이 열리면 그대로 · 없으면 job 에 실린 축소본(b64)을 work_dir 에 풀어 쓴다 · 둘 다 없으면 누락(대체 없음)."""
    import base64
    from PIL import Image
    ok, missing = [], []
    for k, it in enumerate(items or []):
        it = dict(it)
        n = it.get("n") or (k + 1)
        p = it.get("path") or ""
        why = ""
        if not (p and os.path.isfile(p)):
            if it.get("b64"):
                os.makedirs(work_dir, exist_ok=True)
                p = os.path.join(work_dir, "_job사진_%02d.jpg" % int(n))
                with open(p, "wb") as f:
                    f.write(base64.b64decode(it["b64"]))
                it["path"] = p
            else:
                why = "이 PC 에 파일 없음(서버 경로 · job 에 사진이 실려 있지 않음)"
        if not why:
            try:
                with Image.open(p) as im:
                    im.verify()
            except Exception:
                why = "이미지로 열 수 없음"
        if why:
            missing.append("사진 %s(%s) — %s. 다시 올려 주세요(다른 사진으로 채우지 않습니다)"
                           % (n, it.get("caption") or os.path.basename(p) or "이름 없음", why))
            continue
        ok.append(it)
    return ok, missing


def fit(path: str, work_dir: str, max_px: int = 1600) -> Tuple[str, float]:
    """지면용 축소본(긴 변 max_px · EXIF 회전 반영) → (경로, 가로/세로 비)."""
    from PIL import Image, ImageOps
    os.makedirs(work_dir, exist_ok=True)
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        out = os.path.join(work_dir, "_사진_" + os.path.splitext(os.path.basename(path))[0] + ".jpg")
        im.save(out, quality=88)
        return out, im.width / float(im.height)


__all__ = ["EXT", "PER_PAGE", "store", "anchors", "anchor_pt", "resolve", "embed", "localize", "fit"]
