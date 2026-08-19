#!/usr/bin/env python3
"""⑨ 출력을 노션 DB 행으로 만든다.

**미리보기가 기본이다.** `--commit` 을 붙여야 실제로 쓴다.
기존 행을 고치지 않는다. 새 행만 만든다.

    python tools/notion_row.py 검증 out9.txt
    python tools/notion_row.py 검증 out9.txt --exclude "검증 자료,한계"
    python tools/notion_row.py 검증 out9.txt --set "검증자=최현서"
    python tools/notion_row.py 검증 out9.txt --commit

입력 파일은 ⑨ 출력 그대로다. 한 줄에 `칸 이름: 값` 형식.
빈 값과 자동 생성 칸(생성일, 최근 1주 등)은 알아서 건너뛴다.
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


def build(props: dict, values: dict[str, str]) -> tuple[dict, list[str], list[str]]:
    """노션 properties 를 만든다. 못 넣은 것과 경고를 함께 낸다."""
    body: dict = {}
    skipped: list[str] = []
    warn: list[str] = []

    for key, raw in values.items():
        if key not in props:
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
        else:
            skipped.append(f"{key}  다루지 않는 칸 종류 {t}")
    return body, skipped, warn


def show(dbname: str, props: dict, body: dict, skipped: list[str],
         warn: list[str], excluded: list[str]) -> None:
    print(f"\n대상 DB   {dbname}")
    print(f"넣을 칸   {len(body)}개\n")
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

    values = parse_output(Path(args.infile).read_text(encoding="utf-8"))

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

    show(dbname, props, body, skipped, warn, excluded)

    if not args.commit:
        print("\n미리보기다. 실제로 쓰지 않았다.")
        print("뺄 칸이 있으면  --exclude \"칸1,칸2\"")
        print("고칠 칸이 있으면 --set \"칸=값\"")
        print("그대로 올리려면 --commit")
        return

    page = _call("/pages", "POST",
                 {"parent": {"type": "data_source_id", "data_source_id": ds_id},
                  "properties": body})
    print(f"\n행을 만들었다.\n{page.get('url', page['id'])}")


if __name__ == "__main__":
    main()
