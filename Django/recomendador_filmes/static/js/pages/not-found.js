// Página 404: o fundo fica mais denso no centro e o "404" se monta a partir dos mesmos
// caracteres ASCII do fundo, da esquerda para a direita.
import { gsap } from 'gsap';

const GLIFOS = '.:-=+*%#@';

export default function notFound({ field, reduced, ready }) {
  if (field) {
    gsap.to(field.state, {
      density: 0.55, focusX: 0.5, focusY: 0.55, focusStrength: 0.7, cyan: 1.2, amber: 0.6,
      duration: 1.6, ease: 'power2.out', onUpdate: () => field.invalidate(),
    });
  }

  const el = document.querySelector('[data-scramble]');
  if (!el || reduced) return;
  const final = el.textContent.trim();
  const progresso = { valor: 0 };

  const desenhar = () => {
    // Cada caractere se fixa quando o progresso passa da sua vez; antes disso, sorteia um glifo.
    el.textContent = [...final].map((letra, i) => (
      progresso.valor >= (i + 1) / (final.length + 1)
        ? letra
        : GLIFOS[Math.floor(Math.random() * GLIFOS.length)]
    )).join('');
  };

  desenhar();
  ready.then(() => {
    gsap.to(progresso, {
      valor: 1, duration: 1.4, ease: 'power1.inOut', onUpdate: desenhar,
      onComplete: () => { el.textContent = final; },
    });
  });
}
