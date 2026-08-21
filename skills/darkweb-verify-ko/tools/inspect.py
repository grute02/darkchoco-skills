#!/usr/bin/env python3
"""케이스 폴더 하나를 분석 도구에 태운다.

    python tools/inspect.py <케이스폴더>
    python tools/inspect.py <케이스폴더> --out <결과폴더>

결과는 **케이스 폴더 옆에 두지 않는다.** 지금 폴더의 `07_케이스/<케이스이름>/` 에 쓴다.
공유폴더는 통로라서 분석이 끝나면 비운다. 결과가 거기 있으면 같이 지워진다.

파일마다 **앞바이트로 진짜 종류를 판정하고** 종류에 맞는 도구를 돌린다.
실행 파일과 압축과 문서는 건드리지 않고 경고만 적는다.

확장자를 믿지 않는다. 유출물은 이름을 속인다.
이 스크립트는 파일을 읽기만 한다. 실행하지 않고 셸을 부르지 않는다.
"""
from __future__ import annotations

import argparse
import codecs
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 600          # 도구 하나당 상한
HEAD = 8192            # 종류를 볼 때 읽는 앞부분
SAFE = "텍스트"

# 앞바이트로 가리는 종류. 위는 전부 건드리지 않는다.
MAGIC = [
    (b"MZ",                  "실행 파일(MZ)"),
    (b"\x7fELF",             "실행 파일(ELF)"),
    (b"\xca\xfe\xba\xbe",    "실행 파일(Mach-O)"),
    (b"PK\x03\x04",          "zip 계열(zip·docx·xlsx·jar)"),
    (b"Rar!",                "rar"),
    (b"7z\xbc\xaf\x27\x1c",  "7z"),
    (b"\x1f\x8b",            "gzip"),
    (b"BZh",                 "bzip2"),
    (b"\xfd7zXZ",            "xz"),
    (b"%PDF",                "pdf"),
    (b"\xd0\xcf\x11\xe0",    "옛 office(doc·xls·ppt)"),
    (b"{\\rtf",              "rtf"),
    (b"\x89PNG",             "png"),
    (b"\xff\xd8\xff",        "jpeg"),
    (b"SQLite format 3",     "sqlite 파일"),
]

# 종류마다 어울리는 확장자. 여기 없으면 이름을 속인 것으로 본다
EXT_OK = {
    "실행 파일(MZ)": {".exe", ".dll", ".sys", ".msi", ".scr", ".ocx"},
    "실행 파일(ELF)": {".so", ".elf", ".bin", ""},
    "실행 파일(Mach-O)": {".dylib", ".bin", ""},
    "zip 계열(zip·docx·xlsx·jar)": {".zip", ".docx", ".xlsx", ".pptx", ".jar",
                                    ".apk", ".odt", ".ods", ".epub", ".whl"},
    "rar": {".rar"}, "7z": {".7z"}, "gzip": {".gz", ".tgz", ".tar"},
    "bzip2": {".bz2"}, "xz": {".xz"}, "pdf": {".pdf"},
    "옛 office(doc·xls·ppt)": {".doc", ".xls", ".ppt", ".hwp", ".msg"},
    "rtf": {".rtf"}, "png": {".png"}, "jpeg": {".jpg", ".jpeg"},
    "sqlite 파일": {".db", ".sqlite", ".sqlite3"},
}

# 텍스트일 때 확장자로 도구를 고른다
TOOL = {
    ".sql": "db_tree",
    ".csv": "sample_stats",
    ".tsv": "sample_stats",
}


def sniff(path: Path) -> tuple[str, str]:
    """(종류, 이유). 종류가 '텍스트' 일 때만 도구에 태운다."""
    try:
        head = path.open("rb").read(HEAD)
    except OSError as e:
        return "못 읽음", str(e)

    if not head:
        return "빈 파일", "0 바이트"

    for sig, name in MAGIC:
        if head.startswith(sig):
            return name, "앞바이트 " + repr(sig)[1:]

    if b"\x00" in head:
        return "이진", "앞 %d바이트에 널바이트가 있다" % len(head)

    # 앞부분을 자르면 여러 바이트 글자가 반으로 잘린다. 그것을 오류로 세지 않는다.
    for enc in ("utf-8", "cp949"):
        try:
            codecs.getincrementaldecoder(enc)().decode(head, False)
            return SAFE, enc + " 로 읽힌다"
        except UnicodeDecodeError:
            continue
    return "이진", "utf-8 도 cp949 도 아니다"


def lied(path: Path, kind: str) -> bool:
    """확장자가 실제 종류와 어긋나나. 이름을 속인 파일이 제일 위험하다."""
    if kind in (SAFE, "빈 파일", "못 읽음"):
        return False
    ok = EXT_OK.get(kind)
    if ok is None:
        return False
    return path.suffix.lower() not in ok


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit) if unit != "B" else "%dB" % n
        n /= 1024.0
    return "%dB" % n


