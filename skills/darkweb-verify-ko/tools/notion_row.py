#!/usr/bin/env python3
"""⑨ 출력을 노션 DB 행으로 만든다.

**미리보기가 기본이다.** `--commit` 을 붙여야 실제로 쓴다.
기존 행을 고치지 않는다. 새 행만 만든다.

    python tools/notion_row.py 검증 out9.txt
    python tools/notion_row.py 검증 out9.txt --exclude "검증 자료,한계"
    python tools/notion_row.py 검증 out9.txt --set "검증자=이름"
    python tools/notion_row.py 검증 out9.txt --commit

입력 파일은 ⑨ 출력 그대로다. 한 줄에 `칸 이름: 값` 형식.
빈 값과 자동 생성 칸(생성일, 최근 1주 등)은 알아서 건너뛴다.

relation 칸은 사건 ID 로 준다. `같은 사건: LEAK-8` 처럼 쓰면 그 줄을 찾아 잇는다.
여럿이면 쉼표로 나눈다. 못 찾으면 잇지 않고 확인할 것에 적는다.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from notion import _call, search, title_of

READONLY = {"formula", "created_time", "last_edited_time", "unique_id",
            "created_by", "last_edited_by", "rollup"}
TRUE = {"예", "true", "True", "1", "O", "o", "체크"}


def find_db(name: str) -> tuple[str, str]:
    """이름으로 data_source 를 찾는다. 토큰마다 워크스페이스가 달라 ID를 박지 않는다."""
    hits = [r for r in search(name) if r.get("object") == "data_source"]
    if not hits:
        raise SystemExit(f"'{name}' 이름의 DB를 못 찾았다. notion.py search 로 확인할 것")
    if len(hits) > 1:
        names = ", ".join(title_of(h) for h in hits)
        raise SystemExit(f"같은 이름이 여럿이다: {names}. 정확한 이름을 줄 것")
    return hits[0]["id"], title_of(hits[0])


# 페이지 본문으로 갈 항목. 칸이 아니라 블록이다.
BODY_MARK = "--- 아래는 페이지 본문에 붙인다. 칸이 아니다 ---"
BODY_KEYS = [("캡처", "paragraph"), ("연락처", "paragraph"),
             ("참고사항", "bulleted_list_item")]

# 이 칸이 비면 미리보기에서 알린다. 사람만 아는 값이라 물어봐야 채워진다.
ASK_IF_EMPTY = {"수집": ["원문 URL", "게시 플랫폼"]}


def parse_body(text: str) -> list[tuple[str, str, str]]:
    """본문 표시줄 뒤에서 (제목, 블록종류, 내용) 을 순서대로 뽑는다.

    parse_output 은 같은 칸 이름이 여러 줄이면 마지막만 남긴다.
    참고사항은 여러 줄이 정상이라 따로 읽는다.
    """
    if BODY_MARK not in text:
        return []
    tail = text.split(BODY_MARK, 1)[1]
    out: list[tuple[str, str, str]] = []
    for name, kind in BODY_KEYS:
        for line in tail.split("\n"):
            line = line.strip()
            if not line.startswith(name + ":"):
                continue
            val = line.split(":", 1)[1].strip()
            if val:
                out.append((name, kind, val))
    return out


def body_blocks(items: list[tuple[str, str, str]]) -> list[dict]:
    """본문 항목을 노션 블록으로 바꾼다. 제목마다 heading_3 을 앞에 둔다."""
    def rt(s: str) -> list[dict]:
        return [{"type": "text", "text": {"content": s[:2000]}}]

    out: list[dict] = []
    seen: set[str] = set()
    for name, kind, val in items:
        if name not in seen:
            seen.add(name)
            out.append({"object": "block", "type": "heading_3",
                        "heading_3": {"rich_text": rt(name)}})
        out.append({"object": "block", "type": kind, kind: {"rich_text": rt(val)}})
    return out


def parse_output(text: str) -> dict[str, str]:
    """⑨ 출력에서 '칸: 값' 을 뽑는다."""
    out: dict[str, str] = {}
    for line in text.split("\n"):
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith(("#", "-", "*", "[", "■", "```")):
            continue
        m = re.match(r"^\s{0,4}([^:]{1,30}?)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        # 주석성 꼬리표 제거
        val = re.sub(r"\s{2,}\(.*\)$", "", val)
        if key and val:
            out[key] = val
    return out


_ROWS: dict[str, list[dict]] = {}


def _target_rows(ds_id: str) -> list[dict]:
    """상대 DB 의 줄을 한 번만 받아 둔다."""
    if ds_id not in _ROWS:
        out, cursor = [], None
        while True:
            body: dict = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            d = _call(f"/data_sources/{ds_id}/query", "POST", body)
            out += d["results"]
            if not d.get("has_more"):
                break
            cursor = d["next_cursor"]
        _ROWS[ds_id] = out
    return _ROWS[ds_id]


def _row_labels(row: dict) -> set[str]:
    """이 줄을 부를 수 있는 이름들. 사건 ID 와 제목."""
    out: set[str] = set()
    for v in row.get("properties", {}).values():
        ty = v.get("type")
        if ty == "unique_id":
            u = v.get("unique_id") or {}
            pre, num = (u.get("prefix") or ""), u.get("number")
            if num is not None:
                out.add(f"{pre}-{num}".lower())
                out.add(f"{pre}{num}".lower())
                out.add(str(num))
        elif ty == "title":
            s = "".join(x.get("plain_text", "") for x in v.get("title", []))
            if s.strip():
                out.add(s.strip().lower())
    return out


def resolve_relation(ds_id: str, raw: str) -> tuple[list[str], list[str]]:
    """사건 ID 나 제목을 page id 로 바꾼다. (찾은 것, 못 찾은 것)"""
    want = [x.strip() for x in re.split(r"[,·/]", raw) if x.strip()]
    found, missing = [], []
    rows = _target_rows(ds_id)
    for w in want:
        key = w.lower()
        hit = next((r for r in rows if key in _row_labels(r)), None)
        if hit:
            if hit["id"] not in found:
                found.append(hit["id"])
        else:
            missing.append(w)
    return found, missing


def build(props: dict, values: dict[str, str]) -> tuple[dict, list[str], list[str]]:
    """노션 properties 를 만든다. 못 넣은 것과 경고를 함께 낸다."""
    body: dict = {}
    skipped: list[str] = []
    warn: list[str] = []

    known_body = {n for n, _ in BODY_KEYS}
    for key, raw in values.items():
        if key not in props:
            if key in known_body:
                continue          # 본문으로 간다. 따로 보고한다
            skipped.append(f"{key}  DB에 없는 칸")
            continue
        t = props[key]["type"]
        if t in READONLY:
            skipped.append(f"{key}  자동 생성 칸이라 입력 불가")
            continue

        if t == "title":
            body[key] = {"title": [{"text": {"content": raw[:2000]}}]}
        elif t == "rich_text":
            body[key] = {"rich_text": [{"text": {"content": raw[:2000]}}]}
        elif t == "number":
            num = re.sub(r"[^\d.\-]", "", raw)
            if not num:
                skipped.append(f"{key}  숫자로 못 읽음: {raw}")
                continue
            body[key] = {"number": float(num)}
        elif t == "checkbox":
            body[key] = {"checkbox": raw in TRUE}
        elif t == "date":
            m = re.search(r"\d{4}-\d{2}-\d{2}", raw)
            if not m:
                skipped.append(f"{key}  날짜로 못 읽음: {raw}")
                continue
            body[key] = {"date": {"start": m.group(0)}}
        elif t == "select":
            opts = [o["name"] for o in props[key]["select"]["options"]]
            if raw not in opts:
                warn.append(f"{key}  '{raw}' 는 없는 선택지다. 있는 것: {', '.join(opts)}")
                skipped.append(f"{key}  선택지에 없어 건너뜀")
                continue
            body[key] = {"select": {"name": raw}}
        elif t == "multi_select":
            opts = [o["name"] for o in props[key]["multi_select"]["options"]]
            items = [x.strip() for x in re.split(r"[,·/]", raw) if x.strip()]
            bad = [x for x in items if x not in opts]
            if bad:
                warn.append(f"{key}  없는 선택지 {', '.join(bad)}. 있는 것: {', '.join(opts)}")
            ok = [x for x in items if x in opts]
            if not ok:
                skipped.append(f"{key}  넣을 선택지가 없어 건너뜀")
                continue
            body[key] = {"multi_select": [{"name": x} for x in ok]}
        elif t == "url":
            body[key] = {"url": raw}
        elif t == "relation":
            ds = props[key].get("relation", {}).get("data_source_id", "")
            if not ds:
                skipped.append(f"{key}  상대 DB를 못 찾음")
                continue
            ids, missing = resolve_relation(ds, raw)
            if missing:
                warn.append(f"{key}  못 찾은 줄: {', '.join(missing)}. 사건 ID 나 제목 그대로 줄 것")
            if not ids:
                skipped.append(f"{key}  이을 줄을 못 찾아 건너뜀")
                continue
            body[key] = {"relation": [{"id": i} for i in ids]}
        else:
            skipped.append(f"{key}  다루지 않는 칸 종류 {t}")
    return body, skipped, warn


def show(dbname: str, props: dict, body: dict, skipped: list[str],
         warn: list[str], excluded: list[str],
         blocks: list[dict] | None = None) -> None:
    blocks = blocks or []
    print(f"\n대상 DB   {dbname}")
    print(f"넣을 칸   {len(body)}개")
    print(f"본문 블록  {len(blocks)}개\n")
    print("| 칸 | 종류 | 값 |")
    print("|---|---|---|")
    for k, v in body.items():
        t = props[k]["type"]
        if t in ("title", "rich_text"):
            s = v[t][0]["text"]["content"]
        elif t == "select":
            s = v["select"]["name"]
        elif t == "multi_select":
            s = ", ".join(x["name"] for x in v["multi_select"])
        elif t == "date":
            s = v["date"]["start"]
        elif t == "checkbox":
            s = "체크" if v["checkbox"] else "해제"
        elif t == "relation":
            s = f"{len(v['relation'])}줄과 이음"
        else:
            s = str(v.get(t))
        s = s.replace("\n", " ")
        print(f"| {k} | {t} | {s[:70]}{'...' if len(s) > 70 else ''} |")

    if excluded:
        print("\n[사람이 뺀 칸]")
        for k in excluded:
            print(f"  {k}")
    if skipped:
        print("\n[못 넣은 칸]")
        for s in skipped:
            print(f"  {s}")
    if blocks:
        print("\n[페이지 본문]")
        for b in blocks:
            t = b["type"]
            s = b[t]["rich_text"][0]["text"]["content"].replace("\n", " ")
            head = "  " if t == "heading_3" else "    - "
            print(f"{head}{s[:76]}{'...' if len(s) > 76 else ''}")
    if warn:
        print("\n[확인할 것]")
        for w in warn:
            print(f"  {w}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="DB 이름. 예: 검증, 수집")
    ap.add_argument("infile", help="⑨ 출력 파일")
    ap.add_argument("--exclude", default="", help="뺄 칸. 쉼표 구분")
    ap.add_argument("--set", dest="sets", action="append", default=[],
                    help="칸=값 으로 고침. 여러 번 쓸 수 있다")
    ap.add_argument("--commit", action="store_true", help="실제로 행을 만든다")
    args = ap.parse_args()

    ds_id, dbname = find_db(args.db)
    props = _call(f"/data_sources/{ds_id}")["properties"]

    text = Path(args.infile).read_text(encoding="utf-8")
    values = parse_output(text)
    blocks = body_blocks(parse_body(text))

    excluded = [x.strip() for x in args.exclude.split(",") if x.strip()]
    for k in excluded:
        values.pop(k, None)
    for pair in args.sets:
        if "=" not in pair:
            raise SystemExit(f"--set 은 칸=값 형식이다: {pair}")
        k, v = pair.split("=", 1)
        values[k.strip()] = v.strip()

    body, skipped, warn = build(props, values)
    if not body:
        raise SystemExit("넣을 칸이 하나도 없다. 입력 형식을 확인할 것")

    # 사람만 아는 값이 비었으면 알린다. 물어보라는 뜻이다.
    for k in ASK_IF_EMPTY.get(args.db.strip(), []):
        if k in props and k not in body and k not in excluded:
            warn.append(f"{k} 이(가) 비었다. 캡처에 없으면 사람에게 묻는다. "
                        f"원문 URL 이 포럼을 정한다")
    if not blocks:
        warn.append("페이지 본문이 없다. 캡처·연락처·참고사항을 안 냈는지 확인한다")

    show(dbname, props, body, skipped, warn, excluded, blocks)

    if not args.commit:
        print("\n미리보기다. 실제로 쓰지 않았다.")
        print("뺄 칸이 있으면  --exclude \"칸1,칸2\"")
        print("고칠 칸이 있으면 --set \"칸=값\"")
        print("그대로 올리려면 --commit")
        return

    page = _call("/pages", "POST",
                 {"parent": {"type": "data_source_id", "data_source_id": ds_id},
                  "properties": body})
    if blocks:
        # 노션은 한 번에 100 블록까지 받는다.
        for i in range(0, len(blocks), 100):
            _call(f"/blocks/{page['id']}/children", "PATCH",
                  {"children": blocks[i:i + 100]})
    print(f"\n행을 만들었다. 칸 {len(body)}개 · 본문 {len(blocks)}블록")
    print(page.get("url", page["id"]))


if __name__ == "__main__":
    main()
