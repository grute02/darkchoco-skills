/* 디렉터리 인덱스 수집 도구 v1
   랜섬웨어 유출 사이트와 노출된 파일 서버의 목록 페이지에서 쓴다.
   nginx autoindex 와 Apache mod_autoindex 둘 다 읽는다.

   **파일을 내려받지 않는다.** 주소가 / 로 끝나는 것만 요청한다.
   파일 링크를 요청하는 코드가 이 안에 없다. 실수로도 못 받는다.

   요청 간격은 2.5~5초다. 줄이지 마라. 계정과 회선을 셋이 공유한다.
   2026-08-21 다크초코 */
(() => {
  const VER = 'index kit v1';
  if (window.__IK) { try { window.__IK.remove(); } catch (e) {} window.__IK = null; }

  const T = e => (e ? (e.innerText || e.textContent || '') : '').replace(/ /g, ' ').replace(/\s+/g, ' ').trim();
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const GAP = 3.75;   /* 요청 간격 2.5~5초의 가운데. 시간 어림에 쓴다 */
  const dur = s => {
    s = Math.max(0, Math.round(s));
    if (s >= 3600) return Math.floor(s / 3600) + '시간 ' + Math.round((s % 3600) / 60) + '분';
    if (s >= 60) return Math.floor(s / 60) + '분 ' + (s % 60) + '초';
    return s + '초';
  };
  const CHAL = /cf[-_]chl|cf_chl_opt|Just a moment|Checking your browser|__cf_chl|Attention Required/i;
  const MONTH = { Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
                  Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12' };

  /* 시작 자리. 이 아래로만 걸어다닌다 */
  const ROOT = new URL(location.href.split('?')[0].split('#')[0]);
  if (!ROOT.pathname.endsWith('/')) ROOT.pathname += '/';
  const BASE = ROOT.origin + ROOT.pathname;
  const LABEL = (ROOT.pathname.replace(/\/+$/, '').split('/').pop()) || ROOT.hostname;

  /* ── 크기와 날짜 다듬기 ───────────────────────── */
  const bytesOf = s => {
    const m = /^([\d.]+)\s*([KMGT])?B?$/i.exec((s || '').trim());
    if (!m) return null;
    const n = parseFloat(m[1]);
    const p = { K: 1024, M: 1048576, G: 1073741824, T: 1099511627776 }[(m[2] || '').toUpperCase()];
    return Math.round(p ? n * p : n);
  };
  const dateOf = s => {
    let m = /(\d{2})-([A-Za-z]{3})-(\d{4})\s+(\d{2}:\d{2})/.exec(s || '');   /* nginx */
    if (m) return m[3] + '-' + (MONTH[m[2]] || '00') + '-' + m[1] + ' ' + m[4];
    m = /(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/.exec(s || '');   /* Apache */
    if (m) return m[1] + ' ' + m[2];
    return '';
  };

  /* ── 인덱스 한 장 읽기 ────────────────────────── */
  const SKIP = /^(\.\.\/?|\/|\?|#)/;
  const parse = (doc, pageUrl) => {
    const out = [];
    const seen = new Set();
    const add = (a, tail, cells) => {
      const raw = a.getAttribute('href') || '';
      if (!raw || SKIP.test(raw) || /^[a-z]+:/i.test(raw) && !/^https?:/i.test(raw)) return;
      if (/[?&]C=[NMSD]|[?&]O=[AD]/.test(raw)) return;   /* Apache 정렬 링크 */
      let u;
      try { u = new URL(raw, pageUrl); } catch (e) { return; }
      if (u.origin !== ROOT.origin) return;
      const full = u.origin + u.pathname;
      if (!full.startsWith(BASE)) return;   /* 위로 올라가지 않는다 */
      if (full === pageUrl || seen.has(full)) return;
      seen.add(full);
      const isDir = u.pathname.endsWith('/');
      let sizeTxt = '', dateTxt = '';
      if (cells) {   /* Apache 표 */
        dateTxt = dateOf(cells[0] || '');
        sizeTxt = (cells[1] || '').trim();
      } else {   /* nginx pre */
        dateTxt = dateOf(tail);
        const m = /(\d[\d.]*\s*[KMGT]?)\s*$/i.exec(tail.replace(/\s+-\s*$/, ''));
        sizeTxt = isDir ? '' : (m ? m[1].trim() : '');
      }
      out.push({
        url: full,
        rel: decodeURIComponent(full.slice(BASE.length)),
        isDir: isDir,
        sizeTxt: isDir ? '' : sizeTxt,
        bytes: isDir ? null : bytesOf(sizeTxt),
        date: dateTxt
      });
    };

    /* Apache 표 먼저 */
    const trs = [...doc.querySelectorAll('table tr')].filter(tr => tr.querySelector('a[href]'));
    if (trs.length) {
      trs.forEach(tr => {
        const tds = [...tr.querySelectorAll('td')].map(T);
        const a = tr.querySelector('a[href]');
        add(a, '', tds.slice(1));
      });
      if (out.length) return out;
    }

    /* nginx pre. 링크 뒤에 오는 글자를 크기와 날짜로 읽는다 */
    const pres = doc.querySelectorAll('pre');
    const scope = pres.length ? pres : [doc.body || doc];
    scope.forEach(pre => {
      const as = [...pre.querySelectorAll('a[href]')];
      as.forEach(a => {
        let tail = '', n = a.nextSibling;
        while (n && !(n.nodeType === 1 && n.tagName === 'A')) {
          tail += n.textContent || '';
          n = n.nextSibling;
        }
        add(a, tail.split('\n')[0] || tail, null);
      });
    });
    return out;
  };

  /* ── 걸어다니기. 디렉터리만 요청한다 ──────────── */
  let ABORT = false, BUSY = false;
  let RESULT = [], STOPPED = '', WALKED = 0, UNOPENED = [], T0 = 0, TOOK = 0;

  const fetchDir = async url => {
    if (!url.endsWith('/')) throw new Error('디렉터리가 아닌 주소는 요청하지 않는다: ' + url);
    const r = await fetch(url, { credentials: 'include' });
    const html = await r.text();
    if (r.status === 403) throw new Error('403. 등급 제한이거나 막혔다');
    if (r.status === 429 || r.status === 503) throw new Error(r.status + '. 즉시 중단한다');
    if (CHAL.test(html)) throw new Error('Cloudflare 확인 화면. 즉시 중단한다');
    if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
    return new DOMParser().parseFromString(html, 'text/html');
  };

  const walk = async (maxDepth, maxReq) => {
    RESULT = []; STOPPED = ''; WALKED = 0; UNOPENED = []; T0 = Date.now(); TOOK = 0;
    const seen = new Set([BASE]);
    const queue = [{ url: BASE, depth: 0 }];
    while (queue.length) {
      if (ABORT) { STOPPED = '사용자 중단'; break; }
      if (WALKED >= maxReq) { STOPPED = '요청 상한 ' + maxReq + ' 도달'; break; }
      const cur = queue.shift();
      let doc;
      try {
        doc = cur.depth === 0 ? document : await fetchDir(cur.url);
        if (cur.depth > 0) { WALKED++; await sleep(2500 + Math.random() * 2500); }
      } catch (e) {
        RESULT.push({ url: cur.url, rel: decodeURIComponent(cur.url.slice(BASE.length)),
                      isDir: true, sizeTxt: '', bytes: null, date: '', err: String(e.message || e) });
        STOPPED = '조회 실패로 중단 : ' + (e.message || e);
        break;
      }
      const rows = parse(doc, cur.url);
      rows.forEach(r => {
        RESULT.push(r);
        if (!r.isDir || seen.has(r.url)) return;
        if (cur.depth + 1 > maxDepth) {
          /* 깊이 상한이다. 있는 줄은 알지만 안을 못 봤다. 반드시 적는다 */
          UNOPENED.push({ rel: r.rel, why: '깊이 상한 ' + maxDepth });
          return;
        }
        seen.add(r.url);
        queue.push({ url: r.url, depth: cur.depth + 1 });
      });
      say('걸어다니는 중 · 요청 ' + WALKED + ' · 모은 것 ' + RESULT.length
          + ' · 남은 폴더 ' + queue.length
          + ' · 지난 ' + dur((Date.now() - T0) / 1000)
          + ' · 최소 ' + dur(queue.length * GAP) + ' 더'
          + (UNOPENED.length ? ' · 안 열어본 ' + UNOPENED.length : ''));
    }
    TOOK = (Date.now() - T0) / 1000;
    /* 멈춰서 큐에 남은 것도 안 열어본 것이다 */
    queue.forEach(q => UNOPENED.push({
      rel: decodeURIComponent(q.url.slice(BASE.length)),
      why: STOPPED || '멈춤'
    }));
    return sum();
  };

  const depthOf = rel => rel.replace(/\/+$/, '').split('/').filter(Boolean).length;
  const deepest = () => RESULT.reduce((a, r) => Math.max(a, depthOf(r.rel)), 0);

  const sum = () => {
    const dirs = RESULT.filter(r => r.isDir).length;
    const files = RESULT.length - dirs;
    const bytes = RESULT.reduce((a, r) => a + (r.bytes || 0), 0);
    const cut = UNOPENED.length;
    return {
      md: paths(),
      status: '폴더 ' + dirs + ' · 파일 ' + files + ' · 어림 ' + (bytes / 1048576).toFixed(1) + 'MB'
             + ' · 깊이 ' + deepest() + ' · 요청 ' + WALKED
             + (TOOK ? ' · ' + dur(TOOK) + ' 걸림' : '')
             + (cut ? ' · 안 열어본 폴더 ' + cut + '. 아래 숫자는 일부다'
                    : ' · 다 봤다. 깊이가 전체 깊이다')
             + (STOPPED ? ' · ' + STOPPED : '')
    };
  };

  /* ── 내보내기 둘. 네트워크를 안 쓴다 ──────────── */
  const paths = () => {
    if (!RESULT.length) return '모은 것이 없다. 먼저 걸어다니기를 누를 것';
    const L = RESULT.map(r => LABEL + '/' + r.rel);
    L.sort();
    return L.join('\n');
  };
  const tsv = () => {
    if (!RESULT.length) return '모은 것이 없다. 먼저 걸어다니기를 누를 것';
    const L = ['경로\t종류\t크기표기\t바이트어림\t날짜'];
    RESULT.slice().sort((a, b) => a.rel.localeCompare(b.rel)).forEach(r => {
      L.push([LABEL + '/' + r.rel, r.isDir ? '폴더' : '파일',
              r.sizeTxt || '', r.bytes == null ? '' : r.bytes, r.date || ''].join('\t'));
    });
    const bytes = RESULT.reduce((a, r) => a + (r.bytes || 0), 0);
    L.push('');
    L.push('# 어림 합계 ' + bytes.toLocaleString() + ' 바이트');
    L.push('# 크기는 서버가 반올림한 값이다. 정확한 바이트가 아니다');
    L.push('# 본 깊이 ' + deepest());
    if (TOOK) L.push('# 걸린 시간 ' + dur(TOOK) + ' · 요청 ' + WALKED + '회');
    if (UNOPENED.length) L.push('# 남은 것을 다 보려면 최소 ' + dur(UNOPENED.length * GAP) + ' 더 든다');
    if (UNOPENED.length) {
      L.push('# 안 열어본 폴더 ' + UNOPENED.length + '. 위 숫자는 일부다');
      L.push('# 아래 주소에서 다시 눌러 이어서 걸어다닌다');
      UNOPENED.forEach(u => L.push('#   ' + LABEL + '/' + u.rel + '   (' + u.why + ')'));
    } else {
      L.push('# 안 열어본 폴더 없음. 전체를 다 봤고 위 깊이가 전체 깊이다');
    }
    L.push('# 수집 ' + new Date().toISOString().slice(0, 16).replace('T', ' ') + ' · ' + BASE);
    if (STOPPED) L.push('# ' + STOPPED);
    return L.join('\n');
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
  const dWrap = inp('깊이', '8', 2);
  const rWrap = inp('요청상한', '200', 4);

  const bHere = mk('이 쪽만', async () => {
    RESULT = parse(document, BASE); STOPPED = ''; WALKED = 0;
    return sum();
  }, false);
  const bWalk = mk('걸어다니기', async () =>
    walk(Math.max(1, parseInt(dWrap.__i.value, 10) || 4),
         Math.max(1, parseInt(rWrap.__i.value, 10) || 200)), true);
  const bPaths = mk('경로 목록', async () => ({ md: paths(), status: 'tree_scan 에 그대로 넣는다' }), false);
  const bTsv = mk('크기·날짜 TSV', async () => ({ md: tsv(), status: 'TSV ' + RESULT.length + '줄' }), false);

  const stopB = document.createElement('button');
  stopB.textContent = '중단';
  stopB.style.cssText = 'padding:3px 9px;cursor:pointer;font:12px sans-serif;background:#422;color:#fdd;border:1px solid #855';
  stopB.onclick = () => { ABORT = true; say('중단 요청. 현재 요청이 끝나면 멈춘다'); };
  const closeB = document.createElement('button');
  closeB.textContent = '닫기';
  closeB.style.cssText = 'padding:3px 9px;cursor:pointer;font:12px sans-serif;background:#422;color:#fdd;border:1px solid #855';
  closeB.onclick = () => box.remove();


  /* ── 최소화. 접어도 상태와 중단은 남긴다 ────── */
  let MINI = false;
  const miniB = document.createElement('button');
  miniB.textContent = '최소화';
  miniB.setAttribute('data-mini', '1');
  miniB.style.cssText = 'padding:3px 9px;cursor:pointer;font:12px sans-serif;background:#333;color:#ddd;border:1px solid #555';
  const KEEP = [st, miniB, stopB, closeB];
  miniB.onclick = () => {
    MINI = !MINI;
    box.style.inset = MINI ? 'auto 10px 10px auto' : '4%';
    box.style.maxWidth = MINI ? '52vw' : '';
    ta.style.display = MINI ? 'none' : '';
    [...bar.children].forEach(c => { c.style.display = (MINI && KEEP.indexOf(c) < 0) ? 'none' : ''; });
    miniB.textContent = MINI ? '펼치기' : '최소화';
  };

  bar.append(bHere, bWalk, bPaths, bTsv, dWrap, rWrap, st, stopB, miniB, closeB);
  box.append(bar, ta);
  document.body.appendChild(box);
  window.__IK = box;

  const n = parse(document, BASE);
  const nd = n.filter(r => r.isDir).length;
  say(VER + ' · ' + LABEL + ' · 이 쪽에 ' + nd + '폴더 '
      + n.filter(r => !r.isDir).length + '파일'
      + (nd ? ' · 깊이 1만 돌아도 최소 ' + dur(nd * GAP) : '')
      + ' · 파일은 요청하지 않는다');
})();
