// Página de perfil: números, avatar ASCII, DNA, radar de gêneros, títulos que te definem
// (com o modo "e se"), conforto × exploração e watchlist. Os dados chegam no próprio HTML
// (json_script) e a API os recalcula a cada mudança.
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

import { hideMenu, revealMenu } from '../fx/menu-motion.js';
import { scrollToElement } from '../fx/smooth-scroll.js';
import { initTilt } from '../fx/tilt.js';
import { api, isAbort } from '../lib/api.js';
import { refreshHeaderAvatar } from '../lib/avatar.js';
import { esc, fmt, KIND_LABEL, KIND_PLURAL } from '../lib/format.js';
import { posterCaption, posterHTML } from '../lib/poster.js';
import { loadTitle, TasteMap } from '../lib/taste-map.js';

const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
const $$ = (seletor, raiz = document) => [...raiz.querySelectorAll(seletor)];

const RAMP = ' .:-=+*#%@';
const INK = { cyan: 'var(--color-cyan)', amber: 'var(--color-amber)', silver: 'var(--color-silver)', dim: 'var(--color-dim)' };
const DNA_COLUMNS = [
  { title: 'Gêneros', groups: ['gênero'] },
  { title: 'Pessoas', groups: ['elenco', 'direção'] },
  { title: 'Temas', groups: ['tema'] },
];
const BLOCK_LABEL = { synopsis: 'sinopse', tags: 'etiquetas', attributes: 'atributos' };
const STATE_LABEL = {
  favorite: 'favorito', like: 'curti', dislike: 'não curti', seen: 'já vi', watchlist: 'quero assistir',
};

// Painel do mapa: o que cada botão faz a partir do estado atual (null = tira do perfil),
// com a mesma lógica dos botões do playground.
const POSITIVE = new Set(['favorite', 'like']);
const NEXT_STATE = {
  like: (atual) => (POSITIVE.has(atual) ? null : 'like'),
  dislike: (atual) => (atual === 'dislike' ? null : 'dislike'),
  favorite: (atual) => (atual === 'favorite' ? 'like' : 'favorite'),
  watchlist: (atual) => (atual === 'watchlist' ? null : 'watchlist'),
  seen: (atual) => (atual === 'seen' ? null : 'seen'),
};
const PRESSED = {
  like: (estado) => POSITIVE.has(estado),
  dislike: (estado) => estado === 'dislike',
  favorite: (estado) => estado === 'favorite',
  watchlist: (estado) => estado === 'watchlist',
  seen: (estado) => estado === 'seen',
};
const MAP_ACTIONS = [['like', 'Curti'], ['dislike', 'Não curti'], ['favorite', 'Favorito'], ['watchlist', 'Quero assistir'], ['seen', 'Já vi']];

const plural = (n, um, varios) => `${fmt.int(n)} ${n === 1 ? um : varios}`;

export default function profile({ field, reduced }) {
  const dados = JSON.parse($('#profile-data')?.textContent || 'null');
  if (!dados) return;
  if (field) {
    gsap.to(field.state, { density: 0.12, focusStrength: 0.35, duration: 1.6, ease: 'power2.out', onUpdate: () => field.invalidate() });
  }
  new ProfilePage(dados, { reduced }).start();
}

class ProfilePage {
  constructor(dados, { reduced }) {
    this.data = dados;
    this.reduced = reduced;
    this.excluded = new Set();
    this.avatar = new AsciiAvatar($('[data-avatar]'), { reduced });
    this.bars = new Map();       // chave -> largura atual (para animar as mudanças)
    this.radarValues = null;
    this.map = null;             // TasteMap, criado uma vez e atualizado a cada recálculo
    this.selected = null;        // título aberto no painel do mapa
  }

  start() {
    this.renderAll({ first: true });
    this.bind();
    this.trackNav();
  }

  body(nome) {
    return $(`[data-section="${nome}"] [data-body]`);
  }

  // ------------------------------------------------------------ eventos

  bind() {
    document.addEventListener('click', (evento) => {
      const doMapa = evento.target.closest('[data-map-act]');
      if (doMapa) {
        const atual = this.stateOf(this.selected);
        this.setState(this.selected, NEXT_STATE[doMapa.dataset.mapAct](atual));
        return;
      }
      const vizinho = evento.target.closest('[data-map-select]');
      if (vizinho) {
        this.showMapPanel(Number(vizinho.dataset.mapSelect));
        return;
      }
      const alvo = evento.target.closest('[data-act]');
      if (!alvo) return;
      const id = Number(alvo.closest('[data-id]')?.dataset.id);
      const acao = alvo.dataset.act;
      if (acao === 'exclude') this.toggleExclude(id);
      else if (acao === 'restore') this.restore();
      else if (acao === 'remove') this.setState(id, null);
      else this.setState(id, acao);
    });

    $$('[data-profile-nav] a').forEach((link) => link.addEventListener('click', (evento) => {
      const destino = $(link.getAttribute('href'));
      if (!destino) return;
      evento.preventDefault();
      scrollToElement(destino, { offset: -96 });
      history.replaceState(null, '', link.getAttribute('href'));
      this.toggleNav(false);
    }));
    this.bindNavToggle();
  }

