#!/usr/bin/env python3
"""읽는 소스(.js)를 북마클릿 한 줄(.txt)로 만든다.

문법 검사를 통과해야만 파일을 쓴다. 실패하면 옛 txt를 그대로 둔다.
손으로 만들다가 js만 고치고 txt를 안 고치는 일을 막으려는 것이다.

    python bookmarklets/build_bookmarklet.py                       같은 폴더의 .js 전부
    python bookmarklets/build_bookmarklet.py bookmarklets/qilin_kit.js   하나만
    python bookmarklets/build_bookmarklet.py --no-check             node 없을 때

foo.js  ->  foo.bookmarklet.txt
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIMIT = 60_000          # 이보다 길면 브라우저 주소 칸에서 잘릴 수 있다
NODE_TIMEOUT = 30


def to_one_line(src: str) -> str:
    """머리 주석을 떼고 한 줄로 만든다."""
    body = re.sub(r"^\s*/\*.*?\*/\s*", "", src, flags=re.S)
    body = re.sub(r"\n\s*", " ", body)
    body = re.sub(r"\s{2,}", " ", body)
    return "javascript:" + body.strip()


def line_comments(src: str) -> list[int]:
    """// 주석을 찾는다. 줄 맨 앞이든 줄 끝이든 한 줄로 합치면 뒤가 통째로 죽는다."""
    out = []
    for i, l in enumerate(src.split("\n"), 1):
        if l.lstrip().startswith("//"):
            out.append(i)
        elif "://" not in l and re.search(r"(^|[^:/\\])//[^/]", l):
            out.append(i)          # 줄 끝 주석. 정규식 안의 \/\/ 는 뺀다
    return out


def node_check(code: str) -> tuple[bool, str]:
    """node --check 로 문법을 본다. node가 없으면 (None, 사유)."""
    tmp = Path(tempfile.gettempdir()) / "_bookmarklet_check.js"
    tmp.write_text(code, encoding="utf-8")
    try:
        p = subprocess.run(["node", "--check", str(tmp)],
                           capture_output=True, timeout=NODE_TIMEOUT,
                           encoding="utf-8", errors="replace")
        return p.returncode == 0, p.stderr.strip()
    except FileNotFoundError:
        return None, "node를 못 찾았다"
    except subprocess.TimeoutExpired:
        return False, f"node --check 가 {NODE_TIMEOUT}초를 넘겼다"
    finally:
        tmp.unlink(missing_ok=True)


def build(js: Path, do_check: bool) -> bool:
    out = js.with_suffix("")
    out = out.with_name(out.name + ".bookmarklet.txt")
    src = js.read_text(encoding="utf-8")

    bad = line_comments(src)
    if bad:
        print(f"  건너뜀  // 주석이 있다: {bad[:8]}번 줄")
        print(f"          한 줄로 합치면 뒤가 통째로 주석이 된다. /* */ 로 바꿀 것")
        return False

    one = to_one_line(src)

    if do_check:
        ok, err = node_check(one[len("javascript:"):])
        if ok is None:
            print(f"  건너뜀  {err}. 검사 없이 만들려면 --no-check")
            return False
        if not ok:
            print(f"  건너뜀  문법 오류. 옛 txt를 그대로 둔다")
            for l in err.split("\n")[:6]:
                print(f"          {l}")
            return False

    warn = "  (주소 칸에서 잘릴 수 있다)" if len(one) > LIMIT else ""
    before = len(out.read_text(encoding="utf-8")) if out.exists() else 0
    out.write_text(one, encoding="utf-8")
    delta = f"{before:,} -> " if before else ""
    print(f"  만듦    {out.name}  {delta}{len(one):,}자{warn}")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="비우면 같은 폴더의 .js 전부")
    ap.add_argument("--no-check", action="store_true", help="문법 검사를 건너뛴다")
    args = ap.parse_args()

    targets = [Path(f) for f in args.files] if args.files else sorted(HERE.glob("*.js"))
    if not targets:
        raise SystemExit("만들 .js 가 없다")

    made = 0
    for js in targets:
        if not js.exists():
            print(f"{js}\n  없는 파일")
            continue
        print(js.name)
        made += build(js, not args.no_check)

    print(f"\n{made}/{len(targets)} 개 만듦")
    if made < len(targets):
        sys.exit(1)


if __name__ == "__main__":
    main()
