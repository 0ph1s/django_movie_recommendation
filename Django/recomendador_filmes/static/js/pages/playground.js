// Playground: catálogo à esquerda, perfil + filtro híbrido + recomendações à direita.
// Toda ação (curtir, mexer num controle, buscar "parecidos") recalcula na hora.
import { gsap } from 'gsap';
import { Flip } from 'gsap/Flip';

import { initMagnetic } from '../fx/magnetic.js';
import { initTilt } from '../fx/tilt.js';
import { api, isAbort } from '../lib/api.js';
import { debounce, esc, fmt, KIND_LABEL, KIND_PLURAL } from '../lib/format.js';
import { posterCaption, posterHTML } from '../lib/poster.js';

const PAGE_SIZE = 24;
const RESULTS = 12;
const BLOCK_LABEL = { synopsis: 'sinopse', tags: 'etiquetas', attributes: 'atributos' };
const LIKE = 1;
const DISLIKE = -1;

const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
const $$ = (seletor, raiz = document) => [...raiz.querySelectorAll(seletor)];

export default function playground({ field, reduced }) {
  if (field) {
    gsap.to(field.state, { density: 0.13, focusStrength: 0.4, duration: 1.6, ease: 'power2.out', onUpdate: () => field.invalidate() });
  }
  new Playground({ field, reduced }).start();
}

class Playground {
  constructor({ field, reduced }) {
    this.field = field;
    this.reduced = reduced;
    this.catalog = { q: '', kind: '', offset: 0, total: 0, first: true };
    this.history = new Map();   // title_id -> { signal, title }
    this.mode = 'profile';
    this.similar = null;        // card do título de referência no modo "parecidos"

    const raiz = $('[data-playground]');
    this.el = {
      search: $('[data-search]', raiz),
      kindButtons: $$('[data-catalog-kinds] [data-kind]', raiz),
      grid: $('[data-catalog-grid]', raiz),
      status: $('[data-catalog-status]', raiz),
      loadMore: $('[data-load-more]', raiz),
      tabs: $$('[data-mode]', raiz),
      stats: $('[data-stats]', raiz),
      history: $('[data-history]', raiz),
      reset: $('[data-reset]', raiz),
      dna: $('[data-dna]', raiz),
      dnaList: $('[data-dna-list]', raiz),
      dnaSummary: $('[data-dna-summary]', raiz),
      sliders: $$('[data-param]', raiz),
      recKinds: $$('[data-rec-kind]', raiz),
      resultsTitle: $('[data-results-title]', raiz),
      resultsNote: $('[data-results-note]', raiz),
      results: $('[data-results]', raiz),
      matrixSection: $('[data-matrix-section]', raiz),
      matrix: $('[data-matrix]', raiz),
    };
    this.refreshSoon = debounce(() => this.refresh(), 140);
  }

  async start() {
    this.bind();
    this.el.sliders.forEach((s) => this.showSlider(s));
    this.syncInks();

    const inicial = Number(new URLSearchParams(location.search).get('similar'));
    if (inicial) {
      try {
        this.similar = await api(`titles/${inicial}/`);
        this.mode = 'similar';
      } catch { /* id inválido: segue no modo perfil */ }
    }
    await Promise.all([this.loadCatalog(), this.loadProfile()]);
    this.refresh();
  }

  // ------------------------------------------------------------ eventos

