/** O mini-avatar do cabeçalho busca a versão nova (o ETag evita baixar se nada mudou). */
export function refreshHeaderAvatar() {
  document.querySelectorAll('[data-header-avatar]').forEach((img) => {
    img.src = `${img.src.split('?')[0]}?v=${Date.now()}`;
  });
}
