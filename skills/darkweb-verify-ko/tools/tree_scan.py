#!/usr/bin/env python3
"""파일 트리 위험도 분석기.

파일 목록만 읽는다. 파일 내용은 열지 않는다.
값을 보지 않으므로 마스킹 없이 돌릴 수 있다.

    python tools/tree_scan.py <트리파일> [--rules tree_rules.json] [--md 출력.md]

입력 형식은 아래를 받는다.
    한 줄에 경로 하나
    tree 명령 출력 (가지 문자 포함)
    unzip -l, find, git ls-files 출력
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

BRANCH = re.compile(r"^[\s│├└─|`+\-]*")
SIZE_LINE = re.compile(r"^\s*(\d+)\s+[\d-]{8,10}\s+[\d:]{5,8}\s+(.+)$")
NOISE = re.compile(
    r"^\s*(Archive:|Length\s+Date|-{3,}|$)"       # 머리말과 구분선
    r"|^[\s\d,]*\d+\s+files?\s*$"                  # unzip -l 꼬리 합계
    r"|^[\s\d,]*\d+\s+file\(s\)"                   # dir 명령 꼬리 합계
)
HAS_BRANCH = re.compile(r"[│├└]|\|--|`--")


def _depth(raw: str) -> int:
    """tree 출력의 들여쓰기 깊이. 한 단계가 4칸이다."""
    return len(BRANCH.match(raw).group(0)) // 4


def _from_tree(lines: list[str]) -> tuple[list[str], list[str]]:
    """tree 명령 출력에서 온전한 경로를 되살린다.

    가지 문자만 떼면 상위 디렉터리가 날아가 .git/config 같은 규칙이 안 걸린다.
    깊이로 스택을 쌓아 이어 붙이고, 자식이 없는 줄만 낸다.
    디렉터리까지 세면 건수가 부풀어 규모 대조가 어긋난다.
    """
    nodes: list[tuple[int, str]] = []
    dropped: list[str] = []
    for raw in lines:
        if NOISE.match(raw):
            dropped.append(raw)
            continue
        name = BRANCH.sub("", raw).strip().rstrip("/")
        if not name or name.endswith(":"):
            dropped.append(raw)
            continue
        nodes.append((_depth(raw), name))

    paths: list[str] = []
    stack: list[str] = []
    for i, (d, name) in enumerate(nodes):
        del stack[d:]
        stack.append(name)
        child = i + 1 < len(nodes) and nodes[i + 1][0] > d
        if not child:
            paths.append("/".join(stack))
    return paths, dropped


def parse_tree(text: str) -> tuple[list[str], list[str]]:
    """경로 목록과 못 읽은 줄을 낸다."""
    lines = [l.rstrip() for l in text.split("\n") if l.strip()]
    if any(HAS_BRANCH.search(l) for l in lines):
        return _from_tree(lines)

    paths: list[str] = []
    dropped: list[str] = []
    for line in lines:
        if NOISE.match(line):
            dropped.append(line)
            continue
        m = SIZE_LINE.match(line)
        if m:
            paths.append(m.group(2).strip())
            continue
        cleaned = BRANCH.sub("", line).strip()
        if not cleaned or cleaned.endswith(":"):
            dropped.append(line)
            continue
        paths.append(cleaned)
    return paths, dropped


def mask_path(p: str, pattern: re.Pattern) -> str:
    """개인정보가 걸린 부분만 가린다. 경로 구조는 남긴다."""
    return pattern.sub(lambda m: m.group(0)[0] + "○" * (len(m.group(0)) - 1), p)


def load_rules(path: Path) -> dict:
    rules = json.loads(path.read_text(encoding="utf-8"))
    for key in ("path", "진위신호", "자격증명값", "파일명개인정보"):
        for r in rules.get(key, []):
            r["_re"] = re.compile(r["정규식"])
    return rules


def scan(paths: list[str], rules: dict) -> dict:
    hits: dict[str, list[tuple[str, str, str]]] = {g: [] for g in rules["_등급"]}
    seen: set[str] = set()
    for p in paths:
        for r in rules["path"]:
            if r["_re"].search(p):
                if p not in seen:
                    hits[r["등급"]].append((p, r["이름"], r["왜"]))
                    seen.add(p)
                break

    signals: dict[str, list[str]] = {}
    for r in rules["진위신호"]:
        if r.get("대상") != "path":
            continue
        found = [p for p in paths if r["_re"].search(p)]
        if found:
            signals[r["이름"]] = found[:8]

    # 분석은 원문 경로로 한다. 출력에 실을 때만 걸린 부분을 가린다.
    pii: list[tuple[str, str]] = []
    for p in paths:
        for r in rules["파일명개인정보"]:
            if r["_re"].search(p):
                pii.append((mask_path(p, r["_re"]), r["이름"]))
                break

    ext: Counter = Counter()
    for p in paths:
        name = p.rsplit("/", 1)[-1]
        ext[name.rsplit(".", 1)[-1].lower() if "." in name else "(확장자없음)"] += 1
    depth = Counter(p.count("/") for p in paths)

    return {
        "등급별": hits,
        "진위신호": signals,
        "파일명개인정보": pii,
        "확장자": ext,
        "깊이": depth,
        "총건수": len(paths),
        "미분류": [p for p in paths if p not in seen],
    }


def report(res: dict, rules: dict, dropped: list[str], src: str) -> str:
    o: list[str] = []
    a = o.append

    a(f"# 파일 트리 분석  {src}")
    a("")
    a(f"경로 {res['총건수']}건. 파일 내용은 열지 않았다.")
    a("")

    a("## 자산 민감도")
    a("")
    a("| 등급 | 건수 |")
    a("|---|---|")
    for g in rules["_등급"]:
        a(f"| {g} | {len(res['등급별'][g])} |")
    a(f"| 미분류 | {len(res['미분류'])} |")
    a("")
    a("등급을 하나로 합치지 않는다. 치명 1건과 중간 500건은 성격이 다르다.")
    a("")

    for g in rules["_등급"]:
        rows = res["등급별"][g]
        if not rows:
            continue
        a(f"### {g} ({len(rows)}건)")
        a("")
        a("| 경로 | 규칙 | 왜 |")
        a("|---|---|---|")
        for p, name, why in rows[:40]:
            a(f"| {p} | {name} | {why} |")
        if len(rows) > 40:
            a(f"| 외 {len(rows) - 40}건 | | |")
        a("")

    a("## 진위 신호")
    a("")
    if res["진위신호"]:
        a("| 신호 | 예 |")
        a("|---|---|")
        for k, v in res["진위신호"].items():
            a(f"| {k} | {', '.join(v[:4])} |")
    else:
        a("못 봄 — 경로에서 진위 신호를 찾지 못했다. 내용 대상 규칙은 이 도구가 적용하지 않는다.")
    a("")

    a("## 파일명 개인정보")
    a("")
    if res["파일명개인정보"]:
        a(f"**{len(res['파일명개인정보'])}건. 아래 경로는 걸린 부분을 가려서 냈다.**")
        a("")
        a("분석은 원문 경로로 했다. 트리는 값이 아니라 이름과 구조라 원문 그대로 본다.")
        a("가린 것은 이 산출물이 밖으로 나가기 때문이다.")
        a("")
        a("| 경로 | 규칙 |")
        a("|---|---|")
        for p, name in res["파일명개인정보"][:20]:
            a(f"| {p} | {name} |")
    else:
        a("없음 — 규칙에 걸린 것이 없다. 규칙이 아는 형식만 본다.")
    a("")

    a("## 규모")
    a("")
    a("| 확장자 | 건수 |")
    a("|---|---|")
    for e, n in res["확장자"].most_common(15):
        a(f"| {e} | {n} |")
    a("")
    a(f"디렉터리 깊이 최대 {max(res['깊이']) if res['깊이'] else 0}")
    a("")

    a("## 못 봄")
    a("")
    a("| 항목 | 내용 |")
    a("|---|---|")
    a("| 자격증명 값 | 파일 내용을 열지 않아 확인하지 못함. 규칙에 패턴은 있으나 이 도구의 적용 대상이 아님 |")
    a("| 토큰 유효성 | 확인하지 않음. 남의 자격증명을 실제로 쓰는 행위라 하지 않는다 |")
    a(f"| 못 읽은 줄 | {len(dropped)}건 |")
    a("")
    a("빈칸으로 남기지 않는다. 없음과 못 봄은 다르다.")
    return "\n".join(o)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    ap.add_argument("--rules", default=str(Path(__file__).with_name("tree_rules.json")))
    ap.add_argument("--md")
    args = ap.parse_args()

    text = Path(args.tree).read_text(encoding="utf-8", errors="replace")
    paths, dropped = parse_tree(text)
    if not paths:
        raise SystemExit("경로를 하나도 못 읽었다. 입력 형식을 확인할 것")

    rules = load_rules(Path(args.rules))
    res = scan(paths, rules)
    out = report(res, rules, dropped, Path(args.tree).name)

    if args.md:
        p = Path(args.md)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out + "\n", encoding="utf-8")
        print(f"{p}  {len(out)}자")
    else:
        print(out)


if __name__ == "__main__":
    main()
