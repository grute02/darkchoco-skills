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


TLD = {"www", "co", "kr", "com", "net", "org", "io", "biz", "info"}
FORUM_TLD = TLD | {"onion", "st", "su", "ru", "is", "to", "cc", "sx", "pw", "me"}


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


def norm_handle(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", (s or "").lower())


def split_aliases(s: str) -> list[str]:
    """행위자 DB 의 `다른 이름` 은 자유 서술이다. 조각으로 자른다.

    max987 줄이 이렇게 적혀 있다.
        Max98 (breached.st 둘째 계정) · Max (Signal)
    구분자로 자르고 괄호 설명을 뗀다.
    """
    out = []
    for p in re.split(r"[,·/|;\n]|\s+또는\s+", s or ""):
        p = re.sub(r"\(.*?\)", " ", p).strip(" .'\"")
        if 2 <= len(p) <= 40:
            out.append(p)
    return out


_ALIAS: dict[str, tuple[set, str, str]] = {}


def alias_set(handle: str) -> tuple[set, str, str]:
    """행위자 DB 에서 같은 사람의 다른 닉을 모은다.

    (별칭 집합, 대표 핸들, 메모) 를 낸다.
    **행위자 DB 가 없어도 멈추지 않는다.** 빈 값으로 물러나고 문자열 비교로 돌아간다.
    """
    key = norm_handle(handle)
    if not key:
        return set(), "", ""
    if key in _ALIAS:
        return _ALIAS[key]

    try:
        ds, _ = find_db("행위자")
        rs = rows(ds)
    except SystemExit:
        _ALIAS[key] = (set(), "", "행위자 DB 없음. 문자열로만 비교했다")
        return _ALIAS[key]

    for r in rs:
        props = r.get("properties", {})
        canon = as_text(props.get("핸들", {}))
        names = [canon] + split_aliases(as_text(props.get("다른 이름", {})))
        keys = {norm_handle(n) for n in names if norm_handle(n)}
        if key in keys:
            shown = " · ".join(n for n in names if n)
            _ALIAS[key] = (keys, canon, f"행위자 DB 에 있다. {shown}")
            return _ALIAS[key]

    _ALIAS[key] = (set(), "", "행위자 DB 에 없다. 새 행위자면 ⑨ 에서 넣는다")
    return _ALIAS[key]


def same_handle(a: str, b: str, aliases: set | None = None) -> bool | None:
    """행위자가 같은가. 한쪽이라도 비면 None.

    aliases 를 주면 같은 사람의 다른 닉도 같다고 본다.
    """
    x, y = norm_handle(a), norm_handle(b)
    if not x or not y:
        return None
    if x == y:
        return True
    if aliases and x in aliases and y in aliases:
        return True
    return False


def forum_keys(s: str) -> set[str]:
    """포럼을 가리키는 조각들. 이름이든 주소든 받는다.

    onion 주소의 앞 해시는 길어서 버린다. 같은 포럼도 미러마다 해시가 달라
    비교에 못 쓴다. 그럴 때는 게시 플랫폼 칸이나 --forum 을 봐야 한다.
    """
    keys: set[str] = set()
    low = (s or "").strip().lower()
    if not low:
        return keys
    for host in re.findall(r"[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)+", low):
        for p in host.split("."):
            if p not in FORUM_TLD and 3 <= len(p) <= 24:
                keys.add(p)
    name = re.sub(r"[^0-9a-z가-힣]+", "", low)
    if 3 <= len(name) <= 24:
        keys.add(name)
    return keys


def same_forum(a: str, b: str) -> bool | None:
    """포럼이 같은가. 한쪽이라도 못 읽으면 None."""
    x, y = forum_keys(a), forum_keys(b)
    if not x or not y:
        return None
    return bool(x & y)


def size_keys(s: str) -> set[str]:
    """주장 규모에서 자릿수 있는 숫자만 뽑는다. 구분기호는 뗀다."""
    out: set[str] = set()
    for m in re.findall(r"\d[\d,\.]{2,}\d", s or ""):
        n = re.sub(r"[,\.]", "", m)
        if len(n) >= 4:
            out.add(n)
    return out


def size_note(a: str, b: str) -> str:
    """규모가 같아 보이는지. 분류를 가르지 않고 사람이 보라고 적기만 한다."""
    x, y = size_keys(a), size_keys(b)
    if not x or not y:
        return ""
    return ". 주장 규모 같음" if x & y else ". 주장 규모 표기가 다름"


def classify(row_url: str, row_org: str, row_date: str, row_handle: str,
             row_forum: str, row_size: str,
             new_url: str, new_org: str, new_date: str, new_handle: str,
             new_forum: str, new_size: str,
             aliases: set | None = None) -> tuple[str, str]:
    """이 줄이 새 건과 어떤 사이인지. (분류, 다음에 할 일)

    축은 셋이다. 케이스가 같은가, 행위자가 같은가, 포럼이 같은가.

        아예 동일 케이스            케이스·행위자·포럼이 모두 같다
        재게시                    케이스·행위자가 같고 포럼만 다르다
        일부 조건이 다른 같은 케이스   케이스는 같고 행위자가 다르다

    케이스가 같은지는 대상 조직으로 후보만 고른다. 규모로는 못 가른다.
    AT&T 건에서 49,102,176 과 73,481,539 가 같은 데이터였다. 앞은 고유
    이메일 수고 뒤는 행 수다. 규모는 사람이 보라고 옆에 적어만 둔다.
    """
    if new_url and row_url and norm_url(row_url) == norm_url(new_url):
        return "아예 동일 케이스", "원문 URL 이 같다. 같은 글이다. 새로 채번하지 않고 이 줄에 이어 붙인다"
    if not new_org and not new_url:
        return "확인 못 함", "새 건의 대상 조직을 --org 로 줘야 가른다"

    a, b = org_keys(row_org), org_keys(new_org)
    if not b:
        return "확인 못 함", "새 건에서 대상을 못 읽었다. --org 를 줄 것"
    if not (a & b):
        if in_url(new_org, row_url) or in_url(row_org, new_url):
            return "같은 대상 의심", "이름은 다른데 주소 안에 상대 이름이 있다. 사람이 확인할 것"
        return "다른 건", "대상이 다르다. 대조 재료로만 본다"

    # 여기부터 같은 케이스 후보다
    d = days_between(row_date, new_date)
    gap = f"게시 시각 차이 {d}일" if d is not None else "게시 시각을 못 읽음"
    tail = f". {gap}{size_note(row_size, new_size)}"

    h = same_handle(row_handle, new_handle, aliases)
    f = same_forum(row_forum, new_forum)
    by_alias = (h is True and norm_handle(row_handle) != norm_handle(new_handle))

    if h is False:
        who = f"{row_handle or '?'} vs {new_handle or '?'}"
        also = ""
        if f is False:
            also = f", 포럼도 다르다 ({row_forum or '?'} vs {new_forum or '?'})"
        elif f is True:
            also = f", 포럼은 같다 ({row_forum})"
        return ("일부 조건이 다른 같은 케이스",
                f"행위자가 다르다 ({who}){also}. 신규성 판정에서 재유포를 먼저 본다{tail}")
    if h is None:
        return "확인 못 함", f"행위자를 못 읽었다. --handle 을 주면 가른다{tail}"

    # 행위자가 같다
    same_by = f" (행위자 DB 별칭으로 확인. {row_handle} = {new_handle})" if by_alias else ""
    if f is False:
        return ("재게시",
                f"같은 행위자가 다른 포럼에 올렸다 ({row_forum or '?'} 에서 {new_forum or '?'} 로)"
                f"{same_by}{tail}")
    if f is True:
        return ("아예 동일 케이스",
                f"행위자와 포럼이 같다 ({row_handle}, {row_forum}){same_by}{tail}")
    return "확인 못 함", f"포럼을 못 읽었다. --forum 을 주면 재게시인지 가른다{tail}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="DB 이름. 예: 수집, 검증")
    ap.add_argument("query", help="찾을 문자열. 대소문자 무시")
    ap.add_argument("--field", default="", help="이 칸에서만 찾는다")
    ap.add_argument("--url", default="", help="새 건의 원문 URL. 주면 같은 글인지 가른다")
    ap.add_argument("--org", default="", help="새 건의 대상 조직")
    ap.add_argument("--date", default="", help="새 건의 게시 시각 YYYY-MM-DD")
    ap.add_argument("--handle", default="", help="새 건의 행위자 핸들. 재게시를 가른다")
    ap.add_argument("--forum", default="", help="새 건의 포럼. 재게시와 아예 동일을 가른다")
    ap.add_argument("--size", default="", help="새 건의 주장 규모. 사람이 보라고 옆에 적는다")
    args = ap.parse_args()

    ds_id, dbname = find_db(args.db)
    q = args.query.lower()
    all_rows = rows(ds_id)

    # 같은 사람이 포럼마다 다른 닉을 쓴다. 행위자 DB 로 먼저 푼다.
    aliases, canon, alias_note = alias_set(args.handle) if args.handle else (set(), "", "")

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
                    # 원문 URL 은 자르지 않는다. 같은 글 판별에 통째로 쓴다
                    print(f"  {k}: {s if k == '원문 URL' else s[:90]}")
        if args.url or args.org or args.date or args.handle or args.forum:
            kind, todo = classify(
                as_text(props.get("원문 URL", {})), as_text(props.get("대상 조직", {})),
                as_text(props.get("게시 시각", {})) or as_text(props.get("수집일", {})),
                as_text(props.get("게시자 핸들", {})),
                as_text(props.get("게시 플랫폼", {})), as_text(props.get("주장 규모", {})),
                args.url, args.org, args.date, args.handle, args.forum, args.size,
                aliases)
            print(f"  >> {kind} — {todo}")
        print()

    if alias_note:
        print(f"행위자   {args.handle}"
              + (f"  (대표 {canon})" if canon and canon != args.handle else ""))
        print(f"         {alias_note}")
        print()

    if args.url or args.org or args.date or args.handle or args.forum:
        print("분류는 참고다. 사람이 확인하고 정한다.")
        print("아예 동일 케이스가 하나라도 있으면 새 조사를 시작하지 않는다.")
    else:
        print("대상 조직·행위자·포럼을 주면 분류까지 한다.")
        print('  --org "<대상 조직>" --handle "<행위자>" --forum "<포럼>" --url "<원문 URL>" --date YYYY-MM-DD')
    print("이미 있는 줄이면 새로 채번하지 않는다. 그 줄에 이어 붙인다.")


if __name__ == "__main__":
    main()
