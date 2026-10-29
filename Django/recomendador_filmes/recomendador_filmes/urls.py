# recomendador_filmes/urls.py
from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.views import serve
from django.urls import include, path, re_path
from django.views.decorators.cache import never_cache

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('', include('web.urls')),
]

if settings.DEBUG:
    # Com `runserver --nostatic`, os estáticos passam por aqui sem cache. Útil ao editar
    # o JavaScript: o navegador guarda módulos ES em cache e ignora o F5 comum.
    urlpatterns += [re_path(r'^static/(?P<path>.*)$', never_cache(serve))]
