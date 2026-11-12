"""
Avatar gerado a partir do DNA do perfil: uma grade 12 × 12 de caracteres ASCII.

Cada token do DNA (gênero, pessoa, tema) vira uma "mancha" gaussiana numa posição fixa,
derivada do hash do token, com raio e intensidade proporcionais ao peso. A soma das manchas
dá a densidade de cada célula, que escolhe o caractere numa rampa (" " → "@"). A metade
esquerda é espelhada, como num identicon. A tinta vem do tipo dominante no perfil.

É determinístico: o mesmo perfil gera sempre o mesmo avatar, e ele muda quando o gosto muda.
"""
import hashlib

import numpy as np

SIZE = 12
HALF = SIZE // 2
RAMP = ' .:-=+*#%@'
MAX_TOKENS = 10

# Tinta por tipo dominante (as mesmas cores do site).
INKS = {'cyan': '#5fc3d6', 'amber': '#f2a541', 'silver': '#d8dee8', 'dim': '#8794ab'}
INK_OF_KIND = {'movie': 'cyan', 'series': 'amber', 'anime': 'silver'}
NIGHT = '#0a1322'


def _neutral():
    """Sem perfil ainda: uma retícula discreta de pontos."""
    linhas = [''.join('.' if (x + y) % 3 == 0 else ' ' for x in range(SIZE)) for y in range(SIZE)]
    return {'rows': linhas, 'ink': 'dim', 'empty': True}


def avatar_grid(resumo):
    """`resumo` é o resultado de engine.describe_profile (ou None, sem perfil)."""
    if not resumo or not resumo.get('dna'):
        return _neutral()

    ys, xs = np.mgrid[0:SIZE, 0:HALF].astype(float)
    campo = np.zeros((SIZE, HALF))
    for item in resumo['dna'][:MAX_TOKENS]:
        semente = hashlib.sha1(item['token'].encode()).digest()
        cx = semente[0] / 255 * (HALF - 0.5)
        cy = semente[1] / 255 * (SIZE - 1)
        raio = 1.0 + 2.4 * item['weight']
        campo += item['weight'] * np.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * raio ** 2))
    campo /= campo.max() or 1.0

    niveis = np.minimum(np.rint(campo ** 0.8 * (len(RAMP) - 1)).astype(int), len(RAMP) - 1)
    metades = [''.join(RAMP[n] for n in linha) for linha in niveis]

    tipos = resumo.get('kinds') or {}
    dominante = max(tipos, key=tipos.get) if tipos else 'movie'
    return {'rows': [m + m[::-1] for m in metades], 'ink': INK_OF_KIND.get(dominante, 'cyan'), 'empty': False}


def avatar_etag(grade):
    return hashlib.sha1(('|'.join(grade['rows']) + grade['ink']).encode()).hexdigest()[:16]


def avatar_svg(grade):
    """SVG quadrado (120 × 120): fundo noturno e um caractere por célula, mais forte quanto mais denso."""
    cor = INKS[grade['ink']]
    passo = 10
    textos = []
    for y, linha in enumerate(grade['rows']):
        for x, caractere in enumerate(linha):
            if caractere == ' ':
                continue
            nivel = RAMP.index(caractere) / (len(RAMP) - 1)
            opacidade = 0.35 + 0.65 * nivel
            textos.append(
                f'<text x="{x * passo + passo / 2:g}" y="{y * passo + passo * 0.8:g}" '
                f'fill-opacity="{opacidade:.2f}">{caractere}</text>'
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE * passo} {SIZE * passo}" '
        f'role="img" aria-label="Avatar gerado a partir do perfil de gosto">'
        f'<rect width="100%" height="100%" fill="{NIGHT}"/>'
        f'<g fill="{cor}" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="11" '
        f'font-weight="700" text-anchor="middle">{"".join(textos)}</g></svg>'
    )