  bind() {
    const { el } = this;
    el.search.addEventListener('input', debounce(() => {
      this.catalog.q = el.search.value;
      this.loadCatalog();
    }, 220));

    el.kindButtons.forEach((botao) => botao.addEventListener('click', () => {
      el.kindButtons.forEach((b) => b.setAttribute('aria-pressed', String(b === botao)));
      this.catalog.kind = botao.dataset.kind;
      this.loadCatalog();
    }));

    el.loadMore.addEventListener('click', () => this.loadCatalog({ append: true }));

    // Ações dos pôsteres (catálogo e recomendações) por delegação.
    document.addEventListener('click', (evento) => {
      const botao = evento.target.closest('[data-act]');
      if (!botao) return;
      const id = Number(botao.closest('[data-id]').dataset.id);
      const card = this.cards.get(id);
      if (botao.dataset.act === 'like') this.toggleSignal(card, LIKE);
      if (botao.dataset.act === 'dislike') this.toggleSignal(card, DISLIKE);
      if (botao.dataset.act === 'similar') this.showSimilar(card);
    });

    el.history.addEventListener('click', (evento) => {
      const botao = evento.target.closest('[data-remove]');
      if (botao) this.removeSignal(Number(botao.dataset.remove));
    });

    el.reset.addEventListener('click', async () => {
      const dados = await api('profile/', { method: 'DELETE' });
      this.setHistory(dados.history);
      this.refresh();
    });

    el.tabs.forEach((aba) => aba.addEventListener('click', () => {
      if (aba.disabled) return;
      this.mode = aba.dataset.mode;
      this.refresh();
    }));

    el.sliders.forEach((slider) => slider.addEventListener('input', () => {
      this.showSlider(slider);
      if (slider.dataset.param === 'alpha') this.syncInks();
      this.refreshSoon();
    }));

    el.recKinds.forEach((caixa) => caixa.addEventListener('change', () => {
      // Pelo menos um tipo precisa ficar marcado.
      if (!el.recKinds.some((c) => c.checked)) caixa.checked = true;
      this.refreshSoon();
    }));
  }

  // Todos os cards já vistos (catálogo, recomendações, histórico), por id.
  cards = new Map();

  remember(titulos) {
    titulos.forEach((t) => this.cards.set(t.id, t));
  }

  // ------------------------------------------------------------ catálogo

  async loadCatalog({ append = false } = {}) {
    const c = this.catalog;
    c.offset = append ? c.offset + PAGE_SIZE : 0;
    this.el.grid.setAttribute('aria-busy', 'true');
    try {
      const dados = await api('catalog/', {
        params: { q: c.q, kinds: c.kind, limit: PAGE_SIZE, offset: c.offset },
        channel: 'catalog',
      });
      c.total = dados.count;
      this.remember(dados.results);
      this.renderCatalog(dados, append);
    } catch (erro) {
      if (!isAbort(erro)) this.el.status.textContent = erro.message;
    } finally {
      this.el.grid.removeAttribute('aria-busy');
    }
  }

  renderCatalog(dados, append) {
    const { el, catalog: c } = this;
    const termo = c.q.trim();
    if (!dados.count) {
      el.status.textContent = termo ? `Nada encontrado para “${termo}”. Confira a grafia ou busque pelo título original.` : 'O catálogo está vazio. Rode python manage.py import_dataset.';
    } else if (dados.approximate) {
      el.status.textContent = `Nenhum título com “${termo}”. Mostrando os nomes mais parecidos.`;
    } else {
      el.status.textContent = termo
        ? `${fmt.int(dados.count)} ${dados.count === 1 ? 'resultado' : 'resultados'} para “${termo}”`
        : `${fmt.int(dados.count)} títulos, dos mais populares para os menos. Clique num pôster para ver os parecidos.`;
    }

    const html = dados.results.map((t) => this.catalogItem(t)).join('');
    if (append) el.grid.insertAdjacentHTML('beforeend', html);
    else el.grid.innerHTML = html;

    const novos = $$('li:not([data-ready])', el.grid);
    novos.forEach((li) => { li.dataset.ready = ''; });
    initTilt(el.grid, { reduced: this.reduced });
    el.loadMore.classList.toggle('hidden', c.offset + PAGE_SIZE >= c.total);
    initMagnetic(el.loadMore.parentElement, { reduced: this.reduced });

    if (!this.reduced && novos.length) {
      gsap.from(novos, {
        y: c.first ? 48 : 16,
        autoAlpha: 0,
        duration: c.first ? 1 : 0.5,
        ease: 'expo.out',
        stagger: c.first ? 0.04 : 0.015,
      });
    }
    c.first = false;
  }

