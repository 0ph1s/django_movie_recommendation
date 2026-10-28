# filmes/views.py
from django.shortcuts import render

from .forms import RecomendacaoForm
from .recomendador import recomendar


def index(request):
    form = RecomendacaoForm(request.POST or None)
    filme_encontrado = None
    recomendacoes = []

    if form.is_valid():
        filme_encontrado, recomendacoes = recomendar(
            form.cleaned_data['filme'], form.cleaned_data['quantidade']
        )

    return render(request, 'filmes/index.html', {
        'form': form,
        'filme_requerido': form.cleaned_data.get('filme', '') if form.is_bound else '',
        'filme_encontrado': filme_encontrado,
        'recomendacoes': recomendacoes,
    })