  /** No celular o menu de seções é um hambúrguer: abre a lista e fecha ao escolher, clicar fora ou Esc. */
  bindNavToggle() {
    const botao = $('[data-profile-nav-toggle]');
    if (!botao) return;
    botao.addEventListener('click', () => this.toggleNav(botao.getAttribute('aria-expanded') !== 'true'));
    document.addEventListener('pointerdown', (evento) => {
      if (!evento.target.closest('[data-profile-nav], [data-profile-nav-toggle]')) this.toggleNav(false);
    });
    document.addEventListener('keydown', (evento) => {
      if (evento.key !== 'Escape' || botao.getAttribute('aria-expanded') !== 'true') return;
      this.toggleNav(false);
      botao.focus();
    });
  }

  toggleNav(aberto) {
    const botao = $('[data-profile-nav-toggle]');
    if (!botao || (botao.getAttribute('aria-expanded') === 'true') === aberto) return;
    const lista = $('[data-profile-nav]');
    botao.setAttribute('aria-expanded', String(aberto));
    if (aberto) {
      lista.classList.add('is-open');
      revealMenu(lista, { origin: 'top left' });
    } else {
      // A lista só some (display: none) quando a animação de saída termina.
      hideMenu(lista, () => lista.classList.remove('is-open'));
    }
  }

  /** O link da seção visível fica marcado no menu fixo. */
  trackNav() {
    const links = $$('[data-profile-nav] a');
    links.forEach((link) => {
      const secao = $(link.getAttribute('href'));
      if (!secao) return;
      ScrollTrigger.create({
        trigger: secao,
        start: 'top 45%',
        end: 'bottom 45%',
        onToggle: (self) => {
          if (!self.isActive) return;
          links.forEach((l) => l.toggleAttribute('aria-current', l === link));
          const atual = $('[data-profile-nav-current]');
          if (atual) atual.textContent = link.textContent;
          if (link.offsetParent) link.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        },
      });
    });
  }

  // ------------------------------------------------------------ dados

  async reload({ everything = false } = {}) {
    document.body.setAttribute('aria-busy', 'true');
    try {
      const dados = await api('profile/insights/', { params: { exclude: [...this.excluded] }, channel: 'insights' });
      this.data = dados;
      if (everything) this.renderAll();
      else this.renderWhatIf();
    } catch (erro) {
      if (!isAbort(erro)) this.toast(erro.message);
    } finally {
      document.body.removeAttribute('aria-busy');
    }
  }

  toggleExclude(id) {
    if (this.excluded.has(id)) this.excluded.delete(id);
    else this.excluded.add(id);
    this.reload();
  }

  restore() {
    this.excluded.clear();
    this.reload();
  }

  /** Avalia um título (sugestão de ponto cego ou item da watchlist) e recalcula tudo. */
  async setState(id, estado) {
    if (!id) return;
    try {
      if (estado) await api('profile/interactions/', { method: 'POST', body: { title_id: id, state: estado } });
      else await api(`profile/interactions/${id}/`, { method: 'DELETE' });
    } catch (erro) {
      this.toast(erro.message);
      return;
    }
    this.excluded.delete(id);
    await this.reload({ everything: true });
    refreshHeaderAvatar();
  }

  toast(texto) {
    const aviso = document.createElement('p');
    aviso.className = 'toast fixed bottom-4 left-4 z-[80] max-w-md rounded-sm border border-rule bg-night/95 px-4 py-3 text-sm';
    aviso.setAttribute('role', 'status');
    aviso.textContent = texto;
    document.body.append(aviso);
    setTimeout(() => aviso.remove(), 10000);
  }

  // ------------------------------------------------------------ renderização

  renderAll({ first = false } = {}) {
    this.renderStats();
    this.avatar.render(this.data.avatar, { first });
    this.renderSection('dna', () => this.renderDNA());
    this.renderSection('radar', () => this.renderRadar());
    this.renderSection('map', () => this.renderMap());
    this.renderSection('defining', () => this.renderDefining());
    this.renderSection('comfort', () => this.renderComfort());
    this.renderWatchlist();
    if (!first) ScrollTrigger.refresh();
  }

  /** Só o que o modo "e se" muda: DNA, radar, centro no mapa, conforto e os interruptores. */
  renderWhatIf() {
    this.renderSection('dna', () => this.renderDNA());
    this.renderSection('radar', () => this.renderRadar());
    this.renderSection('map', () => this.renderMap());
    this.renderSection('comfort', () => this.renderComfort());
    this.renderDefining();
  }

  renderSection(nome, desenhar) {
    if (!this.body(nome)) return;
    const trava = this.data.locks[nome];
    if (trava && !trava.unlocked) {
      this.body(nome).innerHTML = lockedHTML(trava);
      this.bars.clear();
      if (nome === 'radar') this.radarValues = null;
      if (nome === 'map') this.map = null;
      return;
    }
    desenhar();
  }

  // ---- mapa do gosto

  stateOf(id) {
    return (this.data.map?.points || []).find((p) => p.title_id === id)?.state;
  }

