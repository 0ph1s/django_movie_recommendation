// Inclinação 3D dos pôsteres: o cartão gira em direção ao cursor, a retícula interna
// desliza em sentido oposto (paralaxe) e um brilho acompanha o ponteiro.
import { gsap } from 'gsap';

const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
const MAX_ROTATION = 9;

export function initTilt(raiz = document, { reduced = false } = {}) {
  if (reduced || !finePointer.matches) return;
  raiz.querySelectorAll('[data-tilt]:not([data-tilt-ready])').forEach((card) => {
    card.dataset.tiltReady = '';
    const tom = card.querySelector('.poster__image') || card.querySelector('.poster__tone');
    const titulo = card.querySelector('[data-tilt-depth]');
    gsap.set(card, { transformPerspective: 900 });
    const rx = gsap.quickTo(card, 'rotationX', { duration: 0.6, ease: 'power3.out' });
    const ry = gsap.quickTo(card, 'rotationY', { duration: 0.6, ease: 'power3.out' });
    const tx = tom && gsap.quickTo(tom, 'x', { duration: 0.8, ease: 'power3.out' });
    const ty = tom && gsap.quickTo(tom, 'y', { duration: 0.8, ease: 'power3.out' });
    const hx = titulo && gsap.quickTo(titulo, 'x', { duration: 0.6, ease: 'power3.out' });
    const hy = titulo && gsap.quickTo(titulo, 'y', { duration: 0.6, ease: 'power3.out' });

    card.addEventListener('pointermove', (e) => {
      const r = card.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5;
      const py = (e.clientY - r.top) / r.height - 0.5;
      rx(-py * MAX_ROTATION * 2);
      ry(px * MAX_ROTATION * 2);
      tx?.(-px * 18);
      ty?.(-py * 18);
      hx?.(px * 8);
      hy?.(py * 8);
      card.style.setProperty('--gx', `${(px + 0.5) * 100}%`);
      card.style.setProperty('--gy', `${(py + 0.5) * 100}%`);
    });
    card.addEventListener('pointerleave', () => {
      rx(0); ry(0); tx?.(0); ty?.(0); hx?.(0); hy?.(0);
    });
  });
}