  catalogItem(t) {
    const sinal = this.history.get(t.id)?.signal;
    return `
      <li data-id="${t.id}" data-signal="${sinal || ''}" class="group/item data-[signal='-1']:opacity-55">
        <button type="button" data-act="similar" aria-label="Ver parecidos com ${esc(t.title)}"
          class="block w-full rounded-[4px] text-left ring-offset-4 ring-offset-night group-data-[signal='1']/item:ring-2 group-data-[signal='1']/item:ring-cyan">
          ${posterHTML(t)}
        </button>
        ${posterCaption(t)}
        <p class="${t.poster_url ? 'mt-0.5' : 'mt-2.5'} line-clamp-1 text-xs text-dim">${esc(t.genres.slice(0, 3).join(', ') || KIND_LABEL[t.kind])}</p>
        ${this.actions(t, sinal, { similar: false })}
      </li>`;
  }

  actions(t, sinal, { compact = false, similar = true } = {}) {
    const base = 'whitespace-nowrap rounded-full border px-2.5 py-1 text-xs transition-colors';
    const tamanho = compact ? '' : 'flex-1';
    return `
      <div class="mt-2 flex gap-1.5" role="group" aria-label="Avaliar ${esc(t.title)}">
        <button type="button" data-act="like" aria-pressed="${sinal === LIKE}"
          class="${base} ${tamanho} border-rule hover:border-cyan aria-pressed:border-cyan aria-pressed:bg-cyan aria-pressed:text-night">Curti</button>
        <button type="button" data-act="dislike" aria-pressed="${sinal === DISLIKE}"
          class="${base} ${tamanho} border-rule hover:border-silver/60 aria-pressed:border-silver aria-pressed:bg-silver aria-pressed:text-night">Não curti</button>
        ${similar ? `<button type="button" data-act="similar" aria-label="Ver parecidos com ${esc(t.title)}"
          class="${base} border-rule hover:border-silver/60">Parecidos</button>` : ''}
      </div>`;
  }

  /** Atualiza o estado visual de um título em todas as listas onde ele aparece. */
  paintSignal(id) {
    const sinal = this.history.get(id)?.signal;
    $$(`[data-id="${id}"]`).forEach((item) => {
      item.dataset.signal = sinal || '';
      $$('[data-act="like"]', item).forEach((b) => b.setAttribute('aria-pressed', String(sinal === LIKE)));
      $$('[data-act="dislike"]', item).forEach((b) => b.setAttribute('aria-pressed', String(sinal === DISLIKE)));
    });
  }

  // ------------------------------------------------------------ perfil

  async loadProfile() {
    const dados = await api('profile/');
    this.setHistory(dados.history);
  }

  setHistory(historico) {
    const anteriores = new Set(this.history.keys());
    this.history = new Map(historico.map((h) => [h.title.id, { signal: h.signal, title: h.title }]));
    this.remember(historico.map((h) => h.title));
    new Set([...anteriores, ...this.history.keys()]).forEach((id) => this.paintSignal(id));
    this.renderHistory();
  }

  async toggleSignal(card, sinal) {
    if (this.history.get(card.id)?.signal === sinal) {
      this.removeSignal(card.id);
      return;
    }
    // Otimista: a interface responde antes do servidor.
    this.history.delete(card.id);
    this.history.set(card.id, { signal: sinal, title: card });
    this.paintSignal(card.id);
    this.renderHistory();
    try {
      const dados = await api('profile/interactions/', { method: 'POST', body: { title_id: card.id, signal: sinal } });
      this.setHistory(dados.history);
    } catch (erro) {
      this.el.resultsNote.textContent = erro.message;
      await this.loadProfile();
    }
    if (this.mode === 'similar' && sinal === LIKE && !this.reduced) this.pulseTab('profile');
    this.refresh();
  }

