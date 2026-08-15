"""历史 data/uploads 审计清单：只读列出每个文件的归类与建议迁移目标。

规则（写死并注释）：
- 已在新布局（路径含 resumes_raw/knowledge_raw/resume_threads）→ 跳过
- data/uploads/{user}/... 视为该用户 legacy 文件
- 文件名含「简历/resume」或位于 resumes/ 子目录 → resume，否则 → knowledge
- 顶层散落文件归属 u_001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careercrew_api.storage import L, layout

RESUME_HINT = ("简历", "resume", "Resume", "RESUME")
_SKIP_PARTS = ("resumes_raw", "knowledge_raw", "resume_threads")


def classify(path: Path, uploads_root: Path) -> tuple[str, str]:
    """返回 (kind, owner)。"""
    rel = path.relative_to(uploads_root)
    parts = rel.parts
    if any(p in _SKIP_PARTS for p in parts):
        return "skip", ""
    if len(parts) >= 2:
        owner = parts[0]
    else:
        owner = "u_001"
    name = path.name
    if any(h in name for h in RESUME_HINT) or "resumes" in {p.lower() for p in parts[:-1]}:
        return "resume", owner
    return "knowledge", owner


def suggest_target(kind: str, owner: str, path: Path, upload_uuid: str, lay: object = L) -> Path:
    ext = path.suffix.lower()
    if kind == "resume":
        return lay.resumes_raw / owner / f"{upload_uuid}{ext}"
    return lay.knowledge_raw / owner / f"{upload_uuid}{ext}"


def audit(uploads_root: Path = None, lay: object = L) -> list[dict]:
    """扫描 uploads 根，返回文件清单（只读）。"""
    import uuid

    root = Path(uploads_root) if uploads_root is not None else lay.uploads
    if not root.exists():
        return []
    rows = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        kind, owner = classify(p, root)
        if kind == "skip":
            continue
        upload_uuid = uuid.uuid4().hex[:12]
        target = suggest_target(kind, owner, p, upload_uuid, lay=lay)
        rows.append({
            "path": str(p),
            "kind": kind,
            "owner": owner,
            "suggested_target": str(target),
            "exists_in_new_layout": False,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="历史 data/uploads 审计清单（只读）")
    parser.add_argument("--json", dest="json_out", default="", help="输出 JSON 清单到文件")
    args = parser.parse_args()

    rows = audit()
    for r in rows:
        print(f"{r['path']} | {r['kind']} | {r['owner']} | {r['suggested_target']}")
    print(f"共 {len(rows)} 个历史文件待迁移")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON 清单已写 {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
