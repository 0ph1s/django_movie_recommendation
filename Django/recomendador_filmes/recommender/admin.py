from django.contrib import admin

from .models import Interaction, TasteEvent, UserPreferences


@admin.register(Interaction)
class InteractionAdmin(admin.ModelAdmin):
    list_display = ['owner', 'title', 'state', 'updated_at']
    list_filter = ['state']
    raw_id_fields = ['title']
    search_fields = ['owner', 'title__title']


@admin.register(TasteEvent)
class TasteEventAdmin(admin.ModelAdmin):
    list_display = ['owner', 'title', 'from_state', 'to_state', 'created_at']
    list_filter = ['to_state']
    raw_id_fields = ['title']
    search_fields = ['owner', 'title__title']


@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    list_display = ['user', 'updated_at']
    raw_id_fields = ['user']
