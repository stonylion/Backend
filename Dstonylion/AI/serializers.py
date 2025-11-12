from rest_framework import serializers
from story.models import Story
from .models import *

class IllustrationJobSerializer(serializers.ModelSerializer):
    story_title = serializers.ReadOnlyField(source="story.title")

    class Meta:
        model = IllustrationJob
        fields = ["id", "story_title", "status", "total_pages", "completed_pages", "error_message", "created_at"]

class StoryInputSerializer(serializers.Serializer):
    story_id = serializers.IntegerField(help_text="기존 Story의 ID")

class StoryExtensionInputSerializer(serializers.Serializer):
    story_id = serializers.IntegerField()
    user_message = serializers.CharField()

class StoryExtensionSerializer(serializers.ModelSerializer):
    story_title = serializers.ReadOnlyField(source="story.title")

    class Meta:
        model = StoryExtension
        fields = [
            "id",
            "story_title",
            "user",
            "status",
            "prompt",
            "result_text",
            "error_message",
            "created_at",
            "finished_at",
        ]
