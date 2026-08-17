/**
 * Throwaway icon builder — rasterizes the DevScope reticle tile to the three
 * Chrome icon sizes. Each size gets a viewBox-tuned SVG so stroke weight and
 * tile corner radius stay visually correct; the 16px variant is simplified
 * (shorter crosshair ticks, heavier stroke, bigger dot) to stay legible.
 *
 * Run: node scripts/build-icons.mjs   (requires `npm install --no-save sharp`)
 */
import sharp from 'sharp';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PUBLIC = join(__dirname, '..', 'public');

const TILE = '#signalTile';
const GRAD = `
  <defs>
    <linearGradient id="signalTile" x1="0" y1="0" x2="0" y2="128" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#E86D13"/>
      <stop offset="1" stop-color="#C95A08"/>
    </linearGradient>
  </defs>`;

/**
 * Build an SVG string in a 0..128 coordinate space (sharp scales to `size`).
 * `simple` drops the reticle to its boldest essentials for the 16px tile.
 */
function svg({ stroke, rx, simple }) {
  const reticle = simple
    ? `
    <g stroke="#FFFFFF" stroke-width="${stroke}" stroke-linecap="round" fill="none">
      <circle cx="64" cy="64" r="40"/>
      <path d="M64 14V30"/>
      <path d="M64 98V114"/>
      <path d="M14 64H30"/>
      <path d="M98 64H114"/>
    </g>
    <circle cx="64" cy="64" r="13" fill="#FFFFFF"/>`
    : `
    <g stroke="#FFFFFF" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" fill="none">
      <circle cx="64" cy="64" r="39"/>
      <circle cx="64" cy="64" r="17"/>
      <path d="M64 9V25"/>
      <path d="M64 103V119"/>
      <path d="M9 64H25"/>
      <path d="M103 64H119"/>
    </g>
    <circle cx="64" cy="64" r="5.4" fill="#FFFFFF"/>`;

  return `<svg width="128" height="128" viewBox="0 0 128 128" xmlns="http://www.w3.org/2000/svg">${GRAD}
    <rect x="0" y="0" width="128" height="128" rx="${rx}" fill="url(${TILE})"/>${reticle}
  </svg>`;
}

const targets = [
  { size: 16, file: 'icon-16.png', stroke: 9, rx: 26, simple: true },
  { size: 48, file: 'icon-48.png', stroke: 6.5, rx: 28, simple: false },
  { size: 128, file: 'icon-128.png', stroke: 6, rx: 28, simple: false },
];

for (const t of targets) {
  const source = svg(t);
  const out = join(PUBLIC, t.file);
  await sharp(Buffer.from(source))
    .resize(t.size, t.size, { fit: 'fill' })
    .png({ compressionLevel: 9 })
    .toFile(out);
  const meta = await sharp(out).metadata();
  console.log(`${t.file}: ${meta.width}x${meta.height} (${meta.format})`);
}
writeFileSync(join(PUBLIC, '.icons-built'), new Date().toISOString());
