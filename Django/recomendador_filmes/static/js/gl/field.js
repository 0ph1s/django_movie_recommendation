// Fundo WebGL em caracteres ASCII, reativo ao cursor e à rolagem.
//
// O estado visual fica em `field.state` (objeto simples), para que o GSAP possa
// animá-lo diretamente: gsap.to(field.state, { density: 0.4 }).
import { COMPOSITE_FRAG, FIELD_FRAG, VERTEX } from './shaders.js';
import { createGlyphAtlas, GLYPH_RAMP } from './glyph-atlas.js';

const INKS = {
  silver: [0.847, 0.871, 0.91],
  cyan: [0.373, 0.765, 0.839],
  amber: [0.949, 0.647, 0.255],
  night: [0.039, 0.075, 0.133],
};

const CELL_CSS_PX = 9;
const MAX_DPR = 1.5;

export class AsciiField {
  constructor(canvas, { reduced = false } = {}) {
    this.canvas = canvas;
    this.reduced = reduced;
    this.state = {
      density: 0,
      cyan: 0.6,
      amber: 1,
      veil: 0,
      focusX: 0.8,
      focusY: 0.78,
      focusStrength: 0.8,
    };
    this.pointer = { x: -1e4, y: -1e4, tx: -1e4, ty: -1e4, force: 0 };
    this.scroll = 0;
    this.time = 7.3;
    this.dirty = true;
  }

