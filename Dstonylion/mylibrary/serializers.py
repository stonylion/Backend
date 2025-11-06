from rest_framework import serializers
from .models import Library, History
from story.serializers import StorySerializer, StoryInfoSerializer

class LibrarySerializer(serializers.ModelSerializer):
    story = StoryInfoSerializer(read_only=True)

    class Meta:
        model = Library
        fields = ["id", "story", "likes", "last_viewed_time"]

class HistorySerializer(serializers.ModelSerializer):
    story = StorySerializer(read_only=True)

    class Meta:
        model = History
        fields = ["id", "story", "viewed_time"]
