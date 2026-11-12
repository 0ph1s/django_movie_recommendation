// Abertura e fechamento suaves de menus suspensos (menu da conta, hambúrguer do perfil):
// o painel desce e cresce do canto de onde nasce, e os itens entram em cascata.
import { gsap } from 'gsap';

const reduzido = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const partes = (painel) => [painel, ...painel.children];

/** Anima a entrada de um painel que acabou de ficar visível. */
export function revealMenu(painel, { origin = 'top right' } = {}) {
  gsap.killTweensOf(partes(painel));
  if (reduzido()) {
    gsap.set(partes(painel), { clearProps: 'opacity,visibility,transform' });
    return;
  }
  gsap.fromTo(painel,
    { autoAlpha: 0, y: -10, scale: 0.96, transformOrigin: origin },
    { autoAlpha: 1, y: 0, scale: 1, duration: 0.5, ease: 'expo.out' });
  gsap.fromTo(painel.children,
    { autoAlpha: 0, y: -6 },
    { autoAlpha: 1, y: 0, duration: 0.4, ease: 'power3.out', stagger: 0.035, delay: 0.06 });
}

/** Anima a saída e chama `aoFim` quando o painel pode ser escondido de fato. */
export function hideMenu(painel, aoFim) {
  gsap.killTweensOf(partes(painel));
  const terminar = () => {
    aoFim();
    gsap.set(partes(painel), { clearProps: 'opacity,visibility,transform' });
  };
  if (reduzido()) {
    terminar();
    return;
  }
  gsap.to(painel, { autoAlpha: 0, y: -6, scale: 0.97, duration: 0.22, ease: 'power2.in', onComplete: terminar });
}
