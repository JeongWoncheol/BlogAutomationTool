# -*- coding: utf-8 -*-
"""Import a user-selected external manuscript/image folder into the draft pipeline.

The external package is treated as immutable input.  Every usable artifact is
copied under this release's ``posts`` directory, then bound to SQLite.  Rows
that already reached a verified Naver draft status keep their content and
images; only their import-batch metadata is refreshed so the selected-batch
buttons can still report them without producing a duplicate draft.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path

from PIL import Image

from .common import (
    COUPANG_DISCLOSURE_LINES,
    DATA,
    DB,
    OUTPUTS,
    POSTS,
    canonical_disclosure_block,
    init_db,
    log,
)


STATE_PATH = DATA / "external_selected_batch.json"
LEGACY_STATE_PATH = DATA / "external_175_selected_batch.json"
CACHE_ROOT = DATA / "external_import_cache"
REPORT_ROOT = OUTPUTS / "external_import"
MANIFEST_NAMES = ("전체_포스트.json", "전체_포스트_175.json", "posts.json", "manifest.json")
# Backward-compatible alias used by the v8.05/v8.06 offline regression fixtures.
MANIFEST_NAME = "전체_포스트_175.json"
SOURCE_PLATFORM = "외부원고"
LEGACY_SOURCE_PLATFORM = "외부175"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DISCLOSURE_FIRST = COUPANG_DISCLOSURE_LINES[0]
DISCLOSURE_SECOND = COUPANG_DISCLOSURE_LINES[1]


def health():
    return {"ready": True, "name": "외부 원고 폴더 가져오기", "message": "개수 제한 없이 폴더/ZIP 자동 인식·안전 복사 준비됨"}


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _ensure_import_columns(con: sqlite3.Connection) -> None:
    columns = {row[1] for row in con.execute("PRAGMA table_info(products)").fetchall()}
    for name, kind in (
        ("import_batch_id", "TEXT"),
        ("import_source_dir", "TEXT"),
        ("import_item_no", "INTEGER"),
        ("import_image_state", "TEXT"),
        ("import_content_state", "TEXT"),
    ):
        if name not in columns:
            con.execute(f"ALTER TABLE products ADD COLUMN {name} {kind}")
    con.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_external_batch "
        "ON products(import_batch_id,import_image_state,import_item_no)"
    )
    con.commit()


def _safe_extract_zip(zip_path: Path) -> Path:
    zip_hash = _sha256_file(zip_path)
    target = CACHE_ROOT / f"{re.sub(r'[^0-9A-Za-z가-힣_-]+','_',zip_path.stem)[:48]}_{zip_hash[:12]}"
    ready = target / ".extract_complete"
    if ready.exists():
        return target
    target.mkdir(parents=True, exist_ok=True)
    target_resolved = target.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            member = info.filename.replace("\\", "/")
            if not member or member.endswith("/"):
                continue
            destination = (target / member).resolve()
            try:
                destination.relative_to(target_resolved)
            except ValueError as exc:
                raise RuntimeError(f"ZIP 경로 이탈 항목 차단: {member}") from exc
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    ready.write_text(zip_hash, encoding="utf-8")
    return target


def _find_manifest(scan_root: Path) -> Path | None:
    candidates=[]
    for name in MANIFEST_NAMES:
        direct=scan_root/name
        if direct.is_file():
            return direct
    for depth_pattern in ("*", "*/*"):
        for base in scan_root.glob(depth_pattern):
            if not base.is_dir():
                continue
            for name in MANIFEST_NAMES:
                cand=base/name
                if cand.is_file():
                    candidates.append(cand)
    # Legacy/variant names: accept one obvious JSON list manifest.
    if not candidates:
        for cand in list(scan_root.glob("*.json"))+list(scan_root.glob("*/*.json")):
            if cand.name in {"post.json","image_evidence.json","seo_evidence.json"}:
                continue
            try:
                obj=json.loads(cand.read_text(encoding="utf-8-sig"))
                if isinstance(obj,list) and obj and isinstance(obj[0],dict) and any(k in obj[0] for k in ("title","product_name","source_keyword","body")):
                    candidates.append(cand)
            except Exception:
                pass
    unique=[]
    for x in candidates:
        if x not in unique: unique.append(x)
    return unique[0] if len(unique)==1 else None


def _looks_like_product_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    names={x.name for x in folder.iterdir() if x.is_file()}
    if "post.json" in names or "본문.txt" in names or "제목.txt" in names or "태그.txt" in names:
        return True
    return any(name.lower().startswith("image_") and Path(name).suffix.lower() in IMAGE_EXTENSIONS for name in names)


def _blocks_to_plain(blocks) -> str:
    if not isinstance(blocks,list):
        return ""
    parts=[]
    for block in blocks:
        if not isinstance(block,dict):
            continue
        typ=str(block.get("type") or "")
        if typ=="disclosure":
            lines=block.get("lines") or []
            parts.append("\n".join(str(x) for x in lines if str(x).strip()))
        elif typ in {"heading","check"}:
            text=str(block.get("text") or "").strip()
            if text: parts.append(text)
        else:
            lines=block.get("lines") or []
            text="\n".join(str(x) for x in lines if str(x).strip()) if isinstance(lines,list) else str(block.get("text") or "")
            if text.strip(): parts.append(text.strip())
    return "\n\n".join(x for x in parts if x)


def _read_text_any(folder: Path, names) -> str:
    for name in names:
        f=folder/name
        if f.is_file():
            try:return f.read_text(encoding="utf-8-sig").strip()
            except Exception:
                try:return f.read_text(encoding="utf-8").strip()
                except Exception:pass
    return ""


def _row_from_folder(root: Path, folder: Path, index: int) -> dict:
    post={}
    pf=folder/"post.json"
    if pf.is_file():
        try:
            obj=json.loads(pf.read_text(encoding="utf-8-sig"))
            if isinstance(obj,dict): post=obj
        except Exception: pass
    title=str(post.get("title") or _read_text_any(folder,("제목.txt","title.txt")) or "").strip()
    body=_read_text_any(folder,("본문.txt","body.txt")) or _blocks_to_plain(post.get("blocks"))
    tags=post.get("tags") or _read_text_any(folder,("태그.txt","tags.txt"))
    clean_folder=re.sub(r"^\d{1,4}[_ .-]*", "", folder.name).replace("_"," ").strip()
    product_name=str(post.get("product_name") or post.get("name") or "").strip()
    if not product_name and title:
        product_name=title.split(" 추천｜",1)[0].split("｜",1)[0].strip()
    product_name=product_name or clean_folder or f"외부상품 {index}"
    try:rel=folder.relative_to(root).as_posix()
    except Exception:rel=folder.name
    image_files=_image_files(folder)
    return {
        "no": index,
        "folder": rel,
        "product_name": product_name,
        "title": title,
        "body": body,
        "tags": tags,
        "category": post.get("category") or "",
        "family": post.get("family") or "",
        "coupang_url": post.get("source_url") or post.get("coupang_url") or "",
        "image_status": "COMPLETE" if len(image_files)>=3 else "INCOMPLETE",
        "images": post.get("images") if isinstance(post.get("images"),list) else [],
    }


def _auto_rows(root: Path) -> list[dict]:
    folders=[]
    if _looks_like_product_folder(root): folders.append(root)
    products=root/"products"
    bases=[products] if products.is_dir() else []
    bases.append(root)
    for base in bases:
        for child in sorted(base.iterdir() if base.is_dir() else []):
            if child.is_dir() and _looks_like_product_folder(child) and child not in folders:
                folders.append(child)
            elif child.is_dir():
                for grand in sorted(child.iterdir()):
                    if grand.is_dir() and _looks_like_product_folder(grand) and grand not in folders:
                        folders.append(grand)
    if not folders:
        raise RuntimeError("외부 원고 폴더에서 post.json / 본문.txt / 이미지 파일이 있는 상품 폴더를 찾지 못했습니다.")
    return [_row_from_folder(root,folder,i) for i,folder in enumerate(folders,1)]


def _resolve_package_root(selected_path) -> tuple[Path, Path, Path | None]:
    selected = Path(selected_path).expanduser().resolve()
    if not selected.exists():
        raise RuntimeError("선택한 외부 원고 위치가 존재하지 않습니다.")
    scan_root = _safe_extract_zip(selected) if selected.is_file() and selected.suffix.lower() == ".zip" else selected
    if scan_root.is_file():
        raise RuntimeError("폴더 또는 ZIP 파일만 선택할 수 있습니다.")
    manifest=_find_manifest(scan_root)
    if manifest:
        return selected, manifest.parent, manifest
    # No fixed 175-manifest required: use ordinary product folders directly.
    _auto_rows(scan_root)  # validate that at least one recognizable folder exists
    return selected, scan_root, None


def _load_rows(root: Path, manifest: Path | None = None) -> list[dict]:
    if manifest is None:
        return _auto_rows(root)
    try:
        rows = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"외부 원고 목록 파일을 읽지 못했습니다: {exc}") from exc
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("외부 원고 목록이 비어 있거나 형식이 올바르지 않습니다.")
    normalized = []
    seen = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise RuntimeError(f"외부 원고 {index}번 항목이 JSON 객체가 아닙니다.")
        no = int(row.get("no") or index)
        if no in seen:
            raise RuntimeError(f"중복 상품 번호가 있습니다: {no}")
        seen.add(no)
        copy = dict(row)
        copy["no"] = no
        normalized.append(copy)
    normalized.sort(key=lambda item: item["no"])
    return normalized


def _tree_fingerprint(root: Path) -> str:
    digest=hashlib.sha256()
    digest.update(str(root.resolve()).encode("utf-8","ignore"))
    for path in sorted((x for x in root.rglob("*") if x.is_file()), key=lambda x:x.as_posix())[:5000]:
        try:
            st=path.stat(); rel=path.relative_to(root).as_posix()
            digest.update(f"{rel}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8","ignore"))
        except Exception: pass
    return digest.hexdigest()

def _product_folder(root: Path, row: dict) -> Path | None:
    declared = str(row.get("folder") or "").strip()
    candidates = []
    if declared:
        candidates.extend((root / "products" / declared, root / declared))
    prefix = f"{int(row['no']):03d}_"
    for base in (root / "products", root):
        if base.is_dir():
            candidates.extend(sorted(base.glob(prefix + "*")))
    found = []
    for candidate in candidates:
        if candidate.is_dir() and candidate not in found:
            found.append(candidate)
    return found[0] if len(found) == 1 else (found[0] if declared and found else None)


def _image_files(folder: Path | None) -> list[Path]:
    if folder is None:
        return []
    all_images=[path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
    files=[path for path in all_images if path.name.lower().startswith("image_")]
    if not files:
        # Generic external folders may use representative/detail/product names instead of image_1..3.
        banned=("price","compare","banner","logo","screenshot","capture","evidence","chart","graph","배송","가격비교")
        preferred=[p for p in all_images if not any(x in p.name.casefold() for x in banned)]
        files=preferred or all_images
    def order(path: Path):
        name = path.name.casefold()
        if "representative" in name or re.search(r"image[_-]?1(?:\D|$)", name):
            return (0, name)
        if "detail_1" in name or re.search(r"image[_-]?2(?:\D|$)", name):
            return (1, name)
        if "detail_2" in name or re.search(r"image[_-]?3(?:\D|$)", name):
            return (2, name)
        return (9, name)
    return sorted(files, key=order)


def _dhash(image: Image.Image) -> int:
    small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return value


def _image_audit(files: list[Path], package_status: str, declared_images=None) -> dict:
    entries = []
    errors = []
    hashes = []
    if len(files) != 3:
        errors.append(f"이미지 실파일 {len(files)}/3")
    for index, path in enumerate(files[:3], 1):
        try:
            with Image.open(path) as opened:
                opened.load()
                width, height = opened.size
                image_hash = _dhash(opened)
            if min(width, height) < 280:
                errors.append(f"{path.name} 해상도 {width}x{height}")
            hashes.append(image_hash)
            entries.append(
                {
                    "source": str(path),
                    "source_name": path.name,
                    "role": "representative" if index == 1 else f"detail_{index-1}",
                    "width": width,
                    "height": height,
                    "sha256": _sha256_file(path),
                    "dhash": f"{image_hash:016x}",
                }
            )
        except Exception as exc:
            errors.append(f"{path.name} 디코딩 실패: {type(exc).__name__}")
    distances = []
    for i, left in enumerate(hashes):
        for right in hashes[i + 1 :]:
            distances.append((left ^ right).bit_count())
    if distances and min(distances) < 8:
        errors.append(f"이미지 중복 dHash={min(distances)}")
    status_text = str(package_status or "").upper()
    if status_text and not status_text.startswith("COMPLETE"):
        errors.append(f"패키지 상태 {package_status}")
    declared = declared_images if isinstance(declared_images, list) else []
    if declared:
        roles = [str(item.get("role") or "") for item in declared if isinstance(item, dict)]
        if roles != ["representative", "detail_1", "detail_2"]:
            errors.append("이미지 역할 증거 대표1+상세2 불일치")
        declared_by_name = {
            str(item.get("file") or ""): item
            for item in declared if isinstance(item, dict) and str(item.get("file") or "")
        }
        for entry in entries:
            proof = declared_by_name.get(entry["source_name"])
            if not proof:
                errors.append(f"{entry['source_name']} 역할 증거 없음")
                continue
            if str(proof.get("sha256") or "") and str(proof.get("sha256")) != entry["sha256"]:
                errors.append(f"{entry['source_name']} SHA256 증거 불일치")
            source_state = str(proof.get("source_url_status") or "")
            if source_state and not source_state.startswith("VERIFIED"):
                errors.append(f"{entry['source_name']} 제품 이미지 검증 미완료")
    return {
        "ok": len(files) == 3 and len(entries) == 3 and not errors,
        "entries": entries,
        "errors": errors,
        "minimum_dhash_distance": min(distances) if distances else None,
    }


def _tags(row: dict, folder: Path | None) -> list[str]:
    value = row.get("tags")
    if isinstance(value, list):
        tags = [str(item).strip().lstrip("#") for item in value if str(item).strip()]
    else:
        tags = [item.strip().lstrip("#") for item in re.split(r"[,\n]+", str(value or "")) if item.strip()]
    if not tags and folder and (folder / "태그.txt").is_file():
        text = (folder / "태그.txt").read_text(encoding="utf-8-sig")
        tags = [item.strip().lstrip("#") for item in re.split(r"[,\n]+", text) if item.strip()]
    return tags


def _body(row: dict, folder: Path | None) -> str:
    value = str(row.get("body") or "").strip()
    if not value and folder and (folder / "본문.txt").is_file():
        value = (folder / "본문.txt").read_text(encoding="utf-8-sig").strip()
    return value


def _content_audit(row: dict, folder: Path | None) -> dict:
    title = str(row.get("title") or "").strip()
    body = _body(row, folder)
    tags = _tags(row, folder)
    errors = []
    if " 추천｜" not in title:
        errors.append("제목 추천｜ 형식 누락")
    else:
        tail = title.split("｜", 1)[1]
        if len([part for part in tail.split("·") if part.strip()]) < 3:
            errors.append("제목 서브키워드 3개 미만")
    body_length = len(body)
    if not 1100 <= body_length <= 1600:
        errors.append(f"본문 글자수 {body_length}/1100~1600")
    if not body.startswith(DISCLOSURE_FIRST) or body.count(DISCLOSURE_FIRST) != 1 or body.count(DISCLOSURE_SECOND) != 1:
        errors.append("경제적 이해관계 고지문 최상단 1회 불일치")
    if not 20 <= len(tags) <= 30:
        errors.append(f"관련 태그 {len(tags)}/20~30")
    if len(tags) != len({tag.casefold() for tag in tags}):
        errors.append("태그 중복")
    return {"ok": not errors, "errors": errors, "title": title, "body": body, "body_chars": body_length, "tags": tags}


def inspect_package(selected_path) -> dict:
    original, root, manifest = _resolve_package_root(selected_path)
    manifest_hash = _sha256_file(manifest) if manifest else _tree_fingerprint(root)
    batch_id = "EXT_" + manifest_hash[:16]
    rows = _load_rows(root, manifest)
    items = []
    for row in rows:
        folder = _product_folder(root, row)
        content = _content_audit(row, folder)
        images = _image_audit(
            _image_files(folder),
            str(row.get("image_status") or ""),
            row.get("images"),
        )
        items.append(
            {
                "no": int(row["no"]),
                "row": row,
                "folder": str(folder) if folder else "",
                "content": content,
                "images": images,
                "image_state": "complete" if images["ok"] else "incomplete",
            }
        )
    complete = sum(item["image_state"] == "complete" for item in items)
    content_ready = sum(bool(item["content"]["ok"]) for item in items)
    return {
        "source_path": str(original),
        "resolved_root": str(root),
        "batch_id": batch_id,
        "manifest_hash": manifest_hash,
        "manifest_path": str(manifest) if manifest else "AUTO_FOLDER_SCAN",
        "total": len(items),
        "complete": complete,
        "incomplete": len(items) - complete,
        "content_ready": content_ready,
        "items": items,
    }

def _slug(value: str, limit: int = 34) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value or "상품"))
    value = re.sub(r"\s+", "_", value.strip()).strip(" ._") or "상품"
    return value[:limit]


def _visual_lines(text: str, max_chars: int = 22) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    lines = []
    current = ""
    for word in text.split():
        candidate = word if not current else current + " " + word
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _body_blocks(body: str) -> list[dict]:
    blocks = [canonical_disclosure_block()]
    paragraphs = [part.strip() for part in re.split(r"\r?\n\s*\r?\n+", str(body or "")) if part.strip()]
    section_index = -1
    advantage_mode = False
    intro_count = 0
    check_count = 0
    for paragraph in paragraphs:
        compact = re.sub(r"\s+", "", paragraph)
        if "쿠팡파트너스활동의일환" in compact or "일정액의수수료를제공받습니다" in compact:
            continue
        if re.fullmatch(r"\[쿠팡[^\]]*보기\]", paragraph):
            continue
        if paragraph.startswith(("💙", "🤍", "💛", "❤️")):
            section_index += 1
            advantage_mode = False
            blocks.append(
                {
                    "type": "heading",
                    "text": paragraph,
                    "format": "bold_bg_exact",
                    "background_hex": "#fff8b2",
                    "bold": True,
                    "align": "center",
                    "section_index": section_index,
                }
            )
            continue
        if paragraph.startswith("✔ 장점 요약"):
            advantage_mode = True
            blocks.append(
                {
                    "type": "heading",
                    "text": "✔ 장점 요약",
                    "format": "bold_bg_exact",
                    "background_hex": "#fff8b2",
                    "bold": True,
                    "align": "center",
                }
            )
            continue
        numbered = re.match(r"^\d+\.\s*(.+)$", paragraph, flags=re.S)
        if advantage_mode and numbered and check_count < 5:
            text = numbered.group(1).strip()
            blocks.append(
                {
                    "type": "check",
                    "text": "✔ " + text,
                    "format": "bold_bg_exact",
                    "background_hex": "#fff8b2",
                    "bold": True,
                    "align": "center",
                }
            )
            check_count += 1
            continue
        role = None
        if section_index < 0 and not advantage_mode:
            role = "intro"
            intro_count += 1
        elif advantage_mode and check_count >= 5:
            role = "conclusion"
        block = {"type": "paragraph", "lines": _visual_lines(paragraph), "layout": "mobile_center"}
        if role:
            block["role"] = role
        if section_index >= 0 and not advantage_mode:
            block["section_index"] = section_index
        blocks.append(block)
    return blocks


def _category(row: dict) -> str:
    direct=str(row.get("category") or "").strip()
    if direct:return direct
    family = str(row.get("family") or "").casefold()
    if family in {"food", "fresh_food", "supplement"}:
        return "식품"
    if family in {"phone", "computer", "tablet", "audio_wearable", "large_appliance", "small_appliance", "gaming_camera"}:
        return "디지털/가전"
    if family == "beauty":
        return "화장품/미용"
    if family == "living":
        return "가구/인테리어"
    return "생활용품"


def _title_keywords(title: str) -> list[str]:
    if "｜" not in title:
        return []
    return [part.strip() for part in title.split("｜", 1)[1].split("·") if part.strip()][:4]


def _copy_images(item: dict, target: Path) -> tuple[list[str], dict]:
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("image_1_representative.jpg", "image_2_detail_1.jpg", "image_3_detail_2.jpg"):
        try:
            (target / filename).unlink(missing_ok=True)
        except Exception:
            pass
    copied = []
    entries = []
    for index, entry in enumerate(item["images"]["entries"][:3], 1):
        source = Path(entry["source"])
        role = "representative" if index == 1 else f"detail_{index-1}"
        name = f"image_{index}_{role}.jpg"
        destination = target / name
        with Image.open(source) as opened:
            image = opened.convert("RGB")
            image.save(destination, "JPEG", quality=93, optimize=True, progressive=True)
        copied.append(str(destination.resolve()))
        entries.append(
            {
                "role": role,
                "file": name,
                "path": str(destination.resolve()),
                "source_file": str(source),
                "width": image.width,
                "height": image.height,
                "sha256": _sha256_file(destination),
            }
        )
    complete = bool(item["images"]["ok"] and len(copied) == 3)
    evidence = {
        "policy": "EXTERNAL_FOLDER_REPRESENTATIVE_PLUS_TWO_V8_09",
        "composition": {
            "verified": complete,
            "representative_count": 1 if complete else min(1, len(copied)),
            "secondary_count": 2 if complete else max(0, len(copied) - 1),
            "required": "representative_1_plus_product_visible_secondary_2",
        },
        "physical_count": len(copied),
        "verified_count": 3 if complete else len(copied),
        "minimum_dhash_distance": item["images"].get("minimum_dhash_distance"),
        "errors": list(item["images"].get("errors") or []),
        "items": entries,
        "checked_at": _now(),
    }
    evidence_path = target / "image_evidence.json"
    _atomic_json(evidence_path, evidence)
    evidence["path"] = str(evidence_path.resolve())
    return copied, evidence


def _find_existing(con: sqlite3.Connection, state: dict, item: dict):
    row = con.execute(
        "SELECT * FROM products WHERE source_platform IN (?,?) AND import_source_dir=? AND import_item_no=? ORDER BY id LIMIT 1",
        (SOURCE_PLATFORM, LEGACY_SOURCE_PLATFORM, state["source_path"], int(item["no"])),
    ).fetchone()
    if row:
        return row
    name = str(item["row"].get("product_name") or item["row"].get("source_keyword") or "").strip()
    source_url = str(item["row"].get("coupang_url") or item["row"].get("coupang_search_url") or "").strip()
    return con.execute(
        "SELECT * FROM products WHERE source_platform=? AND product_identity=? AND COALESCE(source_url,'')=? ORDER BY id LIMIT 1",
        (SOURCE_PLATFORM, name, source_url),
    ).fetchone()


def import_package(selected_path, progress=None) -> dict:
    init_db()
    state = inspect_package(selected_path)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    POSTS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    _ensure_import_columns(con)
    max_no = int(con.execute("SELECT COALESCE(MAX(product_no),0) FROM products").fetchone()[0] or 0)
    imported = 0
    updated = 0
    preserved_completed = 0
    product_ids = []
    complete_ids = []
    incomplete_ids = []
    report_items = []
    try:
        for index, item in enumerate(state["items"], 1):
            row_data = item["row"]
            content = item["content"]
            existing = _find_existing(con, state, item)
            if existing:
                product_no = int(existing["product_no"] or existing["id"])
                product_id = int(existing["id"])
            else:
                max_no += 1
                product_no = max_no
                product_id = 0
            name = str(row_data.get("product_name") or row_data.get("source_keyword") or f"외부상품 {item['no']}").strip()
            source_url = str(row_data.get("coupang_url") or row_data.get("coupang_search_url") or "").strip()
            post_dir = POSTS / f"{product_no:03d}_EXT_{state['batch_id'][-8:]}_{_slug(name)}"
            completed_before = bool(existing and str(existing["status"] or "").startswith("임시저장완료"))
            if completed_before:
                con.execute(
                    "UPDATE products SET import_batch_id=?,import_source_dir=?,import_item_no=?,import_image_state=?,"
                    "import_content_state=?,updated_at=datetime('now','localtime') WHERE id=?",
                    (
                        state["batch_id"], state["source_path"], int(item["no"]), item["image_state"],
                        "ready" if content["ok"] else "invalid", product_id,
                    ),
                )
                preserved_completed += 1
                current_image_state = str(existing["import_image_state"] or item["image_state"])
            else:
                images, evidence = _copy_images(item, post_dir)
                image_values = images + [None, None, None]
                blocks = _body_blocks(content["body"])
                sharelink = str(existing["sharelink"] or "") if existing else ""
                quality = {
                    "ok": bool(content["ok"]),
                    "source": "external_folder_import",
                    "body_chars": content["body_chars"],
                    "errors": content["errors"],
                    "checked_at": _now(),
                }
                post = {
                    "title": content["title"],
                    "blocks": blocks,
                    "tags": content["tags"],
                    "sharelink": sharelink,
                    "content_quality_audit": quality,
                    "reference_layout_slots": ["after_intro", "after_section_1", "after_section_2"],
                    "layout_policy": "V8_09_EXTERNAL_FOLDER_DISCLOSURE_TOP_ONCE_REPRESENTATIVE_PLUS_TWO",
                    "external_import": {"batch_id": state["batch_id"], "item_no": int(item["no"]), "source_path": state["source_path"]},
                }
                _atomic_json(post_dir / "post.json", post)
                (post_dir / "본문.txt").write_text(content["body"], encoding="utf-8")
                (post_dir / "태그.txt").write_text(", ".join(content["tags"]), encoding="utf-8")
                seo_path = post_dir / "seo_evidence.json"
                _atomic_json(
                    seo_path,
                    {
                        "source": "external_folder_import",
                        "content_quality_audit": quality,
                        "title_keywords": _title_keywords(content["title"]),
                        "checked_at": _now(),
                    },
                )
                image_count = 3 if evidence["composition"]["verified"] else len(images)
                current_image_state = "complete" if evidence["composition"]["verified"] else "incomplete"
                status = (
                    "외부가져오기완료(사진3장)" if current_image_state == "complete" and content["ok"]
                    else "외부가져오기완료(이미지미완료)" if content["ok"]
                    else "외부가져오기보완(원고)"
                )
                body_json = json.dumps(blocks, ensure_ascii=False)
                tags_text = ", ".join(content["tags"])
                seo_keywords = ", ".join(_title_keywords(content["title"]))
                values = (
                    product_no, name, _category(row_data), name, SOURCE_PLATFORM, source_url, status,
                    content["title"], body_json, tags_text,
                    image_values[0], image_values[1], image_values[2],
                    sharelink, 1, str(post_dir.resolve()), None,
                    image_count, evidence["path"], seo_keywords, str(seo_path.resolve()),
                    state["batch_id"], state["source_path"], int(item["no"]), current_image_state,
                    "ready" if content["ok"] else "invalid",
                )
                if existing:
                    con.execute(
                        """UPDATE products SET product_no=?,name=?,category=?,product_identity=?,source_platform=?,source_url=?,status=?,
                        title=?,body=?,tags=?,image1=?,image2=?,image3=?,sharelink=?,approved=?,post_dir=?,last_error=?,
                        image_verified_count=?,image_evidence_json=?,seo_keywords=?,seo_evidence_json=?,import_batch_id=?,
                        import_source_dir=?,import_item_no=?,import_image_state=?,import_content_state=?,updated_at=datetime('now','localtime')
                        WHERE id=?""",
                        (*values, product_id),
                    )
                    updated += 1
                else:
                    cursor = con.execute(
                        """INSERT INTO products(product_no,name,category,product_identity,source_platform,source_url,status,
                        title,body,tags,image1,image2,image3,sharelink,approved,post_dir,last_error,image_verified_count,
                        image_evidence_json,seo_keywords,seo_evidence_json,import_batch_id,import_source_dir,import_item_no,
                        import_image_state,import_content_state,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                        values,
                    )
                    product_id = int(cursor.lastrowid)
                    imported += 1
            product_ids.append(product_id)
            if current_image_state == "complete":
                complete_ids.append(product_id)
            else:
                incomplete_ids.append(product_id)
            report_items.append(
                {
                    "item_no": int(item["no"]),
                    "product_id": product_id,
                    "product_no": product_no,
                    "name": name,
                    "content_state": "ready" if content["ok"] else "invalid",
                    "content_errors": content["errors"],
                    "image_state": current_image_state,
                    "image_errors": item["images"]["errors"],
                    "preserved_completed": completed_before,
                }
            )
            if progress:
                progress(index, len(state["items"]), f"외부 원고 가져오기 {index}/{len(state['items'])}: {name[:30]}")
        con.commit()
    finally:
        con.close()

    selected = {
        "batch_id": state["batch_id"],
        "source_path": state["source_path"],
        "resolved_root": state["resolved_root"],
        "manifest_hash": state["manifest_hash"],
        "total": state["total"],
        "complete": len(complete_ids),
        "incomplete": len(incomplete_ids),
        "content_ready": state["content_ready"],
        "product_ids": product_ids,
        "complete_product_ids": complete_ids,
        "incomplete_product_ids": incomplete_ids,
        "imported": imported,
        "updated": updated,
        "preserved_completed": preserved_completed,
        "selected_at": _now(),
    }
    report_json = REPORT_ROOT / f"{state['batch_id']}_report.json"
    report_csv = REPORT_ROOT / f"{state['batch_id']}_report.csv"
    _atomic_json(report_json, {**selected, "items": report_items})
    with report_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ["item_no", "product_id", "product_no", "name", "content_state", "content_errors", "image_state", "image_errors", "preserved_completed"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in report_items:
            row = dict(item)
            row["content_errors"] = " | ".join(item["content_errors"])
            row["image_errors"] = " | ".join(item["image_errors"])
            writer.writerow(row)
    selected["report_json"] = str(report_json.resolve())
    selected["report_csv"] = str(report_csv.resolve())
    _atomic_json(STATE_PATH, selected)
    log(
        f"외부 원고 가져오기 완료: batch={state['batch_id']} total={state['total']} "
        f"image_complete={len(complete_ids)} incomplete={len(incomplete_ids)} imported={imported} updated={updated} preserved={preserved_completed}"
    )
    return {
        "processed": state["total"],
        "stage_ok": state["content_ready"] == state["total"],
        "soft_pending": len(incomplete_ids) > 0 or state["content_ready"] != state["total"],
        "message": (
            f"외부 {state['total']}개 가져오기 완료 · 사진3장 {len(complete_ids)}개 · "
            f"이미지 미완료 {len(incomplete_ids)}개 · 원고 정상 {state['content_ready']}개"
        ),
        **selected,
    }


def selected_state() -> dict:
    for path in (STATE_PATH, LEGACY_STATE_PATH):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict): return value
        except Exception:
            pass
    return {}


def selected_product_ids(image_state: str) -> list[int]:
    state = selected_state()
    if image_state == "complete":
        return [int(value) for value in state.get("complete_product_ids") or []]
    if image_state == "incomplete":
        return [int(value) for value in state.get("incomplete_product_ids") or []]
    return [int(value) for value in state.get("product_ids") or []]
