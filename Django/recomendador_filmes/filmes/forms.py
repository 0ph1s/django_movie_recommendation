# filmes/forms.py
from django import forms

MAXIMO_RECOMENDACOES = 50


class RecomendacaoForm(forms.Form):
    filme = forms.CharField(
        label='Nome do filme',
        max_length=200,
        widget=forms.TextInput(attrs={'placeholder': 'Nome do filme:'}),
    )
    quantidade = forms.IntegerField(
        label='Número de recomendações',
        min_value=1,
        max_value=MAXIMO_RECOMENDACOES,
        widget=forms.NumberInput(attrs={'placeholder': 'Número de recomendações:'}),
    )