  renderMap() {
    const corpo = this.body('map');
    const mapa = this.data.map;
    if (!this.data.map_available || !mapa) return;
    if (!this.map) {
      corpo.innerHTML = `
        <div class="grid gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div class="min-w-0">
            <div class="mb-4 flex flex-wrap items-center justify-between gap-3" data-map-controls>
              <div class="seg" role="group" aria-label="Tipos mostrados no mapa" data-map-kinds>
                <button type="button" data-kind="" aria-pressed="true">Tudo</button>
                <button type="button" data-kind="movie" aria-pressed="false">Filmes</button>
                <button type="button" data-kind="series" aria-pressed="false">Séries</button>
                <button type="button" data-kind="anime" aria-pressed="false">Animes</button>
              </div>
              <div class="flex flex-wrap items-center gap-1.5">
                <button type="button" class="icon-btn" data-map-zoom="in" aria-label="Aproximar" title="Aproximar">+</button>
                <button type="button" class="icon-btn" data-map-zoom="out" aria-label="Afastar" title="Afastar">−</button>
                <button type="button" class="rounded-full border border-rule px-3 py-1 text-xs hover:border-silver/60" data-map-zoom="center">Ir ao meu centro</button>
                <button type="button" class="rounded-full border border-rule px-3 py-1 text-xs hover:border-silver/60" data-map-zoom="reset">Ver tudo</button>
              </div>
            </div>
            <div class="taste-map" data-map>
              <canvas role="img" aria-label="Mapa do catálogo em duas dimensões: títulos parecidos ficam próximos. Os seus títulos estão destacados e uma mira marca o centro do seu perfil."></canvas>
              <div class="taste-map__tooltip" data-map-tooltip hidden></div>
              <p class="taste-map__hint" aria-hidden="true">Clique para explorar o mapa</p>
            </div>
            <p class="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-dim" aria-hidden="true">
              <span class="inline-flex items-center gap-1.5"><span class="inline-block size-2.5 rounded-full bg-cyan"></span>favorito</span>
              <span class="inline-flex items-center gap-1.5"><span class="inline-block size-2 rounded-full bg-silver"></span>curti</span>
              <span class="inline-flex items-center gap-1.5"><span class="text-[0.7rem]">✕</span>não curti</span>
              <span class="inline-flex items-center gap-1.5"><span class="inline-block size-2.5 rounded-full border border-dashed border-silver"></span>quero assistir</span>
              <span class="inline-flex items-center gap-1.5"><span class="inline-block size-1.5 rounded-full bg-dim"></span>já vi</span>
              <span class="inline-flex items-center gap-1.5"><span class="inline-block size-3 rounded-full border-2 border-cyan"></span>centro do perfil</span>
              <span class="inline-flex items-center gap-1.5">fundo: <span class="inline-block size-1.5 bg-silver/40"></span>filmes <span class="inline-block size-1.5 bg-amber/70"></span>séries <span class="inline-block size-1.5 bg-cyan/70"></span>animes</span>
            </p>
            <div class="mt-8" data-map-neighbors></div>
          </div>
          <aside class="xl:sticky xl:top-24 xl:self-start" data-map-panel aria-live="polite">
            <p class="rounded-sm border border-dashed border-rule px-5 py-6 text-sm leading-relaxed text-dim">Clique num ponto para ver o título e avaliá-lo ali mesmo. O centro do perfil se move na hora.</p>
          </aside>
        </div>`;
      this.map = new TasteMap($('[data-map]', corpo), { reduced: this.reduced, onSelect: (id) => this.showMapPanel(id) });
      this.map.start(mapa).catch((erro) => this.toast(erro.message));
      this.bindMapControls(corpo);
    } else {
      this.map.update(mapa);
    }
    this.renderNeighbors(mapa);
    if (this.selected) this.showMapPanel(this.selected, { keepScroll: true });
  }

  bindMapControls(corpo) {
    const botoes = $$('[data-map-kinds] button', corpo);
    botoes.forEach((botao) => botao.addEventListener('click', () => {
      botoes.forEach((b) => b.setAttribute('aria-pressed', String(b === botao)));
      this.map.setKinds(botao.dataset.kind ? [botao.dataset.kind] : ['movie', 'series', 'anime']);
    }));
    $$('[data-map-zoom]', corpo).forEach((botao) => botao.addEventListener('click', () => {
      const acao = botao.dataset.mapZoom;
      if (acao === 'in') this.map.zoomAt(this.map.w / 2, this.map.h / 2, 1.8, { animate: true });
      if (acao === 'out') this.map.zoomAt(this.map.w / 2, this.map.h / 2, 1 / 1.8, { animate: true });
      if (acao === 'center') this.map.focusCenter();
      if (acao === 'reset') this.map.reset();
    }));
  }

  renderNeighbors(mapa) {
    const lista = $('[data-map-neighbors]');
    if (!lista) return;
    if (!mapa.neighbors?.length) {
      lista.innerHTML = '';
      return;
    }
    lista.innerHTML = `
      <h3 class="text-sm font-semibold">Perto do seu centro, e ainda fora do perfil</h3>
      <ul class="mt-3 flex flex-wrap gap-2">
        ${mapa.neighbors.map((t) => `<li><button type="button" class="chip hover:border-silver/60 hover:text-silver" data-map-select="${t.id}">${esc(t.title)}${t.year ? ` <span class="text-dim">${t.year}</span>` : ''}</button></li>`).join('')}
      </ul>`;
  }

