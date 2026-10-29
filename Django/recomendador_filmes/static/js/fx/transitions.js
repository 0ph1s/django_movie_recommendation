// Transição entre páginas: o fundo WebGL sobe para a frente do conteúdo e a cortina
// de pontos cobre a tela; na página seguinte, os pontos encolhem e revelam o conteúdo.
// Sem WebGL, uma cortina sólida faz o mesmo papel com um simples fade.
import { gsap } from 'gsap';

const STORAGE_KEY = 'angulo:veil';

function lerSinal() {
  try {
    const valor = sessionStorage.getItem(STORAGE_KEY);
    sessionStorage.removeItem(STORAGE_KEY);
    return Boolean(valor);
  } catch {
    return false;
  }
}

function gravarSinal() {
  try { sessionStorage.setItem(STORAGE_KEY, '1'); } catch { /* modo privado: segue sem cortina */ }
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

/**
 * Liga a transição de saída nos links internos e executa a de entrada.
 * Devolve uma Promise resolvida quando o conteúdo da página está visível.
 */
export function initTransitions(field, { reduced = false } = {}) {
  const html = document.documentElement;
  const chegandoDeTransicao = lerSinal();

  let entrada;
  if (chegandoDeTransicao && field && !reduced) {
    field.state.veil = 1;
    field.invalidate();
    document.body.classList.add('is-veiled');
    // Só tira a cortina CSS depois que o canvas já desenhou a dele.
    requestAnimationFrame(() => requestAnimationFrame(() => html.classList.remove('is-entering')));
    entrada = new Promise((resolve) => {
      gsap.to(field.state, {
        veil: 0,
        duration: 1.05,
        ease: 'power2.inOut',
        delay: 0.05,
        onComplete() {
          document.body.classList.remove('is-veiled');
          resolve();
        },
      });
      // A partir de ~60% os pontos já liberam a leitura: a intro pode começar.
      gsap.delayedCall(0.55, resolve);
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
    document.querySelectorAll('[data-curtain]').forEach((el) => el.remove());
  });

  if (reduced) return entrada;

  document.addEventListener('click', (evento) => {
    const link = evento.target.closest('a[href]');
    if (!isInternalNavigation(link, evento)) return;
    evento.preventDefault();
    const destino = link.href;
    gravarSinal();

    let saiu = false;
    const sair = () => {
      if (saiu) return;
      saiu = true;
      location.assign(destino);
    };
    // Se a animação não terminar (aba em segundo plano congela o requestAnimationFrame),
    // a navegação acontece mesmo assim.
    setTimeout(sair, 1500);

    if (field) {
      document.body.classList.add('is-veiled');
      gsap.to(field.state, { veil: 1, duration: 0.75, ease: 'power2.in', overwrite: true, onComplete: sair });
    } else {
      const cortina = solidCurtain();
      cortina.dataset.curtain = '';
      gsap.to(cortina, { opacity: 1, duration: 0.4, onComplete: sair });
    }
  });

  return entrada;
}
