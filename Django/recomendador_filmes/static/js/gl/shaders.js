// GLSL ES 1.0 (roda em WebGL 1 e 2).
//
// Passada 1 (FIELD): calcula, em baixa resolução, três tons por ponto da tela:
//   R = campo principal (ruído com domain warping)  -> tinta prata
//   G = curvas de nível do campo                    -> tinta ciano (similaridade)
//   B = ondulação em torno do cursor                -> tinta âmbar (interação)
// Passada 2 (COMPOSITE): divide a tela em células do tamanho de um caractere, lê os
// tons no centro de cada uma e desenha o caractere ASCII de densidade equivalente
// (" " no vazio, "@" no pleno), na cor da tinta dominante. Também desenha a cortina
// da transição de página, que cobre a tela com caracteres da cor do fundo.

export const VERTEX = /* glsl */ `
attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

// Simplex noise 3D — Ian McEwan, Ashima Arts (licença MIT).
const SIMPLEX = /* glsl */ `
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
            i.z + vec4(0.0, i1.z, i2.z, 1.0))
          + i.y + vec4(0.0, i1.y, i2.y, 1.0))
          + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}
`;

export const FIELD_FRAG = /* glsl */ `
precision highp float;
uniform vec2 uRes;       // tela, em pixels do dispositivo
uniform vec2 uFieldRes;  // resolução desta passada
uniform float uTime;
uniform vec2 uMouse;     // pixels do dispositivo, origem embaixo à esquerda
uniform float uForce;    // velocidade do cursor, suavizada (0–1)
uniform float uScroll;   // rolagem em alturas de tela
uniform vec3 uFocus;     // (x, y) em uv e intensidade: onde o campo fica mais denso

${SIMPLEX}

float warped(vec2 p, float t) {
  vec2 q = vec2(snoise(vec3(p, t)), snoise(vec3(p + vec2(5.2, 1.3), t)));
  vec2 r = vec2(
    snoise(vec3(p + 1.7 * q + vec2(1.7, 9.2), t * 1.2)),
    snoise(vec3(p + 1.7 * q + vec2(8.3, 2.8), t * 1.2))
  );
  return snoise(vec3(p + 1.5 * r, t * 0.8));
}

void main() {
  vec2 uv = gl_FragCoord.xy / uFieldRes;
  float escala = 2.4 / uRes.y;
  vec2 p = (uv * uRes - 0.5 * uRes) * escala;
  vec2 m = (uMouse - 0.5 * uRes) * escala;
  p.y -= uScroll * 0.9;
  m.y -= uScroll * 0.9;

  // Lente do cursor: empurra o campo para fora, mais forte quando o mouse se move rápido.
  vec2 dm = p - m;
  float d = length(dm);
  float lente = exp(-d * d * 3.2);
  p += dm / max(d, 1e-3) * lente * (0.16 + 0.4 * uForce);

  float t = uTime * 0.045;
  float f = warped(p * 0.55, t);

  float base = smoothstep(0.02, 0.92, f) * 0.9;
  float nivel = abs(fract(f * 4.5 + uTime * 0.015) - 0.5);
  float curva = (1.0 - smoothstep(0.03, 0.14, nivel)) * smoothstep(-0.35, 0.45, f);
  float onda = lente * (0.55 + 0.45 * sin(d * 26.0 - uTime * 2.6)) * (0.55 + 0.8 * uForce);

  // Foco de composição: deixa o campo mais ralo longe do ponto escolhido (ex.: atrás do texto).
  vec2 aspecto = vec2(uRes.x / uRes.y, 1.0);
  float peso = mix(1.0 - uFocus.z, 1.0, smoothstep(1.15, 0.05, length((uv - uFocus.xy) * aspecto)));

  gl_FragColor = vec4(base * peso, curva * peso, clamp(onda, 0.0, 1.0), 1.0);
}
`;

export const COMPOSITE_FRAG = /* glsl */ `
precision highp float;
uniform sampler2D uField;
uniform sampler2D uGlyphs;
uniform vec2 uRes;
uniform float uCell;       // tamanho base da célula em pixels do dispositivo
uniform float uDensity;    // intensidade geral das tintas
uniform float uCyan;
uniform float uAmber;
uniform float uVeil;       // 0–1: cortina da transição de página
uniform float uGlyphCount;
uniform vec3 uSilverInk;
uniform vec3 uCyanInk;
uniform vec3 uAmberInk;
uniform vec3 uNight;

// Cobertura do glifo de densidade "tom" (0–1) no ponto "local" da célula.
float glifo(float tom, vec2 local) {
  float indice = floor(clamp(tom, 0.0, 1.0) * (uGlyphCount - 0.001));
  return texture2D(uGlyphs, vec2((indice + local.x) / uGlyphCount, 1.0 - local.y)).r;
}

// Composição "por cima", com alfa pré-multiplicado.
void over(inout vec3 cor, inout float alfa, vec3 tinta, float k) {
  cor = tinta * k + cor * (1.0 - k);
  alfa = k + alfa * (1.0 - k);
}

void main() {
  vec2 frag = gl_FragCoord.xy;
  vec2 tamanho = vec2(uCell * 1.1, uCell * 1.75);  // proporção de um caractere monoespaçado
  vec2 id = floor(frag / tamanho);
  vec2 local = fract(frag / tamanho);
  vec2 centro = (id + 0.5) * tamanho / uRes;
  vec3 cor = vec3(0.0);
  float alfa = 0.0;

  // Cortina: uma frente diagonal de caracteres cada vez mais densos, na cor do fundo,
  // que termina em preenchimento sólido.
  if (uVeil > 0.0) {
    float frente = clamp(uVeil * 1.7 - (centro.x * 0.35 + centro.y * 0.35), 0.0, 1.0);
    float cobre = frente > 0.97 ? 1.0 : glifo(frente, local);
    over(cor, alfa, uNight, cobre);
  }

  // Tons do campo no centro da célula; a tinta dominante define a cor do caractere.
  vec4 f = texture2D(uField, centro);
  float prata = f.r * uDensity;
  float ciano = f.g * uCyan * uDensity;
  float ambar = f.b * uAmber * (0.35 + 0.65 * uDensity);
  // Um caractere cobre bem menos da célula que um ponto cheio; a curva < 1 compensa,
  // puxando os tons médios para glifos mais densos.
  float tom = pow(clamp(max(prata, max(ciano, ambar)), 0.0, 1.0), 0.75);
  vec3 tinta = ambar >= max(prata, ciano) ? uAmberInk : (ciano >= prata ? uCyanInk : uSilverInk);
  over(cor, alfa, tinta, glifo(tom, local));

  gl_FragColor = vec4(cor, alfa);
}
`;
