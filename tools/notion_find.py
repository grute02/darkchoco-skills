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
import datetime
import re
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


def norm_url(u: str) -> str:
    """같은 글인지 보려고 주소를 다듬는다. tid·aid 는 글을 가리키므로 남긴다."""
    u = re.sub(r"^https?://", "", (u or "").strip().lower()).rstrip("/")
    m = re.search(r"[?&](tid|aid|pid)=(\d+)", u)
    base = u.split("?")[0].split("#")[0]
    return f"{base}#{m.group(1)}{m.group(2)}" if m else base


def days_between(a: str, b: str) -> int | None:
    """YYYY-MM-DD 두 개의 날짜 차이. 못 읽으면 None."""
    ra = re.search(r"\d{4}-\d{2}-\d{2}", a or "")
    rb = re.search(r"\d{4}-\d{2}-\d{2}", b or "")
    if not ra or not rb:
        return None
    fa = datetime.date.fromisoformat(ra.group(0))
    fb = datetime.date.fromisoformat(rb.group(0))
    return abs((fa - fb).days)


SAME_DAYS = 3


TLD = {"www", "co", "kr", "com", "net", "org", "io", "biz", "info"}


def org_keys(org: str) -> set[str]:
    """대상을 가리키는 조각들. 대상 조직 칸에서만 뽑는다.

    원문 URL 에서는 뽑지 않는다. 그것은 포럼 주소라서 같은 포럼 글이
    전부 같은 대상으로 잡힌다. 거짓 양성은 조사를 잘못 멈추게 한다.
    """
    keys: set[str] = set()
    low = (org or "").lower()
    for host in re.findall(r"[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)+", low):
        parts = [p for p in host.split(".") if p not in TLD]
        if parts:
            keys.add(parts[0])
    name = re.sub(r"[^0-9a-z가-힣]+", "", re.sub(r"\(.*?\)", " ", low))
    if len(name) >= 2:
        keys.add(name)
    return keys


def in_url(org: str, url: str) -> bool:
    """대상 이름이 주소 안에 들어 있나. 포럼 슬러그가 대상을 담는 경우가 있다."""
    key = re.sub(r"[^0-9a-z]+", "", re.sub(r"\(.*?\)", " ", (org or "").lower()))
    if len(key) < 4:
        return False
    return key in re.sub(r"[^0-9a-z]+", "", (url or "").lower())


def classify(row_url: str, row_org: str, row_date: str,
             new_url: str, new_org: str, new_date: str) -> tuple[str, str]:
    """이 줄이 새 건과 어떤 사이인지. (분류, 다음에 할 일)"""
    if new_url and row_url and norm_url(row_url) == norm_url(new_url):
        return "완전 동일 건", "새로 채번하지 않는다. 이 줄에 이어 붙인다"
    if not new_org and not new_url:
        return "확인 못 함", "새 건의 대상 조직을 --org 로 줘야 가른다"

    a, b = org_keys(row_org), org_keys(new_org)
    if not b:
        return "확인 못 함", "새 건에서 대상을 못 읽었다. --org 를 줄 것"
    if not (a & b):
        if in_url(new_org, row_url) or in_url(row_org, new_url):
            return "같은 대상 의심", "이름은 다른데 주소 안에 상대 이름이 있다. 사람이 확인할 것"
        return "다른 건", "대상이 다르다. 대조 재료로만 본다"

    d = days_between(row_date, new_date)
    if d is None:
        return "같은 대상", "날짜를 못 읽었다. 사람이 재게시인지 가른다"
    if d <= SAME_DAYS:
        return "조건만 다른 같은 건", f"게시 시각 차이 {d}일. 같은 배포로 본다"
    return "재게시 후보", f"게시 시각 차이 {d}일. 재유포인지 별건인지 가른다"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="DB 이름. 예: 수집, 검증")
    ap.add_argument("query", help="찾을 문자열. 대소문자 무시")
    ap.add_argument("--field", default="", help="이 칸에서만 찾는다")
    ap.add_argument("--url", default="", help="새 건의 원문 URL. 주면 같은 글인지 가른다")
    ap.add_argument("--org", default="", help="새 건의 대상 조직")
    ap.add_argument("--date", default="", help="새 건의 게시 시각 YYYY-MM-DD")
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
        for k in ("대상 조직", "게시 플랫폼", "원문 URL", "게시자 핸들", "상태",
                  "수집일", "게시 시각", "주장 규모", "샘플",
                  "검증 분류", "진위 판정", "검증일"):
            if k in props:
                s = as_text(props[k])
                if s:
                    # 원문 URL 은 자르지 않는다. 완전 동일 건 판별에 통째로 쓴다
                    print(f"  {k}: {s if k == '원문 URL' else s[:90]}")
        if args.url or args.org or args.date:
            kind, todo = classify(
                as_text(props.get("원문 URL", {})), as_text(props.get("대상 조직", {})),
                as_text(props.get("게시 시각", {})) or as_text(props.get("수집일", {})),
                args.url, args.org, args.date)
            print(f"  >> {kind} — {todo}")
        print()

    if args.url or args.org or args.date:
        print("분류는 참고다. 사람이 확인하고 정한다.")
        print("완전 동일 건이 하나라도 있으면 새 조사를 시작하지 않는다.")
    else:
        print("원문 URL·대상 조직·게시 시각을 주면 분류까지 한다.")
        print('  --url "<원문 URL>" --org "<대상 조직>" --date YYYY-MM-DD')
    print("이미 있는 줄이면 새로 채번하지 않는다. 그 줄에 이어 붙인다.")


if __name__ == "__main__":
    main()
