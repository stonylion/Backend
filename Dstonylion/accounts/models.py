from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

# Create your models here.
class User(AbstractUser):
    AVATAR_CHOICES = (
        ("woman", "Woman"),
        ("man", "Man"),
        ("grand1", "Grand1"),
        ("grand2", "Grand2"),
    )
    avatar_code = models.CharField(max_length=50, default="woman", null=True, blank=True)

    def __str__(self):
        return self.username

class Child(models.Model):
    GENDER_CHOICES = (
        ("F", "여자"),
        ("M", "남자"),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="children")
    name = models.CharField(max_length=100)
    birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    child_image_code = models.CharField(max_length=50)
    is_active = models.BooleanField(null=True, default=False)

    def __str__(self):
        return self.name
    
class ClonedVoice(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cloned_voices")
    voice_name = models.CharField(max_length=255, null=True, blank=True)
    reference_audio_url = models.URLField(null=True, blank=True)
    voice_image_code = models.CharField(max_length=50)
    se_file = models.FileField(upload_to="cloned_se/", null=True, blank=True)  # 사용자의 음색 벡터 파일
    cloned_voice_file = models.FileField(upload_to="tts_outputs/", null=True, blank=True)  # 변환된 클로닝 음성
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}의 클로닝된 음성"
    

