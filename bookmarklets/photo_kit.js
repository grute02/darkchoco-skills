/* 증거 사진 수집 도구 v1
   랜섬웨어 유출 사이트가 피해자 글에 올린 증거 사진을 받는다.
   TITAN, 킬린처럼 썸네일 격자를 쓰는 사이트에서 쓴다.

   **검증에 쓸 것만 받는다.** 기본 20장이고 개수를 직접 정한다.
   요청 간격은 2.5~5초다. 줄이지 마라. 계정과 회선을 셋이 공유한다.
   받은 파일은 VM 안에 둔다. 케이스가 끝나면 지운다.

   먼저 찾기 로 주소를 확인하고, 썸네일이면 원본 주소 확인 으로 규칙을 본 뒤 받는다.
   2026-08-21 다크초코 */
(() => {
  const VER = 'photo kit v1';
  if (window.__PK) { try { window.__PK.remove(); } catch (e) {} window.__PK = null; }

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const CHAL = /cf[-_]chl|cf_chl_opt|Just a moment|Checking your browser|__cf_chl|Attention Required/i;
  const GAP = 3.75;
  const dur = s => {
    s = Math.max(0, Math.round(s));
    if (s >= 60) return Math.floor(s / 60) + '분 ' + (s % 60) + '초';
    return s + '초';
  };

  let ABORT = false, BUSY = false, FOUND = [], GOT = 0, FAIL = [], SIZES = [];
  const kb = n => n >= 1048576 ? (n / 1048576).toFixed(1) + 'MB' : Math.round(n / 1024) + 'KB';

  /* ── 사진 주소 모으기. 네트워크를 안 쓴다 ────── */
  const pick = () => {
    const pat = (patW.__i.value || '').trim();
    const re = pat ? new RegExp(pat, 'i') : /\/uploads?\//i;
    const seen = new Set();
    const out = [];
    document.querySelectorAll('img[src]').forEach(im => {
      const raw = im.getAttribute('src') || '';
      if (!raw || !re.test(raw)) return;
      let u;
      try { u = new URL(raw, location.href).href; } catch (e) { return; }
      if (seen.has(u)) return;
      seen.add(u);
      const r = im.getBoundingClientRect();
      out.push({ url: u, w: im.naturalWidth || 0, h: im.naturalHeight || 0,
                 보임: r.width > 0 && r.height > 0 });
    });
    return out;
  };

  /* 주소 바꾸기. 썸네일과 원본의 규칙이 다를 때 쓴다 */
  const swap = u => {
    const rule = (ruleW.__i.value || '').trim();
    if (!rule || rule.indexOf('->') < 0) return u;
    const [a, b] = rule.split('->').map(s => s.trim());
    return a ? u.split(a).join(b) : u;
  };

  const nameOf = (u, i) => {
    let base = '';
    try { base = decodeURIComponent(new URL(u).pathname.split('/').pop() || ''); } catch (e) {}
    if (!base || base.length > 60) base = 'shot';
    if (!/\.(png|jpe?g|gif|webp|bmp)$/i.test(base)) base += '.png';
    return String(i + 1).padStart(2, '0') + '_' + base;
  };

  const find = async () => {
    FOUND = pick();
    const L = ['# 증거 사진 ' + FOUND.length + '개 · 화면에 보이는 것 '
               + FOUND.filter(f => f.보임).length,
               '# ' + location.href,
               '# 아직 아무것도 받지 않았다. 주소를 확인한 뒤 받기 를 누른다',
               ''];
    FOUND.forEach((f, i) => L.push(nameOf(swap(f.url), i) + '\t' + swap(f.url)
                                   + (f.w ? '\t' + f.w + 'x' + f.h : '')));
    if (!FOUND.length) {
      L.push('못 찾았다. 주소 조각 칸에 /uploads/ 같은 것을 넣어보거나');
      L.push('접힌 사진이 있으면 먼저 펼친다');
    }
    return { md: L.join('\n'), status: '찾음 ' + FOUND.length + '개 · 아직 안 받았다' };
  };

  /* ── 원본 주소 확인. 썸네일을 한 번 눌러 본다 ── */
  const probe = async () => {
    const before = new Set(pick().map(f => f.url));
    const btn = document.querySelector('button img, a img, [role="button"] img');
    if (!btn) return { md: '누를 만한 썸네일을 못 찾았다', status: '실패' };
    (btn.closest('button, a, [role="button"]') || btn).click();
    await sleep(1200);
    const after = pick();
    const fresh = after.filter(f => !before.has(f.url));
    const big = after.filter(f => f.w >= 900).slice(0, 5);
    const L = ['# 썸네일을 한 번 눌러 본 결과', ''];
    L.push('## 새로 뜬 주소 ' + fresh.length + '개');
    fresh.slice(0, 8).forEach(f => L.push('- ' + f.url + '  ' + f.w + 'x' + f.h));
    L.push('');
    L.push('## 큰 이미지(가로 900 이상) ' + big.length + '개');
    big.forEach(f => L.push('- ' + f.url + '  ' + f.w + 'x' + f.h));
    L.push('');
    L.push('썸네일과 원본 주소가 다르면 **주소 바꾸기** 칸에 규칙을 넣는다.');
    L.push('예   /uploads/p/ -> /uploads/o/');
    L.push('같으면 비워 둔다. 창을 닫고 받기 를 누른다.');
    return { md: L.join('\n'), status: '새 주소 ' + fresh.length + ' · 큰 것 ' + big.length };
  };

  /* ── 받기. 여기만 네트워크를 쓴다 ───────────── */
  const grab = async () => {
    if (!FOUND.length) FOUND = pick();
    if (!FOUND.length) return { md: '받을 것이 없다. 찾기 를 먼저 누른다', status: '없음' };
    const cap = Math.max(1, parseInt(capW.__i.value, 10) || 20);
    const list = FOUND.slice(0, cap);
    GOT = 0; FAIL = []; SIZES = [];
    const T0 = Date.now();

    for (let i = 0; i < list.length; i++) {
      if (ABORT) break;
      const u = swap(list[i].url);
      const nm = nameOf(u, i);
      try {
        const r = await fetch(u, { credentials: 'include' });
        if (r.status === 403) throw new Error('403');
        if (r.status === 429 || r.status === 503) throw new Error(r.status + '. 즉시 중단');
        if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
        const ct = r.headers.get('content-type') || '';
        const blob = await r.blob();
        if (CHAL.test(await blob.slice(0, 2048).text().catch(() => ''))) throw new Error('Cloudflare 화면');
        if (!/^image\//i.test(ct) && blob.size < 200) throw new Error('이미지가 아니다 (' + ct + ')');
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = nm;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 15000);
        SIZES.push({ nm: nm, size: blob.size });
        GOT++;
      } catch (e) {
        FAIL.push(nm + '  ' + (e.message || e));
        if (/429|503|Cloudflare/.test(String(e.message || e))) { ABORT = true; break; }
      }
      const left = list.length - i - 1;
      say('받는 중 ' + (i + 1) + '/' + list.length + ' · 성공 ' + GOT
          + (FAIL.length ? ' · 실패 ' + FAIL.length : '')
          + ' · 지난 ' + dur((Date.now() - T0) / 1000)
          + (left ? ' · 최소 ' + dur(left * GAP) + ' 더' : ''));
      if (left && !ABORT) await sleep(2500 + Math.random() * 2500);
    }

    const took = (Date.now() - T0) / 1000;
    const L = ['# 증거 사진 받기',
               '# 찾은 것 ' + FOUND.length + ' · 상한 ' + cap + ' · 성공 ' + GOT
               + ' · 실패 ' + FAIL.length + ' · ' + dur(took) + ' 걸림'
               + (SIZES.length ? ' · 합계 ' + kb(SIZES.reduce((a, s) => a + s.size, 0))
                  + ' · 평균 ' + kb(SIZES.reduce((a, s) => a + s.size, 0) / SIZES.length) : '')
               + (ABORT ? ' · 중단' : ''),
               '# ' + location.href,
               '# 받은 파일은 VM 안에 둔다. 케이스가 끝나면 지운다',
               ''];
    if (FOUND.length > cap) {
      L.push('# 상한에 걸려 ' + (FOUND.length - cap) + '개를 안 받았다. 개수를 올리고 다시 누른다');
      L.push('');
    }
    const bySize = {};
    SIZES.forEach(s => { bySize[s.nm] = s.size; });
    list.slice(0, GOT + FAIL.length).forEach((f, i) => {
      const nm = nameOf(swap(f.url), i);
      L.push(nm + '\t' + (bySize[nm] == null ? '실패' : kb(bySize[nm])) + '\t' + swap(f.url));
    });
    const small = SIZES.filter(s => s.size < 30720);
    if (small.length) {
      L.push('');
      L.push('# 30KB 아래가 ' + small.length + '개다. 원본이 아니라 썸네일을 받았을 수 있다');
      L.push('# 원본 주소 확인 을 눌러 주소 규칙을 다시 본다');
    }
    if (FAIL.length) {
      L.push('');
      L.push('## 못 받은 것');
      FAIL.forEach(f => L.push('- ' + f));
    }
    return { md: L.join('\n'),
             status: '성공 ' + GOT + '/' + list.length + (FAIL.length ? ' · 실패 ' + FAIL.length : '')
                     + (SIZES.length ? ' · 합계 ' + kb(SIZES.reduce((a, s) => a + s.size, 0)) : '')
                     + ' · ' + dur(took) + (ABORT ? ' · 중단' : '') };
  };

  /* ── 화면 ─────────────────────────────────────── */
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;inset:4%;z-index:2147483647;background:#111;color:#eee;border:2px solid #666;padding:8px;display:flex;flex-direction:column;gap:6px;font:13px sans-serif';
  const bar = document.createElement('div');
  bar.style.cssText = 'display:flex;gap:6px;align-items:center;flex-wrap:wrap';
  const st = document.createElement('span');
  st.style.cssText = 'flex:1;min-width:220px;color:#0f0;font:12px monospace';
  const ta = document.createElement('textarea');
  ta.style.cssText = 'flex:1;width:100%;background:#000;color:#0f0;font:12px monospace;border:1px solid #444';
  const say = s => { st.textContent = s; };
  const put = s => { ta.value = s; ta.focus(); ta.select(); };
  const mk = (label, fn, hot) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.style.cssText = 'padding:3px 9px;cursor:pointer;font:12px sans-serif;' + (hot ? 'background:#0a4;color:#fff;border:1px solid #0f8;font-weight:bold' : 'background:#333;color:#ddd;border:1px solid #555');
    b.onclick = async () => {
      if (BUSY) { say('실행 중이다. 끝나거나 중단한 뒤에 누를 것'); return; }
      BUSY = true; ABORT = false;
      try { const r = await fn(); put(r.md); say(r.status + ' · Ctrl+C'); }
      catch (e) { say('오류 : ' + e); put('오류\n\n' + (e && e.stack || e)); }
      BUSY = false;
    };
    return b;
  };
  const inp = (label, val, size) => {
    const l = document.createElement('label');
    l.style.cssText = 'display:flex;gap:3px;align-items:center;font:12px sans-serif;color:#aaa';
    const i = document.createElement('input');
    i.value = val; i.size = size;
    i.style.cssText = 'background:#000;color:#0f0;border:1px solid #444;font:12px monospace;width:' + (9 * size) + 'px';
    l.append(document.createTextNode(label), i);
    l.__i = i;
    return l;
  };
  const capW = inp('몇 장', '20', 3);
  const patW = inp('주소 조각', '', 10);
  const ruleW = inp('주소 바꾸기', '', 16);

  const bFind = mk('찾기', find, true);
  const bProbe = mk('원본 주소 확인', probe, false);
  const bGrab = mk('받기', grab, false);

  /* ── 최소화. 접어도 상태와 중단은 남긴다 ────── */
  let MINI = false;
  const miniB = document.createElement('button');
  miniB.textContent = '최소화';
  miniB.setAttribute('data-mini', '1');
  miniB.style.cssText = 'padding:3px 9px;cursor:pointer;font:12px sans-serif;background:#333;color:#ddd;border:1px solid #555';
  const stopB = document.createElement('button');
  stopB.textContent = '중단';
  stopB.style.cssText = 'padding:3px 9px;cursor:pointer;font:12px sans-serif;background:#422;color:#fdd;border:1px solid #855';
  stopB.onclick = () => { ABORT = true; say('중단 요청. 현재 요청이 끝나면 멈춘다'); };
  const closeB = document.createElement('button');
  closeB.textContent = '닫기';
  closeB.style.cssText = 'padding:3px 9px;cursor:pointer;font:12px sans-serif;background:#422;color:#fdd;border:1px solid #855';
  closeB.onclick = () => box.remove();
  const KEEP = [st, miniB, stopB, closeB];
  miniB.onclick = () => {
    MINI = !MINI;
    box.style.inset = MINI ? 'auto 10px 10px auto' : '4%';
    box.style.maxWidth = MINI ? '52vw' : '';
    ta.style.display = MINI ? 'none' : '';
    [...bar.children].forEach(c => { c.style.display = (MINI && KEEP.indexOf(c) < 0) ? 'none' : ''; });
    miniB.textContent = MINI ? '펼치기' : '최소화';
  };

  bar.append(bFind, bProbe, bGrab, capW, patW, ruleW, st, stopB, miniB, closeB);
  box.append(bar, ta);
  document.body.appendChild(box);
  window.__PK = box;

  const n = pick();
  say(VER + ' · 이 쪽에 사진 ' + n.length + '개'
      + (n.length ? ' · 20장이면 최소 ' + dur(Math.min(n.length, 20) * GAP) : '')
      + ' · 찾기 부터');
})();
