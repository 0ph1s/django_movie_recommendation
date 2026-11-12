from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('entrar/', views.login_view, name='login'),
    path('criar-conta/', views.signup, name='signup'),
    path('sair/', views.logout_view, name='logout'),
    path('configuracoes/', views.settings_view, name='settings'),
    path('configuracoes/exportar/', views.export_view, name='export'),
]
