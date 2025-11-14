from django.shortcuts import render
import os, json, base64, re
from uuid import uuid4
from django.conf import settings
from django.utils import timezone
from rest_framework.views import APIView

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from rest_framework.response import Response
from dotenv import load_dotenv
from openai import OpenAI

from story.models import Story, StoryPage, Illustrations
from .models import IllustrationJob
from .serializers import StoryInputSerializer, IllustrationJobSerializer

load_dotenv(settings.BASE_DIR/ ".env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

def safe_filename(s: str) -> str:
    return SAFE_FILENAME_RE.sub("_", s.strip())[:80] or "story"

class GenerateIllustrationsView(APIView):
    def post(self, request):
        story_id = request.data.get("story_id")
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)

        pages = story.pages.all().order_by("page_number")
        total_pages = len(pages)
        if total_pages == 0:
            return Response({"detail": "No pages in story"}, status=400)

        job = IllustrationJob.objects.create(story=story, total_pages=2, status="RUNNING", started_at=timezone.now())

        safe_title = safe_filename(story.title)

        try:
            # 1. 전체 스토리 텍스트를 하나의 prompt로 구성하여 맥락 유지
            story_context = "\n".join([f"Page {p.page_number}: {p.text}" for p in pages])
            intro_page = pages.first()
            final_page = pages.last()

            # 2. 1페이지 삽화 생성
            intro_prompt = (
                "You are illustrating a children's storybook. "
                "Understand the full story context below to keep coherence:\n\n"
                f"{story_context}\n\n"
                f"Now create an illustration for the *first page*:\n{intro_page.text}"
            )
            intro_result = client.images.generate(
                model="gpt-image-1",
                prompt=intro_prompt,
                size="1536x1024"
            )
            intro_b64 = intro_result.data[0].b64_json
            intro_bytes = base64.b64decode(intro_b64)
            intro_filename = f"{safe_title}_p{intro_page.page_number}_{uuid4().hex[:8]}.png"
            
            file_obj = ContentFile(intro_bytes)
            s3_path = default_storage.save(intro_filename, file_obj)
            s3_url = default_storage.url(s3_path)

            Illustrations.objects.create(
                story_page=intro_page,
                image=s3_path,
                prompt=intro_prompt,
                style="default"
            )
            job.completed_pages = 1
            job.save(update_fields=["completed_pages"])

            # 3. 마지막 페이지 삽화 생성 (스토리의 마무리 느낌 강조)
            outro_prompt = (
                "Using the same overall story context to ensure narrative consistency, "
                "create an illustration for the *final page* of the story. The style of illustration should be similar with the intro page.\n\n"
                f"{story_context}\n\n"
                f"Focus on emotional or narrative closure based on this last page:\n{final_page.text}"
            )
            outro_result = client.images.generate(
                model="gpt-image-1",
                prompt=outro_prompt,
                size="1536x1024"
            )
            outro_b64 = outro_result.data[0].b64_json
            outro_bytes = base64.b64decode(outro_b64)
            outro_filename = f"{safe_title}_p{final_page.page_number}_{uuid4().hex[:8]}.png"
            
            file_obj = ContentFile(outro_bytes)
            s3_path = default_storage.save(outro_filename, file_obj)
            s3_url = default_storage.url(s3_path)

            Illustrations.objects.create(
                story_page=final_page,
                image=s3_path,
                prompt=outro_prompt,
                style="default"
            )

            job.completed_pages = 2
            job.status = "SUCCESS"
            job.finished_at = timezone.now()
            job.save()

            return Response({"job": IllustrationJobSerializer(job).data}, status=200)

        except Exception as e:
            job.status = "FAILED"
            job.error_message = str(e)
            job.finished_at = timezone.now()
            job.save()
            return Response({"error": str(e)}, status=500)