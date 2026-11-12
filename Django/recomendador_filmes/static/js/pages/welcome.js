// Primeira avaliação (/bem-vindo/): 24 títulos variados; cada clique marca ou desmarca
// "curti". Com a meta atingida, o botão leva ao perfil.
import { gsap } from 'gsap';

import { initTilt } from '../fx/tilt.js';
import { api } from '../lib/api.js';
import { refreshHeaderAvatar } from '../lib/avatar.js';
import { debounce, esc } from '../lib/format.js';
import { posterCaption, posterHTML } from '../lib/poster.js';

export default function welcome({ field, reduced }) {
  const raiz = document.querySelector('[data-welcome]');
  const titulos = JSON.parse(document.getElementById('welcome-data').textContent);
  const meta = Number(raiz.dataset.goal);
  const grade = raiz.querySelector('[data-welcome-grid]');
  const contador = raiz.querySelector('[data-count]');
  const progresso = raiz.querySelector('[data-progress]');
  const continuar = raiz.querySelector('[data-continue]');
  const curtidos = new Set();

  if (field) {
    gsap.to(field.state, { density: 0.13, focusStrength: 0.4, duration: 1.6, ease: 'power2.out', onUpdate: () => field.invalidate() });
  }

  grade.innerHTML = titulos.map((t) => `
    <li data-id="${t.id}">
      <button type="button" aria-pressed="false" aria-label="Curti ${esc(t.title)}"
        class="group/btn relative block w-full rounded-[4px] text-left ring-offset-4 ring-offset-night transition aria-pressed:ring-2 aria-pressed:ring-cyan">
        ${posterHTML(t)}
        <span class="absolute right-2 top-2 z-10 grid size-8 place-items-center rounded-full border border-silver/20 bg-night/70 text-sm text-transparent backdrop-blur transition group-aria-pressed/btn:border-cyan group-aria-pressed/btn:bg-cyan group-aria-pressed/btn:text-night" aria-hidden="true">✓</span>
      </button>
      ${posterCaption(t)}
    </li>`).join('');
  initTilt(grade, { reduced });
  if (!reduced) {
    gsap.from(grade.children, { y: 40, autoAlpha: 0, duration: 0.9, ease: 'expo.out', stagger: 0.03 });
  }

  const avatarDepois = debounce(refreshHeaderAvatar, 800);
  const atualizar = () => {
    avatarDepois();
    contador.textContent = curtidos.size;
    progresso.style.width = `${Math.min(curtidos.size / meta, 1) * 100}%`;
    continuar.setAttribute('aria-disabled', String(curtidos.size < meta));
  };

  grade.addEventListener('click', async (evento) => {
    const botao = evento.target.closest('button[aria-pressed]');
    if (!botao) return;
    const item = botao.closest('[data-id]');
    const id = Number(item.dataset.id);
    const marcar = !curtidos.has(id);
    // Otimista: marca já; desfaz se o servidor recusar.
    if (marcar) curtidos.add(id); else curtidos.delete(id);
    botao.setAttribute('aria-pressed', String(marcar));
    atualizar();
    try {
      if (marcar) await api('profile/interactions/', { method: 'POST', body: { title_id: id, state: 'like' } });
      else await api(`profile/interactions/${id}/`, { method: 'DELETE' });
    } catch {
      if (marcar) curtidos.delete(id); else curtidos.add(id);
      botao.setAttribute('aria-pressed', String(!marcar));
      atualizar();
    }
  });
}
