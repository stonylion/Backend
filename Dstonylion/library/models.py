from django.db import models
from accounts.models import *
from story.models import *

# Create your models here.

class Library(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="library")
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="in_library")
    likes = models.BooleanField(default=False)
    last_viewed_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('user', 'story')

class History(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="history")
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="history")
    viewed_time = models.DateTimeField(default=timezone.now, db_index=True)

    
    def __str__(self):
        return f"{self.story.title} | {self.viewed_time} 열람"