def run(tool: str, args: list[str]) -> tuple[bool, str]:
    """도구를 돌린다. (성공, 메시지)"""
    cmd = [sys.executable, str(HERE / (tool + ".py"))] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "%d초를 넘겨 멈췄다" % TIMEOUT
    except OSError as e:
        return False, str(e)
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip().split("\n")
        return False, msg[-1] if msg else "코드 %d" % p.returncode
    return True, (p.stdout or "").strip().split("\n")[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", help="케이스 폴더")
    ap.add_argument("--out", default="", help="결과 폴더. 안 주면 <지금폴더>/07_케이스/<케이스이름>")
    ap.add_argument("--rows", type=int, default=0, help="샘플에서 읽을 행 상한. 0이면 전부")
    args = ap.parse_args()

    case = Path(args.case).resolve()
    if not case.is_dir():
        raise SystemExit("폴더가 아니다: %s" % case)

    # 케이스 폴더 옆에 두지 않는다. 공유폴더는 분석이 끝나면 비우는 자리다.
    out = Path(args.out).resolve() if args.out else Path.cwd() / "07_케이스" / case.name
    out.mkdir(parents=True, exist_ok=True)
    if out.resolve() == case.resolve() or case.resolve() in out.resolve().parents:
        raise SystemExit("결과 폴더가 케이스 폴더 안이다. --out 으로 밖을 지정할 것")

    files = sorted(p for p in case.rglob("*") if p.is_file())
    if not files:
        raise SystemExit("파일이 없다: %s" % case)

    # ── 1. 종류 판정 ────────────────────────────────
    rows = []
    for p in files:
        kind, why = sniff(p)
        rows.append({"path": p, "rel": p.relative_to(case).as_posix(),
                     "kind": kind, "why": why, "size": p.stat().st_size,
                     "tool": TOOL.get(p.suffix.lower(), "") if kind == SAFE else "",
                     "fake": lied(p, kind), "done": "", "note": ""})

    faked = [r for r in rows if r["fake"]]
    skipped_kind = [r for r in rows if r["kind"] not in (SAFE, "빈 파일") and not r["fake"]]

    # ── 2. 파일 목록을 tree_scan 에 태운다 ───────────
    listing = out / "_경로목록.txt"
    listing.write_text("\n".join(case.name + "/" + r["rel"] for r in rows) + "\n",
                       encoding="utf-8")
    tree_md = out / "트리.md"
    tree_ok, tree_msg = run("tree_scan", [str(listing), "--md", str(tree_md)])

    # ── 3. 텍스트만 도구에 태운다 ────────────────────
    for r in rows:
        if not r["tool"]:
            if r["kind"] == SAFE:
                r["note"] = "다루는 확장자가 아니다"
            elif r["kind"] == "빈 파일":
                r["note"] = "0 바이트"
            else:
                r["note"] = "건드리지 않았다"
            continue
        stem = r["rel"].replace("/", "_")
        if r["tool"] == "db_tree":
            md = out / ("구조_%s.md" % stem)
            ok, msg = run("db_tree", [str(r["path"]), "--md", str(md)])
        else:
            md = out / ("샘플_%s.md" % stem)
            a = [str(r["path"]), "--md", str(md)]
            if args.rows:
                a += ["--rows", str(args.rows)]
            ok, msg = run("sample_stats", a)
        r["done"] = md.name if ok else ""
        r["note"] = "" if ok else msg[:80]

    # ── 4. 요약 ─────────────────────────────────────
    total = sum(r["size"] for r in rows)
    L = []
    L.append("# 케이스 요약  %s" % case.name)
    L.append("")
    L.append("    폴더    %s" % case)
    L.append("    결과    %s" % out)
    L.append("")
    L.append("파일 %d개 · %s" % (len(rows), human(total)))
    L.append("")

    if faked:
        L.append("## 이름을 속인 파일 %d건" % len(faked))
        L.append("")
        L.append("| 파일 | 확장자 | 실제 종류 | 크기 |")
        L.append("|---|---|---|---|")
        for r in faked:
            L.append("| %s | %s | **%s** | %s |"
                     % (r["rel"], r["path"].suffix or "없음", r["kind"], human(r["size"])))
        L.append("")
        L.append("**확장자와 실제 종류가 어긋난다. 사람이 먼저 본다.**")
        L.append("")
    else:
        L.append("## 이름을 속인 파일 없음")
        L.append("")

    if skipped_kind:
        L.append("## 텍스트가 아니라 안 다룬 것 %d건" % len(skipped_kind))
        L.append("")
        L.append("| 파일 | 실제 종류 | 크기 |")
        L.append("|---|---|---|")
        for r in skipped_kind:
            L.append("| %s | %s | %s |" % (r["rel"], r["kind"], human(r["size"])))
        L.append("")
        L.append("이름과 종류는 맞다. 이 흐름에서 다루지 않을 뿐이다.")
        L.append("")

    L.append("## 파일별")
    L.append("")
    L.append("| 파일 | 실제 종류 | 크기 | 돌린 것 | 결과 |")
    L.append("|---|---|---|---|---|")
    for r in rows:
        L.append("| %s | %s | %s | %s | %s |"
                 % (r["rel"], r["kind"], human(r["size"]),
                    r["tool"] or "-", r["done"] or r["note"] or "-"))
    L.append("")

    made = [r["done"] for r in rows if r["done"]]
    L.append("## 만든 것")
    L.append("")
    L.append("    트리.md            %s" % ("파일 구조 등급" if tree_ok else "실패. " + tree_msg))
    for m in made:
        L.append("    %s" % m)
    L.append("")

    L.append("## 다음")
    L.append("")
    L.append("- `트리.md` 에서 등급이 높은 경로부터 본다")
    L.append("- 구조 md 에서 개인정보 칸이 많은 표를 고른다")
    L.append("- 그 표를 `sample_stats <덤프> --table <표>` 로 따로 돌린다")
    if faked:
        L.append("- **이름을 속인 파일은 이 흐름에 넣지 않는다.** 별도로 다룬다")
    L.append("")

    (out / "00_요약.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    print("케이스   %s" % case.name)
    print("파일     %d개 · %s" % (len(rows), human(total)))
    print("속인 것  %d건" % len(faked))
    print("안 다룸  %d건" % len(skipped_kind))
    print("만든 것  %d개" % (len(made) + (1 if tree_ok else 0)))
    print("요약     %s" % (out / "00_요약.md"))


if __name__ == "__main__":
    main()
