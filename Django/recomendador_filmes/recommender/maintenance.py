"""Limpeza dos dados de gosto anônimos.

Cada visitante sem conta que marca um título cria linhas de `Interaction` e `TasteEvent` com
o dono `s:<chave da sessão>`. O `clearsessions` do Django apaga as sessões expiradas, mas não
essas linhas, que ficariam no banco para sempre. Aqui elas saem junto com a sessão.
"""
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from .models import Interaction, TasteEvent

BATCH = 500


def purge_anonymous():
    """Apaga sessões expiradas e os dados anônimos sem sessão viva. Devolve as contagens."""
    sessoes_antes = Session.objects.count()
    call_command('clearsessions')
    sessoes_apagadas = sessoes_antes - Session.objects.count()

    vivas = set(Session.objects.filter(expire_date__gt=timezone.now()).values_list('session_key', flat=True))
    donos = set(Interaction.objects.filter(owner__startswith='s:').values_list('owner', flat=True).distinct())
    donos |= set(TasteEvent.objects.filter(owner__startswith='s:').values_list('owner', flat=True).distinct())
    orfaos = sorted(dono for dono in donos if dono[2:] not in vivas)

    interacoes = eventos = 0
    for inicio in range(0, len(orfaos), BATCH):
        lote = orfaos[inicio:inicio + BATCH]
        with transaction.atomic():
            interacoes += Interaction.objects.filter(owner__in=lote).delete()[0]
            eventos += TasteEvent.objects.filter(owner__in=lote).delete()[0]
    return {
        'sessions': sessoes_apagadas,
        'owners': len(orfaos),
        'interactions': interacoes,
        'events': eventos,
    }
