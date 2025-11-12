from rest_framework import serializers
from .models import Story, StoryPage, Illustrations

class IllustrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Illustrations
        fields = ["id", "image", "style", "created_at"]

class StoryPageSerializer(serializers.ModelSerializer):
    illustrations = IllustrationSerializer(many=True, read_only=True)

    class Meta:
        model = StoryPage
        fields = ["id", "page_number", "text", "illustrations"]

class StorySerializer(serializers.ModelSerializer):
    pages = StoryPageSerializer(many=True, read_only=True)

    class Meta:
        model = Story
        fields = ["id", "title", "category", "user", "child", "voice", "page_count", "age_group", "moral", "status", "created_at", "pages"]

class StoryInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Story
        fields = ["id", "user", "child", "title", "page_count", "moral", "status", "created_at"]