  async showMapPanel(id, { keepScroll = false } = {}) {
    this.selected = id;
    this.map?.select(id);
    const painel = $('[data-map-panel]');
    if (!painel) return;
    if (!keepScroll) painel.innerHTML = '<p class="px-1 text-sm text-dim">Carregando…</p>';
    let titulo;
    try {
      titulo = await loadTitle(id);
    } catch (erro) {
      painel.innerHTML = `<p class="text-sm text-dim">${esc(erro.message)}</p>`;
      return;
    }
    if (this.selected !== id) return;
    const estado = this.stateOf(id);
    painel.innerHTML = `
      <div class="rounded-sm border border-rule bg-night/85 p-5 backdrop-blur-md">
        <div class="grid grid-cols-[5rem_minmax(0,1fr)] gap-4">
          <div>${posterHTML(titulo, { size: 'sm' })}</div>
          <div class="min-w-0">
            <p class="font-semibold leading-snug">${esc(titulo.title)}</p>
            <p class="mt-1 text-xs text-dim">${esc(KIND_LABEL[titulo.kind])}${titulo.year ? ` de ${titulo.year}` : ''}${titulo.vote_count ? ` · nota ${fmt.one(titulo.vote_average)}` : ''}</p>
            <p class="mt-1 text-xs text-dim">${esc(titulo.genres.slice(0, 4).join(', '))}</p>
            ${estado ? `<p class="mt-2 text-xs text-cyan">No seu perfil: ${esc(STATE_LABEL[estado])}</p>` : ''}
          </div>
        </div>
        ${titulo.overview ? `<p class="mt-4 line-clamp-6 text-sm leading-relaxed text-silver/80">${esc(titulo.overview)}</p>` : ''}
        <div class="mt-5 flex flex-wrap gap-1.5" role="group" aria-label="Avaliar ${esc(titulo.title)}">
          ${MAP_ACTIONS.map(([acao, rotulo]) => `
            <button type="button" data-map-act="${acao}" aria-pressed="${PRESSED[acao](estado)}"
              class="whitespace-nowrap rounded-full border border-rule px-2.5 py-1 text-xs hover:border-silver/60 aria-pressed:border-cyan aria-pressed:bg-cyan aria-pressed:text-night">${rotulo}</button>`).join('')}
        </div>
        <a href="/playground/?similar=${id}" class="mt-5 inline-block text-sm text-dim underline underline-offset-4 hover:text-silver" data-transition-label="Playground">Ver parecidos no playground</a>
      </div>`;
  }

  renderStats() {
    const SEP = '<span class="mx-[0.16em] inline-block size-[0.16em] rounded-full bg-dim align-middle"></span><span class="sr-only">, </span>';
    const lista = $('[data-stats]');
    const { stats, counts, locks } = this.data;
    if (!stats) {
      lista.innerHTML = `<div class="col-span-full">${lockedHTML(locks.stats, { compact: true })}</div>`;
      return;
    }
    const tipos = Object.entries(stats.by_kind).filter(([, n]) => n).map(([k, n]) => `${n} ${n === 1 ? KIND_LABEL[k].toLowerCase() : KIND_PLURAL[k]}`);
    const itens = [
      ['Avaliações', fmt.int(stats.rated), `${plural(counts.positives, 'curtido', 'curtidos')}${stats.by_state.favorite ? `, ${plural(stats.by_state.favorite, 'favorito', 'favoritos')}` : ''}`],
      ['Filmes · séries · animes', ['movie', 'series', 'anime'].map((k) => esc(stats.by_kind[k])).join(SEP), tipos.join(', ') || 'nada ainda'],
      ['Década favorita', esc(stats.favorite_decade ? `${String(stats.favorite_decade).slice(2)}s` : '—'), stats.favorite_decade ? `anos ${stats.favorite_decade}` : 'sem curtidos com ano'],
      ['Horas assistidas', `<span class="text-[0.6em] text-dim">≈</span>${esc(fmt.int(stats.hours))}`, stats.hours_missing ? `${plural(stats.hours_missing, 'título', 'títulos')} sem duração conhecida ${stats.hours_missing === 1 ? 'fica' : 'ficam'} de fora` : 'estimadas pela duração de cada título'],
    ];
    // O valor já vem escapado (com separadores em HTML) e nunca quebra a linha.
    lista.innerHTML = itens.map(([rotulo, valor, nota]) => `
      <div class="@container min-w-0">
        <dt class="text-xs text-dim">${esc(rotulo)}</dt>
        <dd class="display mt-1 whitespace-nowrap text-[clamp(2.5rem,4.5vw,4rem)] tabular-nums"><span class="inline-block">${valor}</span></dd>
        <dd class="mt-1 text-xs leading-relaxed text-dim">${esc(nota)}</dd>
      </div>`).join('');
    // Valor largo demais para a coluna (ex.: 320 · 50 · 10) encolhe só o necessário: mede a
    // largura em em e limita a fonte pela largura do contêiner (cqi), que acompanha o resize.
    lista.querySelectorAll('dd.display').forEach((dd) => {
      const largura = dd.firstElementChild.getBoundingClientRect().width;
      const fonte = parseFloat(getComputedStyle(dd).fontSize);
      if (!largura || !fonte) return;
      const ems = largura / fonte;
      dd.style.fontSize = `min(clamp(2.5rem, 4.5vw, 4rem), ${(100 / ems).toFixed(2)}cqi)`;
    });
  }

  // ---- DNA

