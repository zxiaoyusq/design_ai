// 由CSS重放原始取景并直接截图为JPEG，不生成或修改照片中的视觉内容。
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { createHash } = require('node:crypto');
const assert = require('node:assert/strict');

const output = path.resolve(process.argv[2]);
const playwright = process.env.DESIGN_AI_PLAYWRIGHT_MODULE || '/tmp/bubble-ui-check/node_modules/playwright';
const { chromium } = require(playwright);

(async () => {
  const manifestPath = path.join(output, 'manifest.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ viewport: { width: manifest.width, height: manifest.height }, deviceScaleFactor: 1 });
    for (const board of manifest.boards) {
      await page.goto(pathToFileURL(path.join(output, board.html)).href);
      await page.evaluate(() => Promise.all([...document.images].map(image => image.decode())));
      const rendered = await page.evaluate(() => [...document.querySelectorAll('.frame')].map(frame => {
        const rect = frame.getBoundingClientRect();
        const image = frame.querySelector('img');
        return { id: frame.dataset.instanceId, rect: [rect.x, rect.y, rect.width, rect.height], loaded: image.complete && image.naturalWidth > 0 };
      }));
      assert.deepEqual(rendered.map(image => image.id).sort(), board.images.map(image => image.instance_id).sort());
      assert(rendered.every(image => image.loaded && image.rect[0] >= -0.01 && image.rect[1] >= -0.01 && image.rect[0] + image.rect[2] <= manifest.width + 0.01 && image.rect[1] + image.rect[3] <= manifest.height + 0.01));
      const file = path.join(output, board.image);
      await page.screenshot({ path: file, type: 'jpeg', quality: 96, animations: 'disabled' });
      board.output_sha256 = createHash('sha256').update(fs.readFileSync(file)).digest('hex');
      board.output_bytes = fs.statSync(file).size;
      board.rendered_instances = rendered.map(image => image.id);
      console.log(JSON.stringify({ image: board.image, count: board.retained_count, size: [manifest.width, manifest.height] }));
    }
    manifest.rendered_at = new Date().toISOString();
    manifest.output_encoding = 'JPEG quality 96 / Chromium screenshot';
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