  async removeSignal(id) {
    this.history.delete(id);
    this.paintSignal(id);
    this.renderHistory();
    const dados = await api(`profile/interactions/${id}/`, { method: 'DELETE' });
    this.setHistory(dados.history);
    this.refresh();
  }

  renderHistory() {
    const { el } = this;
    const itens = [...this.history.values()].reverse();  // mais recente primeiro
    el.reset.disabled = itens.length === 0;
    if (!itens.length) {
      el.history.innerHTML = '<li class="text-sm leading-relaxed text-dim">Nenhum título marcado ainda. Use “Curti” nos pôsteres do catálogo.</li>';
      return;
    }
    el.history.innerHTML = itens.map(({ signal, title }) => `
      <li>
        <button type="button" data-remove="${title.id}" aria-label="Tirar ${esc(title.title)} do perfil"
          class="chip group ${signal === LIKE ? 'border-cyan/70 text-silver' : 'text-dim line-through'} hover:border-silver">
          <span class="inline-block size-1.5 rounded-full ${signal === LIKE ? 'bg-cyan' : 'bg-dim'}" aria-hidden="true"></span>
          ${esc(title.title)}
          <span class="text-dim group-hover:text-silver" aria-hidden="true">×</span>
        </button>
      </li>`).join('');
  }

  renderDNA(perfil) {
    const { el } = this;
    el.dna.classList.toggle('hidden', !perfil);
    if (!perfil) return;

    el.dnaList.innerHTML = perfil.dna.slice(0, 8).map((d) => `
      <li class="grid grid-cols-[minmax(0,1fr)_7rem] items-center gap-3 text-xs">
        <span class="truncate"><span class="text-silver">${esc(d.label)}</span> <span class="text-dim">${esc(d.group)}</span></span>
        <span class="inkbar" aria-hidden="true"><span class="inkbar__sim" style="width:${(d.weight * 100).toFixed(1)}%"></span></span>
      </li>`).join('');

    const partes = [];
    const tipos = Object.entries(perfil.kinds || {}).filter(([, v]) => v >= 0.05).sort((a, b) => b[1] - a[1]);
    if (tipos.length) {
      partes.push(`Tipos: ${tipos.map(([k, v]) => `${fmt.pct(v)} ${KIND_PLURAL[k]}`).join(', ')}.`);
    }
    if (perfil.year) partes.push(`Época preferida: por volta de ${Math.round(perfil.year)}.`);
    if (perfil.rating) partes.push(`Nota preferida: perto de ${fmt.one(perfil.rating)}.`);
    const blocos = Object.entries(perfil.blocks).map(([b, v]) => `${BLOCK_LABEL[b]} ${fmt.pct(v)}`).join(', ');
    partes.push(`Peso de cada bloco no vetor: ${blocos}.`);
    el.dnaSummary.textContent = partes.join(' ');
  }

  // ------------------------------------------------------------ controles

  params() {
    const valores = Object.fromEntries(this.el.sliders.map((s) => [s.dataset.param, Number(s.value)]));
    const tipos = this.el.recKinds.filter((c) => c.checked).map((c) => c.value);
    return { ...valores, k: RESULTS, kinds: tipos.length === this.el.recKinds.length ? '' : tipos };
  }

  showSlider(slider) {
    const valor = Number(slider.value);
    const saida = $(`[data-out="${slider.dataset.param}"]`);
    const textos = {
      alpha: `${fmt.pct(valor)} / ${fmt.pct(1 - valor)}`,
      rating_weight: `${fmt.pct(valor)} / ${fmt.pct(1 - valor)}`,
      obscurity: valor > 0 ? `${fmt.pct(valor)} mais raros` : 'nenhum',
      diversity: valor > 0 ? fmt.two(valor) : 'desligada',
    };
    saida.textContent = textos[slider.dataset.param];
    slider.style.setProperty('--fill', `${((valor - slider.min) / (slider.max - slider.min)) * 100}%`);
  }