  renderDNA() {
    const corpo = this.body('dna');
    const perfil = this.data.dna;
    if (!perfil) {
      corpo.innerHTML = emptyProfileHTML();
      return;
    }
    const colunas = DNA_COLUMNS.map(({ title, groups }) => {
      const termos = perfil.dna.filter((d) => groups.includes(d.group)).slice(0, 8);
      if (!termos.length) return '';
      return `
        <div>
          <h3 class="text-sm font-semibold">${esc(title)}</h3>
          <ul class="mt-4 space-y-2.5">
            ${termos.map((d) => `
              <li class="grid grid-cols-[minmax(0,1fr)_minmax(5rem,9rem)] items-center gap-4 text-sm">
                <span class="truncate"><span class="text-silver">${esc(d.label)}</span>${groups.length > 1 ? ` <span class="text-xs text-dim">${esc(d.group)}</span>` : ''}</span>
                <span class="inkbar" aria-hidden="true"><span class="inkbar__sim" data-bar="dna:${esc(d.token)}" data-width="${(d.weight * 100).toFixed(1)}"></span></span>
              </li>`).join('')}
          </ul>
        </div>`;
    }).join('');

    const blocos = Object.entries(perfil.blocks);
    const resumo = [];
    const tipos = Object.entries(perfil.kinds || {}).filter(([, v]) => v >= 0.05).sort((a, b) => b[1] - a[1]);
    if (tipos.length) resumo.push(`Tipos: ${tipos.map(([k, v]) => `${fmt.pct(v)} ${KIND_PLURAL[k]}`).join(', ')}.`);
    if (perfil.year) resumo.push(`Época preferida: por volta de ${Math.round(perfil.year)}.`);
    if (perfil.rating) resumo.push(`Nota preferida: perto de ${fmt.one(perfil.rating)}.`);

    corpo.innerHTML = `
      <div class="grid gap-10 md:grid-cols-3">${colunas}</div>
      <div class="mt-14 max-w-3xl">
        <h3 class="text-sm font-semibold">Peso de cada bloco no vetor</h3>
        <div class="mt-4 flex h-3 overflow-hidden rounded-[1px]" role="img" aria-label="${esc(blocos.map(([b, v]) => `${BLOCK_LABEL[b]} ${fmt.pct(v)}`).join(', '))}">
          ${blocos.map(([b, v], i) => `<span class="block h-full ${['bg-cyan', 'bg-silver', 'bg-amber'][i % 3]}" data-bar="bloco:${b}" data-width="${(v * 100).toFixed(1)}"></span>`).join('')}
        </div>
        <p class="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-dim">
          ${blocos.map(([b, v], i) => `<span class="inline-flex items-center gap-1.5"><span class="inline-block size-2 ${['bg-cyan', 'bg-silver', 'bg-amber'][i % 3]}"></span>${BLOCK_LABEL[b]} ${fmt.pct(v)}</span>`).join('')}
        </p>
        ${resumo.length ? `<p class="mt-6 text-sm leading-relaxed text-silver/80">${esc(resumo.join(' '))}</p>` : ''}
      </div>`;
    this.animateBars(corpo);
  }

  /** Barras crescem a partir da largura anterior (ou de zero, na primeira vez). */
  animateBars(raiz) {
    $$('[data-bar]', raiz).forEach((barra) => {
      const chave = barra.dataset.bar;
      const alvo = Number(barra.dataset.width);
      const antes = this.bars.get(chave) ?? 0;
      this.bars.set(chave, alvo);
      if (this.reduced) {
        barra.style.width = `${alvo}%`;
        return;
      }
      gsap.fromTo(barra, { width: `${antes}%` }, { width: `${alvo}%`, duration: 0.9, ease: 'expo.out' });
    });
  }

  // ---- radar

  renderRadar() {
    const corpo = this.body('radar');
    const radar = this.data.radar;
    if (!radar) {
      corpo.innerHTML = emptyProfileHTML();
      this.radarValues = null;
      return;
    }
    const eixos = radar.axes;
    const acima = eixos.filter((e) => e.catalog > 0 && e.user / e.catalog >= 1.3).sort((a, b) => b.user / b.catalog - a.user / a.catalog).slice(0, 3);
    const abaixo = eixos.filter((e) => e.catalog > 0 && e.user / e.catalog <= 0.7).sort((a, b) => a.user / a.catalog - b.user / b.catalog).slice(0, 2);
    const razao = (e) => `${fmt.one(e.user / e.catalog)}×`;

    const desenhado = $('[data-radar]', corpo);
    const mesmosEixos = desenhado && this.radarValues && this.radarValues.genres.join('|') === eixos.map((e) => e.genre).join('|');
    if (!mesmosEixos) {
      corpo.innerHTML = `
        <div class="grid items-center gap-12 lg:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]">
          <div data-radar>${radarSVG(eixos)}</div>
          <div data-radar-notes></div>
        </div>`;
    }
    $('[data-radar-notes]', corpo).innerHTML = `
      <p class="flex flex-wrap gap-x-5 gap-y-1 text-xs text-dim">
        <span class="inline-flex items-center gap-1.5"><span class="inline-block size-2 rounded-full bg-cyan"></span>você</span>
        <span class="inline-flex items-center gap-1.5"><span class="inline-block h-0 w-4 border-t border-dashed border-dim"></span>catálogo</span>
      </p>
      ${acima.length ? `
        <h3 class="mt-8 text-sm font-semibold">Acima da média do catálogo</h3>
        <ul class="mt-3 space-y-2 text-lg">${acima.map((e) => `<li><span class="text-cyan">${esc(e.genre)}</span> <span class="text-dim">${razao(e)} a parcela do gênero no catálogo</span></li>`).join('')}</ul>` : ''}
      ${abaixo.length ? `
        <h3 class="mt-8 text-sm font-semibold">Abaixo da média</h3>
        <ul class="mt-3 space-y-2 text-lg">${abaixo.map((e) => `<li><span class="text-silver">${esc(e.genre)}</span> <span class="text-dim">${razao(e)}</span></li>`).join('')}</ul>` : ''}`;

    this.tweenRadar(corpo, eixos, mesmosEixos);
  }

