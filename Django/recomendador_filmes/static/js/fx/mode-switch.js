// Alterna o fundo entre retícula e ASCII (com transição) e lembra a escolha.
import { gsap } from 'gsap';

const STORAGE_KEY = 'angulo:mode';

function lerModo() {
  try { return localStorage.getItem(STORAGE_KEY) === 'ascii' ? 'ascii' : 'halftone'; } catch { return 'halftone'; }
}

export function initModeSwitch(field) {
  const botoes = document.querySelectorAll('[data-field-mode]');
  if (!field) {
    botoes.forEach((b) => { b.closest('.seg').style.display = 'none'; });
    return;
  }

  const aplicar = (modo, animar) => {
    botoes.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.fieldMode === modo)));
    const alvo = modo === 'ascii' ? 1 : 0;
    if (animar) {
      gsap.to(field.state, { mode: alvo, duration: 0.9, ease: 'power2.inOut', onUpdate: () => field.invalidate() });
    } else {
      field.state.mode = alvo;
      field.invalidate();
    }
  };

  aplicar(lerModo(), false);
  botoes.forEach((botao) => botao.addEventListener('click', () => {
    const modo = botao.dataset.fieldMode;
    try { localStorage.setItem(STORAGE_KEY, modo); } catch { /* sem armazenamento: vale só nesta página */ }
    aplicar(modo, true);
  }));
}
