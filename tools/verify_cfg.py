#!/usr/bin/env python3
"""⑥ 출력 방식 설정.

    python tools/verify_cfg.py                  지금 설정을 보인다
    python tools/verify_cfg.py 화면=전체         하나를 바꾼다
    python tools/verify_cfg.py --기본값           처음 값으로 되돌린다

설정 파일은 이 스크립트 옆의 `verify_config.json` 이다.
없으면 기본값으로 돈다. 지워도 된다.

**이 스크립트는 출력을 만들지 않는다.** 무엇을 낼지만 알려준다.
⑥ 로그는 AI 가 쓰고, 이 설정이 화면에 무엇을 낼지 정한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CFG = Path(__file__).with_name("verify_config.json")

# 이름: (기본값, 고를 수 있는 값, 뜻)
SPEC = {
    "md": ("항상", ["항상", "묻기", "안 함"],
           "⑥ 로그를 07_케이스/<케이스>/ 에 md 로 쓴다"),
    "화면": ("요약", ["요약", "전체"],
             "요약만 낼지 로그까지 낼지"),
    "요약위치": ("아래", ["아래", "위"],
                 "CLI 는 마지막 줄이 보인다. 아래가 기본"),
    "요약폭": ("72", ["60", "72", "88", "0"],
               "표를 접는 글자 수. 0이면 안 접는다"),
}


def load() -> dict:
    out = {k: v[0] for k, v in SPEC.items()}
    if CFG.exists():
        try:
            out.update(json.loads(CFG.read_text(encoding="utf-8")))
        except (ValueError, OSError) as e:
            print("설정 파일을 못 읽었다. 기본값으로 돈다. %s" % e, file=sys.stderr)
    return out


def show(cur: dict) -> None:
    print("\n⑥ 출력 설정   %s" % (CFG if CFG.exists() else "(파일 없음. 기본값)"))
    print()
    print("| 이름 | 지금 | 고를 수 있는 값 | 뜻 |")
    print("|---|---|---|---|")
    for k, (dflt, opts, why) in SPEC.items():
        mark = "**%s**" % cur[k] if cur[k] != dflt else cur[k]
        print("| %s | %s | %s | %s |" % (k, mark, " / ".join(opts), why))
    print()
    print("바꾸려면   python tools/verify_cfg.py 화면=전체")
    print("되돌리려면 python tools/verify_cfg.py --기본값")
    print()
    print("[AI 가 읽을 것]")
    print("  md %s · 화면 %s · 요약위치 %s" % (cur["md"], cur["화면"], cur["요약위치"]))
    if cur["화면"] == "요약":
        print("  로그는 md 로만 낸다. 화면에는 요약 네 절과 md 경로만 낸다.")
    else:
        print("  로그와 요약을 둘 다 화면에 낸다.")


def main() -> None:
    args = [a for a in sys.argv[1:]]
    if "--기본값" in args:
        if CFG.exists():
            CFG.unlink()
        print("기본값으로 되돌렸다")
        show(load())
        return

    cur = load()
    changed = False
    for a in args:
        if "=" not in a:
            raise SystemExit("이름=값 형식이다. 예: 화면=전체")
        k, v = (x.strip() for x in a.split("=", 1))
        if k not in SPEC:
            raise SystemExit("모르는 이름: %s. 있는 것: %s" % (k, ", ".join(SPEC)))
        if v not in SPEC[k][1]:
            raise SystemExit("%s 는 %s 중 하나다" % (k, " / ".join(SPEC[k][1])))
        cur[k] = v
        changed = True

    if changed:
        CFG.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print("바꿨다")
    show(cur)


if __name__ == "__main__":
    main()
