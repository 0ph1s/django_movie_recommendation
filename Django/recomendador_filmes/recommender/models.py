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
    """O estado atual de um título para um dono. O conjunto ordenado por `updated_at` forma o perfil.

    Cada título tem um único estado por dono: favoritar um título da watchlist, por exemplo,
    o tira da watchlist. Só os estados com peso (`weight`) entram no vetor de perfil; todos
    tiram o título das recomendações.
    """

    class State(models.TextChoices):
        FAVORITE = 'favorite', 'Favorito'
        LIKE = 'like', 'Curti'
        DISLIKE = 'dislike', 'Não curti'
        SEEN = 'seen', 'Já vi'
        WATCHLIST = 'watchlist', 'Quero assistir'

    owner = models.CharField('dono', max_length=64, db_index=True)
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='interactions')
    state = models.CharField('estado', max_length=9, choices=State.choices)
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
        return f'{self.owner} {self.get_state_display()} {self.title}'

    @property
    def weight(self):
        """Peso no vetor de perfil: > 0 aproxima, < 0 afasta, 0 só exclui das recomendações."""
        return state_weight(self.state)

    @property
    def legacy_signal(self):
        """O estado no formato antigo da API: 1 (curti ou favorito), -1 (não curti) ou 0."""
        return LEGACY_SIGNAL_OF.get(self.state, 0)


# Formato antigo da API (`signal`), aceito na escrita e devolvido na leitura.
STATE_OF_LEGACY_SIGNAL = {1: Interaction.State.LIKE, -1: Interaction.State.DISLIKE}
LEGACY_SIGNAL_OF = {
    Interaction.State.FAVORITE: 1,
    Interaction.State.LIKE: 1,
    Interaction.State.DISLIKE: -1,
}


def state_weight(state):
    from .config import get_config

    return {
        Interaction.State.FAVORITE: get_config().favorite_weight,
        Interaction.State.LIKE: 1.0,
        Interaction.State.DISLIKE: -1.0,
    }.get(state, 0.0)


class TasteEvent(models.Model):
    """Registro só de inserção de cada mudança de estado (alimenta a evolução do gosto).

    `from_state` vazio = o título entrou no perfil; `to_state` vazio = saiu.
    """

    owner = models.CharField('dono', max_length=64, db_index=True)
    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name='taste_events')
    from_state = models.CharField('de', max_length=9, choices=Interaction.State.choices, blank=True)
    to_state = models.CharField('para', max_length=9, choices=Interaction.State.choices, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at', 'id']
        verbose_name = 'evento de gosto'
        verbose_name_plural = 'eventos de gosto'

    def __str__(self):
        return f'{self.owner} {self.title}: {self.from_state or "-"} -> {self.to_state or "-"}'


def set_state(owner, title, state):
    """Grava o estado de um título e registra o evento se o estado mudou.

    Repetir o mesmo estado não gera evento, mas renova `updated_at` (o título volta a ser o
    mais recente, como antes).
    """
    with transaction.atomic():
        atual = Interaction.objects.select_for_update().filter(owner=owner, title=title).first()
        if atual is None:
            Interaction.objects.create(owner=owner, title=title, state=state)
            TasteEvent.objects.create(owner=owner, title=title, to_state=state)
            return
        anterior = atual.state
        atual.state = state
        atual.save(update_fields=['state', 'updated_at'])
        if anterior != state:
            TasteEvent.objects.create(owner=owner, title=title, from_state=anterior, to_state=state)


def clear_states(owner, title_ids=None):
    """Tira títulos do perfil (todos, se `title_ids` for None), com um evento por título."""
    with transaction.atomic():
        saindo = Interaction.objects.select_for_update().filter(owner=owner)
        if title_ids is not None:
            saindo = saindo.filter(title_id__in=title_ids)
        saindo = list(saindo)
        TasteEvent.objects.bulk_create([
            TasteEvent(owner=owner, title_id=i.title_id, from_state=i.state) for i in saindo
        ])
        Interaction.objects.filter(pk__in=[i.pk for i in saindo]).delete()
    return len(saindo)


def merge_history(origem, destino):
    """Passa o histórico de `origem` para `destino` (ex.: da sessão anônima para a conta).

    Se o mesmo título estiver nos dois, fica a avaliação mais recente. As datas são
    preservadas (via `update`, que não dispara o auto_now), para que a ordem cronológica que
    pesa no perfil continue a mesma. Os eventos de `origem` também passam para `destino`.
    Devolve quantos títulos vieram de `origem`.
    """
    if not origem or origem == destino:
        return 0
    with transaction.atomic():
        TasteEvent.objects.filter(owner=origem).update(owner=destino)
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
                Interaction.objects.filter(pk=atual.pk).update(state=vinda.state, updated_at=vinda.updated_at)
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
