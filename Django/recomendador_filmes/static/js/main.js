// Ponto de entrada: fundo WebGL, transições, micro-interações e o módulo da página.
import { gsap } from 'gsap';
import { Flip } from 'gsap/Flip';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';

import { initMagnetic } from './fx/magnetic.js';
import { initReveal } from './fx/reveal.js';
import { initTransitions } from './fx/transitions.js';
import { HalftoneField } from './gl/field.js';

gsap.registerPlugin(ScrollTrigger, SplitText, Flip);

const PAGES = {
  home: () => import('./pages/home.js'),
  playground: () => import('./pages/playground.js'),
};

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function createField() {
  const canvas = document.querySelector('[data-field]');
  const field = new HalftoneField(canvas, { reduced });
  if (!field.init()) {
    canvas.remove();
    return null;
  }
  gsap.ticker.add((_, deltaTime) => field.tick(deltaTime));
  return field;
}

const field = createField();
const ready = initTransitions(field, { reduced });

// SplitText e medidas de layout dependem das fontes finais.
document.fonts.ready.then(async () => {
  initMagnetic(document, { reduced });
  initReveal(document, { reduced });
  const pagina = PAGES[document.body.dataset.page];
  if (pagina) {
    const modulo = await pagina();
    modulo.default({ field, reduced, ready });
  }
});
