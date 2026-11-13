// Páginas de conta (entrar, criar conta, configurações): botão "Mostrar" nos campos de senha e,
// em Configurações, envio dos formulários sem recarregar a página.
// Sem JavaScript tudo funciona igual: o botão "Mostrar" fica oculto e os formulários recarregam.
export default function auth() {
  document.querySelectorAll('[data-password]').forEach((grupo) => {
    const campo = grupo.querySelector('input');
    const botao = grupo.querySelector('[data-password-toggle]');
    if (!campo || !botao) return;
    campo.style.paddingRight = '4.5rem';
    botao.classList.remove('hidden');
    botao.addEventListener('click', () => {
      const mostrar = campo.type === 'password';
      campo.type = mostrar ? 'text' : 'password';
      botao.textContent = mostrar ? 'Ocultar' : 'Mostrar';
      botao.setAttribute('aria-pressed', String(mostrar));
      campo.focus();
    });
  });

  if (document.querySelector('[data-ajax]')) settings();
}

// ------------------------------------------------------------------ configurações

function settings() {
  const formFoto = document.querySelector('[data-photo-form]');
  const entrada = formFoto?.querySelector('input[type="file"]');
  const previa = document.querySelector('[data-photo-preview]');
  const rotulo = formFoto?.querySelector('[data-photo-label]');
  const ROTULO = rotulo?.textContent;
  let fotoSalva = previa?.getAttribute('src');
  let urlLocal = null;

  // A foto escolhida aparece na prévia antes de salvar (o recorte final, em quadrado, é feito
  // no servidor; a prévia redonda com object-cover mostra algo bem próximo).
  entrada?.addEventListener('change', () => {
    const arquivo = entrada.files?.[0];
    if (!arquivo) return;
    if (urlLocal) URL.revokeObjectURL(urlLocal);
    urlLocal = URL.createObjectURL(arquivo);
    previa.src = urlLocal;
    rotulo.textContent = arquivo.name;   // o CSS corta com reticências
    rotulo.title = arquivo.name;
    showErrors(formFoto, {});
  });

  const depois = {
    photo(conta) {
      fotoSalva = conta.photo_url;
      previa.src = conta.photo_url;
      entrada.value = '';
      rotulo.textContent = ROTULO;
      rotulo.removeAttribute('title');
    },
    photo_remove(conta) {
      fotoSalva = conta.photo_url;
      previa.src = conta.photo_url;
      entrada.value = '';
      rotulo.textContent = ROTULO;
      rotulo.removeAttribute('title');
      showErrors(formFoto, {});
    },
    password(_, form) {
      form.reset();
    },
  };

  document.querySelectorAll('form[data-ajax]').forEach((form) => {
    form.addEventListener('submit', async (evento) => {
      evento.preventDefault();
      const acao = new FormData(form).get('action');
      // O botão que enviou pode estar fora do formulário (a lixeira usa form="remover-foto").
      const botao = evento.submitter || form.querySelector('[type="submit"]');
      if (botao?.disabled) return;
      botao?.setAttribute('aria-busy', 'true');
      if (botao) botao.disabled = true;
      try {
        // getAttribute: `form.action` devolveria o campo oculto chamado "action".
        const resposta = await fetch(form.getAttribute('action') || location.href, {
          method: 'POST',
          body: new FormData(form),
          headers: { 'X-Requested-With': 'fetch', Accept: 'application/json' },
          credentials: 'same-origin',
        });
        const dados = await resposta.json().catch(() => null);
        if (!dados) throw new Error(resposta.status === 413 ? 'Arquivo grande demais.' : 'Não foi possível salvar. Tente de novo.');
        if (!dados.ok) {
          showErrors(form, dados.errors || {});
          if (acao === 'photo') previa.src = fotoSalva;   // a prévia volta à foto que vale
          return;
        }
        showErrors(form, {});
        depois[acao]?.(dados.account, form);
        updateAccount(dados.account);
        toast(dados.message);
      } catch (erro) {
        toast(erro.message || 'Não foi possível salvar. Tente de novo.', { error: true });
      } finally {
        botao?.removeAttribute('aria-busy');
        if (botao) botao.disabled = false;
      }
    });
  });
}

