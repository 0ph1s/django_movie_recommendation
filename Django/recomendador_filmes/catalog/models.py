# catalog/models.py
from django.db import models
from django.utils.text import slugify


class Genre(models.Model):
    """Gênero canônico, compartilhado entre filmes, séries e animes.

    Os importadores traduzem os rótulos de cada fonte (ex.: "Sci-Fi" do MyAnimeList,
    "Sci-Fi & Fantasy" do TMDB TV) para este vocabulário comum, o que permite que um
    anime de ficção científica seja comparado com um filme do mesmo gênero.
    """

    name = models.CharField('nome', max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'gênero'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class TitleQuerySet(models.QuerySet):
    def for_listing(self):
        return self.prefetch_related('genres')

    def search(self, termo):
        termo = (termo or '').strip()
        if not termo:
            return self
        return self.filter(
            models.Q(title__icontains=termo) | models.Q(original_title__icontains=termo)
        )


class Title(models.Model):
    """Um item do catálogo: filme, série ou anime."""

    class Kind(models.TextChoices):
        MOVIE = 'movie', 'Filme'
        SERIES = 'series', 'Série'
        ANIME = 'anime', 'Anime'

    class Source(models.TextChoices):
        TMDB = 'tmdb', 'TMDB'
        MYANIMELIST = 'mal', 'MyAnimeList'

    kind = models.CharField('tipo', max_length=6, choices=Kind.choices, db_index=True)
    source = models.CharField('fonte', max_length=4, choices=Source.choices)
    external_id = models.CharField('ID na fonte', max_length=32)

    title = models.CharField('título', max_length=255, db_index=True)
    original_title = models.CharField('título original', max_length=255, blank=True)
    overview = models.TextField('sinopse', blank=True)
    tagline = models.CharField('tagline', max_length=400, blank=True)
    keywords = models.TextField('palavras-chave', blank=True)
    # Nomes separados por vírgula. No CSV pré-mesclado do TMDB 5000 o elenco vem como
    # texto corrido, sem separador confiável, e é guardado como está.
    cast = models.TextField('elenco', blank=True)
    # Diretor (filmes), criadores (séries) ou estúdios (animes): a "assinatura autoral".
    director = models.CharField('direção / criação / estúdio', max_length=255, blank=True)
    genres = models.ManyToManyField(Genre, related_name='titles', blank=True, verbose_name='gêneros')

    year = models.PositiveSmallIntegerField('ano', null=True, blank=True, db_index=True)
    runtime = models.PositiveSmallIntegerField('duração (min)', null=True, blank=True)
    episodes = models.PositiveIntegerField('episódios', null=True, blank=True)

    vote_average = models.FloatField('nota média', default=0)
    vote_count = models.PositiveIntegerField('votos', default=0)
    popularity = models.FloatField('popularidade', default=0)
    # Percentil (0–1) da popularidade dentro do tipo. As fontes usam escalas sem relação
    # (índice do TMDB vs. membros do MAL); o percentil é o que permite ordenar o catálogo misto.
    popularity_rank = models.FloatField('percentil de popularidade', default=0, db_index=True)
    poster_url = models.URLField('pôster', max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TitleQuerySet.as_manager()

    class Meta:
        ordering = ['-popularity_rank', 'id']
        verbose_name = 'título'
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'kind', 'external_id'], name='unique_title_per_source'
            ),
        ]
        indexes = [
            models.Index(fields=['kind', '-popularity_rank'], name='title_kind_rank_idx'),
        ]

    def __str__(self):
        return f'{self.title} ({self.year})' if self.year else self.title
