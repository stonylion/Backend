from rest_framework import serializers
from .models import Library
from story.serializers import StoryInfoSerializer

class LibrarySerializer(serializers.ModelSerializer):
    story = StoryInfoSerializer(read_only=True)

    class Meta:
        model = Library
        fields = ["id", "story", "last_viewed_time"]
