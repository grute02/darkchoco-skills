#!/usr/bin/env python3
"""샘플 데이터의 값 분포를 낸다. 정밀 분석에 쓴다.

초동 분석에는 안 쓴다. 거기서는 tree_scan 과 db_tree 로 범위만 본다.
이것은 값이 진짜 같은지 볼 때 쓴다. 김철수·홍길동·12345678 처럼
지어낸 값으로 채워져 있는지가 진위 판정에 걸린다.

**전부 읽는 것이 기본이다.** 행 수와 칸 종류를 다 세려면 잘라 보면 안 된다.
--rows 를 주면 그만큼만 읽고, 잘랐다는 사실을 출력에 적는다.

    python sample_stats.py member.csv
    python sample_stats.py treethink.sql --table member_tb
    python sample_stats.py member.csv --rows 50000 --md 출력.md

**출력에 값이 하나도 안 나온다.** 분포와 규칙성만 낸다.
CSV 와 SQL INSERT 덤프를 받는다.
파이썬 3 표준 라이브러리만 쓴다. Kali VM 에서 그대로 돈다.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from collections import Counter
from pathlib import Path

MAX_ROWS = 0          # 0 이면 전부 읽는다
TOP_DOMAIN = 8

PAT = {
    "이메일": re.compile(r"^[\w.+-]{1,64}@[\w-]+\.[\w.]{2,}$"),
    "휴대전화": re.compile(r"^01[016789][-. ]?\d{3,4}[-. ]?\d{4}$"),
    "유선전화": re.compile(r"^0(?!1)\d{1,2}[-. ]?\d{3,4}[-. ]?\d{4}$"),
    "주민번호형": re.compile(r"^\d{6}[-]?\d{7}$"),
    # MySQL 4.1 이후 비밀번호 해시는 * 를 붙인 40자 16진수다. 유출물에 자주 보인다
    "해시형": re.compile(r"^\*?[0-9a-fA-F]{32,128}$"),
    "base64형": re.compile(r"^[A-Za-z0-9+/]{16,}={0,2}$"),
    "날짜": re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"),
    "숫자": re.compile(r"^-?\d+(\.\d+)?$"),
    "우편번호": re.compile(r"^\d{5}$|^\d{3}-\d{3}$"),
    # 행정구역 접미 뒤에 공백이 오거나 도로명 뒤에 번호가 오는 것만 본다.
    # 옛 규칙은 (시|도|구|...) 한 글자라 아무 한글 문장에나 걸렸다.
    "주소": re.compile(r"[가-힣]{2,10}(?:특별시|광역시|특별자치[시도]|[시군구])\s"
                       r"|[가-힣]{2,10}(?:대?로|길)\s*\d"),
    "한글이름": re.compile(r"^[가-힣]{2,5}$"),
}
NULLS = {"", "null", "NULL", "\\N", "None", "-"}

# 지어낸 값에 자주 쓰이는 것들. 걸리면 합성을 의심한다
DUMMY_NAME = {"홍길동", "홍길순", "김철수", "김영희", "이영희", "박철수", "아무개",
              "테스트", "test", "tester", "admin", "administrator", "guest",
              "user", "sample", "dummy", "john doe", "jane doe", "foo", "bar"}
DUMMY_MARK = re.compile(r"^(test|sample|dummy|temp|tmp|asdf|qwer|abc|aaa)", re.I)
SEQ = re.compile(r"(0123456789|1234567890|9876543210|12345678)")
REPEAT = re.compile(r"(.)\1{5,}")


def synth_marks(vals: list[str]) -> list[str]:
    """지어낸 값으로 보이는 흔적. 값 자체는 내지 않고 건수만 센다."""
    out = []
    if not vals:
        return out
    n = len(vals)
    dummy = sum(1 for v in vals if v.strip().lower() in DUMMY_NAME
                or v.strip() in DUMMY_NAME or DUMMY_MARK.match(v.strip()))
    if dummy:
        out.append(f"흔한 더미 값 {dummy}건 ({dummy*100//n}%)")
    seq = sum(1 for v in vals if SEQ.search(re.sub(r"[^0-9]", "", v)))
    if seq:
        out.append(f"연속 숫자가 든 값 {seq}건 ({seq*100//n}%)")
    rep = sum(1 for v in vals if REPEAT.search(v))
    if rep:
        out.append(f"같은 글자 6회 이상 반복 {rep}건 ({rep*100//n}%)")
    top = Counter(vals).most_common(1)[0]
    if n >= 20 and top[1] * 100 // n >= 20:
        out.append(f"한 값이 {top[1]}건 ({top[1]*100//n}%)으로 몰려 있다")
    return out
HASH_LEN = {32: "MD5", 40: "SHA-1", 56: "SHA-224", 64: "SHA-256", 128: "SHA-512"}


def read_csv(path: Path, limit: int) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        head = f.read(8192)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(head, delimiters=",\t|;")
        except csv.Error:
            dialect = csv.excel
        r = csv.reader(f, dialect)
        try:
            header = next(r)
        except StopIteration:
            return [], []
        rows = []
        for i, row in enumerate(r):
            if limit and i >= limit:
                break
            rows.append(row)
    if any(PAT["숫자"].match(h or "") for h in header) and len(header) > 2:
        rows.insert(0, header)
        header = [f"칸{i+1}" for i in range(len(header))]
    return header, rows


TUPLE = re.compile(r"\(((?:[^()']|'(?:[^']|'')*')*)\)")


def split_values(body: str) -> list[str]:
    out, cur, quote = [], [], False
    i = 0
    while i < len(body):
        c = body[i]
        if quote:
            if c == "'":
                if i + 1 < len(body) and body[i + 1] == "'":
                    cur.append("'")
                    i += 2
                    continue
                quote = False
            else:
                cur.append(c)
        elif c == "'":
            quote = True
        elif c == ",":
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur).strip())
    return out


def read_sql(path: Path, limit: int, table: str) -> tuple[list[str], list[list[str]]]:
    header: list[str] = []
    rows: list[list[str]] = []
    ins = re.compile(r"INSERT\s+INTO\s+[`\"\[]?([\w.]+)[`\"\]]?\s*(\(([^)]*)\))?\s*VALUES",
                     re.I)
    with path.open("r", encoding="utf-8", errors="replace") as f:
        buf = ""
        for line in f:
            if limit and len(rows) >= limit:
                break
            buf += line
            if ";" not in buf and len(buf) < 1_000_000:
                continue
            m = ins.search(buf)
            if m:
                if table and table.lower() not in m.group(1).lower():
                    buf = ""
                    continue
                if m.group(3) and not header:
                    header = [c.strip().strip('`"[]') for c in m.group(3).split(",")]
                for t in TUPLE.findall(buf[m.end():]):
                    rows.append(split_values(t))
                    if limit and len(rows) >= limit:
                        break
            buf = ""
    if not header and rows:
        header = [f"칸{i+1}" for i in range(len(rows[0]))]
    return header, rows


ADDR_MAX = 120     # 주소는 이보다 길지 않다
LONG_TEXT = 1000   # 이보다 긴 값이 있고 가운뎃값도 크면 자유 서술로 본다


def guess(vals: list[str]) -> str:
    """빈 값을 뺀 값들로 종류를 고른다. 가장 많이 맞는 하나."""
    if not vals:
        return "빈 칸"
    sample = vals[:2000]
    L = sorted(len(v) for v in sample)
    med = L[len(L) // 2]

    # 게시판 본문 같은 자유 서술을 먼저 가른다.
    # 안 그러면 주소 규칙이 긴 한글 문장에 걸려 개인정보 칸으로 계상된다.
    if med > ADDR_MAX or (L[-1] > LONG_TEXT and med > 40):
        return "긴 텍스트"

    score = Counter()
    for v in sample:
        for name, rx in PAT.items():
            if name == "주소":
                ok = len(v) <= ADDR_MAX and rx.search(v)
            else:
                ok = rx.match(v)
            if ok:
                score[name] += 1
    if not score:
        return "긴 텍스트" if L[-1] > 200 else "기타 문자열"
    name, n = score.most_common(1)[0]
    return name if n >= len(sample) * 0.5 else "혼합"


def describe(name: str, kind: str, vals: list[str], total: int) -> list[str]:
    """한 칸의 패턴 서술. 값은 절대 넣지 않는다."""
    out = []
    filled = len(vals)
    uniq = len(set(vals))
    out.append(f"  종류      {kind}")
    out.append(f"  채움      {filled}/{total} ({filled*100//max(1,total)}%)")
    if filled:
        out.append(f"  고유값    {uniq} ({uniq*100//filled}%) · 중복률 {100-uniq*100//filled}%")
        L = [len(v) for v in vals]
        out.append(f"  길이      최소 {min(L)} · 최대 {max(L)} · 평균 {sum(L)//len(L)}")

    if kind == "이메일" and filled:
        dom = Counter(v.rsplit("@", 1)[-1].lower() for v in vals)
        top = " · ".join(f"{d} {c*100//filled}%" for d, c in dom.most_common(TOP_DOMAIN))
        out.append(f"  도메인    {len(dom)}종 · {top}")
        bad = sum(1 for v in vals if not PAT["이메일"].match(v))
        out.append(f"  형식      유효 {filled-bad} · 깨짐 {bad}")
    elif kind in ("휴대전화", "유선전화") and filled:
        band = Counter(re.sub(r"[^0-9]", "", v)[:3] for v in vals)
        out.append(f"  대역      " + " · ".join(f"{b} {c*100//filled}%" for b, c in band.most_common(6)))
        dig = Counter(len(re.sub(r"[^0-9]", "", v)) for v in vals)
        out.append(f"  자릿수    " + " · ".join(f"{d}자리 {c}건" for d, c in dig.most_common(4)))
    elif kind == "주민번호형" and filled:
        yy = Counter(v[:2] for v in vals)
        out.append(f"  생년 앞2자리 {len(yy)}종 · 최다 {yy.most_common(1)[0][1]}건")
        sexd = Counter(re.sub(r"[^0-9]", "", v)[6:7] for v in vals)
        out.append(f"  성별자리  " + " · ".join(f"{k or '?'} {c}건" for k, c in sexd.most_common(6)))
        ok = sum(1 for v in vals if checksum_ok(re.sub(r"[^0-9]", "", v)))
        out.append(f"  체크섬    통과 {ok}/{filled} ({ok*100//filled}%)")
    elif kind == "해시형" and filled:
        star = sum(1 for v in vals if v.startswith("*"))
        ln = Counter(len(v.lstrip("*")) for v in vals)
        out.append("  길이별    " + " · ".join(
            f"{n}자 {HASH_LEN.get(n, '미상')} {c}건" for n, c in ln.most_common(4)))
        if star:
            out.append(f"  접두 *    {star}건. MySQL 비밀번호 해시 형식이다")
        out.append("  주의      해시라 원본 값을 확인할 수 없다. 진위 판정에서 못 봄으로 둔다")
    elif kind == "날짜" and filled:
        yr = Counter(v[:4] for v in vals)
        out.append(f"  연도      {min(yr)}~{max(yr)} · {len(yr)}종")
    elif kind == "숫자" and filled:
        nums = sorted(int(float(v)) for v in vals if PAT["숫자"].match(v))
        if nums:
            lo, hi = len(str(abs(nums[0]))), len(str(abs(nums[-1])))
            out.append(f"  자릿수    {lo}자리 ~ {hi}자리"
                       + (" · 음수 있음" if nums[0] < 0 else ""))
            step = [b - a for a, b in zip(nums, nums[1:])]
            if step and all(s == 1 for s in step):
                out.append("  주의      1씩 연속 증가한다. 자동 채번이거나 생성값일 수 있다")
    elif kind == "한글이름" and filled:
        sur = Counter(v[0] for v in vals)
        out.append(f"  성씨      {len(sur)}종 · 최다 {sur.most_common(1)[0][1]}건 "
                   f"({sur.most_common(1)[0][1]*100//filled}%)")
    elif kind == "긴 텍스트" and filled:
        out.append("  주의      자유 서술이다. 칸 단위로는 개인정보 여부를 못 가른다")
        out.append("            안에 이름·전화·주소가 섞일 수 있다. 사람이 표본을 봐야 한다")
    elif kind == "주소" and filled:
        head = Counter(v.split()[0] for v in vals if v.split())
        out.append(f"  앞 단어    {len(head)}종 · 최다 {head.most_common(1)[0][1]}건")

    for m in synth_marks(vals):
        out.append(f"  합성 의심   {m}")
    return out


def checksum_ok(d: str) -> bool:
    if len(d) != 13 or not d.isdigit():
        return False
    w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    s = sum(int(d[i]) * w[i] for i in range(12))
    return (11 - s % 11) % 10 == int(d[12])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="CSV 또는 SQL 덤프")
    ap.add_argument("--rows", type=int, default=MAX_ROWS,
                    help="읽을 행 수 상한. 안 주면 전부 읽는다")
    ap.add_argument("--table", default="", help="SQL 에서 이 표만")
    ap.add_argument("--md", default="", help="결과를 이 파일로")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"없는 파일: {path}")

    if path.suffix.lower() == ".sql":
        header, rows = read_sql(path, args.rows, args.table)
    else:
        header, rows = read_csv(path, args.rows)

    if not rows:
        raise SystemExit("행을 못 읽었다. --table 을 주거나 형식을 확인할 것")

    n = len(header)
    cols: list[list[str]] = [[] for _ in range(n)]
    ragged = 0
    for r in rows:
        if len(r) != n:
            ragged += 1
        for i in range(min(n, len(r))):
            v = (r[i] or "").strip()
            if v not in NULLS:
                cols[i].append(v)

    L = []
    L.append(f"# 샘플 패턴  {path.name}")
    L.append("")
    L.append(f"- 읽은 행 {len(rows):,}" +
             (f" · **상한 {args.rows:,} 에서 잘랐다. 전체가 아니다**" if args.rows else " · 전부 읽었다"))
    L.append(f"- 칸 {n}개" + (f" · 칸 수가 다른 행 {ragged}건" if ragged else ""))
    L.append(f"- 파일 크기 {path.stat().st_size:,} 바이트")
    L.append("")
    L.append("**실제 값은 하나도 없다.** 분포와 규칙성만 적었다.")
    L.append("")
    L.append("## 칸 목록")
    L.append("")
    L.append("```")
    L.append(", ".join(header))
    L.append("```")
    L.append("")
    L.append("## 칸별 패턴")
    L.append("")
    risky = []
    for i, name in enumerate(header):
        kind = guess(cols[i])
        L.append(f"### {name}")
        L += describe(name, kind, cols[i], len(rows))
        L.append("")
        if kind in ("주민번호형", "휴대전화", "유선전화", "이메일", "한글이름", "주소"):
            risky.append((name, kind, len(cols[i])))

    L.append("## 개인정보로 보이는 칸")
    L.append("")
    if risky:
        L.append("| 칸 | 종류 | 채운 행 |")
        L.append("|---|---|---|")
        for name, kind, c in risky:
            L.append(f"| {name} | {kind} | {c:,} |")
    else:
        L.append("없음")
    L.append("")
    L.append("## 합성 의심 정리")
    L.append("")
    synth = []
    for i, name in enumerate(header):
        for m in synth_marks(cols[i]):
            synth.append((name, m))
    if synth:
        L.append("| 칸 | 흔적 |")
        L.append("|---|---|")
        for name, m in synth:
            L.append(f"| {name} | {m} |")
        L.append("")
        L.append("**흔적 하나로 허위를 확정하지 않는다.** 마스킹된 데이터도 이렇게 보인다.")
        L.append("여러 칸에 동시에 걸리면 그때 무게가 실린다.")
    else:
        L.append("걸린 것이 없다. 값이 지어낸 것으로 보이지는 않는다.")
    L.append("")
    L.append("## 사람이 확인할 것")
    L.append("")
    L.append("- 종류가 혼합이거나 기타 문자열인 칸의 내용 성격")
    L.append("- 연속 증가 주의가 붙은 칸이 자동 채번인지 생성값인지")
    L.append("- 체크섬 통과율이 낮으면 합성일 수 있다. 다만 마스킹된 값도 낮게 나온다")
    L.append("")
    L.append("## 이 출력을 어디에 쓰나")
    L.append("")
    L.append("④ 마스킹 결과 자리에 그대로 넣는다. ⑤ 재료 합치기의 샘플 블록이 된다.")
    L.append("합성 의심은 ⑥ 반대 증거와 진위 판정 근거로 쓴다.")

    out = "\n".join(L)
    if args.md:
        Path(args.md).write_text(out, encoding="utf-8")
        print(f"{args.md} 에 썼다. {len(out):,}자")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(out)


if __name__ == "__main__":
    main()
