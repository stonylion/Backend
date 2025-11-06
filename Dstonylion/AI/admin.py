from django.contrib import admin

# Register your models here.
from .models import IllustrationJob

admin.site.register(IllustrationJob)
class IllustrationJobAdmin(admin.ModelAdmin):
    list_display = ("id", "story", "status", "total_pages", "completed_pages", "created_at")
    list_filter = ("status",)
