// Ponto de entrada: fundo WebGL, transições, micro-interações e o módulo da página.
import { gsap } from 'gsap';
import { Flip } from 'gsap/Flip';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';

import { runLoader } from './fx/loader.js';
import { initMagnetic } from './fx/magnetic.js';
import { initReveal } from './fx/reveal.js';
import { initSmoothScroll } from './fx/smooth-scroll.js';
import { initTransitions } from './fx/transitions.js';
import { AsciiField } from './gl/field.js';

gsap.registerPlugin(ScrollTrigger, SplitText, Flip);

const PAGES = {
  home: () => import('./pages/home.js'),
  playground: () => import('./pages/playground.js'),
  'not-found': () => import('./pages/not-found.js'),
};

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function createField() {
  const canvas = document.querySelector('[data-field]');
  const field = new AsciiField(canvas, { reduced });
  if (!field.init()) {
    canvas.remove();
    return null;
  }
  gsap.ticker.add((_, deltaTime) => field.tick(deltaTime));
  return field;
}

initSmoothScroll({ reduced });
const field = createField();
// O módulo da página começa a carregar já, em paralelo com as fontes.
const moduloDaPagina = PAGES[document.body.dataset.page]?.();
const entradaPorTransicao = initTransitions(field, { reduced });

// Na primeira visita da sessão, a tela de carregamento acompanha estas tarefas e, ao sair,
// faz o papel da transição de entrada.
const carregamento = runLoader({
  field,
  tarefas: [
    document.fonts.ready,
    moduloDaPagina,
    new Promise((resolve) => (document.readyState === 'complete' ? resolve() : addEventListener('load', resolve, { once: true }))),
  ],
});
const ready = carregamento ?? entradaPorTransicao;

// SplitText e medidas de layout dependem das fontes finais.
document.fonts.ready.then(async () => {
  initMagnetic(document, { reduced });
  // Os títulos só se revelam quando a página fica visível (depois do carregamento ou da cortina).
  ready.then(() => initReveal(document, { reduced }));
  if (!moduloDaPagina) return;
  try {
    const modulo = await moduloDaPagina;
    modulo.default({ field, reduced, ready });
  } catch (erro) {
    // Sem o módulo, a página continua legível: o CSS revela a abertura sozinho em 3 s.
    console.error('[Ângulo] falha ao iniciar a página:', erro);
  }
});
