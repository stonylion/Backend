from django.shortcuts import render
import os, json, base64, re, random
import boto3
from uuid import uuid4
from django.conf import settings
from django.utils import timezone
from rest_framework import views, status
import threading
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from rest_framework.response import Response
from dotenv import load_dotenv
from openai import OpenAI
from django.db import connection

from story.models import Story, StoryPage, Illustrations
from .models import IllustrationJob, ChatRoom
from .serializers import *

load_dotenv(settings.BASE_DIR / ".env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

def safe_filename(s: str) -> str:
    return SAFE_FILENAME_RE.sub("_", s.strip())[:80] or "story"


def run_illustration_job(job_id):
    job = IllustrationJob.objects.get(id=job_id)
    story = job.story
    
    job.status = "RUNNING"
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])

    # 여기 기존 코드 그대로 복사해서 넣으면 됨
    try:
        style = story.illustration_style or "watercolor"

        style_map = {
            "watercolor": "in soft watercolor children's book illustration style",
            "oil": "in warm classic oil painting fairy-tale style",
            "crayon": "in cute crayon drawing style for toddlers",
            "3d": "in rich 3D Pixar-like digital art style"
        }
        style_text = style_map.get(style, style_map["watercolor"])

        pages = story.pages.all().order_by("page_number")
        total_pages = len(pages)

        safe_title = safe_filename(story.title)
        story_context = "\n".join([f"Page {p.page_number}: {p.text}" for p in pages])

        # =====================
        # 0) COVER 생성
        # =====================
        cover_prompt = f"""
        Create a cover illustration for a children's storybook titled "{story.title}". 
        The illustration MUST be {style_text}.
        Story context:
        {story_context}
        """

        cover_result = client.images.generate(
            model="gpt-image-1",
            prompt=cover_prompt,
            size="1536x1024"
        )
        cover_b64 = cover_result.data[0].b64_json
        cover_bytes = base64.b64decode(cover_b64)

        cover_filename = f"{safe_title}_cover_{uuid4().hex[:8]}.png"
        file_obj = ContentFile(cover_bytes)
        cover_s3_path = default_storage.save(cover_filename, file_obj)

        Illustrations.objects.create(
            story_page=None,
            story=story,
            image=cover_s3_path,
            prompt=cover_prompt,
            style=style
        )

        job.completed_pages = 1
        job.save()

        # =====================
        # 1) 페이지 삽화 생성 (loop)
        # =====================
        for idx, page in enumerate(pages, start=1):
            page_prompt = f"""
            Create an illustration for page {page.page_number}.
            MUST be {style_text}.
            Context:
            {story_context}
            Page text: "{page.text}"
            """

            result = client.images.generate(
                model="gpt-image-1",
                prompt=page_prompt,
                size="1536x1024"
            )

            b64 = result.data[0].b64_json
            img_bytes = base64.b64decode(b64)

            filename = f"{safe_title}_p{page.page_number}_{uuid4().hex[:8]}.png"
            file_obj = ContentFile(img_bytes)
            s3_path = default_storage.save(filename, file_obj)

            Illustrations.objects.create(
                story_page=page,
                image=s3_path,
                prompt=page_prompt,
                style=style
            )

            job.completed_pages = idx + 1
            job.save()

        job.status = "SUCCESS"
        job.finished_at = timezone.now()
        job.save()
        

    except Exception as e:
        job.status = "FAILED"
        job.error_message = str(e)
        job.finished_at = timezone.now()
        job.save()

    finally:
        connection.close()


class GenerateIllustrationsView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        story_id = request.data.get("story_id")
        story = Story.objects.filter(id=story_id).first()

        if not story:
            return Response({"detail": "Story not found"}, status=404)

        # 페이지 수
        pages = story.pages.all().order_by("page_number")
        total_pages = len(pages)

        if total_pages == 0:
            return Response({"detail": "No pages in story"}, status=400)

        # 1) Job 생성 (처음엔 PENDING)
        job = IllustrationJob.objects.create(
            story=story,
            total_pages=total_pages + 1,
            status="PENDING",   # 중요!!
            created_at=timezone.now(),
        )

        # 2) 백그라운드에서 실행할 실제 작업 함수 호출
        threading.Thread(
            target=run_illustration_job,
            args=(job.id,),
            daemon=True
        ).start()

        # 3) 사용자에게 즉시 응답
        return Response({
            "job_id": job.id,
            "status": "PENDING"
        }, status=200)
    
class IllustrationJobStatusView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        job = get_object_or_404(IllustrationJob, id=job_id, story__user=request.user)
        return Response({
            "job_id": job.id,
            "status": job.status,
            "completed_pages": job.completed_pages,
            "total_pages": job.total_pages,
            "error_message": job.error_message,
        })
    
class IllustrationDownloadView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, story_id, page_id):
        # 1) 스토리 유효성 체크
        try:
            story = Story.objects.get(id=story_id, user=request.user)
        except Story.DoesNotExist:
            return Response({"error": "스토리를 찾을 수 없거나 권한이 없습니다."},
                            status=status.HTTP_404_NOT_FOUND)

        # 2) 페이지 가져오기
        try:
            page = StoryPage.objects.get(story=story, page_number=page_id)
        except StoryPage.DoesNotExist:
            return Response({"error": f"{page_id} 페이지를 찾을 수 없습니다."},
                            status=status.HTTP_404_NOT_FOUND)

        # 3) 삽화 가져오기
        illustration = Illustrations.objects.filter(story_page=page).last()
        if not illustration:
            return Response({"error": "해당 페이지의 삽화가 없습니다."},
                            status=status.HTTP_404_NOT_FOUND)

        s3_key = illustration.image.name  # 실제 S3 내부 경로
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        region = settings.AWS_S3_REGION_NAME

        # 4) Presigned URL 생성
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=region
        )

        try:
            presigned_url = s3_client.generate_presigned_url(
                ClientMethod='get_object',
                Params={'Bucket': bucket, 'Key': s3_key},
                ExpiresIn=60 * 5  # 5분 유효
            )
        except Exception as e:
            return Response({"error": f"URL 생성 실패: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "story_id": story_id,
            "page_id": page_id,
            "download_url": presigned_url
        }, status=200)
        
class CreateChatRoomView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        story_id = request.data.get("story_id")
        user = request.user

        if not story_id:
            return Response({"error":"story_id required"}, status=status.HTTP_400_BAD_REQUEST)

        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"error":"동화가 존재하지 않습니다"}, status=status.HTTP_404_NOT_FOUND)
        
        room, created = ChatRoom.objects.get_or_create(story=story, user=user)
        return Response({"room_id": room.id, "created": created}, status=status.HTTP_200_OK)


class ChatRoomView(views.APIView):
    permission_classes = [IsAuthenticated]
    def get_object(self, pk, user):
        room = get_object_or_404(ChatRoom, pk=pk, user=user)
        return room

    def delete(self, request, pk, format=None):
        room = self.get_object(pk, request.user)
        room.delete()
        return Response({"message": "삭제되었습니다."}, status=status.HTTP_204_NO_CONTENT)
