# recomendador_filmes/urls.py
from django.contrib import admin
from django.urls import path
from filmes import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.index, name='index'),  # URL para o recomendador de filmes
]
