// Startup + playback benchmark for the packaged app (dist-electron/win-unpacked).
//
//   node tests/profiling/startup_bench.mjs --exe dist-electron/win-unpacked/FreqEnforcer.exe \
//        --runs 6 --label after [--open tests/fixtures/test_2s_C4.wav] [--out result.json]
//
// Each run launches the exe with its own --user-data-dir (so an installed,
// already-running FreqEnforcer does not trip the single-instance lock) and a
// Chrome DevTools port, then polls the renderer every ~5 ms:
//
//   firstWindow  first window of any kind exists (splash or main)
//   mainVisible  main window document.visibilityState === 'visible'
//   shell        the app shell (.app) is in the DOM
//   ready        engine ready: a file can be opened now
//   loaded       --open file loaded (file meta shown)
//   processed    first processed (B) result shown
//
// After `processed` it plays the sample for 2 s and reads CDP Performance
// metrics (script time, style recalcs, layouts) to show how much renderer work
// playback costs. Then it records the working set of the whole process tree.
// Run 1 is reported separately (first launch: disk cache, profile creation).

import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { tmpdir } from 'node:os';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]);
  return acc;
}, []));
const EXE = resolve(args.exe ?? 'dist-electron/win-unpacked/FreqEnforcer.exe');
const RUNS = Number(args.runs ?? 6);
const LABEL = args.label ?? 'run';
const OPEN = args.open ? resolve(args.open) : null;
const TIMEOUT = 60000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const PROBE = `(() => {
  const a = document.querySelector('.app');
  const cap = document.querySelector('.viewbar__caption');
  return JSON.stringify({
    v: document.visibilityState,
    shell: !!a,
    ready: !!a && (!a.dataset.engine || a.dataset.engine === 'ready'),
    loaded: !!document.querySelector('.file__meta'),
    b: !!cap && cap.textContent.trim().startsWith('B'),
  });
})()`;

class Cdp {
  constructor(url) { this.ws = new WebSocket(url); this.id = 0; this.pending = new Map(); }
  open() {
    return new Promise((res, rej) => {
      this.ws.onopen = res; this.ws.onerror = rej;
      this.ws.onmessage = (m) => {
        const d = JSON.parse(m.data);
        if (d.id && this.pending.has(d.id)) { this.pending.get(d.id)(d); this.pending.delete(d.id); }
      };
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res) => { this.pending.set(id, res); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  async eval(expr, opts = {}) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, ...opts });
    return r.result?.result?.value;
  }
  close() { try { this.ws.close(); } catch { /* closed */ } }
}

