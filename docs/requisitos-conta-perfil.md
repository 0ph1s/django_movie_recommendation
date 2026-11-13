# Requisitos — Conta e perfil de gosto

Fase seguinte do Ângulo: contas de usuário e uma página de perfil que mostra o gosto de forma
visual, dinâmica e pessoal. Este documento consolida as decisões tomadas em 11/11/2026 e guia os
PRs da fase. Cada fatia é um PR, testado localmente; commit, push, merge e deploy só por ordem
explícita.

## Ponto de partida

- `recommender.models.owner_key()` já devolve `u:<pk>` para usuário autenticado e `s:<sessão>`
  para anônimo; `Interaction.owner` é texto (sem chave estrangeira para o usuário).
- O perfil é um vetor de Rocchio com decaimento por recência (`recommender/profile.py`) e o
  "DNA" já é calculado por `engine.describe_profile()`, mas só aparece no painel do playground.
- O sinal é binário (+1/−1) e reavaliar um título sobrescreve `updated_at`: não há histórico.
- Os parâmetros do filtro híbrido vão em cada requisição e não são salvos.
- Deploy: Vercel (serverless, sem disco persistente, `var/**` fora do pacote) + Postgres no Neon.
  Não há envio de e-mail nem armazenamento de mídia.

## Objetivo e escopo

**Na v1:** persistência do perfil entre dispositivos e uma página de perfil rica. O anônimo
continua de primeira classe: a conta é uma melhoria opcional.

**Fora da v1:**

- Perfil público (`/u/<username>/`), seguir pessoas, compatibilidade entre usuários. O modelo já
  nasce com `username` público para isso.
- Evolução do gosto no tempo (visualização). Os dados começam a ser gravados na v1 (RF-13).
- Nota de 1 a 5, OAuth, link mágico, verificação de e-mail e recuperação de
  senha (dependem de um serviço de e-mail, ainda não contratado).

## Decisões transversais

- **Dono do histórico** continua sendo o texto `u:<pk>` / `s:<chave>`. Excluir conta apaga pelo
  dono `u:<pk>`.
- **Sair da conta** limpa a sessão: o navegador volta a ser um anônimo com perfil em branco.
- **Parâmetros novos** (limiares, pesos, tamanho do avatar etc.) ficam em `recommender/config.py`,
  sobrescrevíveis em `settings.RECOMMENDER`, como os atuais.

---

## Fatia 1 — Contas

**RF-01 — Modelo de usuário próprio.** `AUTH_USER_MODEL` aponta para um usuário com e-mail
único (identificador de login) e `username` público único, no formato `^[a-z0-9_]{3,30}$`.

- O username é gerado no cadastro (ex.: `cinefilo_4821`, com nova tentativa em caso de colisão)
  e editável em Configurações (RF-32).
- *Operação:* o banco do Neon já tem as tabelas do `auth`/`admin` migradas com o usuário padrão.
  No deploy desta fatia, as tabelas `auth_*` e `django_admin_log` (e as do axes, se
  existirem) são recriadas e o superusuário é criado de novo. Catálogo, `Interaction` e
  `django_session` ficam intactos: os visitantes anônimos mantêm os seus perfis. Executar só
  com autorização, depois de confirmar que só existe o superusuário.
  *Feito no Neon em 12/11/2026* (não havia nenhum usuário; 6 sessões ativas preservadas).

**RF-02 — Cadastro** em `/criar-conta/`: e-mail + senha, com os `AUTH_PASSWORD_VALIDATORS`
atuais, sem verificação de e-mail. A pessoa sai do cadastro já autenticada.

**RF-03 — Login** em `/entrar/` com e-mail + senha. Respeita `?next=` apenas para destinos do
próprio site (`url_has_allowed_host_and_scheme`).

**RF-04 — Sair** por POST (com CSRF), limpando a sessão.

**RF-05 — Proteção contra força bruta** com django-axes (estado no banco, funciona entre
instâncias serverless): 5 falhas por IP + e-mail bloqueiam por 15 minutos, com mensagem clara.

**RF-06 — Mescla do histórico anônimo.** Ao cadastrar ou entrar, as interações de `s:<chave>`
passam para `u:<pk>`.

- Se o mesmo título existir nos dois, vence o `updated_at` mais recente e a outra linha é
  apagada.
