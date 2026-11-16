const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  p.on('pageerror', e => console.log('PAGEERROR', e.message));
  p.on('console', m => { if (m.type() === 'error') console.log('CONSOLE', m.text().slice(0, 300)); });
  await p.goto('http://127.0.0.1:8765/test.html' + (process.argv[3] ? '?dtype=' + process.argv[3] : ''));
  await p.waitForFunction(() => window.__out && window.__out.ok, null, { timeout: 900000 });
  const o = await p.evaluate(() => window.__out);
  require('fs').writeFileSync(process.argv[2], JSON.stringify(o, null, 1));
  console.log(JSON.stringify(o, (k, v) => k === 'res' ? undefined : v, 1));
  await b.close();
})();
