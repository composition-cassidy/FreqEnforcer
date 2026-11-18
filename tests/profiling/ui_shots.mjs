// Full-resolution screenshots of the packaged app in every theme / UI scale.
//
//   node tests/profiling/ui_shots.mjs --exe dist-electron/win-unpacked/FreqEnforcer.exe \
//        --open tests/fixtures/test_10s_C4_Fs4_tuned.wav --outdir docs/screenshots
//
// Uses its own --user-data-dir, so an installed FreqEnforcer that is already
// running is not affected. Each shot: set prefs in localStorage, resize the
// viewport (DevTools emulation), reload, wait for the processed (B) result, capture.

import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { tmpdir } from 'node:os';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]);
  return acc;
}, []));
const EXE = resolve(args.exe ?? 'dist-electron/win-unpacked/FreqEnforcer.exe');
const OPEN = resolve(args.open ?? 'tests/fixtures/test_10s_C4_Fs4_tuned.wav');
const OUT = resolve(args.outdir ?? 'docs/screenshots');
const PORT = 9533;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const SHOTS = [
  { name: 'ui-dark-1366', theme: 'dark', scale: 100, w: 1366, h: 768 },
  { name: 'ui-dark-1920', theme: 'dark', scale: 100, w: 1920, h: 1080, harm: true },
  { name: 'ui-dark-1920-150', theme: 'dark', scale: 150, w: 1920, h: 1080 },
  { name: 'ui-light-1366', theme: 'light', scale: 100, w: 1366, h: 768 },
  { name: 'ui-contrast-1366', theme: 'contrast', scale: 100, w: 1366, h: 768 },
  // (no 200 % shot: under viewport emulation the main process cannot clamp the
  // scale to the display, so it would show a layout users never get)
];

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
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return r.result?.result?.value;
  }
}

const profile = resolve(tmpdir(), 'fe-ui-shots');
rmSync(profile, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
const child = spawn(EXE, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, `--fe-open=${OPEN}`], { stdio: 'ignore' });

try {
  let page = null;
  for (let i = 0; i < 600 && !page; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      page = list.find((t) => t.type === 'page' && /index\.html/.test(t.url));
    } catch { /* not up yet */ }
    if (!page) await sleep(50);
  }
  if (!page) throw new Error('main window never appeared');
  const cdp = new Cdp(page.webSocketDebuggerUrl);
  await cdp.open();

  for (const s of SHOTS) {
    // Electron has no Browser.setWindowBounds; emulate the viewport instead.
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: s.w, height: s.h, deviceScaleFactor: 1, mobile: false });
    await cdp.eval(`localStorage.setItem('freqenforcer.prefs', JSON.stringify({ theme: '${s.theme}', ui_scale: ${s.scale} })); location.reload()`);
    await sleep(500);
    let ok = false;
    for (let i = 0; i < 400 && !ok; i++) {
      ok = await cdp.eval(`(document.querySelector('.viewbar__caption')?.textContent ?? '').trim().startsWith('B')`).catch(() => false);
      if (!ok) await sleep(50);
    }
    if (s.harm) {
      // turn on the harmonic limiter so the lower pane shows, then wait for the re-render
      await cdp.eval(`(() => { const b = [...document.querySelectorAll('.group__head')].find((x) => /advanced/i.test(x.textContent)); if (b && b.getAttribute('aria-expanded') !== 'true') b.click(); })()`);
      await sleep(200);
      await cdp.eval(`(() => { const l = [...document.querySelectorAll('.check')].find((x) => /enable/i.test(x.textContent)); l?.querySelector('input')?.click(); })()`);
      // the settings change reprocesses after a 600 ms debounce; wait for that
      // run to start, then for it to finish
      for (let i = 0; i < 60 && !(await cdp.eval(`!!document.querySelector('.progress i')`)); i++) await sleep(50);
      for (let i = 0; i < 400 && (await cdp.eval(`!!document.querySelector('.progress i')`)); i++) await sleep(50);
    }
    await sleep(400);
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(resolve(OUT, `${s.name}.png`), Buffer.from(shot.result.data, 'base64'));
    const dims = await cdp.eval('`${innerWidth}x${innerHeight} @${devicePixelRatio}`');
    console.log(`${s.name}: ${dims}${ok ? '' : ' (processed result not seen)'}`);
  }
} finally {
  try { execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ }
  await sleep(1000);
  rmSync(profile, { recursive: true, force: true });
}
