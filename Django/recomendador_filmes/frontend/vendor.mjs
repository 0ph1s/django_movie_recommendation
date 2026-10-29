// Copia os módulos ESM do GSAP usados pelo site de node_modules/ para static/vendor/.
// Assim o Django serve tudo localmente e quem só roda o backend não precisa de Node.
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const raiz = join(dirname(fileURLToPath(import.meta.url)), '..');
const origem = join(raiz, 'node_modules', 'gsap');
const destino = join(raiz, 'static', 'vendor', 'gsap');

// index.js reexporta o núcleo; ScrollTrigger depende de Observer; Flip de utils/matrix.js;
// SplitText é autônomo.
const ARQUIVOS = [
  'index.js', 'gsap-core.js', 'CSSPlugin.js', 'ScrollTrigger.js', 'Observer.js', 'SplitText.js',
  'Flip.js', 'utils/matrix.js',
];

mkdirSync(join(destino, 'utils'), { recursive: true });
for (const arquivo of ARQUIVOS) {
  copyFileSync(join(origem, arquivo), join(destino, arquivo));
}
console.log(`GSAP: ${ARQUIVOS.length} módulos copiados para static/vendor/gsap/`);
