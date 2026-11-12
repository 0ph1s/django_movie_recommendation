// Mapa do gosto em canvas 2D: o catálogo inteiro (t-SNE), os seus títulos destacados e o
// centro do perfil. Zoom com a roda ou pinça, arrasto para mover, passar o mouse mostra o
// título, clicar seleciona (quem usa decide o que fazer, via `onSelect`).
import { gsap } from 'gsap';

import { api } from './api.js';
import { esc, KIND_LABEL } from './format.js';
import { posterHTML } from './poster.js';

const KIND_OF_LETTER = { m: 'movie', s: 'series', a: 'anime' };
// Fundo: um ponto por título, na cor do tipo e bem apagado.
const KIND_COLOR = {
  movie: 'rgba(216, 222, 232, 0.30)',
  series: 'rgba(242, 165, 65, 0.55)',
  anime: 'rgba(95, 195, 214, 0.55)',
};
const C = { silver: '#d8dee8', cyan: '#5fc3d6', dim: '#8794ab', night: '#0a1322', amber: '#f2a541' };
const HOVER_RADIUS = 10;   // px
const MIN_SCALE = 1;
const MAX_SCALE = 40;
const GRID = 48;           // grade de busca do ponto mais próximo

let pontosCache = null;    // o payload de /api/map/points/ é igual para todos: baixa uma vez
const titulosCache = new Map();

export async function loadPoints() {
  if (!pontosCache) {
    pontosCache = api('map/points/').then((dados) => {
      const n = dados.ids.length;
      const pontos = { n, ids: dados.ids, x: new Float32Array(n), y: new Float32Array(n), kinds: new Array(n), row: new Map() };
      for (let i = 0; i < n; i += 1) {
        pontos.x[i] = dados.x[i] / 1000;
        pontos.y[i] = dados.y[i] / 1000;
        pontos.kinds[i] = KIND_OF_LETTER[dados.kinds[i]];
        pontos.row.set(dados.ids[i], i);
      }
      return pontos;
    });
  }
  return pontosCache;
}

export function loadTitle(id) {
  if (!titulosCache.has(id)) titulosCache.set(id, api(`titles/${id}/`));
  return titulosCache.get(id);
}

export class TasteMap {
  constructor(raiz, { reduced = false, onSelect = () => {} } = {}) {
    this.raiz = raiz;
    this.reduced = reduced;
    this.onSelect = onSelect;
    this.canvas = raiz.querySelector('canvas');
    this.ctx = this.canvas.getContext('2d');
    this.tooltip = raiz.querySelector('[data-map-tooltip]');
    this.view = { scale: 1, tx: 0, ty: 0 };   // deslocamento em pixels CSS
    this.visible = new Set(['movie', 'series', 'anime']);
    this.user = new Map();                     // id -> estado
    this.center = null;                        // {x, y} animado
    this.selected = null;
    this.hovered = null;
    this.pointers = new Map();
    this.active = false;                       // só arrasta e dá zoom depois de clicado
    this.armed = null;
    this.dirty = true;
    this.pulse = 0;
  }

  async start(mapa) {
    this.points = await loadPoints();
    this.buildGrid();
    this.update(mapa, { animate: false });
    this.resize();
    new ResizeObserver(() => this.resize()).observe(this.canvas.parentElement);
    this.bind();
    this.loop();
  }

  // ------------------------------------------------------------ dados

  update(mapa, { animate = true } = {}) {
    this.user = new Map((mapa?.points || []).map((p) => [p.title_id, p.state]));
    const alvo = mapa?.center;
    if (!alvo) {
      this.center = null;
    } else if (!this.center || !animate || this.reduced) {
      this.center = { ...alvo };
    } else {
      gsap.to(this.center, { x: alvo.x, y: alvo.y, duration: 1.1, ease: 'expo.inOut', onUpdate: () => { this.dirty = true; } });
    }
    this.dirty = true;
  }

  setKinds(tipos) {
    this.visible = new Set(tipos);
    this.hovered = null;
    this.hideTooltip();
    this.dirty = true;
  }

  select(id) {
    this.selected = id;
    this.dirty = true;
  }

  buildGrid() {
    const { n, x, y } = this.points;
    this.grid = new Map();
    for (let i = 0; i < n; i += 1) {
      const chave = this.cellOf(x[i], y[i]);
      if (!this.grid.has(chave)) this.grid.set(chave, []);
      this.grid.get(chave).push(i);
    }
  }

