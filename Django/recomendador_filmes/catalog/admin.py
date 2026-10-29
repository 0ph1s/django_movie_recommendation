from django.contrib import admin

from .models import Genre, Title


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    search_fields = ['name']


@admin.register(Title)
class TitleAdmin(admin.ModelAdmin):
    list_display = ['title', 'kind', 'year', 'vote_average', 'vote_count', 'popularity']
    list_filter = ['kind', 'source', 'genres']
    search_fields = ['title', 'original_title', 'director']
    filter_horizontal = ['genres']