/** Cabeçalho, botão da lixeira e campo do nome com o estado novo da conta. */
function updateAccount(conta) {
  if (!conta) return;
  document.querySelectorAll('[data-header-photo]').forEach((img) => { img.src = conta.photo_url; });
  document.querySelectorAll('[data-header-username]').forEach((el) => { el.textContent = conta.username; });
  document.querySelector('[data-account-menu] summary')?.setAttribute('aria-label', `Menu da conta de ${conta.username}`);
  const lixeira = document.querySelector('[data-photo-remove]');
  if (lixeira) lixeira.hidden = !conta.has_photo;
  const nome = document.querySelector('input[name="username"]');
  if (nome) nome.value = conta.username;   // o servidor guarda em minúsculas
}

/** Erros por campo (`{campo: [mensagens]}`; "__all__" para os do formulário inteiro). */
function showErrors(form, erros) {
  // Limpa os de antes: listas criadas aqui, as que vieram do servidor e os avisos fixos.
  form.querySelectorAll('[data-js-errors]').forEach((el) => el.remove());
  form.querySelectorAll('[data-field] ul[id$="_error"]').forEach((el) => el.remove());
  form.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'));
  document.querySelectorAll(`[data-field-errors]`).forEach((lista) => {
    if (!form.contains(lista) && !(form.matches('[data-photo-form]') && lista.dataset.fieldErrors === 'photo')) return;
    lista.hidden = true;
    lista.innerHTML = '';
    const ajuda = document.querySelector(`[data-field-help="${lista.dataset.fieldErrors}"]`);
    if (ajuda) ajuda.hidden = false;
  });
  form.querySelectorAll('[data-field] p[id$="_helptext"]').forEach((p) => { p.hidden = false; });

  let primeiro = null;
  Object.entries(erros).forEach(([campo, mensagens]) => {
    const itens = mensagens.map((m) => `<li>${escapeHTML(m)}</li>`).join('');
    const fixa = document.querySelector(`[data-field-errors="${campo}"]`);
    if (fixa && (form.contains(fixa) || campo === 'photo')) {
      fixa.innerHTML = campo === '__all__' ? mensagens.map((m) => `<p>${escapeHTML(m)}</p>`).join('') : itens;
      fixa.hidden = false;
      const ajuda = document.querySelector(`[data-field-help="${campo}"]`);
      if (ajuda) ajuda.hidden = true;
      primeiro ||= form.querySelector(`[name="${campo}"]`);
      return;
    }
    const bloco = form.querySelector(`[data-field="${campo}"]`);
    if (!bloco) return;
    const entrada = bloco.querySelector('input, select, textarea');
    entrada?.setAttribute('aria-invalid', 'true');
    bloco.querySelector('p[id$="_helptext"]')?.setAttribute('hidden', '');
    const lista = document.createElement('ul');
    lista.className = 'mt-2 space-y-1 text-xs text-amber';
    lista.setAttribute('role', 'alert');
    lista.dataset.jsErrors = '';
    lista.innerHTML = itens;
    bloco.append(lista);
    primeiro ||= entrada;
  });
  if (primeiro && primeiro.type !== 'file') primeiro.focus({ preventScroll: true });
}

function toast(texto, { error = false } = {}) {
  const pilha = document.querySelector('[data-toasts]');
  if (!pilha || !texto) return;
  const aviso = document.createElement('p');
  aviso.className = `toast pointer-events-auto max-w-md rounded-sm border border-rule bg-night/95 px-4 py-3 text-sm shadow-lg shadow-night/60 backdrop-blur-md border-l-2 ${error ? 'border-l-amber' : 'border-l-cyan'}`;
  aviso.textContent = texto;
  pilha.append(aviso);
  // A animação some com ele depois de 9 s; aí sai do DOM para a pilha não crescer.
  setTimeout(() => aviso.remove(), 10000);
}

function escapeHTML(texto) {
  return String(texto).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
