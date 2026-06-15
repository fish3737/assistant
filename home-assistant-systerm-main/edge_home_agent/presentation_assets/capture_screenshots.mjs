import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('/Users/fish37/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const root = process.cwd();
const out = path.join(root, 'presentation_assets', 'screenshots');
await fs.mkdir(out, { recursive: true });

async function makeEvidenceHtml() {
  const docker = await readText(path.join(out, 'docker_status.txt'));
  const events = await fs.readFile(path.join(root, 'experiments/mqtt_validation/events.csv'), 'utf8');
  const summary = await fs.readFile(path.join(root, 'experiments/final_results/summary.csv'), 'utf8');
  const files = await listFiles(path.join(root, 'experiments/final_results'));
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    body{margin:0;background:#eef2f6;color:#1d2b45;font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans GB','PingFang SC',Arial,sans-serif;}
    .page{width:1360px;min-height:820px;padding:44px 56px;box-sizing:border-box;}
    h1{font-size:34px;margin:0 0 10px;color:#142033;font-weight:650;letter-spacing:0;}
    .sub{font-size:18px;color:#60708a;margin-bottom:26px;}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;}
    .panel{background:#111b2c;border:1px solid #2c3a54;border-radius:18px;padding:22px;box-shadow:0 12px 34px rgba(24,35,55,.10);}
    .panel h2{font-size:21px;color:#8de5ff;margin:0 0 16px;font-weight:500;}
    pre{white-space:pre-wrap;word-break:break-word;color:#dbe6f7;font-size:14px;line-height:1.52;margin:0;font-family:'SF Mono','Menlo','Consolas',monospace;}
    .wide{grid-column:1 / span 2;}
  </style></head><body><div class="page">
    <h1>实验运行证据截图</h1><div class="sub">Docker 服务、真实 MQTT 验证事件与实验结果文件来自当前项目目录</div>
    <div class="grid">
      <section class="panel"><h2>Docker 服务状态</h2><pre>${escapeHtml(docker)}</pre></section>
      <section class="panel"><h2>结果文件</h2><pre>${escapeHtml(files.slice(0,22).join('\n'))}</pre></section>
      <section class="panel wide"><h2>真实 MQTT 验证事件片段</h2><pre>${escapeHtml(events.split('\n').slice(0,18).join('\n'))}</pre></section>
      <section class="panel wide"><h2>实验 summary.csv 片段</h2><pre>${escapeHtml(summary.split('\n').slice(0,8).join('\n'))}</pre></section>
    </div>
  </div></body></html>`;
  const htmlPath = path.join(out, 'evidence.html');
  await fs.writeFile(htmlPath, html, 'utf8');
  return htmlPath;
}

async function readText(p) { try { return await fs.readFile(p, 'utf8'); } catch { return ''; } }
function escapeHtml(s) { return s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
async function listFiles(dir) {
  const result = [];
  async function walk(d) {
    const entries = await fs.readdir(d, { withFileTypes: true });
    for (const e of entries) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) await walk(p); else result.push(path.relative(root, p));
    }
  }
  await walk(dir);
  return result.sort();
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1360, height: 820 }, deviceScaleFactor: 1 });
try {
  await page.goto('http://127.0.0.1:8123', { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(out, 'home_assistant_page.png'), fullPage: true });
} catch (e) {
  const fallback = `<!doctype html><meta charset="utf-8"><style>body{font-family:-apple-system,Arial;margin:0;background:#eef2f6;color:#142033}.box{margin:80px;padding:40px;background:white;border-radius:18px}</style><div class=box><h1>Home Assistant 页面截图失败</h1><p>${escapeHtml(String(e))}</p></div>`;
  const p = path.join(out, 'ha_fallback.html');
  await fs.writeFile(p, fallback, 'utf8');
  await page.goto('file://' + p);
  await page.screenshot({ path: path.join(out, 'home_assistant_page.png'), fullPage: true });
}

const evidenceHtml = await makeEvidenceHtml();
await page.goto('file://' + evidenceHtml, { waitUntil: 'domcontentloaded' });
await page.screenshot({ path: path.join(out, 'evidence_screenshot.png'), fullPage: true });
await browser.close();
