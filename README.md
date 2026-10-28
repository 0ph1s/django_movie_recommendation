# Recomendador de Filmes (Django)

Sistema de recomendação de filmes baseado em conteúdo. Para o filme informado, ele sugere
os títulos mais parecidos usando **TF-IDF** sobre gêneros, palavras-chave, tagline, elenco
e diretor, e a **similaridade de cosseno** entre esses vetores.

A busca pelo título tolera erros de digitação e ignora maiúsculas/minúsculas (via `difflib`).
Quando há títulos repetidos no dataset (ex.: *Batman* de 1966 e de 1989), é usado o mais popular.

Dataset: `Django/recomendador_filmes/filmes/movies.csv` (TMDB, ~4.800 filmes).

## Como executar

Requer Python 3.11 ou superior. No Windows (PowerShell), a partir da raiz do repositório:

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # só se a ativação for bloqueada
.venv\Scripts\activate
pip install -r requirements.txt

cd Django\recomendador_filmes
python manage.py migrate      # cria o banco SQLite (necessário só para o admin)
python manage.py runserver
```

Acesse <http://127.0.0.1:8000/>.

No Linux/macOS, ative o ambiente com `source .venv/bin/activate`.

## Testes

```powershell
cd Django\recomendador_filmes
python manage.py test filmes
```

## Configuração para produção

As configurações sensíveis são lidas de variáveis de ambiente:

| Variável               | Padrão                     | Descrição                                   |
|------------------------|----------------------------|---------------------------------------------|
| `DJANGO_SECRET_KEY`    | chave insegura de dev      | Chave secreta do Django                     |
| `DJANGO_DEBUG`         | `True`                     | Use `False` em produção                     |
| `DJANGO_ALLOWED_HOSTS` | vazio                      | Hosts separados por vírgula (ex.: `meusite.com`) |

## Estrutura

```
Django/recomendador_filmes/
├── filmes/
│   ├── recomendador.py   # carregamento do dataset, TF-IDF e cálculo das recomendações
│   ├── forms.py          # validação do formulário
│   ├── views.py          # view da página inicial
│   ├── tests.py
│   ├── movies.csv
│   └── templates/filmes/index.html
└── recomendador_filmes/  # settings, urls, wsgi/asgi
```
