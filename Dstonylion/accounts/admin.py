from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("id", "username", "email", "birth", "gender")

admin.site.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "user", "birth", "gender")

admin.site.register(ClonedVoice)
class VoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "voice_name", "user", "voice_file")