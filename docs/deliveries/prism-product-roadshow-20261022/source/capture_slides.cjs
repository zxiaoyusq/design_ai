// 按当前 HTML 的投屏状态原样截图，只截舞台，保留页面自带的标题与页脚。
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');

const [inputPath, outputPath, playwrightModule] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error('用法：node capture_slides.cjs <HTML> <截图目录> [playwright 模块路径]');
const { chromium } = require(playwrightModule || 'playwright');
const input = path.resolve(inputPath);
const output = path.resolve(outputPath);
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const originalHash = digest(fs.readFileSync(input));
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const receipt = { source: input, source_sha256: originalHash, captured_at: new Date().toISOString(), slides: [] };
  try {
    // 使原生 1600×900 舞台的缩放恰好为 1；2 倍像素截图用于投屏清晰度。
    const context = await browser.newContext({ viewport: { width: 1636, height: 1006 }, deviceScaleFactor: 2, offline: true });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(input).href);
    await page.waitForFunction(() => document.documentElement.classList.contains('viewer-ready'));
    await page.evaluate(() => document.fonts.ready);
    const ids = await page.locator('.slide').evaluateAll(slides => slides.map(slide => slide.id));
    assert(ids.length > 0, '原 HTML 中没有可导出的页面');
    for (const [index, id] of ids.entries()) {
      await page.evaluate(id => { location.hash = id; }, id);
      await page.waitForFunction(id => document.querySelector('.slide.active')?.id === id, id);
      await page.locator(`#${id} img[data-board]`).evaluateAll(images => Promise.all(images.map(image => image.decode())));
      const stage = await page.locator('#stage').boundingBox();
      assert(Math.abs(stage.width - 1600) < .01 && Math.abs(stage.height - 900) < .01, '必须保持原生 16:9 舞台比例');
      const filename = `slide-${String(index + 1).padStart(2, '0')}.png`;
      const pixels = await page.locator('#stage').screenshot({ path: path.join(output, filename), animations: 'disabled', scale: 'device' });
      const width = pixels.readUInt32BE(16);
      const height = pixels.readUInt32BE(20);
      assert(width === 3200 && height === 1800, '截图像素不符合导出要求');
      const title = await page.locator(`#${id} .slide-question`).innerText();
      const item = { number: index + 1, id, title: title.replace(/\s+/g, ' ').trim(), backup: await page.locator(`#${id}`).evaluate(slide => slide.classList.contains('backup')), filename, width, height, sha256: digest(pixels) };
      if (id === 'slide-4') {
        // 坐标取自真实 DOM；仅记录两张可见图片的按钮，不覆盖旁边的完整长图入口。
        const zooms = await page.locator('#slide-4 .dna-mini-evidence > button[data-zoom]').evaluateAll(buttons => {
          const frame = document.querySelector('#stage').getBoundingClientRect();
          return buttons.map(button => {
            const image = button.querySelector('img');
            const box = button.getBoundingClientRect();
            return {
              key: image.dataset.board, title: button.dataset.title,
              src: image.src, image_width: image.naturalWidth, image_height: image.naturalHeight,
              bounds: [(box.x - frame.x) / frame.width, (box.y - frame.y) / frame.height, box.width / frame.width, box.height / frame.height],
            };
          });
        });
        item.zoom_hotspots = zooms.map(zoom => {
          assert(zoom.src.startsWith('data:image/png;base64,'), '放大图片必须已离线内嵌');
          const raw = Buffer.from(zoom.src.split(',')[1], 'base64');
          const filename = `zoom-04-${zoom.key}.png`;
          fs.writeFileSync(path.join(output, filename), raw);
          const { src, ...metadata } = zoom;
          return { ...metadata, filename, sha256: digest(raw) };
        });
      }
      receipt.slides.push(item);
    }
    assert.equal(digest(fs.readFileSync(input)), originalHash, '导出期间不能修改原 HTML');
    assert.equal(errors.length, 0, errors.join('\n'));
    fs.writeFileSync(path.join(output, 'capture.json'), JSON.stringify(receipt, null, 2) + '\n');
    // 联系表也由浏览器排版截图，便于逐页检查，不对原截图做裁剪或重排。
    const preview = await context.newPage({ viewport: { width: 1600, height: 1200 } });
    await preview.setViewportSize({ width: 1600, height: 1200 });
    await preview.setContent(`<style>*{box-sizing:border-box}body{margin:0;padding:16px;background:#dfe3e9;font:14px sans-serif}main{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}figure{margin:0}img{display:block;width:100%}figcaption{padding:7px 0;color:#17202b}</style><main>${receipt.slides.map(slide => `<figure><img src="data:image/png;base64,${fs.readFileSync(path.join(output, slide.filename)).toString('base64')}"><figcaption>${String(slide.number).padStart(2, '0')}</figcaption></figure>`).join('')}</main>`);
    await preview.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())));
    await preview.screenshot({ path: path.join(output, 'contact-sheet.png'), fullPage: true, scale: 'css' });
    console.log(JSON.stringify({ slides: receipt.slides.length, main: receipt.slides.filter(slide => !slide.backup).length, backup: receipt.slides.filter(slide => slide.backup).length, pixels: '3200x1800', output }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
