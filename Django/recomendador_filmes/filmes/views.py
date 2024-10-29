# filmes/views.py
import pandas as pd
import difflib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from django.shortcuts import render

# Carregar o dataset
try:
    df = pd.read_csv('filmes/movies.csv').fillna('')
    recursos_selecionados = ['genres', 'keywords', 'tagline', 'cast', 'director']
    recursos_combinados = df['genres'] + ' ' + df['keywords'] + ' ' + df['tagline'] + ' ' + df['cast'] + ' ' + df['director']
    vetorizador = TfidfVectorizer()
    vetores = vetorizador.fit_transform(recursos_combinados)
    similaridade = cosine_similarity(vetores, vetores)
    lista_de_todos_os_titulos = df['title'].tolist()
except FileNotFoundError:
    df, similaridade, lista_de_todos_os_titulos = None, None, []

def index(request):
    recomendacoes = []
    filme_requerido = ""
    quantidade_recomendacoes = 0

    if request.method == 'POST':
        filme_requerido = request.POST.get('filme')
        quantidade_recomendacoes = int(request.POST.get('quantidade'))

        # Encontrar o título mais próximo
        encontrar_mais_proximo = difflib.get_close_matches(filme_requerido, lista_de_todos_os_titulos)
        if encontrar_mais_proximo:
            titulo_mais_proximo = encontrar_mais_proximo[0]
            indice_do_filme = df[df.title == titulo_mais_proximo].index[0]
            pontuacao_similaridade = list(enumerate(similaridade[indice_do_filme]))
            filmes_similares_ordenados = sorted(pontuacao_similaridade, key=lambda x: x[1], reverse=True)

            # Extrair títulos recomendados
            for i, (indice, _) in enumerate(filmes_similares_ordenados[1:quantidade_recomendacoes+1], start=1):
                titulo_do_indice = df.loc[indice, 'title']
                recomendacoes.append(titulo_do_indice)

    return render(request, 'filmes/index.html', {
        'recomendacoes': recomendacoes,
        'filme_requerido': filme_requerido,
        'quantidade_recomendacoes': quantidade_recomendacoes
    })
