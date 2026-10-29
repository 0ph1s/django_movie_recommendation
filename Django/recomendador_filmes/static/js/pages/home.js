// Página inicial: abertura do hero, seção do método guiada pela rolagem e destaques.
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

import { initTilt } from '../fx/tilt.js';
import { splitLines } from '../fx/reveal.js';
import { esc } from '../lib/format.js';
import { posterHTML } from '../lib/poster.js';

// Tintas do fundo em cada passo do método: o campo "ilustra" o termo da fórmula em foco.
const STEP_INKS = {
  text: { cyan: 0.35, amber: 0.5, alpha: 0.75 },
  tags: { cyan: 0.7, amber: 0.5, alpha: 0.75 },
  cosine: { cyan: 1.25, amber: 0.4, alpha: 0.75 },
  hybrid: { cyan: 0.55, amber: 1.6, alpha: 0.5 },
  profile: { cyan: 1, amber: 1, alpha: 0.75 },
};

export default function home({ field, reduced, ready }) {
  const densidade = composeDensity(field);
  heroIntro(densidade, reduced, ready);
  heroScroll(densidade, reduced);
  methodSteps(field, reduced);
  renderFeatured(reduced);
}

/** A densidade do fundo é o produto da abertura (0→1) pelo afastamento do hero na rolagem. */
function composeDensity(field) {
  const fatores = { intro: 0, scroll: 1 };
  const aplicar = () => {
    if (!field) return;
    field.state.density = fatores.intro * fatores.scroll;
    field.invalidate();
  };
  return { fatores, aplicar };
}

function heroIntro({ fatores, aplicar }, reduced, ready) {
  const titulo = document.querySelector('[data-hero-title]');
  const resto = document.querySelectorAll('[data-hero-copy], [data-hero-actions]');

  if (reduced) {
    fatores.intro = 1;
    aplicar();
    gsap.set([titulo, ...resto], { autoAlpha: 1 });
    return;
  }

  const split = splitLines(titulo);
  gsap.set(split.lines, { yPercent: 160 });
  gsap.set(titulo, { autoAlpha: 1 });
  gsap.set(resto, { autoAlpha: 0, y: 24 });

  ready.then(() => {
    gsap.timeline({ defaults: { ease: 'expo.out' } })
      .to(fatores, { intro: 1, duration: 2.2, ease: 'power2.out', onUpdate: aplicar }, 0)
      .to(split.lines, { yPercent: 0, duration: 1.4, stagger: 0.12 }, 0.1)
      .to(resto, { autoAlpha: 1, y: 0, duration: 1.1, stagger: 0.1 }, 0.75);
  });
}

function heroScroll({ fatores, aplicar }, reduced) {
  const hero = document.querySelector('[data-hero]');
  if (!hero) return;
  ScrollTrigger.create({
    trigger: hero,
    start: 'top top',
    end: 'bottom top',
    scrub: reduced ? false : 0.6,
    onUpdate(self) {
      fatores.scroll = 1 - self.progress * 0.7;
      aplicar();
    },
  });
}

function methodSteps(field, reduced) {
  const passos = gsap.utils.toArray('[data-step]');
  const termos = gsap.utils.toArray('[data-term]');
  const leitura = document.querySelector('[data-alpha-readout]');
  const barraSim = document.querySelector('[data-alpha-sim]');
  const barraQualidade = document.querySelector('[data-alpha-quality]');
  if (!passos.length) return;

  const alfa = { valor: 0.75 };
  const mostrarAlfa = () => {
    leitura.textContent = `α = ${alfa.valor.toFixed(2).replace('.', ',')}`;
    barraSim.style.width = `${alfa.valor * 100}%`;
    barraQualidade.style.width = `${(1 - alfa.valor) * 100}%`;
  };
  const duracao = reduced ? 0 : 0.8;

  const ativar = (passo) => {
    const ativos = new Set(passo.dataset.terms.split(' '));
    passos.forEach((p) => gsap.to(p, { opacity: p === passo ? 1 : 0.35, duration: duracao }));
    termos.forEach((t) => gsap.to(t, { opacity: ativos.has(t.dataset.term) ? 1 : 0.4, duration: duracao }));

    const tintas = STEP_INKS[passo.dataset.step];
    gsap.to(alfa, { valor: tintas.alpha, duration: duracao * 1.4, ease: 'power2.inOut', onUpdate: mostrarAlfa });
    if (field) {
      gsap.to(field.state, {
        cyan: tintas.cyan, amber: tintas.amber, duration: duracao * 1.6, ease: 'power2.inOut',
        onUpdate: () => field.invalidate(),
      });
    }
  };

  gsap.set(passos, { opacity: 0.35 });
  passos.forEach((passo) => {
    ScrollTrigger.create({
      trigger: passo,
      start: 'top 62%',
      end: 'bottom 38%',
      onToggle: (self) => self.isActive && ativar(passo),
    });
  });

  // Dentro da seção, o campo se concentra atrás da fórmula (à esquerda) e libera a
  // leitura dos passos; fora dela, volta ao equilíbrio e ao foco do hero.
  if (!field) return;
  const estadoDoCampo = (alvo) => () => gsap.to(field.state, {
    ...alvo, duration: 1.2, ease: 'power2.inOut', overwrite: 'auto', onUpdate: () => field.invalidate(),
  });
  const metodo = { focusX: 0.18, focusY: 0.42, focusStrength: 0.92 };
  const hero = { cyan: 0.6, amber: 1, focusX: 0.8, focusY: 0.78, focusStrength: 0.8 };
  // Depois do método, o foco sai pela base da tela: o resto da página fica calmo.
  const fim = { cyan: 0.6, amber: 1, focusX: 0.5, focusY: -0.6, focusStrength: 0.9 };
  ScrollTrigger.create({
    trigger: '[data-method]',
    start: 'top 60%',
    end: 'bottom 40%',
    onEnter: estadoDoCampo(metodo),
    onEnterBack: estadoDoCampo(metodo),
    onLeave: estadoDoCampo(fim),
    onLeaveBack: estadoDoCampo(hero),
  });
}

function renderFeatured(reduced) {
  const alvo = document.querySelector('[data-featured]');
  const dados = document.getElementById('featured-data');
  if (!alvo || !dados) return;

  const titulos = JSON.parse(dados.textContent);
  alvo.innerHTML = titulos.map((t) => `
    <a href="/playground/?similar=${t.id}" class="group block" aria-label="Ver títulos parecidos com ${esc(t.title)}">
      ${posterHTML(t)}
      <p class="mt-3 line-clamp-2 text-sm text-dim transition-colors group-hover:text-silver">${esc(t.genres.slice(0, 3).join(', '))}</p>
    </a>`).join('');
  initTilt(alvo, { reduced });

  if (!reduced) {
    gsap.from(alvo.children, {
      y: 60,
      autoAlpha: 0,
      duration: 1,
      ease: 'expo.out',
      stagger: { each: 0.06, grid: 'auto', from: 'start' },
      scrollTrigger: { trigger: alvo, start: 'top 85%', once: true },
    });
  }
}