- Os `TasteEvent` da sessão (RF-13) também são reatribuídos.
- Um toast avisa: "10 títulos da sessão foram somados ao seu perfil".
- *Nota técnica:* o Django troca a chave da sessão no login (`cycle_key`). A chave antiga
  precisa ser capturada antes de `login()`.

**RF-07 — Preferências salvas.** `UserPreferences` (1:1 com o usuário) guarda α, nota ×
popularidade, corte de obscuridade, diversidade e tipos.

- O anônimo guarda as mesmas preferências na sessão.
- **Ao criar conta:** as preferências da sessão são copiadas para a conta.
- **Ao entrar numa conta existente:** valem as preferências da conta.
- O playground carrega as preferências como valores iniciais e as salva quando mudam (com
  debounce).
- Um botão "Restaurar padrão" volta aos valores de `config.py`.

**RF-08 — Navegação.** O cabeçalho mostra sempre o link "Perfil" com a foto de perfil em miniatura (RF-18),
inclusive para o anônimo.

- **Anônimo:** aparece "Entrar" ao lado.
- **Logado:** a foto abre um menu com Perfil, Configurações e Sair.

**RF-09 — Oferta de conta no playground.** Ao chegar a 5 interações, um cartão discreto aparece
no painel "Seu perfil": "Guardar meu perfil" / "Agora não".

- A dispensa fica guardada na sessão.
- O cartão volta uma única vez, com 15 interações.
- Nada de modal nem de toast insistente.

**Aceite da fatia 1**

- Anônimo marca 7 títulos, cria conta e vê os 7 no perfil, junto com o toast.
- Entrar numa conta com histórico mescla sem duplicar e respeita a avaliação mais recente.
- A 6ª tentativa errada de login é bloqueada.
- Preferências ajustadas como anônimo sobrevivem ao cadastro.
- As páginas de cadastro e login funcionam sem JavaScript.

---

## Fatia 2 — Novos estados de gosto

**RF-10 — Estado único por título.** `Interaction` passa a ter um campo `state`, mutuamente
exclusivo:

| Estado | No vetor de perfil | Nas recomendações |
|---|---|---|
| `favorite` | positivo, peso ×2 (`FAVORITE_WEIGHT`) | excluído |
| `like` | positivo, peso ×1 | excluído |
| `dislike` | negativo, γ atual (0,5) | excluído |
| `seen` | não entra | excluído |
| `watchlist` | não entra | excluído da lista principal; aparece na watchlist (RF-24) |

A migração de dados converte `signal = 1` em `like` e `signal = −1` em `dislike`.

**RF-11 — Motor.** `build_profile` aplica o peso do estado multiplicado pelo peso de recência.
A recência é contada só entre os estados que entram no vetor: um `seen` recente não envelhece os
curtidos. Não há limite de favoritos.

**RF-12 — Watchlist sai sozinha.** Avaliar um título que está na watchlist o tira dela (o estado
é único).

**RF-13 — Log de eventos.** A tabela `TasteEvent` recebe só inserções, com `owner`, `title`,
`from_state` (nulo se novo), `to_state` (nulo se removido) e `created_at`.

- É gravada a cada mudança: inclusão, troca de estado, remoção e "Limpar perfil" (um evento por
  título).
- Nenhuma tela a usa na v1; ela alimenta a evolução no tempo da v2.

**RF-14 — API.** `POST /api/profile/interactions/` aceita `{"title_id", "state"}` e continua
aceitando o formato legado `{"title_id", "signal": 1 | -1}`. As respostas do perfil passam a
trazer `state`.

**RF-15 — Controles no playground.** 👍 e 👎 continuam como ações principais. Entram ★
(favoritar) e 🔖 (quero assistir); "Já vi, sem opinião" fica num menu "⋯". Os estados ficam
visíveis no cartão e na lista do perfil.

**Aceite da fatia 2**

- Favoritar puxa o vetor o dobro de um curti.
- `seen` e `watchlist` não mudam o vetor e não aparecem nas recomendações.
- Curtir um título da watchlist o remove dela.
- Cada mudança gera exatamente um `TasteEvent`.
- O cliente antigo (`signal`) continua funcionando.

---

## Fatia 3 — Página de perfil

**RF-16 — `/perfil/`** funciona para logado e anônimo. O anônimo vê o perfil da sessão, com a
faixa "Este perfil vive só neste navegador. Crie uma conta para guardá-lo".

