# recommender/models.py
from django.db import models

from catalog.models import Title


def owner_key(request):
    """Dono do histórico: o usuário autenticado ou, se anônimo, a sessão do navegador."""
    if request.user.is_authenticated:
        return f'u:{request.user.pk}'
    if not request.session.session_key:
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
