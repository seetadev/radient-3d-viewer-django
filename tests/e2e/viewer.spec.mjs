import { test, expect } from '@playwright/test';
import { PNG } from 'pngjs';

const MODELS = ['spacesuit', 'lamborghini', 'leeperrysmith', 'factory', 'elephant'];
const BG = 222; // 0xDEDEDE clear colour

let failed, errors;
test.beforeEach(async ({ page }) => {
  failed = []; errors = [];
  page.on('response', (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`); });
  page.on('requestfailed', (r) => failed.push(`FAILED ${r.url()}`));
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
});

const loaded = (page, model) =>
  page.waitForSelector(`#viewer-container[data-loaded="true"][data-model="${model}"]`, { timeout: 60_000 });

// Measures the rendered canvas: number of non-background pixels, their centroid and mean colour.
async function measure(page) {
  await page.mouse.move(990, 690);       // collapse the hover-expanded control panel
  await page.waitForTimeout(900);
  const png = PNG.sync.read(await page.locator('canvas').screenshot());
  let n = 0, sx = 0, sy = 0; const rgb = [0, 0, 0];
  for (let y = 0; y < png.height; y++) {
    for (let x = 0; x < png.width; x++) {
      if (x < 80 && y < 80) continue; // CAM overlay
      const i = (y * png.width + x) * 4, d = png.data;
      if (Math.abs(d[i] - BG) + Math.abs(d[i + 1] - BG) + Math.abs(d[i + 2] - BG) > 30) {
        n++; sx += x; sy += y; rgb[0] += d[i]; rgb[1] += d[i + 1]; rgb[2] += d[i + 2];
      }
    }
  }
  return { n, cx: sx / n, cy: sy / n, rgb: rgb.map((v) => v / n) };
}

test('every model loads and renders', async ({ page }) => {
  await page.goto('/');
  for (const m of MODELS) {
    await page.click(`.model-btn:text-is("${m}")`);
    await loaded(page, m);
    const s = await measure(page);
    expect(s.n, `${m} should render visible geometry`).toBeGreaterThan(5000);
  }
  expect(failed, 'failed requests').toEqual([]);
  expect(errors, 'page errors').toEqual([]);
});

test('colour picker, move buttons, camera and light controls change the render', async ({ page }) => {
  await page.goto('/');
  await loaded(page, 'spacesuit');
  const base = await measure(page);

  await page.locator('#hex-color').fill('#ff0000');
  const red = await measure(page);
  expect(red.rgb[0]).toBeGreaterThan(red.rgb[1] + 60);          // clearly red now
  expect(base.rgb[0]).toBeLessThan(base.rgb[1] + 30);           // was greenish-grey

  await page.hover('#viewer-overlay');
  await page.waitForTimeout(700);
  const box = await page.locator('#move-mesh-right').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down(); await page.waitForTimeout(600); await page.mouse.up();
  const moved = await measure(page);
  expect(moved.cx - red.cx).toBeGreaterThan(5);                  // shifted right

  await page.evaluate(() => { const e = document.querySelector('#camera-degree'); e.value = 135; e.dispatchEvent(new Event('input')); });
  const cam = await measure(page);
  expect(Math.abs(cam.cx - moved.cx) + Math.abs(cam.n - moved.n)).toBeGreaterThan(5);

  await page.evaluate(() => { const e = document.querySelector('#pointLight-x'); e.value = -600; e.dispatchEvent(new Event('input')); });
  const light = await measure(page);
  expect(Math.abs(light.rgb[0] - cam.rgb[0])).toBeGreaterThan(1);

  await page.click('.model-btn:text-is("elephant")');            // colour survives a model switch
  await loaded(page, 'elephant');
  const ele = await measure(page);
  expect(ele.rgb[0]).toBeGreaterThan(ele.rgb[1] + 60);

  expect(failed, 'failed requests').toEqual([]);
  expect(errors, 'page errors').toEqual([]);
});

test('switching models quickly settles on the last one clicked', async ({ page }) => {
  await page.goto('/');
  await loaded(page, 'spacesuit');
  for (const m of ['elephant', 'factory', 'lamborghini']) await page.click(`.model-btn:text-is("${m}")`);
  await loaded(page, 'lamborghini');
  await page.waitForTimeout(1500);
  await expect(page.locator('#viewer-container')).toHaveAttribute('data-model', 'lamborghini');
  expect(errors).toEqual([]);
});
