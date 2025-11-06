from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(Library)
class LibraryAdmin(admin.ModelAdmin):
    list_display = ("user", "story", "likes", "last_viewed_time")
    list_filter = ("likes",)

admin.site.register(History)
class HistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "story", "viewed_time")
    ordering = ("-viewed_time",)