# recommender/models.py
from django.conf import settings
from django.db import models, transaction

from catalog.models import Title


def owner_key(request, create=False):
    """Dono do histórico: o usuário autenticado ou, se anônimo, a sessão do navegador.

    Visitante sem sessão ainda não tem histórico: devolve None, a menos que `create` peça
    uma sessão nova (só ao gravar uma interação, para leituras não encherem o banco).
    """
    if request.user.is_authenticated:
        return f'u:{request.user.pk}'
    if not request.session.session_key:
        if not create:
            return None
        request.session.save()
    return f's:{request.session.session_key}'


class Interaction(models.Model):
    """Um sinal explícito de gosto. O conjunto ordenado por `updated_at` forma o perfil."""

    class Signal(models.IntegerChoices):
        LIKE = 1, 'Curti'
        DISLIKE = -1, 'Não curti'

    owner = models.CharField('dono', max_length=64, db_index=True)
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='interactions')
    signal = models.SmallIntegerField('sinal', choices=Signal.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    # Reavaliar um título o torna a interação mais recente (pesa mais no perfil).
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ['updated_at']
        verbose_name = 'interação'
        verbose_name_plural = 'interações'
        constraints = [
            models.UniqueConstraint(fields=['owner', 'title'], name='unique_interaction_per_owner'),
        ]

    def __str__(self):
        return f'{self.owner} {self.get_signal_display()} {self.title}'


def merge_history(origem, destino):
    """Passa o histórico de `origem` para `destino` (ex.: da sessão anônima para a conta).

    Se o mesmo título estiver nos dois, fica a avaliação mais recente. As datas são
    preservadas (via `update`, que não dispara o auto_now), para que a ordem cronológica que
    pesa no perfil continue a mesma. Devolve quantos títulos vieram de `origem`.
    """
    if not origem or origem == destino:
        return 0
    with transaction.atomic():
        vindas = list(Interaction.objects.select_for_update().filter(owner=origem))
        if not vindas:
            return 0
        existentes = {
            i.title_id: i
            for i in Interaction.objects.select_for_update().filter(
                owner=destino, title_id__in=[v.title_id for v in vindas]
            )
        }
        for vinda in vindas:
            atual = existentes.get(vinda.title_id)
            if atual is not None and vinda.updated_at > atual.updated_at:
                Interaction.objects.filter(pk=atual.pk).update(signal=vinda.signal, updated_at=vinda.updated_at)
        Interaction.objects.filter(owner=origem, title_id__in=list(existentes)).delete()
        Interaction.objects.filter(owner=origem).update(owner=destino)
    return len(vindas)


class UserPreferences(models.Model):
    """Ajustes do filtro híbrido salvos na conta.

    `values` guarda só o que a pessoa mudou (ver recommender.preferences); o resto segue os
    padrões de config.py, então mudar um padrão alcança quem nunca mexeu naquele controle.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='preferences', verbose_name='usuário',
    )
    values = models.JSONField('valores alterados', default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'preferências'
        verbose_name_plural = 'preferências'

    def __str__(self):
        return f'Preferências de {self.user}'
