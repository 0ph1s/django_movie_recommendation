// Pôster de um título. Com `poster_url` (preenchido por `manage.py fetch_posters`), mostra a
// capa original em cores. Por baixo dela sempre existe um pôster gerado, uma composição em
// retícula determinística a partir do ID, que aparece quando não há capa ou ela não carrega.
//   filme  -> pontos redondos (retícula de jornal)
//   série  -> linhas horizontais (varredura de TV)
//   anime  -> retícula fina a 45° (screentone de mangá)
import { esc, KIND_LABEL } from './format.js';

const PATTERNS = {
  movie: '--cell:7px;--dot:44%',
  series: 'background-image:repeating-linear-gradient(0deg,var(--color-silver) 0 1.5px,transparent 1.5px 5px);',
  anime: '--cell:5px;--dot:34%;rotate:45deg;inset:-45%',
};

/** Número pseudoaleatório estável em [0, 1) a partir de um inteiro. */
function hash(n) {
  const x = Math.imul(n, 2654435761) >>> 0;
  return ((x ^ (x >>> 15)) >>> 0) % 1000 / 1000;
}

function mask(id) {
  const a = hash(id);
  const b = hash(id + 7919);
  const c = hash(id + 104729);
  // Gradiente radial em posição e tamanho variáveis: cada pôster tem a sua "mancha" de tinta.
  return `radial-gradient(ellipse ${75 + b * 60}% ${60 + c * 45}% at ${10 + a * 80}% ${5 + b * 45}%, #000 0%, #000 35%, transparent 80%)`;
}

// Variante menor da mesma imagem para as miniaturas (evita baixar 500 px para exibir 44).
function thumbnail(url) {
  return url
    .replace('image.tmdb.org/t/p/w500/', 'image.tmdb.org/t/p/w185/')
    .replace('/media/anime/cover/large/', '/media/anime/cover/medium/');
}

function coverHTML(titulo, size) {
  if (!titulo.poster_url) return '';
  const url = size === 'sm' ? thumbnail(titulo.poster_url) : titulo.poster_url;
  // Se a imagem falhar, ela se remove e o pôster gerado por baixo fica visível.
  return `<img class="poster__image" src="${esc(url)}" alt="${size === 'sm' ? '' : `Capa de ${esc(titulo.title)}`}"
    loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.remove()">`;
}

/** Título abaixo do pôster, para os que têm capa (nos gerados ele já está dentro). */
export function posterCaption(titulo) {
  if (!titulo.poster_url) return '';
  return `<p class="mt-2.5 truncate text-sm font-semibold text-silver">${esc(titulo.title)}<span class="ml-1.5 font-normal text-dim">${titulo.year || ''}</span></p>`;
}

export function posterHTML(titulo, { tilt = true, size = 'md' } = {}) {
  const padrao = PATTERNS[titulo.kind] || PATTERNS.movie;
  const tamanho = 'text-[clamp(1.35rem,2.2vw,2rem)]';
  const imagem = coverHTML(titulo, size);
  const tom = titulo.kind === 'series'
    ? `<div class="poster__tone" style="--mask:${mask(titulo.id)};${padrao}"></div>`
    : `<div class="poster__tone screen" style="--mask:${mask(titulo.id)};${padrao}"></div>`;

  // Miniatura: só a textura, sem texto (o título aparece ao lado).
  if (size === 'sm') {
    return `<div class="poster" aria-hidden="true">${tom}${imagem}</div>`;
  }

  return `
    <div class="poster" ${tilt ? 'data-tilt' : ''}>
      ${tom}
      <div class="absolute inset-0 bg-linear-to-t from-night via-night/10 to-transparent"></div>
      <div class="absolute inset-x-0 bottom-0 p-3 sm:p-4" data-tilt-depth>
        <p class="mb-1.5 text-xs text-silver/70">${esc(KIND_LABEL[titulo.kind])}${titulo.year ? ` de ${titulo.year}` : ''}</p>
        <p class="display ${tamanho} font-extrabold leading-[0.95] text-silver [overflow-wrap:anywhere]">${esc(titulo.title)}</p>
      </div>
      ${imagem}
      <div class="poster__glare"></div>
    </div>`;
}
