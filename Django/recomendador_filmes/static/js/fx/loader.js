// Tela de carregamento da primeira visita de cada sessão. O contador acompanha tarefas reais
// (fontes, módulo da página, recursos da página) e nunca anda mais rápido que MIN_DURATION,
// para não piscar. No fim, entrega o lugar para a mesma cortina ASCII da transição entre
// páginas, que recua e revela o site.
import { gsap } from 'gsap';

import { startScroll, stopScroll } from './smooth-scroll.js';

const SESSION_KEY = 'angulo:loaded';
const MIN_DURATION = 1.4;  // s
const MAX_DURATION = 7;    // s: se algo travar, o site abre mesmo assim
const RAMP = ' .:-=+*%#';

/**
 * Executa a tela de carregamento, se o script do <head> a ativou (html.is-loading).
 * `tarefas` são Promises cujo término move o contador. Devolve uma Promise resolvida
 * quando o conteúdo já pode animar, ou null se não houver tela de carregamento.
 */
export function runLoader({ field, tarefas }) {
  const html = document.documentElement;
  const tela = document.querySelector('[data-loader]');
  if (!tela || !html.classList.contains('is-loading')) return null;
  try { sessionStorage.setItem(SESSION_KEY, '1'); } catch { /* sem sessionStorage: aparece em toda página */ }
  stopScroll();

  const contador = tela.querySelector('[data-loader-count]');
  const barra = desenhoDaBarra(tela.querySelector('[data-loader-bar]'));
  let concluidas = 0;
  tarefas.forEach((t) => Promise.resolve(t).catch(() => {}).finally(() => { concluidas += 1; }));

  const inicio = performance.now();
  let exibido = 0;

  return new Promise((resolve) => {
    let terminou = false;
    const terminar = () => {
      if (terminou) return;
      terminou = true;
      gsap.ticker.remove(atualizar);
      sair({ html, tela, field, resolve });
    };

    function atualizar() {
      const decorrido = (performance.now() - inicio) / 1000;
      // O alvo é o progresso real, mas limitado pelo tempo mínimo de exibição.
      const real = tarefas.length ? concluidas / tarefas.length : 1;
      const alvo = Math.min(real, decorrido / MIN_DURATION);
      exibido += (alvo - exibido) * 0.12;
      if (alvo === 1 && exibido > 0.995) exibido = 1;

      contador.textContent = String(Math.round(exibido * 100)).padStart(3, '0');
      barra(exibido);
      if (exibido === 1 || decorrido > MAX_DURATION) terminar();
    }

    gsap.ticker.add(atualizar);
    // Rede de segurança caso o requestAnimationFrame esteja congelado (aba em segundo plano).
    setTimeout(terminar, MAX_DURATION * 1000 + 500);
  });
}

/** Barra de caracteres: preenchida em ciano, borda com um glifo da rampa, resto pontilhado. */
function desenhoDaBarra(el) {
  const [preenchido, borda, resto] = el.children;
  const medida = document.createElement('span');
  medida.textContent = '#'.repeat(10);
  medida.style.visibility = 'hidden';
  el.append(medida);
  const larguraDoCaractere = medida.getBoundingClientRect().width / 10 || 9;
  medida.remove();
  const total = Math.max(12, Math.floor(el.clientWidth / larguraDoCaractere) - 1);

  return (progresso) => {
    const posicao = progresso * total;
    const cheios = Math.min(Math.floor(posicao), total);
    const fracao = posicao - cheios;
    preenchido.textContent = '#'.repeat(cheios);
    borda.textContent = cheios < total ? RAMP[Math.min(Math.floor(fracao * RAMP.length), RAMP.length - 1)] : '';
    resto.textContent = '.'.repeat(Math.max(total - cheios - 1, 0));
  };
}

function sair({ html, tela, field, resolve }) {
  const conteudo = tela.querySelector('[data-loader-content]');
  const fim = gsap.timeline();
  fim.to(conteudo, { autoAlpha: 0, y: -24, duration: 0.45, ease: 'power2.in' });

  if (!field) {
    fim.to(tela, { autoAlpha: 0, duration: 0.4 })
      .add(() => { html.classList.remove('is-loading'); startScroll(); resolve(); });
    return;
  }

  // Troca invisível: a cortina do fundo cobre a tela com a mesma cor; depois ela recua.
  fim.add(() => {
    field.state.veil = 1;
    field.invalidate();
    document.body.classList.add('is-veiled');
    requestAnimationFrame(() => requestAnimationFrame(() => {
      html.classList.remove('is-loading');
      startScroll();
      gsap.to(field.state, {
        veil: 0,
        duration: 1.1,
        ease: 'power2.inOut',
        onComplete: () => document.body.classList.remove('is-veiled'),
      });
      // Com ~60% da cortina recuada, a abertura da página pode começar.
      gsap.delayedCall(0.6, resolve);
    }));
  });
}
