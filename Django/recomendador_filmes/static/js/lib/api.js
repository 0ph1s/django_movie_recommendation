// Cliente da API JSON. Cada "canal" cancela a requisição anterior do mesmo canal,
// para que uma resposta lenta e antiga nunca sobrescreva uma nova.
const controllers = new Map();

function csrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function api(path, { method = 'GET', body, params, channel } = {}) {
  const url = new URL(`/api/${path}`, location.origin);
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, Array.isArray(v) ? v.join(',') : v);
  });

  let signal;
  if (channel) {
    controllers.get(channel)?.abort();
    const controller = new AbortController();
    controllers.set(channel, controller);
    signal = controller.signal;
  }

  const resposta = await fetch(url, {
    method,
    signal,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(method !== 'GET' ? { 'X-CSRFToken': csrfToken() } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) throw new ApiError(dados.error || `Erro ${resposta.status} ao falar com o servidor.`, resposta.status);
  return dados;
}

export const isAbort = (erro) => erro?.name === 'AbortError';
