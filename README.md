# darkchoco-skills

WHS 4 darkchoco
다크웹 유출 주장 검증 스킬과 도구

## 설치

### Claude Code

```bash
git clone https://github.com/grute02/darkchoco-skills.git
cp -r darkchoco-skills/skills/darkweb-verify-ko ~/.claude/skills/
```

클로드를 새로 켠 뒤 `유출 주장 검증해줘` 라고 하면 걸린다.

### Codex

레포를 작업 폴더로 쓰거나, `AGENTS.md` 를 작업 폴더에 복사한다.

```bash
git clone https://github.com/grute02/darkchoco-skills.git
cd darkchoco-skills
codex
```

둘 다 같은 `skills/darkweb-verify-ko/references/` 를 읽는다.

## 동작

```
[사람]  1 발견 → 3 게시글 확인 (체크리스트, 파일 트리 확보)
[AI]    2 사전 확인 → 4 마스킹 → 5 재료 합치기 → 6 판정 근거 산출
[사람]  7 검토 → 8 판정
[AI]    9 DB 입력   별도 호출
```

**판정은 사람이 한다.** AI는 참고 판정까지만 낸다.
**원본 개인정보를 AI에 넣지 않는다.** 4단계에서 패턴으로 바꾼 뒤 쓴다.

## 도구

### tree_scan.py

유출물 파일 목록으로 초동 분석을 한다. 파일 내용은 열지 않는다.

```bash
python tools/tree_scan.py <트리파일> --md 출력.md
```

입력은 한 줄에 경로 하나, `tree` 출력, `unzip -l`, `find`, `git ls-files` 를 받는다.
자산 민감도 등급별 건수, 진위 신호, 규모 통계, 못 본 것을 낸다.

규칙은 `tools/tree_rules.json` 에 있다. 코드와 분리돼 있어 패턴만 더하면 된다.

### notion.py

노션 읽기 전용 래퍼.

```bash
python tools/notion.py search <검색어>
python tools/notion.py md <page_id> out.md
```

### notion_push.py

마크다운을 노션 페이지로 올린다. 표와 코드블록을 살린다.

```bash
python tools/notion_push.py <parent_id> "<제목>" <md파일> --dry
python tools/notion_push.py <page_id> "<제목>" <md파일> --update
```

### notion_row.py

9단계 출력을 노션 DB 행으로 만든다. **미리보기가 기본이고 `--commit` 을 붙여야 쓴다.**

```bash
python tools/notion_row.py 검증 out9.txt                       # 미리보기
python tools/notion_row.py 검증 out9.txt --exclude "한계"        # 뺄 칸
python tools/notion_row.py 검증 out9.txt --set "검증자=이름"     # 고칠 칸
python tools/notion_row.py 검증 out9.txt --commit               # 실제로 쓴다
```

선택지에 없는 값은 넣지 않는다. 오타로 새 선택지가 생기는 것을 막는다.
기존 행을 고치지 않고 새 행만 만든다. DB는 이름으로 찾으므로 ID를 코드에 박지 않는다.

## 노션 토큰

토큰은 레포 밖 파일에서 읽는다. **코드에 값을 넣지 않는다.**

```bash
export NOTION_TOKEN_FILE=/경로/.notion_token.txt
```

토큰은 notion.so/my-integrations 에서 Internal integration 으로 발급하고,
쓸 페이지에서 Connections 에 그 integration 을 추가한다. 안 하면 404가 난다.

## 구성

```
skills/darkweb-verify-ko/
  SKILL.md              Claude Code 진입점
  references/           단계별 프롬프트 9개, 파일 트리, 발행처 목록
AGENTS.md               Codex 진입점
tools/                  tree_scan, notion, notion_push
```

## 판정 다섯 축

| 축 | 값 |
|---|---|
| 검증 분류 | A / B / C / D |
| 진위 판정 | 확인됨 / 신뢰성 높음 / 미확인 / 신뢰성 낮음 / 허위 |
| 신규성 판정 | 신규 유출 / 재유포 / 혼합 / 확인불가 |
| 판정 신뢰도 | 높음 / 중간 / 낮음 |
| 위험도 | 자산 민감도, 즉시 악용 가능성, 신선도, 피해 범위, 확산 정도 |