  tweenRadar(corpo, eixos, mesmosEixos) {
    const poligono = $('[data-radar-user]', corpo);
    const pontos = $$('[data-radar-dot]', corpo);
    const escala = radarScale(eixos);
    const destino = eixos.map((e) => e.user);
    const origem = mesmosEixos ? this.radarValues.values : destino.map(() => 0);
    this.radarValues = { genres: eixos.map((e) => e.genre), values: destino };

    const desenhar = (valores) => {
      const coords = valores.map((v, i) => radarPoint(i, eixos.length, v / escala));
      poligono.setAttribute('points', coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' '));
      pontos.forEach((ponto, i) => {
        ponto.setAttribute('cx', coords[i][0].toFixed(1));
        ponto.setAttribute('cy', coords[i][1].toFixed(1));
      });
    };
    if (this.reduced) {
      desenhar(destino);
      return;
    }
    const estado = { t: 0 };
    gsap.to(estado, {
      t: 1,
      duration: mesmosEixos ? 0.8 : 1.4,
      ease: 'expo.out',
      onUpdate: () => desenhar(origem.map((o, i) => o + (destino[i] - o) * estado.t)),
    });
  }

  // ---- títulos que te definem

  renderDefining() {
    const corpo = this.body('defining');
    const lista = this.data.defining;
    if (!lista) return;
    const whatif = this.data.whatif;
    const frase = whatIfSentence(whatif);
    corpo.innerHTML = `
      <div class="mb-8 flex min-h-12 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between" aria-live="polite">
        <p class="text-lg leading-relaxed ${whatif ? 'text-cyan' : 'text-dim'}">${frase}</p>
        ${this.excluded.size ? '<button type="button" class="self-start whitespace-nowrap rounded-full border border-rule px-4 py-1.5 text-sm hover:border-silver/60" data-act="restore">Restaurar o perfil</button>' : ''}
      </div>
      <ol class="grid gap-x-6 gap-y-8 sm:grid-cols-2 xl:grid-cols-4">
        ${lista.map((item, i) => `
          <li class="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-4 transition-opacity ${item.excluded ? 'opacity-45' : ''}" data-id="${item.title.id}">
            <div>${posterHTML(item.title, { size: 'sm' })}</div>
            <div class="min-w-0">
              <p class="text-xs tabular-nums text-dim">${i + 1}º · ${esc(STATE_LABEL[item.state])}</p>
              <p class="mt-1 truncate font-semibold">${esc(item.title.title)}</p>
              <p class="mt-0.5 text-xs text-dim">${esc(KIND_LABEL[item.title.kind])}${item.title.year ? ` de ${item.title.year}` : ''}</p>
              <div class="mt-3 flex items-center gap-3">
                <span class="inkbar flex-1" aria-hidden="true"><span class="inkbar__sim" style="width:${(item.share * 100).toFixed(1)}%"></span></span>
                <span class="w-10 text-right text-xs tabular-nums">${fmt.pct(item.share)}</span>
              </div>
              <button type="button" role="switch" aria-checked="${!item.excluded}" data-act="exclude" class="switch mt-3">
                <span class="switch__track" aria-hidden="true"><span class="switch__thumb"></span></span>
                <span class="text-xs">${item.excluded ? 'Fora do cálculo' : 'No cálculo'}<span class="sr-only">: ${esc(item.title.title)}</span></span>
              </button>
            </div>
          </li>`).join('')}
      </ol>`;
  }

  // ---- conforto × exploração

  renderComfort() {
    const corpo = this.body('comfort');
    const conforto = this.data.comfort;
    if (!conforto) {
      corpo.innerHTML = emptyProfileHTML();
      return;
    }
    const ecletismo = conforto.eclecticism;
    const leitura = ecletismo >= 0.66 ? 'Você circula por muitos gêneros e tipos.'
      : ecletismo >= 0.4 ? 'Você tem uma base firme, mas sai dela com frequência.'
        : 'Você sabe bem do que gosta e fica perto disso.';
    const dispersao = conforto.dispersion;
    corpo.innerHTML = `
      <div class="grid gap-12 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <div>
          <p class="display text-[clamp(5rem,12vw,10rem)] tabular-nums leading-none"><span data-count="${Math.round(ecletismo * 100)}">${Math.round(ecletismo * 100)}</span>%</p>
          <p class="mt-2 text-2xl font-semibold">eclético</p>
          <p class="mt-3 text-lg leading-relaxed text-silver/80">${esc(leitura)}</p>
          <p class="mt-3 text-xs leading-relaxed text-dim">Entropia da distribuição de gêneros (70%) e tipos (30%) no que você curtiu: 0% seria um nicho só, 100% seria de tudo um pouco.</p>
          ${dispersao !== null ? `
            <div class="mt-10">
              <div class="flex justify-between text-xs"><span>Concentrado</span><span class="tabular-nums text-dim">dispersão ${fmt.two(dispersao)}</span><span>Espalhado</span></div>
              <div class="relative mt-2 h-[2px] bg-rule">
                <span class="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan" style="left:${Math.min(dispersao, 1) * 100}%"></span>
              </div>
              <p class="mt-3 text-xs leading-relaxed text-dim">1 − cosseno médio entre os seus curtidos e o centro do perfil.</p>
            </div>` : ''}
        </div>
        <div>
          <h3 class="text-sm font-semibold">Pontos cegos</h3>
          <p class="mt-1 text-sm text-dim">Partes do catálogo com muitos títulos bem avaliados e nenhum no seu perfil, cada uma com uma porta de entrada.</p>
          ${conforto.blind_spots.length ? `
            <ul class="mt-6 grid gap-6 sm:grid-cols-2">
              ${conforto.blind_spots.map((ponto) => `
                <li class="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-4 rounded-sm border border-rule bg-night/60 p-4" data-id="${ponto.suggestion.id}">
                  <div>${posterHTML(ponto.suggestion, { size: 'sm' })}</div>
                  <div class="min-w-0">
                    <p class="text-sm"><span class="font-semibold text-cyan">${esc(ponto.label)}</span></p>
                    <p class="mt-0.5 text-xs text-dim">${plural(ponto.count, 'título bem avaliado', 'títulos bem avaliados')}, nenhum seu</p>
                    <p class="mt-3 truncate text-sm">Comece por <span class="font-semibold">${esc(ponto.suggestion.title)}</span>${ponto.suggestion.year ? ` <span class="text-dim">${ponto.suggestion.year}</span>` : ''}</p>
                    ${actionsHTML(ponto.suggestion, ['like', 'watchlist'])}
                  </div>
                </li>`).join('')}
            </ul>` : '<p class="mt-6 text-sm text-dim">Nenhum por enquanto: você já passou por todos os gêneros, tipos e décadas fortes do catálogo.</p>'}
        </div>
      </div>`;
    initTilt(corpo, { reduced: this.reduced });
  }

  // ---- watchlist

  renderWatchlist() {
    const corpo = this.body('watchlist');
    const lista = this.data.watchlist;
    if (!lista.length) {
      corpo.innerHTML = `<p class="text-lg text-dim">Nada aqui ainda. Use o marcador “Quero assistir” nos pôsteres do <a class="text-silver underline underline-offset-4" href="/playground/">playground</a> para guardar o que quer ver.</p>`;
      return;
    }
    corpo.innerHTML = `
      <ul class="grid grid-cols-2 gap-x-4 gap-y-10 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        ${lista.map((item) => `
          <li data-id="${item.title.id}">
            <div class="relative">
              ${posterHTML(item.title)}
              ${item.match !== null ? `<span class="absolute left-2 top-2 rounded-full bg-night/80 px-2.5 py-1 text-xs font-semibold tabular-nums text-cyan backdrop-blur" title="Cosseno com o seu perfil, relativo à melhor recomendação">${fmt.pct(item.match)} de match</span>` : ''}
            </div>
            ${posterCaption(item.title)}
            ${actionsHTML(item.title, ['like', 'dislike', 'remove'])}
          </li>`).join('')}
      </ul>`;
    initTilt(corpo, { reduced: this.reduced });
  }
}

