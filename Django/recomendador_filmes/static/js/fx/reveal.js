// Títulos de seção ([data-reveal]) surgem linha a linha, de dentro de uma máscara,
// quando entram na tela.
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';

export function splitLines(el) {
  return SplitText.create(el, { type: 'lines', mask: 'lines' });
}

export function initReveal(raiz = document, { reduced = false } = {}) {
  if (reduced) return;
  raiz.querySelectorAll('[data-reveal]').forEach((el) => {
    SplitText.create(el, {
      type: 'lines',
      mask: 'lines',
      autoSplit: true,
      onSplit(split) {
        return gsap.from(split.lines, {
          yPercent: 160,
          duration: 1.1,
          ease: 'expo.out',
          stagger: 0.09,
          scrollTrigger: { trigger: el, start: 'top 85%', once: true },
        });
      },
    });
  });
  ScrollTrigger.refresh();
}
