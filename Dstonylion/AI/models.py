from django.db import models
from django.conf import settings
from accounts.models import *
from story.models import *
from django.utils import timezone
from story.models import Story, StoryPage
import uuid

class IllustrationJob(models.Model):
    STYLE_CHOICES = [
        ("watercolor", "수채화"), 
        ("oil", "유화"), 
        ("crayon", "크레파스"),
        ("3d", "3D 애니메이션")
    ]
    
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="ai_jobs")
    style = models.CharField(max_length=50, choices=STYLE_CHOICES, null=True, blank=True)
    status = models.CharField(max_length=20, default="PENDING")  # PENDING, RUNNING, SUCCESS, FAILED
    total_pages = models.PositiveIntegerField(default=0)
    completed_pages = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Illustrations for {self.story.title} ({self.status})"

class ChatRoom(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="chatrooms")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_chatrooms")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ChatRoom ({self.story.title}) - {self.user.username}" #아이 모델 관련한 로직 및 데이터 추가하면 아이와 연결

class Message(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="messages")
    
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    text = models.TextField(blank=True)
    sender = models.CharField(
        max_length=10,
        choices=[("user", "User"), ("ai", "AI")],
    )
    prompt = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

class StoryExtension(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="ai_extensions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_extensions")

    status = models.CharField(max_length=20, default="PENDING")  # PENDING, RUNNING, SUCCESS, FAILED
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Extension for {self.story.title} ({self.status})"

class ExtendChat(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="extend_conversations")
    can_finalize = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    user_token_count = models.IntegerField(default=0)
    is_continuing = models.BooleanField(default=False)

class ExtendMessage(models.Model):
    chat = models.ForeignKey(ExtendChat, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20)  # "user" | "assistant" | "system"
    content = models.TextField()
    input_modality = models.CharField(max_length=10, blank=True, null=True)  # "text" | "voice"
    order = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)