  init() {
    const gl = this.canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false });
    if (!gl) return false;
    this.gl = gl;

    try {
      this.fieldProgram = this.#program(VERTEX, FIELD_FRAG);
      this.compositeProgram = this.#program(VERTEX, COMPOSITE_FRAG);
    } catch (erro) {
      console.warn('[Ângulo] shader indisponível:', erro);
      return false;
    }

    // Um triângulo que cobre a tela inteira.
    this.buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);

    this.fieldTexture = this.#texture();
    this.framebuffer = gl.createFramebuffer();
    this.glyphTexture = this.#texture();
    gl.bindTexture(gl.TEXTURE_2D, this.glyphTexture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, createGlyphAtlas());

    this.uniforms = {
      field: this.#locations(this.fieldProgram, ['uRes', 'uFieldRes', 'uTime', 'uMouse', 'uForce', 'uScroll', 'uFocus']),
      composite: this.#locations(this.compositeProgram, [
        'uField', 'uGlyphs', 'uRes', 'uCell', 'uDensity', 'uCyan', 'uAmber', 'uVeil',
        'uGlyphCount', 'uSilverInk', 'uCyanInk', 'uAmberInk', 'uNight',
      ]),
    };

    this.canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); this.lost = true; });
    window.addEventListener('resize', () => this.resize(), { passive: true });
    window.addEventListener('scroll', () => { this.dirty = true; }, { passive: true });
    if (!this.reduced) {
      window.addEventListener('pointermove', (e) => this.#onPointer(e), { passive: true });
    }
    this.resize();
    return true;
  }

  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    this.dpr = dpr;
    this.width = Math.max(1, Math.round(window.innerWidth * dpr));
    this.height = Math.max(1, Math.round(window.innerHeight * dpr));
    this.canvas.width = this.width;
    this.canvas.height = this.height;
    this.cell = CELL_CSS_PX * dpr;

    // A passada do campo só precisa de ~1,5 texel por célula de caractere.
    const gl = this.gl;
    this.fieldWidth = Math.ceil(this.width / (this.cell * 0.6));
    this.fieldHeight = Math.ceil(this.height / (this.cell * 0.6));
    gl.bindTexture(gl.TEXTURE_2D, this.fieldTexture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, this.fieldWidth, this.fieldHeight, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.framebuffer);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.fieldTexture, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.dirty = true;
  }

  invalidate() {
    this.dirty = true;
  }

  /** Avança e desenha um quadro. `deltaMs` vem do ticker do GSAP. */
  tick(deltaMs) {
    if (this.lost || !this.gl) return;
    const p = this.pointer;
    const animado = !this.reduced;

    if (animado) {
      this.time += Math.min(deltaMs, 50) / 1000;
      const ax = p.x, ay = p.y;
      p.x += (p.tx - p.x) * 0.12;
      p.y += (p.ty - p.y) * 0.12;
      const velocidade = Math.hypot(p.x - ax, p.y - ay) / (this.cell * 6);
      p.force += (Math.min(velocidade, 1) - p.force) * 0.08;
    }
    this.scroll = window.scrollY / Math.max(window.innerHeight, 1);

    if (!animado && !this.dirty) return;
    this.dirty = false;
    this.#draw();
  }

  #draw() {
    const gl = this.gl;
    const s = this.state;
    const p = this.pointer;

    // Passada 1: tons em baixa resolução.
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.framebuffer);
    gl.viewport(0, 0, this.fieldWidth, this.fieldHeight);
    gl.useProgram(this.fieldProgram);
    this.#bindQuad(this.fieldProgram);
    const f = this.uniforms.field;
    gl.uniform2f(f.uRes, this.width, this.height);
    gl.uniform2f(f.uFieldRes, this.fieldWidth, this.fieldHeight);
    gl.uniform1f(f.uTime, this.time);
    gl.uniform2f(f.uMouse, p.x * this.dpr, this.height - p.y * this.dpr);
    gl.uniform1f(f.uForce, p.force);
    gl.uniform1f(f.uScroll, this.scroll);
    gl.uniform3f(f.uFocus, s.focusX, s.focusY, s.focusStrength);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    // Passada 2: caracteres ASCII na resolução da tela.
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.width, this.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.compositeProgram);
    this.#bindQuad(this.compositeProgram);
    const c = this.uniforms.composite;
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.fieldTexture);
    gl.uniform1i(c.uField, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.glyphTexture);
    gl.uniform1i(c.uGlyphs, 1);
    gl.uniform2f(c.uRes, this.width, this.height);
    gl.uniform1f(c.uCell, this.cell);
    gl.uniform1f(c.uDensity, s.density);
    gl.uniform1f(c.uCyan, s.cyan);
    gl.uniform1f(c.uAmber, s.amber);
    gl.uniform1f(c.uVeil, s.veil);
    gl.uniform1f(c.uGlyphCount, GLYPH_RAMP.length);
    gl.uniform3fv(c.uSilverInk, INKS.silver);
    gl.uniform3fv(c.uCyanInk, INKS.cyan);
    gl.uniform3fv(c.uAmberInk, INKS.amber);
    gl.uniform3fv(c.uNight, INKS.night);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  #onPointer(e) {
    if (e.pointerType === 'touch') return;
    const p = this.pointer;
    if (p.tx < -1e3) { p.x = e.clientX; p.y = e.clientY; }  // primeira entrada: sem rastro
    p.tx = e.clientX;
    p.ty = e.clientY;
  }

  #bindQuad(programa) {
    const gl = this.gl;
    const local = gl.getAttribLocation(programa, 'aPos');
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.enableVertexAttribArray(local);
    gl.vertexAttribPointer(local, 2, gl.FLOAT, false, 0, 0);
  }

  #texture() {
    const gl = this.gl;
    const textura = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, textura);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return textura;
  }

  #program(vertexSource, fragmentSource) {
    const gl = this.gl;
    const compilar = (tipo, fonte) => {
      const shader = gl.createShader(tipo);
      gl.shaderSource(shader, fonte);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
      return shader;
    };
    const programa = gl.createProgram();
    gl.attachShader(programa, compilar(gl.VERTEX_SHADER, vertexSource));
    gl.attachShader(programa, compilar(gl.FRAGMENT_SHADER, fragmentSource));
    gl.linkProgram(programa);
    if (!gl.getProgramParameter(programa, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(programa));
    return programa;
  }

  #locations(programa, nomes) {
    return Object.fromEntries(nomes.map((n) => [n, this.gl.getUniformLocation(programa, n)]));
  }
}
