// Atlas de caracteres para o modo ASCII: uma linha de glifos, do mais vazio ao mais denso.
export const GLYPH_RAMP = ' .·:-=+*%#@';

const CELL_W = 40;
const CELL_H = 64;

export function createGlyphAtlas() {
  const canvas = document.createElement('canvas');
  canvas.width = CELL_W * GLYPH_RAMP.length;
  canvas.height = CELL_H;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#fff';
  ctx.font = `700 ${CELL_H * 0.72}px ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  [...GLYPH_RAMP].forEach((glifo, i) => {
    ctx.fillText(glifo, i * CELL_W + CELL_W / 2, CELL_H * 0.54);
  });
  return canvas;
}
