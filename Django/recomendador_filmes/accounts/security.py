"""Ajustes do django-axes (proteção contra força bruta no login)."""
from django.conf import settings

from .models import normalize_email


def client_ip(request):
    """IP de quem tenta entrar.

    No Vercel, REMOTE_ADDR é o proxy: o IP real vem em X-Real-IP, que a borda do Vercel
    sobrescreve (o cliente não consegue forjá-lo). Fora dele, REMOTE_ADDR é o próprio cliente.
    """
    if settings.ON_VERCEL:
        ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0]
        if ip.strip():
            return ip.strip()
    return request.META.get('REMOTE_ADDR')


def login_username(request, credentials):
    """O e-mail digitado, normalizado: maiúsculas não abrem uma contagem de tentativas nova."""
    valor = (credentials or {}).get('username') or request.POST.get('username', '')
    return normalize_email(valor)
