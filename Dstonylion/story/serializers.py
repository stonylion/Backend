from rest_framework import serializers
from .models import *

class IllustrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Illustrations
        fields = ["id", "image", "style", "created_at"]

class StoryPageSerializer(serializers.ModelSerializer):
    illustrations = IllustrationSerializer(many=True, read_only=True)

    class Meta:
        model = StoryPage
        fields = ["id", "page_number", "text", "illustrations"]

class StoryScriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoryPage
        fields = ["id", "page_number", "text"]

class StorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Story
        fields = ["id", "title", "author", "cover", "content", "category",
            "runtime", "age_group", "morals", "created_at", "updated_at"]

class StoryInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Story
        fields = ["id", "title", "author", "category", "page_count", "runtime", "age_group", "morals", "created_at", "updated_at"]

class StoryDraftSerializer(serializers.Serializer):
    draft_text = serializers.CharField(required=False, allow_blank=True)

class MoralThemeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MoralTheme
        fields = ["id", "key", "name"]

class StoryReactionListSerializer(StoryInfoSerializer):
    liked_at = serializers.DateTimeField(required=False)
    disliked_at = serializers.DateTimeField(required=False)

    class Meta(StoryInfoSerializer.Meta):
        fields = StoryInfoSerializer.Meta.fields + ["liked_at", "disliked_at"]

class StoryReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoryReaction
        fields = ["story", "child", "reaction", "created_at"]