// ------------------------------------------------------------ peças

function lockedHTML(trava, { compact = false } = {}) {
  const falta = trava.need - trava.have;
  const verbo = trava.unit === 'positives' ? 'Curta' : 'Avalie';
  return `
    <div class="${compact ? '' : 'rounded-sm border border-dashed border-rule px-6 py-8'} max-w-xl">
      <p class="text-lg">${verbo} mais ${plural(falta, 'título', 'títulos')} para desbloquear ${compact ? 'os números' : 'esta seção'}.</p>
      <div class="mt-4 flex items-center gap-3">
        <span class="inkbar flex-1" aria-hidden="true"><span class="inkbar__sim" style="width:${(trava.have / trava.need) * 100}%"></span></span>
        <span class="text-xs tabular-nums text-dim">${trava.have} de ${trava.need}</span>
      </div>
      <a href="/playground/" class="mt-5 inline-flex rounded-full bg-silver px-5 py-2 text-sm font-semibold text-night hover:bg-cyan" data-transition-label="Playground">Avaliar no playground</a>
    </div>`;
}

function emptyProfileHTML() {
  return '<p class="text-lg text-dim">Com esses títulos fora do cálculo, não sobra nenhum curtido para formar o perfil.</p>';
}

function actionsHTML(titulo, acoes) {
  const rotulos = { like: 'Curti', dislike: 'Não curti', watchlist: 'Quero assistir', remove: 'Tirar da lista' };
  return `
    <div class="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Avaliar ${esc(titulo.title)}">
      ${acoes.map((acao) => `<button type="button" data-act="${acao}" class="whitespace-nowrap rounded-full border border-rule px-2.5 py-1 text-xs hover:border-silver/60">${rotulos[acao]}</button>`).join('')}
    </div>`;
}

function whatIfSentence(whatif) {
  if (!whatif) return 'Desligue um título para ver como o seu perfil ficaria sem ele.';
  const nomes = whatif.titles.map((t) => `<em class="not-italic font-semibold">${esc(t)}</em>`);
  const lista = nomes.length > 2 ? `${nomes.slice(0, -1).join(', ')} e ${nomes.at(-1)}` : nomes.join(' e ');
  if (whatif.empty) return `Sem ${lista}, não sobra nenhum curtido para formar o perfil.`;
  if (!whatif.genre) return `Sem ${lista}, o seu perfil quase não muda.`;
  return `Sem ${lista}, o seu perfil perde ${fmt.pct(whatif.loss)} de ${esc(whatif.genre)}.`;
}

// ---- radar em SVG

const RADAR = { size: 400, radius: 140 };

function radarScale(eixos) {
  return Math.max(...eixos.flatMap((e) => [e.user, e.catalog]), 0.01) * 1.08;
}

function radarPoint(i, n, fracao) {
  const angulo = -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const c = RADAR.size / 2;
  return [c + Math.cos(angulo) * RADAR.radius * fracao, c + Math.sin(angulo) * RADAR.radius * fracao];
}

