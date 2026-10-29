// Rolagem suave com Lenis. A rolagem continua sendo a nativa do navegador (position: sticky,
// âncoras e ScrollTrigger seguem funcionando); o Lenis só interpola a roda do mouse e o
// trackpad. Em telas de toque a rolagem continua nativa. Desligada com prefers-reduced-motion.
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';

let lenis = null;

export function initSmoothScroll({ reduced = false } = {}) {
  if (reduced) return null;
  lenis = new Lenis({
    lerp: 0.1,
    // Links "#ancora" da mesma página também rolam suavemente.
    anchors: true,
    autoRaf: false,
  });
  // Um único relógio: o Lenis avança no mesmo quadro que o GSAP e avisa o ScrollTrigger.
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add((tempo) => lenis.raf(tempo * 1000));
  gsap.ticker.lagSmoothing(0);
  return lenis;
}

/** Rola até um elemento, suavemente se o Lenis estiver ativo. */
export function scrollToElement(el, { offset = 0 } = {}) {
  if (lenis) {
    lenis.scrollTo(el, { offset });
  } else {
    const reduzido = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView({ behavior: reduzido ? 'auto' : 'smooth' });
  }
}

/** Trava a rolagem (ex.: durante a transição de saída da página). */
export function stopScroll() {
  lenis?.stop();
}

export function startScroll() {
  lenis?.start();
}
