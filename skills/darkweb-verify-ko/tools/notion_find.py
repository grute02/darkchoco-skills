#!/usr/bin/env python3
"""노션 DB에서 이미 있는 줄을 찾는다. 중복 조사와 중복 채번을 막는다.

사건 ID는 노션이 자동 부여하므로 ID로 찾지 않는다.
사건명, 대상 조직, 게시자 핸들, 원문 URL 같은 사람이 읽는 값으로 찾는다.

    python tools/notion_find.py 수집 i-mall
    python tools/notion_find.py 수집 Databasehooligan --field "게시자 핸들"
    python tools/notion_find.py 검증 11번가

읽기만 한다. 아무것도 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import time

from notion import _call, search, title_of

PAGE = 100
MAX_ROWS = 1000
TEXTY = {"title", "rich_text", "select", "multi_select", "url", "number", "unique_id"}


def find_db(name: str) -> tuple[str, str]:
    hits = [r for r in search(name) if r.get("object") == "data_source"]
    if not hits:
        raise SystemExit(f"'{name}' 이름의 DB를 못 찾았다. notion.py search 로 확인할 것")
    if len(hits) > 1:
        raise SystemExit("같은 이름이 여럿이다: " + ", ".join(title_of(h) for h in hits))
    return hits[0]["id"], title_of(hits[0])


def rows(ds_id: str) -> list[dict]:
    out: list[dict] = []
    cursor = None
    while len(out) < MAX_ROWS:
        body: dict = {"page_size": PAGE}
        if cursor:
            body["start_cursor"] = cursor
        d = _call(f"/data_sources/{ds_id}/query", "POST", body)
        out += d["results"]
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]
        time.sleep(0.2)
    return out


def as_text(prop: dict) -> str:
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in prop.get(t, []))
    if t == "select":
        return (prop.get("select") or {}).get("name", "")
    if t == "multi_select":
        return ", ".join(x["name"] for x in prop.get("multi_select", []))
    if t == "url":
        return prop.get("url") or ""
    if t == "number":
        v = prop.get("number")
        return "" if v is None else str(v)
    if t == "unique_id":
        u = prop.get("unique_id") or {}
        return f"{u.get('prefix') or ''}{u.get('number', '')}"
    if t == "date":
        d = prop.get("date") or {}
        return d.get("start") or ""
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="DB 이름. 예: 수집, 검증")
    ap.add_argument("query", help="찾을 문자열. 대소문자 무시")
    ap.add_argument("--field", default="", help="이 칸에서만 찾는다")
    args = ap.parse_args()

    ds_id, dbname = find_db(args.db)
    q = args.query.lower()
    all_rows = rows(ds_id)

    hits = []
    for r in all_rows:
        props = r.get("properties", {})
        matched = []
        for k, v in props.items():
            if args.field and k != args.field:
                continue
            if v.get("type") not in TEXTY:
                continue
            s = as_text(v)
            if s and q in s.lower():
                matched.append((k, s))
        if matched:
            hits.append((r, matched))

    print(f"\n대상 DB   {dbname}")
    print(f"전체 줄   {len(all_rows)}")
    print(f"질의      {args.query}" + (f"  (칸: {args.field})" if args.field else ""))
    print(f"일치      {len(hits)}줄\n")

    if not hits:
        print("일치하는 줄이 없다.")
        print("DB를 직접 조회해 부재를 확인했으므로 '없음'으로 적는다.")
        print("검색으로 못 찾은 것과 다르다.")
        return

    for r, matched in hits:
        props = r.get("properties", {})
        head = ""
        for k, v in props.items():
            if v.get("type") == "title":
                head = as_text(v)
                break
        print(f"■ {head or '(제목 없음)'}")
        print(f"  링크  {r.get('url', '')}")
        for k, s in matched:
            print(f"  일치  {k}: {s[:90]}")
        for k in ("대상 조직", "게시자 핸들", "상태", "수집일", "게시 시각",
                  "주장 규모", "검증 분류", "진위 판정", "검증일"):
            if k in props:
                s = as_text(props[k])
                if s:
                    print(f"  {k}: {s[:90]}")
        print()

    print("이미 있는 줄이면 새로 채번하지 않는다. 그 줄에 이어 붙인다.")


if __name__ == "__main__":
    main()
