#!/usr/bin/env python3
"""SQL 덤프의 표 구조를 트리로 낸다. 유출 범위를 한눈에 본다.

파일 트리(tree_scan.py)는 디렉터리와 파일을 본다.
이것은 표와 칸을 본다. DB 덤프에서는 이쪽이 유출 범위를 보여준다.

**칸 이름과 건수만 읽는다. 값을 하나도 출력하지 않는다.**
유출물이 있는 기계 안에서 돌리고 이 출력만 가져가면 된다.

    python db_tree.py treethink.sql
    python db_tree.py dump.sql --md 출력.md

CREATE TABLE 이 없는 덤프도 INSERT 로 표와 칸을 되살린다.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?([\w.]+)[`\"\]]?\s*\(", re.I)
INSERT = re.compile(r"INSERT\s+INTO\s+[`\"\[]?([\w.]+)[`\"\]]?\s*(?:\(([^)]*)\))?\s*VALUES", re.I)
COLNAME = re.compile(r"^[`\"\[]?(\w+)[`\"\]]?\s")
SKIP = re.compile(r"^(PRIMARY|UNIQUE|KEY|INDEX|CONSTRAINT|FOREIGN|CHECK|FULLTEXT|SPATIAL)\b", re.I)


def split_defs(body: str) -> list[str]:
    """CREATE TABLE 괄호 안을 최상위 쉼표로 나눈다.

    줄 단위로 자르면 한 줄짜리 CREATE TABLE 에서 첫 칸만 읽힌다.
    varchar(20) 같은 괄호와 따옴표 안의 쉼표는 건너뛴다.
    """
    out, cur, depth, quote = [], [], 0, ""
    for c in body:
        if quote:
            cur.append(c)
            if c == quote:
                quote = ""
            continue
        if c in "'\"`":
            quote = c
            cur.append(c)
        elif c == "(":
            depth += 1
            cur.append(c)
        elif c == ")":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
    if cur:
        out.append("".join(cur).strip())
    return out

SENSITIVE = [
    ("주민번호", r"jumin|ssn|rrn|resident|주민"),
    ("이름", r"^name$|user_?name|real_?name|이름|_nm$|^nm$"),
    ("이메일", r"e?mail|이메일"),
    ("전화", r"tel|phone|mobile|^hp$|휴대|전화"),
    ("주소", r"addr|주소|zip|우편"),
    ("생년월일", r"birth|생년|생일"),
    ("계정", r"passw|pwd|^pws$|login|userid|user_?id|account"),
    ("카드·금융", r"card|bank|account_?no|계좌|카드"),
    ("결제·주문", r"order|pay|buy|price|amount|주문|결제"),
]


def sens_of(col: str) -> str | None:
    low = col.lower()
    for label, rx in SENSITIVE:
        if re.search(rx, low):
            return label
    return None


def scan(path: Path) -> tuple[OrderedDict, Counter, int]:
    """표별 칸 목록과 INSERT 튜플 수를 센다. 값은 읽지 않는다."""
    tables: OrderedDict[str, list[str]] = OrderedDict()
    rows: Counter = Counter()
    size = path.stat().st_size
    buf = ""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            buf += line
            if len(buf) < 200_000 and ";" not in line:
                continue
            for m in CREATE.finditer(buf):
                name = m.group(1)
                body = buf[m.end():]
                depth, end = 1, 0
                for i, c in enumerate(body):
                    if c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                cols = []
                for d in split_defs(body[:end]):
                    if not d or SKIP.match(d):
                        continue
                    m2 = COLNAME.match(d)
                    if m2:
                        cols.append(m2.group(1))
                if cols:
                    tables.setdefault(name, cols)
            for m in INSERT.finditer(buf):
                name = m.group(1)
                if m.group(2) and name not in tables:
                    tables[name] = [c.strip().strip('`"[] ') for c in m.group(2).split(",")]
                tables.setdefault(name, [])
                tail = buf[m.end():]
                rows[name] += tail.count("),(") + tail.count("), (") + (1 if "(" in tail else 0)
            buf = ""
    return tables, rows, size


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="SQL 덤프")
    ap.add_argument("--md", default="", help="결과를 이 파일로")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"없는 파일: {path}")
    tables, rows, size = scan(path)
    if not tables:
        raise SystemExit("표를 못 찾았다. SQL 덤프가 맞는지 확인할 것")

    L = []
    L.append(f"# DB 구조  {path.name}")
    L.append("")
    L.append(f"- 표 {len(tables)}개 · 파일 {size:,} 바이트")
    L.append(f"- INSERT 로 센 행 합계 {sum(rows.values()):,} (구분자 기준. 어림값이다)")
    L.append("")
    L.append("**칸 이름과 건수만 읽었다. 값은 하나도 없다.**")
    L.append("")

    L.append("## 표 트리")
    L.append("")
    L.append("```")
    for i, (t, cols) in enumerate(tables.items()):
        last = i == len(tables) - 1
        n = rows.get(t, 0)
        L.append(f"{'└── ' if last else '├── '}{t}" + (f"  ({n:,}행)" if n else ""))
        mark = "    " if last else "│   "
        shown = [c for c in cols if sens_of(c)]
        rest = len(cols) - len(shown)
        lines = [f"{c}  <- {sens_of(c)}" for c in shown]
        if rest > 0:
            lines.append(f"그 밖 {rest}칸")
        if not lines:
            lines.append("칸을 못 읽음")
        for j, s in enumerate(lines):
            L.append(f"{mark}{'└── ' if j == len(lines) - 1 else '├── '}{s}")
    L.append("```")
    L.append("")
    L.append("표시된 칸만 개인정보로 보이는 것이다. 나머지는 접었다.")
    L.append("")

    L.append("## 표별 규모")
    L.append("")
    L.append("| 표 | 칸 | 행(어림) | 개인정보 칸 |")
    L.append("|---|---|---|---|")
    for t, cols in sorted(tables.items(), key=lambda kv: -rows.get(kv[0], 0)):
        s = [c for c in cols if sens_of(c)]
        L.append(f"| {t} | {len(cols)} | {rows.get(t, 0):,} | {len(s)} |")
    L.append("")

    L.append("## 개인정보 종류별로 어느 표에 있나")
    L.append("")
    bykind: dict[str, list[str]] = {}
    for t, cols in tables.items():
        for c in cols:
            k = sens_of(c)
            if k:
                bykind.setdefault(k, []).append(f"{t}.{c}")
    if bykind:
        L.append("| 종류 | 자리 |")
        L.append("|---|---|")
        for k, v in sorted(bykind.items(), key=lambda kv: -len(kv[1])):
            L.append(f"| {k} | {len(v)}곳 · " + ", ".join(v[:6]) + (" ..." if len(v) > 6 else "") + " |")
    else:
        L.append("칸 이름으로는 개인정보가 안 잡혔다. 칸 이름이 축약이거나 영문이 아닐 수 있다.")
    L.append("")

    L.append("## 어디에 쓰나")
    L.append("")
    L.append("| 검증 항목 | 이 출력에서 |")
    L.append("|---|---|")
    L.append("| 규모 검증 | 표별 행 수를 주장 규모와 대조한다 |")
    L.append("| 내용 일치 | 게시글이 주장한 항목이 실제 칸에 있는지 본다 |")
    L.append("| 자산 민감도 | 개인정보 종류와 표 개수 |")
    L.append("| 피해 범위 | 회원만인지 주문·상담까지인지 |")
    L.append("")
    L.append("## 못 봄으로 적을 것")
    L.append("")
    L.append("    값의 실재 여부   칸 이름만 읽었다. 값을 안 봤다")
    L.append("    정확한 행 수     구분자로 센 어림값이다. COUNT 를 돌린 것이 아니다")
    L.append("    칸 이름이 축약   무슨 값인지 이름만으로는 모른다")

    out = "\n".join(L)
    if args.md:
        Path(args.md).write_text(out, encoding="utf-8")
        print(f"{args.md} 에 썼다. 표 {len(tables)}개")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(out)


if __name__ == "__main__":
    main()