  /** O fundo acompanha o α: mais ciano quando a similaridade manda, mais âmbar quando a qualidade manda. */
  syncInks() {
    if (!this.field) return;
    const alfa = Number($('[data-param="alpha"]').value);
    gsap.to(this.field.state, {
      cyan: 0.25 + alfa * 1.1,
      amber: 0.25 + (1 - alfa) * 1.6,
      duration: 0.8,
      overwrite: 'auto',
      onUpdate: () => this.field.invalidate(),
    });
  }

  // ------------------------------------------------------------ recomendações

  showSimilar(card) {
    this.similar = card;
    this.mode = 'similar';
    this.refresh();
    if (window.innerWidth < 1024) $('[data-panel]').scrollIntoView({ behavior: this.reduced ? 'auto' : 'smooth' });
  }

  async refresh() {
    const { el } = this;
    this.renderTabs();
    el.results.setAttribute('aria-busy', 'true');
    gsap.to(el.results, { opacity: 0.55, duration: 0.2 });

    try {
      const dados = this.mode === 'similar' && this.similar
        ? await api(`titles/${this.similar.id}/similar/`, { params: this.params(), channel: 'recs' })
        : await api('recommendations/', { params: this.params(), channel: 'recs' });

      if (dados.history) this.setHistory(dados.history);
      this.remember(dados.results);
      this.renderNote(dados);
      this.renderResults(dados.results, dados.params.alpha);
      this.renderStats(dados);
      if (this.mode === 'profile') this.renderDNA(dados.profile);
      this.renderMatrix(dados);
    } catch (erro) {
      if (isAbort(erro)) return;
      el.resultsNote.textContent = erro.message;
    }
    el.results.removeAttribute('aria-busy');
    gsap.to(el.results, { opacity: 1, duration: 0.3 });
  }

  renderTabs() {
    const { el } = this;
    el.tabs.forEach((aba) => {
      const ativa = aba.dataset.mode === this.mode;
      aba.setAttribute('aria-pressed', String(ativa));
      aba.setAttribute('aria-selected', String(ativa));
      if (aba.dataset.mode === 'similar') {
        aba.disabled = !this.similar;
        aba.textContent = this.similar ? `Parecidos com ${truncate(this.similar.title, 18)}` : 'Parecidos com…';
      }
    });
    el.resultsTitle.textContent = this.mode === 'similar' && this.similar
      ? `Mais perto de ${this.similar.title}`
      : 'Para você';

    const url = new URL(location.href);
    if (this.mode === 'similar' && this.similar) url.searchParams.set('similar', this.similar.id);
    else url.searchParams.delete('similar');
    history.replaceState(null, '', url);
  }

  pulseTab(modo) {
    const aba = this.el.tabs.find((a) => a.dataset.mode === modo);
    gsap.fromTo(aba, { scale: 1 }, { scale: 1.08, duration: 0.18, yoyo: true, repeat: 1, ease: 'power2.out' });
  }

  renderNote(dados) {
    const nota = this.el.resultsNote;
    if (!dados.results.length) {
      nota.textContent = 'Nenhum título passa pelos filtros atuais. Diminua “Esconder pouco votados” ou marque mais tipos.';
    } else if (this.mode === 'similar') {
      nota.textContent = `Similaridade do cosseno com ${dados.source.title}${dados.source.year ? ` (${dados.source.year})` : ''}, misturada à qualidade de cada título.`;
    } else if (dados.mode === 'cold_start') {
      nota.textContent = 'Sem nenhum “Curti” ainda, a lista mostra os títulos mais bem avaliados. Marque o que você já viu para personalizar.';
    } else {
      nota.textContent = 'Score = α · similaridade com o seu perfil + (1 − α) · qualidade. Passe o mouse na barra para ver a conta.';
    }
    if (dados.results.length && dados.params.diversity > 0 && dados.mode !== 'cold_start') {
      nota.textContent += ' Com a diversidade ligada, títulos muito parecidos entre si descem na lista, mesmo com score maior.';
    }
  }

