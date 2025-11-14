from django.contrib import admin
from .models import Story, StoryPage, Illustrations, Theme, StoryTheme, Extension

class StoryPageInline(admin.TabularInline):
    model = StoryPage
    extra = 0

admin.site.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "created_at", "page_count")
    inlines = [StoryPageInline]

admin.site.register(Illustrations)
class IllustrationAdmin(admin.ModelAdmin):
    list_display = ("id", "story_page", "created_at")

admin.site.register(Theme)
admin.site.register(StoryTheme)
admin.site.register(Extension)
