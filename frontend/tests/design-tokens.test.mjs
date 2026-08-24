import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const css = readFileSync(
  path.join(__dirname, '..', 'src', 'app', 'globals.css'),
  'utf8'
);

const bannedLiterals = [
  '#6366f1',
  '#818cf8',
  '#8b5cf6',
  '#a855f7',
  '99, 102, 241',
  '139, 92, 246',
  '168, 85, 247',
  '#22c55e',
  '#16a34a',
  '34, 197, 94',
  '#f0f0f5',
  '#8b8b9e',
];

test('old indigo/violet/purple and legacy literals are gone', () => {
  for (const literal of bannedLiterals) {
    assert.ok(
      !css.includes(literal),
      `expected "${literal}" to be absent from globals.css`
    );
  }
});

const expectedTokens = {
  '--bg-primary': '#0d0f12',
  '--bg-secondary': '#15181d',
  '--border-accent': 'rgba(122,160,190,0.35)',
  '--text-primary': '#e6e8eb',
  '--text-secondary': '#9aa3ad',
  '--text-muted': '#7e8891',
  '--accent': '#3f6d8f',
  '--accent-hover': '#4b80a5',
  '--accent-light': '#8fb3cd',
  '--accent-glow': 'rgba(63,109,143,0.14)',
  '--success': '#4a9a70',
  '--success-text': '#85c9a2',
  '--success-glow': 'rgba(74,154,112,0.12)',
  '--warning': '#d4a04a',
  '--danger': '#ea5a5f',
};

function readToken(name) {
  const re = new RegExp(`${name}\\s*:\\s*([^;]+);`);
  const match = css.match(re);
  return match ? match[1].replace(/\s+/g, '') : null;
}

test('new design tokens are defined with the agreed values', () => {
  for (const [name, expected] of Object.entries(expectedTokens)) {
    const actual = readToken(name);
    assert.equal(
      actual,
      expected.replace(/\s+/g, ''),
      `expected ${name} to be ${expected}, found ${actual}`
    );
  }
});

test('dead tokens --bg-glass and --gradient-subtle are removed', () => {
  assert.equal(readToken('--bg-glass'), null);
  assert.equal(readToken('--gradient-subtle'), null);
});

// WCAG 2.1 relative luminance / contrast ratio
function hexToRgb(hex) {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const num = parseInt(full, 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

function relativeLuminance([r, g, b]) {
  const [rs, gs, bs] = [r, g, b].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

function contrastRatio(hexA, hexB) {
  const lA = relativeLuminance(hexToRgb(hexA));
  const lB = relativeLuminance(hexToRgb(hexB));
  const [lighter, darker] = lA > lB ? [lA, lB] : [lB, lA];
  return (lighter + 0.05) / (darker + 0.05);
}

const contrastPairs = [
  ['--text-primary on --bg-primary', '#e6e8eb', '#0d0f12'],
  ['--text-secondary on --bg-primary', '#9aa3ad', '#0d0f12'],
  ['--text-muted on --bg-secondary', '#7e8891', '#15181d'],
  ['--accent-light on --bg-primary', '#8fb3cd', '#0d0f12'],
  ['white on --accent', '#ffffff', '#3f6d8f'],
  ['--success-text on --bg-primary', '#85c9a2', '#0d0f12'],
  ['--danger on error-banner tint', '#ea5a5f', '#15181d'],
  ['white on btn-success gradient (top stop)', '#ffffff', '#3a7d5b'],
  ['white on btn-success gradient (bottom stop)', '#ffffff', '#337152'],
];

test('text/background and label/fill pairs clear WCAG AA (4.5:1)', () => {
  for (const [label, fg, bg] of contrastPairs) {
    const ratio = contrastRatio(fg, bg);
    assert.ok(
      ratio >= 4.5,
      `${label}: expected contrast >= 4.5, got ${ratio.toFixed(2)}`
    );
  }
});
