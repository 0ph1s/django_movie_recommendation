"""Foto de perfil: validação, recorte e gravação.

Toda imagem enviada é decodificada e reescrita pelo Pillow: o que fica guardado é sempre um WebP
quadrado e pequeno, sem os metadados do arquivo original (EXIF com local da foto, câmera etc.).
Um arquivo que não seja JPEG, PNG ou WebP de verdade é recusado, seja qual for a extensão.
"""
import io
import time
import warnings

from django.core.exceptions import ValidationError
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import ProfilePhoto

MAX_UPLOAD_BYTES = 4 * 1024 * 1024        # o Vercel recusa corpos acima de 4,5 MB
MAX_PIXELS = 40_000_000                   # protege contra "bombas" de descompressão
ACCEPTED_FORMATS = {'JPEG', 'PNG', 'WEBP'}
SIZE = 384
QUALITY = 82
BACKGROUND = (10, 19, 34)                 # cor de fundo do site, sob áreas transparentes


def process_photo(arquivo):
    """Lê o upload e devolve os bytes do WebP final, ou levanta ValidationError."""
    if arquivo.size > MAX_UPLOAD_BYTES:
        raise ValidationError('A imagem passa de 4 MB. Escolha uma menor.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            imagem = Image.open(arquivo)
            if imagem.format not in ACCEPTED_FORMATS:
                raise ValidationError('Envie uma imagem JPEG, PNG ou WebP.')
            if imagem.width * imagem.height > MAX_PIXELS:
                raise ValidationError('A imagem tem pixels demais. Escolha uma menor.')
            imagem.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError):
        raise ValidationError('Não foi possível ler esse arquivo como imagem.') from None

    imagem = ImageOps.exif_transpose(imagem)   # respeita a orientação da câmera antes de jogar o EXIF fora
    if imagem.mode in ('RGBA', 'LA') or (imagem.mode == 'P' and 'transparency' in imagem.info):
        fundo = Image.new('RGB', imagem.size, BACKGROUND)
        fundo.paste(imagem.convert('RGBA'), mask=imagem.convert('RGBA').getchannel('A'))
        imagem = fundo
    imagem = ImageOps.fit(imagem.convert('RGB'), (SIZE, SIZE), Image.LANCZOS, centering=(0.5, 0.4))

    saida = io.BytesIO()
    imagem.save(saida, 'WEBP', quality=QUALITY, method=6)   # sem exif=: nenhum metadado vai junto
    return saida.getvalue()


def save_photo(user, dados):
    with transaction.atomic():
        ProfilePhoto.objects.update_or_create(user=user, defaults={'image': dados})
        user.photo_version = _new_version(user)
        user.save(update_fields=['photo_version'])


def remove_photo(user):
    with transaction.atomic():
        ProfilePhoto.objects.filter(user=user).delete()
        user.photo_version = 0
        user.save(update_fields=['photo_version'])


def _new_version(user):
    """Muda a cada troca (entra na URL da foto, que é guardada em cache por muito tempo)."""
    return max(int(time.time()), user.photo_version + 1)
