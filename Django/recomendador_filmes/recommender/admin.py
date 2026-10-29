from django.contrib import admin

from .models import Interaction


@admin.register(Interaction)
class InteractionAdmin(admin.ModelAdmin):
    list_display = ['owner', 'title', 'signal', 'updated_at']
    list_filter = ['signal']
    raw_id_fields = ['title']
