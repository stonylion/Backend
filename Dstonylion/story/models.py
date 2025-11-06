from django.db import models
from django.conf import settings
from accounts.models import *
from django.utils import timezone

# Create your models here.
class Theme(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
    
class Story(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stories")
    child = models.ForeignKey(Child, on_delete=models.CASCADE, blank=True, null=True, related_name="stories")
    voice = models.ForeignKey(Voice, on_delete=models.CASCADE, blank=True, null=True, related_name="stories")

    title = models.CharField(max_length=200)
    cover = models.ImageField(upload_to='stories/', null=True)
    content = models.TextField()
    page_count = models.IntegerField(default=0)
    runtime = models.CharField(max_length=50, null=True, blank=True)
    age_group = models.CharField(max_length=50, null=True, blank=True)
    moral = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=50, null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)
    def __str__(self):
        return self.title

class StoryTheme(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="themes")
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="themes")

    class Meta:
        unique_together = ('story', 'theme')

class StoryPage(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="pages")
    page_number = models.PositiveIntegerField()
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['page_number']

class Illustrations(models.Model):
    story_page = models.ForeignKey(StoryPage, on_delete=models.CASCADE, related_name="illustrations")
    image = models.ImageField(upload_to='illustrations/')
    prompt = models.TextField()
    style = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return f"{self.story_page.story.title}(p.{self.story_page.page_number}) 삽화"
    
class Extension(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="extensions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="extensions")
    extended_content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return f"{self.story.title}의 확장"