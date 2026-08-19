"""마크다운 파일을 노션 새 페이지로 올린다.

읽기 전용인 notion.py 는 건드리지 않고 그쪽 인증과 호출만 빌려 쓴다.

    python tools/notion_push.py <parent_page_id> <제목> <md파일>
    python tools/notion_push.py <parent_page_id> <제목> <md파일> --dry
    python tools/notion_push.py <page_id> <제목> <md파일> --update

--dry 는 블록만 만들어 개수를 세고 요청을 보내지 않는다.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from notion import _call

LIMIT = 100      # 한 요청에 붙일 수 있는 블록 수
TEXT_MAX = 1900  # rich_text 하나의 길이 상한 (규격은 2000)


def _rt(s: str) -> list[dict]:
    """긴 문자열을 여러 rich_text 조각으로 나눈다."""
    s = s or ""
    out = []
    while s:
        out.append({"type": "text", "text": {"content": s[:TEXT_MAX]}})
        s = s[TEXT_MAX:]
    return out or [{"type": "text", "text": {"content": ""}}]


def _para(s: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _rt(s)}}


def _head(level: int, s: str) -> dict:
    t = f"heading_{min(level, 3)}"
    return {"object": "block", "type": t, t: {"rich_text": _rt(s)}}


def _bullet(s: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _rt(s)}}


def _code(lines: list[str]) -> dict:
    return {"object": "block", "type": "code",
            "code": {"rich_text": _rt("\n".join(lines)), "language": "plain text"}}


def _row(cells: list[str]) -> dict:
    return {"object": "block", "type": "table_row",
            "table_row": {"cells": [_rt(c) for c in cells]}}


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_sep(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def md_to_blocks(text: str) -> list[dict]:
    """마크다운을 노션 블록으로 바꾼다. 표, 코드블록, 제목, 불릿, 구분선만 다룬다."""
    blocks: list[dict] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        # 코드블록
        if s.startswith("```"):
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            blocks.append(_code(body))
            continue

        # 표
        if s.startswith("|") and s.endswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cur = lines[i].strip()
                if not _is_sep(cur):
                    rows.append(_split_row(cur))
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                blocks.append({
                    "object": "block", "type": "table",
                    "table": {"table_width": width, "has_column_header": True,
                              "has_row_header": False,
                              "children": [_row(r) for r in rows]},
                })
            continue

        # 구분선
        if re.fullmatch(r"-{3,}", s):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # 제목
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            blocks.append(_head(len(m.group(1)), m.group(2)))
            i += 1
            continue

        # 불릿
        m = re.match(r"^[-*]\s+(.*)$", s)
        if m:
            blocks.append(_bullet(m.group(1)))
            i += 1
            continue

        # 들여쓴 줄은 코드블록으로 묶는다
        if line.startswith("    ") and s:
            body = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                if lines[i].strip() or body:
                    body.append(lines[i][4:] if lines[i].startswith("    ") else "")
                i += 1
            while body and not body[-1].strip():
                body.pop()
            blocks.append(_code(body))
            continue

        if s:
            blocks.append(_para(s))
        i += 1
    return blocks


def create_page(parent_id: str, title: str, blocks: list[dict]) -> str:
    body = {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": _rt(title)}},
        "children": blocks[:LIMIT],
    }
    page = _call("/pages", "POST", body)
    pid = page["id"]
    rest = blocks[LIMIT:]
    while rest:
        _call(f"/blocks/{pid}/children", "PATCH", {"children": rest[:LIMIT]})
        rest = rest[LIMIT:]
        time.sleep(0.4)
    return page.get("url", pid)


def update_page(page_id: str, title: str, blocks: list[dict]) -> str:
    """기존 페이지의 본문을 통째로 갈아끼운다. 기존 블록은 보관 처리된다."""
    old = _call(f"/blocks/{page_id}/children?page_size=100")["results"]
    while old:
        for b in old:
            _call(f"/blocks/{b['id']}", "DELETE")
            time.sleep(0.2)
        old = _call(f"/blocks/{page_id}/children?page_size=100")["results"]
    print(f"기존 블록 비움")

    if title:
        _call(f"/pages/{page_id}", "PATCH",
              {"properties": {"title": {"title": _rt(title)}}})

    rest = blocks
    while rest:
        _call(f"/blocks/{page_id}/children", "PATCH", {"children": rest[:LIMIT]})
        rest = rest[LIMIT:]
        time.sleep(0.4)
    return f"https://app.notion.com/{page_id.replace('-', '')}"


def _main(argv: list[str]) -> None:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) < 3:
        raise SystemExit(__doc__)
    target, title, path = args[0], args[1], Path(args[2])

    text = path.read_text(encoding="utf-8")
    blocks = md_to_blocks(text)
    kinds: dict[str, int] = {}
    for b in blocks:
        kinds[b["type"]] = kinds.get(b["type"], 0) + 1
    print(f"블록 {len(blocks)}개  " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))

    if "--dry" in argv:
        print("dry run. 요청을 보내지 않았다.")
        return
    if "--update" in argv:
        print(update_page(target, title, blocks))
    else:
        print(create_page(target, title, blocks))


if __name__ == "__main__":
    _main(sys.argv)
