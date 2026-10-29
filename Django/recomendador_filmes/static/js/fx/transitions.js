// Transição entre páginas: o fundo WebGL sobe para a frente do conteúdo e uma onda de
// caracteres ASCII (com a borda em ciano) cobre a tela, enquanto o nome da página de
// destino aparece no centro. Na página seguinte, a cortina recua e o nome some.
// Sem WebGL, uma cortina sólida faz o mesmo papel com um simples fade.
import { gsap } from 'gsap';

import { startScroll, stopScroll } from './smooth-scroll.js';

const STORAGE_KEY = 'angulo:veil';

// Nome mostrado na cortina, por caminho. Links podem sobrescrever com data-transition-label.
const LABELS = {
  '/': 'Início',
  '/playground/': 'Playground',
};

/** Lê (e apaga) o aviso deixado pela página anterior: null, ou o nome do destino. */
function lerSinal() {
  try {
    const valor = sessionStorage.getItem(STORAGE_KEY);
    sessionStorage.removeItem(STORAGE_KEY);
    return valor ? valor.slice(2) : null;  // formato "1|Nome"
  } catch {
    return null;
  }
}

function gravarSinal(rotulo) {
  try { sessionStorage.setItem(STORAGE_KEY, `1|${rotulo}`); } catch { /* modo privado: segue sem cortina */ }
}

function rotuloDe(link) {
  if (link.dataset.transitionLabel) return link.dataset.transitionLabel;
  return LABELS[new URL(link.href, location.href).pathname] ?? '';
}

function isInternalNavigation(link, evento) {
  if (!link || evento.defaultPrevented || evento.button !== 0) return false;
  if (evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return false;
  if (link.target && link.target !== '_self') return false;
  if (link.hasAttribute('download') || link.dataset.transition === 'off') return false;
  const url = new URL(link.href, location.href);
  if (url.origin !== location.origin) return false;
  // Âncora na mesma página: rolagem normal.
  return !(url.pathname === location.pathname && url.search === location.search && url.hash);
}

function solidCurtain() {
  const el = document.createElement('div');
  el.setAttribute('aria-hidden', 'true');
  el.style.cssText = 'position:fixed;inset:0;z-index:95;background:#0a1322;opacity:0;pointer-events:none';
  document.body.append(el);
  return el;
}

/** Nome da página sobre a cortina. Na entrada, a animação volta pausada para quem a dispara. */
function mostrarRotulo(texto, { entrando }) {
  const el = document.querySelector('[data-transition-label]');
  if (!el || !texto) return null;
  el.textContent = texto;
  return entrando
    ? gsap.fromTo(el, { autoAlpha: 0, yPercent: 40 }, { autoAlpha: 1, yPercent: 0, duration: 0.45, ease: 'expo.out', paused: true })
    : gsap.fromTo(el, { autoAlpha: 1, yPercent: 0 }, { autoAlpha: 0, yPercent: -30, duration: 0.55, delay: 0.1, ease: 'power2.in' });
}

// A partir deste ponto da cortina (0–1) quase toda a tela está coberta e o nome pode entrar.
const VEIL_LABEL_THRESHOLD = 0.75;

/**
 * Liga a transição de saída nos links internos e executa a de entrada.
 * Devolve uma Promise resolvida quando o conteúdo da página está visível.
 */
export function initTransitions(field, { reduced = false } = {}) {
  const html = document.documentElement;
  const rotuloDeChegada = lerSinal();

  let entrada;
  if (rotuloDeChegada !== null && field && !reduced) {
    field.state.veil = 1;
    field.invalidate();
    document.body.classList.add('is-veiled');
    // Só tira a cortina CSS depois que o canvas já desenhou a dele.
    requestAnimationFrame(() => requestAnimationFrame(() => html.classList.remove('is-entering')));
    mostrarRotulo(rotuloDeChegada, { entrando: false });
    entrada = new Promise((resolve) => {
      gsap.to(field.state, {
        veil: 0,
        duration: 1.05,
        ease: 'power2.inOut',
        delay: 0.15,
        onComplete() {
          document.body.classList.remove('is-veiled');
          resolve();
        },
      });
      // A partir de ~60% os caracteres já liberam a leitura: a intro pode começar.
      gsap.delayedCall(0.65, resolve);
    });
  } else {
    html.classList.remove('is-entering');
    entrada = Promise.resolve();
  }

  // Voltando pelo histórico (bfcache), a página reaparece como foi deixada: coberta.
  window.addEventListener('pageshow', (e) => {
    if (!e.persisted) return;
    if (field) field.state.veil = 0;
    document.body.classList.remove('is-veiled');
    gsap.set('[data-transition-label]', { autoAlpha: 0 });
    startScroll();
    document.querySelectorAll('[data-curtain]').forEach((el) => el.remove());
  });

  if (reduced) return entrada;

  document.addEventListener('click', (evento) => {
    const link = evento.target.closest('a[href]');
    if (!isInternalNavigation(link, evento)) return;
    evento.preventDefault();
    const destino = link.href;
    const rotulo = rotuloDe(link);
    gravarSinal(rotulo);
    stopScroll();

    let saiu = false;
    const sair = () => {
      if (saiu) return;
      saiu = true;
      location.assign(destino);
    };
    // Se a animação não terminar (aba em segundo plano congela o requestAnimationFrame),
    // a navegação acontece mesmo assim.
    setTimeout(sair, 1800);

    const nome = mostrarRotulo(rotulo, { entrando: true });
    if (field) {
      document.body.classList.add('is-veiled');
      gsap.to(field.state, {
        veil: 1,
        duration: 0.8,
        ease: 'power2.in',
        overwrite: true,
        // O nome entra quando a cortina já cobriu quase tudo, para não se sobrepor ao conteúdo.
        onUpdate: () => {
          if (nome && !nome.isActive() && nome.progress() === 0 && field.state.veil >= VEIL_LABEL_THRESHOLD) nome.play();
        },
        // Um respiro depois de cobrir a tela, para o nome do destino ser lido.
        onComplete: () => gsap.delayedCall(0.3, sair),
      });
    } else {
      const cortina = solidCurtain();
      cortina.dataset.curtain = '';
      nome?.play();
      gsap.to(cortina, { opacity: 1, duration: 0.4, onComplete: sair });
    }
  });

  return entrada;
}
