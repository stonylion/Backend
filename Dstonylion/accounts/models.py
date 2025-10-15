from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

# Create your models here.
class User(AbstractUser):
    birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    profile_image = models.ImageField(upload_to='users/', null=True, blank=True)
    
    def __str__(self):
        return self.username

class Child(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="children")
    name = models.CharField(max_length=100)
    birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    profile_image = models.ImageField(upload_to='children/', null=True, blank=True)

    def __str__(self):
        return self.name
    
class Voice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="voices")
    name = models.CharField(max_length=100)
    voice_file = models.FileField(upload_to='voices/')

    def __str__(self):
        return self.name