function memBreakdown() {
  const dir = dirname(EXE).replace(/'/g, "''");
  const out = execFileSync('powershell', ['-NoProfile', '-Command',
    `Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like '${dir}*' } | ForEach-Object {
       $t = if ($_.CommandLine -match '--type=([a-z-]+)') { $Matches[1] } elseif ($_.Name -like 'freqenforcer-backend*') { 'backend' } else { 'main' }
       "$t $([math]::Round($_.WorkingSetSize/1MB)) $([math]::Round($_.PrivatePageCount/1MB))" }`],
  { encoding: 'utf8' });
  return out.trim().split(/\r?\n/).filter(Boolean).map((l) => { const [type, ws, priv] = l.trim().split(' '); return { type, ws: +ws, priv: +priv }; });
}

function treeProcesses() {
  const dir = dirname(EXE).replace(/'/g, "''");
  const out = execFileSync('powershell', ['-NoProfile', '-Command',
    `Get-Process | Where-Object { $_.Path -like '${dir}*' } | ForEach-Object { "$($_.Id) $($_.WorkingSet64) $($_.PrivateMemorySize64)" }`],
  { encoding: 'utf8' });
  return out.trim().split(/\r?\n/).filter(Boolean).map((l) => l.split(' ').map(Number));
}

async function killTree(pid) {
  try { execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ }
  for (let i = 0; i < 100; i++) {
    const left = treeProcesses();
    if (!left.length) return;
    for (const [p] of left) { try { execFileSync('taskkill', ['/PID', String(p), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ } }
    await sleep(100);
  }
}

async function oneRun(n) {
  const port = 9400 + n;
  const profile = resolve(tmpdir(), `fe-bench-${LABEL}`);
  mkdirSync(profile, { recursive: true });
  const argv = [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`];
  if (OPEN) argv.push(`--fe-open=${OPEN}`);

  const t0 = performance.now();
  const child = spawn(EXE, argv, { stdio: 'ignore', windowsHide: false });
  const ms = () => Math.round(performance.now() - t0);
  const m = { run: n };
  let cdp = null;

  try {
    while (ms() < TIMEOUT) {
      let targets = [];
      try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); } catch { /* not up yet */ }
      const pages = targets.filter((t) => t.type === 'page');
      if (pages.length && m.firstWindow == null) m.firstWindow = ms();
      const main = pages.find((t) => /index\.html|localhost:5174/.test(t.url));
      if (main) { cdp = new Cdp(main.webSocketDebuggerUrl); await cdp.open(); break; }
      await sleep(5);
    }
    if (!cdp) throw new Error('main window never appeared');
    m.mainCreated = ms();

    while (ms() < TIMEOUT) {
      let s;
      try { s = JSON.parse(await cdp.eval(PROBE) ?? '{}'); } catch { s = {}; }
      if (s.v === 'visible' && m.mainVisible == null) m.mainVisible = ms();
      if (s.shell && m.shell == null) m.shell = ms();
      if (s.ready && m.ready == null) m.ready = ms();
      if (s.loaded && m.loaded == null) m.loaded = ms();
      if (s.b && m.processed == null) m.processed = ms();
      const done = m.mainVisible != null && m.ready != null && (!OPEN || m.processed != null);
      if (done) break;
      await sleep(5);
    }

    const paint = JSON.parse(await cdp.eval(`JSON.stringify({
      fcp: performance.getEntriesByType('paint').find((e) => e.name === 'first-contentful-paint')?.startTime ?? null,
      dcl: performance.getEntriesByType('navigation')[0]?.domContentLoadedEventEnd ?? null,
      heap: performance.memory?.usedJSHeapSize ?? null })`));
    m.rendererFcp = paint.fcp != null ? Math.round(paint.fcp) : null;
    m.rendererDcl = paint.dcl != null ? Math.round(paint.dcl) : null;
    m.jsHeapMB = paint.heap != null ? +(paint.heap / 1048576).toFixed(1) : null;

    if (OPEN && m.processed != null) {
      // 2 s of playback: how much renderer work does it cost?
      await sleep(300);
      await cdp.send('Performance.enable', { timeDomain: 'timeTicks' });
      const before = await cdp.send('Performance.getMetrics');
      await cdp.eval(`document.querySelector('.btn--play')?.click()`, { userGesture: true });
      await sleep(1000);
      const posText = await cdp.eval(`document.querySelector('.transport__time')?.textContent ?? ''`);
      await sleep(1000);
      const after = await cdp.send('Performance.getMetrics');
      await cdp.eval(`document.querySelector('.btn--play')?.click()`, { userGesture: true });
      const get = (r, k) => r.result.metrics.find((x) => x.name === k)?.value ?? 0;
      const d = (k) => get(after, k) - get(before, k);
      m.play2s = {
        scriptMs: Math.round(d('ScriptDuration') * 1000),
        taskMs: Math.round(d('TaskDuration') * 1000),
        styleRecalcs: d('RecalcStyleCount'),
        layouts: d('LayoutCount'),
        posAt1s: posText.trim().split(/\s/)[0],
      };
    }

    await sleep(1500);
    const procs = treeProcesses();
    m.procs = procs.length;
    m.workingSetMB = Math.round(procs.reduce((a, p) => a + p[1], 0) / 1048576);
    m.privateMB = Math.round(procs.reduce((a, p) => a + p[2], 0) / 1048576);
    if (n === 2) m.mem = memBreakdown();
  } catch (e) {
    m.error = String(e.message ?? e);
  } finally {
    cdp?.close();
    await killTree(child.pid);
    await sleep(800);
  }
  return m;
}

function median(xs) {
  const v = xs.filter((x) => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid] : Math.round((v[mid - 1] + v[mid]) / 2);
}

const KEYS = ['firstWindow', 'mainCreated', 'mainVisible', 'shell', 'ready', 'loaded', 'processed', 'rendererFcp', 'jsHeapMB', 'workingSetMB', 'privateMB', 'procs'];
const runs = [];
for (let i = 1; i <= RUNS; i++) {
  const r = await oneRun(i);
  runs.push(r);
  console.log(JSON.stringify(r));
}
const warm = runs.slice(1).filter((r) => !r.error);
const summary = { label: LABEL, exe: EXE, open: OPEN, first: runs[0], warmMedian: {} };
for (const k of KEYS) summary.warmMedian[k] = median(warm.map((r) => r[k]));
if (warm.some((r) => r.play2s)) {
  summary.warmMedian.play2s = Object.fromEntries(['scriptMs', 'taskMs', 'styleRecalcs', 'layouts']
    .map((k) => [k, median(warm.map((r) => r.play2s?.[k]))]));
}
console.log('\nSUMMARY ' + JSON.stringify(summary, null, 2));
if (args.out) writeFileSync(args.out, JSON.stringify({ summary, runs }, null, 2));
rmSync(resolve(tmpdir(), `fe-bench-${LABEL}`), { recursive: true, force: true });
