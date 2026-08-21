/* 범용 구조 진단 v1
   포럼이 아닌 사이트에 쓴다. 랜섬 유출 사이트, 텔레그램 미러, 자체 제작 사이트.
   forum kit 판정이 실패하고 진단마저 비었을 때 이걸 돌린다.
   네트워크를 쓰지 않는다. 열려 있는 페이지의 DOM만 읽는다.
   2026-08-20 다크초코 */
(() => {
  const out = [];
  const r = s => out.push(s);
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const sig = e => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
  const chain = e => { const p = []; let n = e, i = 0; for (; n && n !== document.body && i < 6; i++) { p.push(sig(n)); n = n.parentElement; } return p.join(' < '); };
  const A = [...document.querySelectorAll('a[href]')];
  r('# 범용 구조 진단');
  r('- URL : ' + location.href);
  r('- TITLE : ' + document.title);
  r('- 확인 : ' + new Date().toISOString().slice(0, 10));
  r('- 링크 ' + A.length + '개 · 요소 ' + document.querySelectorAll('*').length + '개');
  r('');
  const shape = h => { try { return new URL(h, location.href).pathname.replace(/\/\d+/g, '/N').replace(/\/[0-9a-f]{16,}/gi, '/HEX').replace(/\/[^/]{20,}/g, '/LONG'); } catch (e) { return '?'; } };
  const cnt = new Map();
  A.forEach(a => { const s = shape(a.getAttribute('href')); cnt.set(s, (cnt.get(s) || 0) + 1); });
  r('## 링크 경로 모양 (많은 순 15)');
  [...cnt.entries()].sort((a, b) => b[1] - a[1]).slice(0, 15).forEach(([s, n]) => r('- ' + n + '회  ' + s));
  r('');
  const bag = new Map();
  [...document.querySelectorAll('body *')].forEach(e => { const p = e.parentElement; if (!p) return; const m = bag.get(p) || new Map(); const k = sig(e); m.set(k, (m.get(k) || 0) + 1); bag.set(p, m); });
  const cands = [...bag.entries()].map(([p, m]) => { const top = [...m.entries()].sort((a, b) => b[1] - a[1])[0]; return { p: p, s: top[0], n: top[1] }; }).filter(x => x.n >= 3).sort((a, b) => b.n - a.n).slice(0, 6);
  r('## 반복 블록 후보 (같은 모양 자식 3개 이상)');
  if (!cands.length) r('없음. 자바스크립트로 그리는 페이지일 수 있다');
  cands.forEach(x => r('- ' + x.n + '개 · 자식 ' + x.s + ' · 부모 ' + chain(x.p)));
  r('');
  if (cands.length) {
    const top = cands[0];
    const same = [...top.p.children].filter(c => sig(c) === top.s);
    if (same.length) {
      r('## 반복 블록 하나 outerHTML (1800자)');
      r('```html'); r(same[0].outerHTML.slice(0, 1800)); r('```'); r('');
      r('## 앞 3개 innerText (블록마다 300자)');
      r('```');
      same.slice(0, 3).forEach((c, i) => r((i + 1) + '. ' + txt(c).slice(0, 300)));
      r('```'); r('');
    }
  }
  const cls = new Map();
  document.querySelectorAll('[class]').forEach(e => { if (typeof e.className !== 'string') return; e.className.trim().split(/\s+/).forEach(c => { if (c) cls.set(c, (cls.get(c) || 0) + 1); }); });
  r('## 클래스 빈도 (많은 순 15)');
  if (!cls.size) r('클래스를 안 쓴다');
  [...cls.entries()].sort((a, b) => b[1] - a[1]).slice(0, 15).forEach(([c, n]) => r('- ' + n + '회  .' + c));
  r('');
  const pg = A.filter(a => /page[=/-]\d/i.test(a.getAttribute('href') || '')).map(a => txt(a).slice(0, 8) + ' <- ' + a.getAttribute('href'));
  r('## 페이지네이션');
  r(pg.length ? pg.slice(0, 12).map(s => '- ' + s).join('\n') : '없음');
  r('');
  const body = document.body.innerText || document.body.textContent || '';
  const nums = [...new Set(body.match(/\b\d{1,3}(?:[,.]\d{3})+\b|\b\d+(?:\.\d+)?\s?(?:GB|TB|MB)\b/gi) || [])];
  r('## 규모로 보이는 값 (앞 20)');
  r(nums.length ? nums.slice(0, 20).join(' · ') : '없음');
  r('');
  const dates = [...new Set(body.match(/\b\d{4}-\d{2}-\d{2}\b|\b\d{2}[/.]\d{2}[/.]\d{4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b/gi) || [])];
  r('## 날짜로 보이는 값 (앞 12)');
  r(dates.length ? dates.slice(0, 12).join(' · ') : '없음');
  r('');
  r('## 본문 앞 800자');
  r('```'); r(body.replace(/\s+/g, ' ').trim().slice(0, 800)); r('```');
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;inset:4%;z-index:2147483647;background:#111;color:#eee;border:2px solid #666;padding:8px;display:flex;flex-direction:column;gap:6px;font:13px sans-serif';
  const bar = document.createElement('div');
  bar.style.cssText = 'display:flex;gap:8px;align-items:center';
  const st = document.createElement('span');
  st.style.cssText = 'flex:1;color:#0f0;font:12px monospace';
  st.textContent = '범용 진단 완료 · 링크 ' + A.length + ' · 반복 블록 후보 ' + cands.length + ' · Ctrl+C';
  const x = document.createElement('button');
  x.textContent = '닫기';
  x.onclick = () => box.remove();
  const ta = document.createElement('textarea');
  ta.style.cssText = 'flex:1;width:100%;background:#000;color:#0f0;font:12px monospace;border:1px solid #444';
  ta.value = out.join('\n');

  /* ── 최소화. 접어도 상태와 중단은 남긴다 ────── */
  let MINI = false;
  const miniB = document.createElement('button');
  miniB.textContent = '최소화';
  miniB.setAttribute('data-mini', '1');
  miniB.style.cssText = 'padding:3px 9px;cursor:pointer;font:12px sans-serif;background:#333;color:#ddd;border:1px solid #555';
  const KEEP = [st, miniB, x];
  miniB.onclick = () => {
    MINI = !MINI;
    box.style.inset = MINI ? 'auto 10px 10px auto' : '4%';
    box.style.maxWidth = MINI ? '52vw' : '';
    ta.style.display = MINI ? 'none' : '';
    [...bar.children].forEach(c => { c.style.display = (MINI && KEEP.indexOf(c) < 0) ? 'none' : ''; });
    miniB.textContent = MINI ? '펼치기' : '최소화';
  };

  bar.append(st, miniB, x);
  box.append(bar, ta);
  document.body.appendChild(box);
  ta.focus();
  ta.select();
})()