  renderResults(resultados, alfa) {
    const lista = this.el.results;
    const estado = Flip.getState($$('[data-flip-id]', lista));
    lista.innerHTML = resultados.map((r, i) => this.resultItem(r, i, alfa)).join('');

    if (this.reduced) return;
    Flip.from(estado, {
      targets: $$('[data-flip-id]', lista),
      duration: 0.7,
      ease: 'power3.inOut',
      stagger: 0.015,
      onEnter: (novos) => gsap.fromTo(novos, { autoAlpha: 0, x: -14 }, { autoAlpha: 1, x: 0, duration: 0.5, stagger: 0.03, ease: 'power2.out' }),
    });
  }

  resultItem(r, posicao, alfa) {
    const sim = alfa * r.relevance;
    const qualidade = (1 - alfa) * r.quality;
    const conta = r.similarity
      ? `${fmt.two(alfa)} × relevância ${fmt.two(r.relevance)} + ${fmt.two(1 - alfa)} × qualidade ${fmt.two(r.quality)} = ${fmt.two(r.score)}`
      : `Qualidade ${fmt.two(r.quality)} (sem perfil, só a qualidade conta)`;
    const decomposicao = r.similarity
      ? `cos ${fmt.two(r.similarity)} = ${Object.entries(r.contributions).map(([b, v]) => `${BLOCK_LABEL[b]} ${fmt.two(v)}`).join(' + ')}`
      : '';
    const sinal = this.history.get(r.id)?.signal;

    return `
      <li data-flip-id="r-${r.id}" data-id="${r.id}" data-signal="${sinal || ''}" class="grid grid-cols-[2.75rem_minmax(0,1fr)] gap-3 rounded-sm px-2 py-3 hover:bg-deep/80">
        <div class="pt-0.5">${posterHTML(r, { size: 'sm' })}</div>
        <div class="min-w-0">
          <div class="flex items-baseline justify-between gap-3">
            <p class="truncate font-semibold"><span class="mr-1.5 tabular-nums text-dim">${posicao + 1}</span>${esc(r.title)}</p>
            <p class="shrink-0 text-sm tabular-nums" title="Score de 0 a 100">${Math.round(r.score * 100)}</p>
          </div>
          <p class="mt-0.5 flex flex-wrap gap-x-3 text-xs text-dim">
            <span>${esc(KIND_LABEL[r.kind])}${r.year ? ` de ${r.year}` : ''}</span>
            ${r.vote_count ? `<span>nota ${fmt.one(r.vote_average)}</span><span>${fmt.int(r.vote_count)} votos</span>` : ''}
          </p>
          <div class="inkbar mt-2.5" title="${esc(conta)}">
            <span class="inkbar__sim transition-[width] duration-500" style="width:${(sim * 100).toFixed(1)}%"></span>
            <span class="inkbar__quality transition-[width] duration-500" style="width:${(qualidade * 100).toFixed(1)}%"></span>
          </div>
          ${decomposicao ? `<p class="mt-1.5 text-[0.6875rem] tabular-nums text-dim">${esc(decomposicao)}</p>` : ''}
          ${r.reasons.length ? `<ul class="mt-2 flex flex-wrap gap-1.5" aria-label="Em comum">${r.reasons.map((m) => `<li class="chip" title="${esc(m.group)}">${esc(m.label)}</li>`).join('')}</ul>` : ''}
          ${this.actions(r, sinal, { compact: true })}
        </div>
      </li>`;
  }

