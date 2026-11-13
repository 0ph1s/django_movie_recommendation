"""Dados pessoais de uma conta (LGPD): exportação completa e exclusão definitiva."""
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
import base64

from django.db import transaction
from django.utils import timezone

from recommender.models import Interaction, TasteEvent, UserPreferences

from .models import ProfilePhoto


def export_user_data(user):
    """Tudo o que o Ângulo guarda sobre a conta, em um dicionário pronto para JSON.

    A senha nunca sai (nem o hash).
    """
    preferencias = UserPreferences.objects.filter(user=user).values_list('values', flat=True).first()
    interacoes = Interaction.objects.filter(owner=user.owner).select_related('title').order_by('updated_at')
    eventos = TasteEvent.objects.filter(owner=user.owner).select_related('title').order_by('created_at', 'id')
    foto = ProfilePhoto.objects.filter(user=user).values_list('image', flat=True).first()
    return {
        'exported_at': timezone.now().isoformat(),
        'account': {
            'email': user.email,
            'username': user.username,
            'date_joined': user.date_joined.isoformat(),
            'last_login': user.last_login.isoformat() if user.last_login else None,
            # A foto enviada (já reprocessada em WebP), embutida no próprio arquivo.
            'profile_photo': f'data:image/webp;base64,{base64.b64encode(bytes(foto)).decode()}' if foto else None,
        },
        'preferences': preferencias or {},
        'interactions': [
            {
                'title_id': i.title_id,
                'title': i.title.title,
                'kind': i.title.kind,
                'year': i.title.year,
                'state': i.state,
                'created_at': i.created_at.isoformat(),
                'updated_at': i.updated_at.isoformat(),
            }
            for i in interacoes
        ],
        'events': [
            {
                'title_id': e.title_id,
                'title': e.title.title,
                'from_state': e.from_state or None,
                'to_state': e.to_state or None,
                'created_at': e.created_at.isoformat(),
            }
            for e in eventos
        ],
    }


def delete_user_data(user):
    """Apaga a conta e tudo o que pertence a ela. Devolve quantas linhas de gosto saíram."""
    dono = user.owner
    with transaction.atomic():
        interacoes, _ = Interaction.objects.filter(owner=dono).delete()
        eventos, _ = TasteEvent.objects.filter(owner=dono).delete()
        # O axes guarda o e-mail digitado (sem vínculo com a conta) nas tentativas de login.
        for modelo in (AccessAttempt, AccessLog, AccessFailureLog):
            modelo.objects.filter(username=user.email).delete()
        user.delete()  # UserPreferences e a foto de perfil vão juntas (CASCADE)
    return interacoes + eventos
