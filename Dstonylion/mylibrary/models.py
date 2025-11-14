from django.db import models
from accounts.models import *
from story.models import *

# Create your models here.

class Library(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="library")
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="in_library")
    last_viewed_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('user', 'story')