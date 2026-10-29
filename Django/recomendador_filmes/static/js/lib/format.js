// Escape de HTML e formatação de números em pt-BR.
const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export const esc = (valor) => String(valor ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);

const inteiro = new Intl.NumberFormat('pt-BR');
const decimal = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const duasCasas = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const porcento = new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 0 });

export const fmt = {
  int: (n) => inteiro.format(n),
  one: (n) => decimal.format(n),
  two: (n) => duasCasas.format(n),
  pct: (n) => porcento.format(n),
};

export const KIND_LABEL = { movie: 'Filme', series: 'Série', anime: 'Anime' };
export const KIND_PLURAL = { movie: 'filmes', series: 'séries', anime: 'animes' };

export function debounce(fn, ms) {
  let id;
  return (...args) => {
    clearTimeout(id);
    id = setTimeout(() => fn(...args), ms);
  };
}
