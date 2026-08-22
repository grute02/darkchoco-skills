#!/usr/bin/env python3
"""SQL 덤프의 표 구조를 트리로 낸다. 유출 범위를 한눈에 본다.

파일 트리(tree_scan.py)는 디렉터리와 파일을 본다.
이것은 표와 칸을 본다. DB 덤프에서는 이쪽이 유출 범위를 보여준다.

**칸 이름과 건수만 읽는다. 값을 하나도 출력하지 않는다.**

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


# 표 단위 등급. tree_scan 의 파일 단위 등급과 축이 다르다. 합치지 않는다.
# tree_scan 은 파일명만 봐서 덤프 하나에 든 표 수십 개를 못 가른다.
ADMIN = re.compile(r"master|admin|manager|^root|super_?user|operator|관리자", re.I)
# 자격증명 값이 드는 칸. 아이디만 있는 칸과 가른다.
# order_admin_memo 같은 칸이 관리자 자격증명으로 잡히던 오탐을 막는다.
PWD = re.compile(r"passw|pwd|^pws$|secret|token|api_?key|해시|비밀번호", re.I)
PUBLIC = re.compile(r"^zip|우편|postal|^code$|region|sido|gugun|법정동|행정동", re.I)
IDENT = {"이름", "이메일", "전화", "주소"}
GRADES = ["치명", "높음", "중간", "낮음", "미분류"]


def grade_of(table: str, cols: list[str]) -> tuple[str, str]:
    """(등급, 왜). 칸 이름만 보고 매긴다. 값이 실제로 있는지는 못 본다."""
    kinds = {k for k in (sens_of(c) for c in cols) if k}
    pwd = [c for c in cols if PWD.search(c)]
    # 한 칸이 관리자와 비밀번호를 둘 다 만족하거나, 표 이름이 관리자 계열이면서 비밀번호 칸이 있을 때
    if [c for c in pwd if ADMIN.search(c)] or (ADMIN.search(table) and pwd):
        return "치명", "관리자 자격증명 칸이 있다"
    if "주민번호" in kinds:
        return "높음", "주민번호 칸이 있다. 값이 들었는지는 못 봤다"
    if "카드·금융" in kinds:
        return "높음", "카드·금융 칸이 있다"
    if pwd:
        return "높음", "비밀번호 칸이 있다 (%s)" % ", ".join(pwd[:3])
    if PUBLIC.search(table) and not (kinds - {"주소"}):
        return "낮음", "공개 데이터로 보이는 표다"
    ident = kinds & IDENT
    if len(ident) >= 2:
        return "높음", "신원 칸이 %d종이다 (%s)" % (len(ident), ", ".join(sorted(ident)))
    if ident:
        return "중간", "신원 칸이 하나다 (%s)" % ", ".join(sorted(ident))
    if kinds & {"계정", "결제·주문", "생년월일"}:
        return "중간", "계정 아이디나 이력 칸이 있다 (%s)" % ", ".join(sorted(kinds))
    return "미분류", "개인정보로 보이는 칸이 없다"


def count_tuples(tail: str) -> tuple[int, str]:
    """INSERT 의 VALUES 뒤를 받아 튜플 수와 센 방식을 돌려준다. 값은 읽지 않는다.

    여는 괄호로 줄이 시작하면 거기서 튜플이 하나 시작하고,
    `),(` 로 이어 붙은 수만큼 그 줄에 튜플이 더 있다.
    이 한 식으로 아래 세 형식을 다 센다.

        줄 단위 튜플    phpMyAdmin 내보내기. 튜플이 한 줄에 하나씩 온다
        확장 INSERT     mysqldump 기본. 한 줄에 튜플이 이어 붙는다
        문장당 한 튜플   INSERT 문 하나에 튜플 하나

    값 안에 든 괄호는 줄 첫 글자가 아니라서 세지 않는다.
    값 안에 진짜 줄바꿈이 있으면 더 세므로 어림값이다.
    """
    joined = tail.count("),(") + tail.count("), (")
    heads = sum(1 for ln in tail.splitlines() if ln.lstrip().startswith("("))
    if heads > 1:
        how = "줄 단위 튜플"
    elif joined:
        how = "확장 INSERT"
    else:
        how = "문장당 한 튜플"
    return heads + joined, how


def scan(path: Path) -> tuple[OrderedDict, Counter, int, Counter]:
    """표별 칸 목록과 INSERT 튜플 수를 센다. 값은 읽지 않는다."""
    tables: OrderedDict[str, list[str]] = OrderedDict()
    rows: Counter = Counter()
    methods: Counter = Counter()
    size = path.stat().st_size
    buf = ""
    pending = ""
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
            hits = list(INSERT.finditer(buf))
            if pending:
                # 읽기 버퍼는 세미콜론이 든 줄마다 비워진다. 값 안에 세미콜론이 있으면
                # 한 INSERT 의 튜플이 여러 버퍼로 갈린다. 첫 INSERT 앞에 남은 줄은
                # 앞 버퍼에서 이어진 것이다. 기억하지 않으면 통째로 버려진다.
                head = buf[:hits[0].start()] if hits else buf
                rows[pending] += count_tuples(head)[0]
            for i, m in enumerate(hits):
                name = m.group(1)
                if m.group(2) and name not in tables:
                    tables[name] = [c.strip().strip('`"[] ') for c in m.group(2).split(",")]
                tables.setdefault(name, [])
                stop = hits[i + 1].start() if i + 1 < len(hits) else len(buf)
                n, how = count_tuples(buf[m.end():stop])
                rows[name] += n
                methods[how] += 1
            if hits:
                pending = hits[-1].group(1)
            buf = ""
    return tables, rows, size, methods


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="SQL 덤프")
    ap.add_argument("--md", default="", help="결과를 이 파일로")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"없는 파일: {path}")
    tables, rows, size, methods = scan(path)
    if not tables:
        raise SystemExit("표를 못 찾았다. SQL 덤프가 맞는지 확인할 것")

    L = []
    L.append(f"# DB 구조  {path.name}")
    L.append("")
    L.append(f"- 표 {len(tables)}개 · 파일 {size:,} 바이트")
    L.append(f"- INSERT 로 센 행 합계 {sum(rows.values()):,} (구분자 기준. 어림값이다)")
    if methods:
        L.append("- 집계 방식 " + ", ".join(f"{k} {v}건" for k, v in methods.most_common()))
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

    graded = {t: grade_of(t, cols) for t, cols in tables.items()}
    bygrade: Counter = Counter(g for g, _ in graded.values())

    L.append("## 표 단위 자산 민감도")
    L.append("")
    L.append("**`tree_scan` 의 파일 단위 등급과 축이 다르다. 합치지 마라.**")
    L.append("파일명만 보는 도구는 덤프 하나에 든 표 수십 개를 못 가른다.")
    L.append("여기서 치명이 나와도 파일 단위로는 미분류일 수 있다. 둘 다 적는다.")
    L.append("")
    L.append("| 등급 | 표 |")
    L.append("|---|---|")
    for g in GRADES:
        L.append(f"| {g} | {bygrade.get(g, 0)} |")
    L.append("")
    L.append("등급을 하나로 합치지 않는다. 치명 1행과 중간 50만행은 성격이 다르다.")
    L.append("")
    jumin = [t for t, (_, why) in graded.items() if "주민번호" in why]
    if jumin:
        L.append(f"**주민번호 칸이 {len(jumin)}개 표에 있다.** "
                 + ", ".join(jumin[:8]) + (" ..." if len(jumin) > 8 else ""))
        L.append("칸이 있다는 것과 값이 들었다는 것은 다르다.")
        L.append("`sample_stats <덤프> --table <표>` 로 채움률을 보고 등급을 확정한다.")
        L.append("")

    L.append("## 표별 규모")
    L.append("")
    L.append("| 표 | 등급 | 칸 | 행(어림) | 개인정보 칸 | 왜 |")
    L.append("|---|---|---|---|---|---|")
    order = {g: i for i, g in enumerate(GRADES)}
    for t, cols in sorted(tables.items(),
                          key=lambda kv: (order[graded[kv[0]][0]], -rows.get(kv[0], 0))):
        s = [c for c in cols if sens_of(c)]
        g, why = graded[t]
        L.append(f"| {t} | **{g}** | {len(cols)} | {rows.get(t, 0):,} | {len(s)} | {why} |")
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
    L.append("| 자산 민감도 | **표 단위 자산 민감도 절.** 파일 단위와 나란히 적는다 |")
    L.append("| 피해 범위 | 회원만인지 주문·상담까지인지 |")
    L.append("")
    L.append("## 못 봄으로 적을 것")
    L.append("")
    L.append("    값의 실재 여부   칸 이름만 읽었다. 값을 안 봤다")
    L.append("    정확한 행 수     구분자로 센 어림값이다. COUNT 를 돌린 것이 아니다")
    L.append("    칸 이름이 축약   무슨 값인지 이름만으로는 모른다")
    L.append("    표 단위 등급     칸 이름 기준이다. 값이 비어 있어도 등급이 내려가지 않는다")

    out = "\n".join(L)
    if args.md:
        Path(args.md).write_text(out, encoding="utf-8")
        print(f"{args.md} 에 썼다. 표 {len(tables)}개")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(out)


if __name__ == "__main__":
    main()