  renderStats(dados) {
    const partes = [];
    if (dados.catalog_size) partes.push(`${fmt.int(dados.catalog_size)} títulos`);
    if (dados.dimensions) partes.push(`${fmt.int(dados.dimensions)} dimensões`);
    partes.push(`${fmt.one(dados.elapsed_ms)} ms`);
    this.el.stats.innerHTML = partes.map((p) => `<span class="block">${p}</span>`).join('');
  }

  // ------------------------------------------------------------ matriz

  async renderMatrix(dados) {
    const { el } = this;
    let ids;
    if (this.mode === 'similar' && this.similar) {
      ids = [this.similar.id, ...dados.results.slice(0, 6).map((r) => r.id)];
    } else {
      const curtidos = [...this.history.entries()].filter(([, h]) => h.signal === LIKE).map(([id]) => id).slice(-4);
      ids = curtidos.length ? [...curtidos, ...dados.results.slice(0, 4).map((r) => r.id)] : [];
    }
    if (ids.length < 2) {
      el.matrixSection.classList.add('hidden');
      return;
    }

    try {
      const matriz = await api('similarity-matrix/', { params: { ids }, channel: 'matrix' });
      el.matrixSection.classList.remove('hidden');
      el.matrix.innerHTML = matrixSVG(matriz, new Set(this.mode === 'similar' ? [this.similar.id] : [...this.history.keys()]));
    } catch (erro) {
      if (!isAbort(erro)) el.matrixSection.classList.add('hidden');
    }
  }
}

function truncate(texto, limite) {
  return texto.length > limite ? `${texto.slice(0, limite - 1)}…` : texto;
}

/** Matriz em retícula: a área de cada ponto é proporcional ao cosseno. */
function matrixSVG({ titles, matrix }, referencias) {
  const n = titles.length;
  const celula = 30;
  const margem = 22;
  const lado = margem + n * celula;
  const pontos = [];
  matrix.forEach((linha, i) => linha.forEach((valor, j) => {
    const cx = margem + j * celula + celula / 2;
    const cy = margem + i * celula + celula / 2;
    const raio = Math.sqrt(Math.max(valor, 0)) * celula * 0.46;
    const diagonal = i === j;
    const cruza = referencias.has(titles[i].id) !== referencias.has(titles[j].id);
    const cor = diagonal ? 'var(--color-rule)' : cruza ? 'var(--color-cyan)' : 'var(--color-silver)';
    pontos.push(`<circle cx="${cx}" cy="${cy}" r="${raio.toFixed(2)}" fill="${cor}" opacity="${diagonal ? 1 : 0.9}"><title>${esc(titles[i].title)} × ${esc(titles[j].title)}: cos ${fmt.two(valor)}</title></circle>`);
  }));
  const rotulos = titles.map((_, i) => {
    const c = margem + i * celula + celula / 2;
    return `<text x="${c}" y="14" text-anchor="middle">${i + 1}</text><text x="10" y="${c + 4}" text-anchor="middle">${i + 1}</text>`;
  }).join('');

  return `
    <div class="grid gap-5 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-start">
      <svg viewBox="0 0 ${lado} ${lado}" width="${lado}" height="${lado}" class="max-w-full" role="img" aria-label="Matriz de similaridade do cosseno entre ${n} títulos">
        <g fill="var(--color-dim)" font-size="10" font-family="var(--font-sans)">${rotulos}</g>
        ${pontos.join('')}
      </svg>
      <ol class="space-y-1 text-xs text-dim">
        ${titles.map((t, i) => `<li class="flex gap-2"><span class="w-4 shrink-0 text-right tabular-nums">${i + 1}</span><span class="truncate ${referencias.has(t.id) ? 'text-cyan' : 'text-silver'}">${esc(t.title)}</span></li>`).join('')}
      </ol>
    </div>
    <p class="mt-4 text-xs leading-relaxed text-dim">Pontos em ciano comparam um título ${referencias.size > 1 ? 'do seu perfil' : 'de referência'} (nomes em ciano) com uma recomendação.</p>`;
}
