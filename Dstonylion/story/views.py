from django.shortcuts import render

# Create your views here.
import os, json
from django.conf import settings
from django.core.files.storage import default_storage
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Story, StoryPage, Child, Voice
from .serializers import StorySerializer
from django.contrib.auth import get_user_model
User = get_user_model()

class StoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Story.objects.all().order_by("-created_at")
    serializer_class = StorySerializer

class StoryJsonImportView(APIView):
    """
    S3의 files/stories 폴더에서 json 파일을 읽어 Story와 StoryPage로 저장
    파일명 예: stories/story1.json (버킷 내부 경로)
    """
    def post(self, request):
        filename = request.data.get("filename")
        if not filename:
            return Response({"detail": "filename required"}, status=400)
        
        """
        path = os.path.join(settings.BASE_DIR, "static", "stories", filename)
        if not os.path.exists(path):
            return Response({"detail": "file not found"}, status=404)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        """
        s3_path = f"stories/{filename}"
        if not default_storage.exists(s3_path):
            s3_path = f"media/stories/{filename}"
            if not default_storage.exists(s3_path):
                return Response({"detail": f"{s3_path} not found in S3"}, status=404)
        with default_storage.open(s3_path, "r") as f:
            data = json.load(f)


        story = Story.objects.create(
            user = request.user,
            title=data.get("title", "무제 동화"),
            content=" ".join([p.get("text", "") for p in data.get("pages", [])]),
            page_count=len(data.get("pages", []))
        )


        for i, page in enumerate(data["pages"], start=1):
            StoryPage.objects.create(story=story, page_number=i, text=page.get("text", ""))

        return Response({"story_id": story.id, "title": story.title}, status=201)
