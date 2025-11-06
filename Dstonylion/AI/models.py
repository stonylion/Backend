from django.db import models
from django.conf import settings
from accounts.models import *
from story.models import *
from django.utils import timezone
from story.models import Story, StoryPage
# Create your models here.
class IllustrationJob(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="ai_jobs")
    status = models.CharField(max_length=20, default="PENDING")  # PENDING, RUNNING, SUCCESS, FAILED
    total_pages = models.PositiveIntegerField(default=0)
    completed_pages = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"AI Job for {self.story.title} ({self.status})"

