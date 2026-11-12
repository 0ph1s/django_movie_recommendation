// Páginas de conta (entrar, criar conta): botão "Mostrar" nos campos de senha.
// Sem JavaScript o botão fica oculto e o formulário funciona igual.
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
}