  cellOf(x, y) {
    const cx = Math.min(GRID - 1, Math.max(0, Math.floor(((x + 1) / 2) * GRID)));
    const cy = Math.min(GRID - 1, Math.max(0, Math.floor(((y + 1) / 2) * GRID)));
    return cy * GRID + cx;
  }

  // ------------------------------------------------------------ geometria

  resize() {
    const caixa = this.canvas.parentElement.getBoundingClientRect();
    const largura = caixa.width;
    const altura = largura < 640 ? largura : largura * 0.62;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = largura;
    this.h = altura;
    this.dpr = dpr;
    this.canvas.width = Math.round(largura * dpr);
    this.canvas.height = Math.round(altura * dpr);
    this.canvas.style.height = `${altura}px`;
    this.dirty = true;
  }

  get base() {
    return (Math.min(this.w, this.h) / 2) * 0.92;
  }

  toScreen(x, y) {
    const s = this.base * this.view.scale;
    return [this.w / 2 + x * s + this.view.tx, this.h / 2 + y * s + this.view.ty];
  }

  toWorld(px, py) {
    const s = this.base * this.view.scale;
    return [(px - this.w / 2 - this.view.tx) / s, (py - this.h / 2 - this.view.ty) / s];
  }

  /** Zoom mantendo fixo o ponto da tela (px, py). */
  zoomAt(px, py, fator, { animate = false } = {}) {
    const escala = Math.min(MAX_SCALE, Math.max(MIN_SCALE, this.view.scale * fator));
    const [wx, wy] = this.toWorld(px, py);
    const s = this.base * escala;
    const destino = { scale: escala, tx: px - this.w / 2 - wx * s, ty: py - this.h / 2 - wy * s };
    this.goTo(destino, animate);
  }

  goTo(destino, animate = true) {
    if (!animate || this.reduced) {
      Object.assign(this.view, destino);
      this.dirty = true;
      return;
    }
    gsap.to(this.view, { ...destino, duration: 0.7, ease: 'expo.out', overwrite: true, onUpdate: () => { this.dirty = true; } });
  }

  reset() {
    this.goTo({ scale: 1, tx: 0, ty: 0 });
  }

  /** Aproxima e centraliza o centro do perfil. */
  focusCenter() {
    if (!this.center) return;
    const escala = 4;
    const s = this.base * escala;
    this.goTo({ scale: escala, tx: -this.center.x * s, ty: -this.center.y * s });
  }

  nearest(px, py) {
    const [wx, wy] = this.toWorld(px, py);
    const raio = HOVER_RADIUS / (this.base * this.view.scale);
    const passo = 2 / GRID;
    const alcance = Math.ceil(raio / passo);
    const cx = Math.floor(((wx + 1) / 2) * GRID);
    const cy = Math.floor(((wy + 1) / 2) * GRID);
    let melhor = null;
    let menor = raio * raio;
    for (let gy = cy - alcance; gy <= cy + alcance; gy += 1) {
      for (let gx = cx - alcance; gx <= cx + alcance; gx += 1) {
        if (gx < 0 || gy < 0 || gx >= GRID || gy >= GRID) continue;
        for (const i of this.grid.get(gy * GRID + gx) || []) {
          if (!this.visible.has(this.points.kinds[i])) continue;
          const dx = this.points.x[i] - wx;
          const dy = this.points.y[i] - wy;
          // Os seus títulos ganham prioridade (o "raio" deles é maior).
          const d = (dx * dx + dy * dy) * (this.user.has(this.points.ids[i]) ? 0.4 : 1);
          if (d < menor) {
            menor = d;
            melhor = i;
          }
        }
      }
    }
    return melhor;
  }

  // ------------------------------------------------------------ eventos