function radarSVG(eixos) {
  const n = eixos.length;
  const escala = radarScale(eixos);
  const c = RADAR.size / 2;
  const anel = (f) => eixos.map((_, i) => radarPoint(i, n, f).map((v) => v.toFixed(1)).join(',')).join(' ');
  const catalogo = eixos.map((e, i) => radarPoint(i, n, e.catalog / escala).map((v) => v.toFixed(1)).join(',')).join(' ');
  const zero = eixos.map(() => `${c},${c}`).join(' ');
  const rotulos = eixos.map((e, i) => {
    const [x, y] = radarPoint(i, n, 1.16);
    const ancora = Math.abs(x - c) < 8 ? 'middle' : x > c ? 'start' : 'end';
    return `<text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="${ancora}">${esc(e.genre)}</text>`;
  }).join('');
  const descricao = eixos.map((e) => `${e.genre}: você ${fmt.pct(e.user)}, catálogo ${fmt.pct(e.catalog)}`).join('; ');

  return `
    <svg viewBox="-60 0 ${RADAR.size + 120} ${RADAR.size}" class="w-full overflow-visible" role="img" aria-label="Radar de gêneros. ${esc(descricao)}">
      <g fill="none" stroke="var(--color-rule)" stroke-width="1">
        ${[0.25, 0.5, 0.75, 1].map((f) => `<polygon points="${anel(f)}"/>`).join('')}
        ${eixos.map((_, i) => { const [x, y] = radarPoint(i, n, 1); return `<line x1="${c}" y1="${c}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`; }).join('')}
      </g>
      <polygon points="${catalogo}" fill="none" stroke="var(--color-dim)" stroke-width="1.5" stroke-dasharray="3 4"/>
      <polygon points="${zero}" fill="var(--color-cyan)" fill-opacity="0.22" stroke="var(--color-cyan)" stroke-width="2" stroke-linejoin="round" data-radar-user/>
      ${eixos.map(() => `<circle r="3.5" cx="${c}" cy="${c}" fill="var(--color-cyan)" data-radar-dot/>`).join('')}
      <g fill="var(--color-silver)" font-size="13" font-family="var(--font-sans)">${rotulos}</g>
    </svg>`;
}

// ---- avatar ASCII

class AsciiAvatar {
  constructor(el, { reduced }) {
    this.el = el;
    this.reduced = reduced;
    this.rows = null;
    this.timer = null;
  }

  render(avatar, { first = false } = {}) {
    if (!this.el) return;
    this.el.style.color = INK[avatar.ink] || INK.cyan;
    const anteriores = this.rows;
    this.rows = avatar.rows;
    if (!anteriores || first || this.reduced) {
      this.el.innerHTML = avatar.rows.map((linha) => `<span class="avatar-grid__row">${[...linha].map((c) => cellHTML(c)).join('')}</span>`).join('');
      if (first && !this.reduced) this.intro();
    } else {
      this.morph(avatar.rows);
    }
    this.startFlicker();
  }

  cells() {
    return $$('[data-cell]', this.el);
  }

  /** Entrada: cada célula embaralha caracteres antes de assentar no seu. */
  intro() {
    this.cells().forEach((celula) => {
      const final = celula.dataset.cell;
      if (final === ' ') return;
      const estado = { i: 0 };
      gsap.to(estado, {
        i: 8,
        duration: 0.9,
        delay: Math.random() * 0.6,
        ease: 'none',
        onUpdate: () => { celula.textContent = estado.i >= 7.5 ? final : RAMP[1 + Math.floor(Math.random() * (RAMP.length - 1))]; },
      });
    });
  }

  /** Perfil mudou: as células que mudam passam por um caractere aleatório até o novo. */
  morph(novas) {
    const celulas = this.cells();
    novas.join('').split('').forEach((caractere, i) => {
      const celula = celulas[i];
      if (!celula || celula.dataset.cell === caractere) return;
      setTimeout(() => {
        celula.textContent = RAMP[1 + Math.floor(Math.random() * (RAMP.length - 1))];
        setTimeout(() => setCell(celula, caractere), 140);
      }, Math.random() * 500);
    });
  }

  /** Cintilação: algumas células sobem ou descem um nível na rampa por um instante. */
  startFlicker() {
    if (this.reduced || this.timer) return;
    this.timer = setInterval(() => {
      if (document.hidden) return;
      const celulas = this.cells().filter((c) => c.dataset.cell !== ' ');
      for (let k = 0; k < 3 && celulas.length; k += 1) {
        const celula = celulas[Math.floor(Math.random() * celulas.length)];
        const nivel = RAMP.indexOf(celula.dataset.cell);
        const vizinho = Math.min(Math.max(nivel + (Math.random() < 0.5 ? -1 : 1), 1), RAMP.length - 1);
        celula.textContent = RAMP[vizinho];
        setTimeout(() => { celula.textContent = celula.dataset.cell; }, 260);
      }
    }, 140);
  }
}

function cellHTML(caractere) {
  const nivel = Math.max(RAMP.indexOf(caractere), 0) / (RAMP.length - 1);
  return `<span data-cell="${caractere === ' ' ? ' ' : esc(caractere)}" style="opacity:${(0.35 + 0.65 * nivel).toFixed(2)}">${caractere === ' ' ? '&nbsp;' : esc(caractere)}</span>`;
}

function setCell(celula, caractere) {
  const nivel = Math.max(RAMP.indexOf(caractere), 0) / (RAMP.length - 1);
  celula.dataset.cell = caractere;
  celula.style.opacity = (0.35 + 0.65 * nivel).toFixed(2);
  celula.innerHTML = caractere === ' ' ? '&nbsp;' : esc(caractere);
}