**RF-17 — Endpoint de insights.** `GET /api/profile/insights/?exclude=1,2` devolve, num único
payload, todas as seções abaixo e o estado de desbloqueio de cada uma. `exclude` recalcula sem
gravar nada (RF-22).

**RF-18 — Foto de perfil.** *(Revisto em 13/11/2026: o avatar gerado do gosto, primeiro em
grade ASCII e depois como criatura vetorial, saiu por enquanto.)*

- **Padrão:** todo perfil começa com a foto padrão do Ângulo; o anônimo fica sempre com ela.
- **Escolha:** em Configurações, o usuário envia JPEG, PNG ou WebP de até 4 MB, com prévia antes de
  salvar, e pode remover para voltar à padrão.
- **Processamento:** o servidor valida que o arquivo é mesmo uma imagem, recorta em quadrado e
  grava um WebP 384 × 384 sem os metadados do original.
- **Onde aparece:** no cabeçalho (mini) e na abertura do `/perfil/`, com link para trocar.
- **LGPD:** a foto entra na exportação e é apagada com a conta.

**RF-19 — Cabeçalho e estatísticas:** foto de perfil, username, total de avaliações, divisão
filme/série/anime, década favorita e horas assistidas.

- **Títulos que entram nas horas:** favorito, curti, não curti e já vi (a watchlist fica de
  fora).
- **Duração de cada título:** `runtime` para filmes; `runtime × episodes` para séries e animes,
  quando os dois existem.
- **Títulos sem dados:** ficam fora da soma, e o total aparece como "≈ 312 h".

**RF-20 — DNA expandido:** tokens dominantes agrupados por categoria (gênero, pessoa, palavra-
chave), com peso relativo, mais a parcela de cada bloco (sinopse / tags / atributos).

**RF-21 — Radar de gêneros:** a afinidade por gênero (parcela ponderada por estado e recência
entre os títulos positivos) comparada com a parcela do gênero no catálogo.

**RF-22 — Títulos que te definem.** Até 8 títulos positivos, ordenados pela contribuição ao
vetor (peso do estado × peso de recência × cosseno com o perfil).

