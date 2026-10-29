// Botões magnéticos: o elemento acompanha o cursor e o rótulo vai um pouco além,
// criando profundidade. Volta com elasticidade quando o cursor sai.
import { gsap } from 'gsap';

const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');

export function initMagnetic(raiz = document, { reduced = false } = {}) {
  if (reduced || !finePointer.matches) return;
  raiz.querySelectorAll('[data-magnetic]:not([data-magnetic-ready])').forEach((el) => {
    el.dataset.magneticReady = '';
    const label = el.querySelector('.magnetic__label');
    const forca = parseFloat(el.dataset.magneticStrength || '0.35');
    const moveX = gsap.quickTo(el, 'x', { duration: 0.5, ease: 'power3.out' });
    const moveY = gsap.quickTo(el, 'y', { duration: 0.5, ease: 'power3.out' });
    const labelX = label && gsap.quickTo(label, 'x', { duration: 0.6, ease: 'power3.out' });
    const labelY = label && gsap.quickTo(label, 'y', { duration: 0.6, ease: 'power3.out' });

    el.addEventListener('pointermove', (e) => {
      const r = el.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2);
      const dy = e.clientY - (r.top + r.height / 2);
      moveX(dx * forca);
      moveY(dy * forca);
      labelX?.(dx * forca * 0.45);
      labelY?.(dy * forca * 0.45);
    });
    el.addEventListener('pointerleave', () => {
      gsap.to(el, { x: 0, y: 0, duration: 0.9, ease: 'elastic.out(1, 0.4)', overwrite: 'auto' });
      if (label) gsap.to(label, { x: 0, y: 0, duration: 0.9, ease: 'elastic.out(1, 0.4)', overwrite: 'auto' });
    });
  });
}
