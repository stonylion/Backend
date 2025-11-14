from django.db import models
from django.conf import settings
from accounts.models import *
from django.utils import timezone

# Create your models here.
class MoralTheme(models.Model):
    key = models.CharField(max_length=50, unique=True, null=True, blank=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
    
class Story(models.Model):
    CATEGORY_CHOICES = [ 
        ("classic", "명작동화"),
        ("custom", "제작동화"),
        ("extended", "확장동화"),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stories")
    child = models.ForeignKey(Child, on_delete=models.CASCADE, blank=True, null=True, related_name="stories")
    voice = models.ForeignKey(Voice, on_delete=models.CASCADE, blank=True, null=True, related_name="stories")

    title = models.CharField(max_length=200)
    author = models.CharField(max_length=50)
    cover = models.ImageField(upload_to='stories/', null=True)
    content = models.TextField()

    page_count = models.IntegerField(default=0)
    runtime = models.CharField(max_length=50, null=True, blank=True)
    age_group = models.CharField(max_length=50, null=True, blank=True)
    category = models.CharField (max_length=20, choices=CATEGORY_CHOICES, default="classic")

    morals = models.ManyToManyField(MoralTheme, related_name="stories", blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return self.title

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

class StoryLike(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="likes")
    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("story", "child")

class StoryView(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="views")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="views")
    last_viewed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("story", "user")

class StoryExtension(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="extensions")
    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="extensions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="extensions")
    extended_content = models.TextField()
    dialogue_history = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.child.name}의 {self.story.title}"
