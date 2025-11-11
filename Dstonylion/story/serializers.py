from rest_framework import serializers

class StoryDraftSerializer(serializers.Serializer):
    """
    Whisper STT 결과(임시 저장된 텍스트)를 직렬화/역직렬화하는 Serializer
    """
    draft_text = serializers.CharField(required=False, allow_blank=True)