- **Modo "e se":** um interruptor em cada item o retira do cálculo (via `exclude`). O DNA, o
  radar e o centro no mapa se recalculam na hora, com uma frase-resumo ("Sem *Interestelar*,
  seu perfil perde 40% de ficção científica").
- Nada é gravado, e um botão restaura o estado original.

**RF-23 — Conforto × exploração.**

- **Ecletismo (número principal):** entropia normalizada da distribuição de gêneros e tipos nos
  títulos positivos, de 0 a 1. Aparece como "Seu gosto é 62% eclético".
- **Dispersão (apoio):** 1 − cosseno médio entre os positivos e o centro do perfil.
- **Pontos cegos (lista acionável):** gêneros, tipos e décadas com muitos títulos bem avaliados
  no catálogo e nenhuma interação sua. Cada um traz um título de entrada sugerido: o de melhor
  qualidade dentro dele entre os mais próximos do perfil.

**RF-24 — Watchlist.** Os títulos marcados com 🔖 aparecem com "% de match" (cosseno com o
perfil, na mesma escala de `relevance` das recomendações), ordenados por match, com ações para
avaliar ou remover.

**RF-25 — Desbloqueio progressivo.** Abaixo do mínimo, a seção aparece bloqueada com o
progresso ("Avalie mais 3 títulos para desbloquear o mapa"). Os limiares ficam em `config.py`:

| Seção | Mínimo |
|---|---|
| Mapa | 1 positivo |
| DNA, radar, títulos que te definem | 3 positivos |
| Estatísticas | 5 avaliações |
| Conforto × exploração | 8 positivos |

**RF-26 — Primeira avaliação.** Uma conta que nasce com zero interações (nada a mesclar) vai
para `/bem-vindo/`.

- A tela mostra 24 títulos populares, sorteados de forma estratificada por tipo, gênero e
  década, com o pedido "Marque pelo menos 5 que você curtiu".
- Dá para pular. Ao concluir ou pular, a pessoa vai para `/perfil/`.
- Quem já veio com histórico da sessão vai direto para `/perfil/`.

**RF-27 — Forma da página.** Rolagem narrativa, no espírito da home, nesta ordem: cabeçalho →
DNA → radar → mapa → títulos que te definem → conforto × exploração → watchlist. Um minimenu
fixo pula entre as seções.

**Aceite da fatia 3**

- Anônimo e logado veem a página.
- As seções respeitam os limiares.
- A foto enviada é reprocessada (sem metadados) e some junto com a conta.
- O "e se" não grava nada.
- Sem WebGL ou com `prefers-reduced-motion`, a página segue legível e estática.

---

## Fatia 4 — Mapa do gosto

**RF-28 — Projeção offline.** `build_index` / `import_dataset`, rodados localmente, calculam
TruncatedSVD (≈50 dimensões) → t-SNE 2D (scikit-learn, `random_state` fixo) e gravam
`Title.map_x` / `map_y` no banco.

- O Vercel nunca calcula a projeção; o Neon serve as coordenadas prontas.
- Sem coordenadas, a seção do mapa fica oculta.

**RF-29 — Pontos.** `GET /api/map/points/` devolve `id, x, y, kind` em formato compacto,
cacheável e igual para todos. Os estados do usuário vêm no payload de insights.

**RF-30 — Centro do perfil:** média das coordenadas dos ~10 títulos mais próximos do vetor de
perfil (o t-SNE não projeta pontos novos).

**RF-31 — Interação.** O mapa é desenhado em canvas 2D.

- **Pontos:** a cor do tipo; seus estados aparecem destacados (favorito, curti, não curti) e o
  centro fica marcado.
- **Navegação:** zoom e pan, tooltip com título e pôster, filtro por tipo.
- **Clique num ponto:** abre um painel lateral para avaliar o título ali mesmo. O centro se move
  com animação.

**Aceite da fatia 4**

- A projeção é reprodutível.
- O mapa fica fluido com ~5 mil pontos.
- Avaliar pelo painel move o centro sem recarregar a página.

---

## Fatia 5 — Configurações e LGPD

**RF-32 — `/configuracoes/`:** trocar o username (com validação de formato e unicidade) e
trocar a senha (exige a senha atual).

**RF-33 — Exportar meus dados:** download em JSON com conta (sem a senha), preferências,
interações e eventos.

**RF-34 — Excluir conta:** confirmação com a senha. Apaga na hora o usuário, `Interaction` e
`TasteEvent` de `u:<pk>` e as preferências, e encerra a sessão.

**RF-35 — Limpeza dos dados anônimos.** O comando `purge_anonymous` roda `clearsessions` e
apaga `Interaction` / `TasteEvent` de donos `s:<chave>` cuja sessão não existe mais.

- O Vercel Cron chama uma URL, não um comando. Por isso o comando é exposto em uma rota protegida
  por `Authorization: Bearer $CRON_SECRET`, agendada uma vez por dia no `vercel.json` (limite do
  plano gratuito).

**Aceite da fatia 5**

- A exportação contém todo o histórico.
- Depois da exclusão, nenhuma linha com o dono `u:<pk>` permanece.
- A rota do cron recusa chamadas sem o segredo.
- Dados de sessões expiradas somem depois da limpeza.

---

## Requisitos não funcionais

- **Testes:** cada fatia traz testes (modelo, motor, API e fluxos de conta) no padrão de
  `recommender/tests` e `api/tests.py`.
- **Desempenho:** `insights` responde em menos de 300 ms com o índice quente; o mapa não
  materializa nada por usuário além dos estados.
- **Dependências:** a única nova é o `django-axes`. Nada de numba/UMAP nem de armazenamento de
  mídia.
- **Acessibilidade e movimento:** tudo respeita `prefers-reduced-motion`; formulários com rótulos
  e erros associados; as visualizações têm resumo em texto.
- **Segurança:** CSRF em todas as mutações, `?next=` validado, cookies seguros fora do DEBUG
  (como hoje).
- **Idioma:** toda a interface em português.

## Ordem de entrega

1 → 2 → 3, com a 4 em paralelo à 3 depois da 2 → 5. Um PR por fatia.

## Para a v2

- Evolução do gosto no tempo, a partir do `TasteEvent`.
- Perfil público `/u/<username>/` com controle de visibilidade, compatibilidade entre pessoas e
  seguir.
- Serviço de e-mail: verificação, recuperação de senha e, talvez, link mágico.