  bind() {
    const tela = this.canvas;
    const local = (e) => {
      const r = tela.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };

    // Inativo, o mapa deixa a roda e o toque para a página; um clique (ou toque) sem arrasto o ativa
    // e um clique fora dele (ou Esc) desativa. Os controles de zoom e tipo contam como "dentro".
    document.addEventListener('pointerdown', (e) => {
      if (this.active && !this.raiz.contains(e.target) && !e.target.closest?.('[data-map-controls]')) this.setActive(false);
    }, true);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.active) this.setActive(false);
    });

    tela.addEventListener('wheel', (e) => {
      if (!this.active) return;
      e.preventDefault();
      const [px, py] = local(e);
      this.zoomAt(px, py, Math.exp(-e.deltaY * 0.0018));
    }, { passive: false });

    tela.addEventListener('pointerdown', (e) => {
      if (!this.active) {
        this.armed = { id: e.pointerId, inicio: local(e) };
        return;
      }
      // Captura o ponteiro para o arrasto seguir fora do canvas (pode falhar sem um ponteiro ativo).
      try { tela.setPointerCapture(e.pointerId); } catch { /* segue sem captura */ }
      this.pointers.set(e.pointerId, { inicio: local(e), ultimo: local(e) });
      this.moved = false;
      if (this.pointers.size === 2) this.pinch = this.pinchDistance();
    });

    tela.addEventListener('pointermove', (e) => {
      const ponto = local(e);
      const toque = this.pointers.get(e.pointerId);
      if (!toque) {
        if (e.pointerType === 'mouse') this.hover(ponto);
        return;
      }
      const [dx, dy] = [ponto[0] - toque.ultimo[0], ponto[1] - toque.ultimo[1]];
      toque.ultimo = ponto;
      if (Math.hypot(ponto[0] - toque.inicio[0], ponto[1] - toque.inicio[1]) > 4) this.moved = true;
      if (this.pointers.size === 2) {
        const distancia = this.pinchDistance();
        const [a, b] = [...this.pointers.values()].map((p) => p.ultimo);
        this.zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, distancia / (this.pinch || distancia));
        this.pinch = distancia;
      } else if (this.moved) {
        gsap.killTweensOf(this.view);
        this.view.tx += dx;
        this.view.ty += dy;
        this.dirty = true;
        this.hideTooltip();
      }
    });

    const soltar = (e) => {
      if (!this.active) {
        const armado = this.armed;
        this.armed = null;
        if (armado?.id === e.pointerId && e.type === 'pointerup') {
          const [x, y] = local(e);
          if (Math.hypot(x - armado.inicio[0], y - armado.inicio[1]) <= 6) this.setActive(true);
        }
        return;
      }
      const toque = this.pointers.get(e.pointerId);
      this.pointers.delete(e.pointerId);
      if (this.pointers.size < 2) this.pinch = null;
      if (toque && !this.moved && e.type === 'pointerup') {
        const i = this.nearest(...local(e));
        if (i !== null) {
          this.select(this.points.ids[i]);
          this.onSelect(this.points.ids[i]);
        }
      }
    };
    tela.addEventListener('pointerup', soltar);
    tela.addEventListener('pointercancel', soltar);
    tela.addEventListener('pointerleave', () => {
      this.hovered = null;
      this.hideTooltip();
      this.dirty = true;
    });
    tela.addEventListener('dblclick', (e) => {
      if (this.active) this.zoomAt(...local(e), 2, { animate: true });
    });

    // Só anima enquanto o mapa está na tela.
    new IntersectionObserver(([entrada]) => { this.onScreen = entrada.isIntersecting; }).observe(tela);
  }

  setActive(ativo) {
    if (this.active === ativo) return;
    this.active = ativo;
    this.raiz.classList.toggle('is-active', ativo);
    // Ativo, o Lenis ignora a roda sobre o mapa; inativo, ela rola a página normalmente.
    this.raiz.toggleAttribute('data-lenis-prevent', ativo);
    if (!ativo) {
      this.pointers.clear();
      this.pinch = null;
    }
    this.canvas.style.cursor = '';
  }

  pinchDistance() {
    const [a, b] = [...this.pointers.values()].map((p) => p.ultimo);
    return Math.hypot(a[0] - b[0], a[1] - b[1]);
  }

  async hover(ponto) {
    const i = this.nearest(...ponto);
    this.canvas.style.cursor = !this.active ? '' : i === null ? 'grab' : 'pointer';
    if (i === this.hovered) {
      if (i !== null) this.placeTooltip(ponto);
      return;
    }
    this.hovered = i;
    this.dirty = true;
    if (i === null) {
      this.hideTooltip();
      return;
    }
    const id = this.points.ids[i];
    this.placeTooltip(ponto);
    this.tooltip.innerHTML = '<p class="text-xs text-dim">…</p>';
    this.tooltip.hidden = false;
    const titulo = await loadTitle(id).catch(() => null);
    if (this.hovered !== i || !titulo) return;
    const estado = this.user.get(id);
    this.tooltip.innerHTML = `
      <div class="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-3">
        <div>${posterHTML(titulo, { size: 'sm' })}</div>
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold">${esc(titulo.title)}</p>
          <p class="text-xs text-dim">${esc(KIND_LABEL[titulo.kind])}${titulo.year ? ` de ${titulo.year}` : ''}</p>
          <p class="mt-1 text-[0.6875rem] text-dim">${estado ? 'No seu perfil · ' : ''}clique para avaliar</p>
        </div>
      </div>`;
  }

  placeTooltip([px, py]) {
    const largura = 240;
    const esquerda = px + 16 + largura > this.w ? px - 16 - largura : px + 16;
    this.tooltip.style.transform = `translate(${Math.max(0, esquerda)}px, ${Math.max(0, py - 20)}px)`;
  }

  hideTooltip() {
    this.tooltip.hidden = true;
  }

  // ------------------------------------------------------------ desenho

  loop() {
    const quadro = (tempo) => {
      if (this.onScreen !== false) {
        if (this.center && !this.reduced) {
          this.pulse = (tempo / 1600) % 1;
          this.dirty = true;
        }
        if (this.dirty) this.draw();
      }
      requestAnimationFrame(quadro);
    };
    requestAnimationFrame(quadro);
  }

  draw() {
    this.dirty = false;
    const { ctx, points: p } = this;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.w, this.h);
    const lado = Math.min(3.2, 1.6 + Math.log2(this.view.scale) * 0.45);

    // Fundo: um quadradinho por título, agrupado por tipo (uma cor por passada).
    for (const tipo of ['movie', 'series', 'anime']) {
      if (!this.visible.has(tipo)) continue;
      ctx.fillStyle = KIND_COLOR[tipo];
      for (let i = 0; i < p.n; i += 1) {
        if (p.kinds[i] !== tipo) continue;
        const [x, y] = this.toScreen(p.x[i], p.y[i]);
        if (x < -4 || y < -4 || x > this.w + 4 || y > this.h + 4) continue;
        ctx.fillRect(x - lado / 2, y - lado / 2, lado, lado);
      }
    }

    // Os seus títulos por cima.
    for (const [id, estado] of this.user) {
      const i = p.row.get(id);
      if (i === undefined || !this.visible.has(p.kinds[i])) continue;
      this.drawUserPoint(...this.toScreen(p.x[i], p.y[i]), estado);
    }

    if (this.center) this.drawCenter(...this.toScreen(this.center.x, this.center.y));

    for (const [indice, cor, raio] of [[this.hovered, C.silver, 7], [this.selected === null ? null : p.row.get(this.selected), C.cyan, 9]]) {
      if (indice === null || indice === undefined) continue;
      const [x, y] = this.toScreen(p.x[indice], p.y[indice]);
      ctx.beginPath();
      ctx.arc(x, y, raio, 0, Math.PI * 2);
      ctx.strokeStyle = cor;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }

  drawUserPoint(x, y, estado) {
    const { ctx } = this;
    ctx.setLineDash([]);
    ctx.beginPath();
    if (estado === 'favorite' || estado === 'like') {
      ctx.arc(x, y, estado === 'favorite' ? 5.5 : 4.2, 0, Math.PI * 2);
      ctx.fillStyle = estado === 'favorite' ? C.cyan : C.silver;
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = C.night;
      ctx.stroke();
    } else if (estado === 'dislike') {
      const r = 3.5;
      ctx.moveTo(x - r, y - r); ctx.lineTo(x + r, y + r);
      ctx.moveTo(x + r, y - r); ctx.lineTo(x - r, y + r);
      ctx.strokeStyle = C.dim;
      ctx.lineWidth = 1.6;
      ctx.stroke();
    } else if (estado === 'seen') {
      ctx.arc(x, y, 2.6, 0, Math.PI * 2);
      ctx.fillStyle = C.dim;
      ctx.fill();
    } else if (estado === 'watchlist') {
      ctx.arc(x, y, 4.2, 0, Math.PI * 2);
      ctx.setLineDash([2, 2]);
      ctx.strokeStyle = C.silver;
      ctx.lineWidth = 1.4;
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  drawCenter(x, y) {
    const { ctx } = this;
    ctx.setLineDash([]);
    if (!this.reduced) {
      ctx.beginPath();
      ctx.arc(x, y, 10 + this.pulse * 18, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(95, 195, 214, ${0.55 * (1 - this.pulse)})`;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(x, y, 9, 0, Math.PI * 2);
    ctx.strokeStyle = C.cyan;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - 15, y); ctx.lineTo(x - 5, y);
    ctx.moveTo(x + 5, y); ctx.lineTo(x + 15, y);
    ctx.moveTo(x, y - 15); ctx.lineTo(x, y - 5);
    ctx.moveTo(x, y + 5); ctx.lineTo(x, y + 15);
    ctx.stroke();
  }
}
