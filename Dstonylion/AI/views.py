from django.shortcuts import render
import os, json, base64, re, random
import boto3
from uuid import uuid4
from django.conf import settings
from django.utils import timezone
from rest_framework import views, status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from rest_framework.response import Response
from dotenv import load_dotenv
from openai import OpenAI

from story.models import Story, StoryPage, Illustrations
from .models import IllustrationJob, ChatRoom
from .serializers import *

load_dotenv(settings.BASE_DIR/ ".env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

def safe_filename(s: str) -> str:
    return SAFE_FILENAME_RE.sub("_", s.strip())[:80] or "story"

class GenerateIllustrationsView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        story_id = request.data.get("story_id")
        story = Story.objects.filter(id=story_id).first()

        if not story:
            return Response({"detail": "Story not found"}, status=404)
        
        # 1) story 앱에서 저장한 스타일 가져오기
        style = story.illustration_style or "watercolor"

        style_map = {
            "watercolor": "in soft watercolor children's book illustration style",
            "oil": "in warm classic oil painting fairy-tale style",
            "crayon": "in cute crayon drawing style for toddlers",
            "3d": "in rich 3D Pixar-like digital art style"
        }
        style_text = style_map.get(style, style_map["watercolor"])

        # 2) 모든 페이지 가져오기
        pages = story.pages.all().order_by("page_number")
        total_pages = len(pages)

        if total_pages == 0:
            return Response({"detail": "No pages in story"}, status=400)

        # 3) 삽화 생성 Job 생성
        job = IllustrationJob.objects.create(
            story=story,
            total_pages=total_pages + 1,
            status="RUNNING",
            started_at=timezone.now()
        )
        safe_title = safe_filename(story.title)

        # 5) 전체 스토리 컨텍스트
        story_context = "\n".join([f"Page {p.page_number}: {p.text}" for p in pages])

        try:
            # ----------------------------
            # 🎨 0) 표지(Cover Image) 생성
            # ----------------------------

            cover_prompt = f"""
            Create a cover illustration for a children's storybook titled "{story.title}". 
            The illustration MUST be {style_text}.
            The story's overall theme and mood are as follows:

            {story_context}

            Make it visually appealing as a cover and consistent with the world of the story.
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

            # 표지는 story_page가 없으므로 story에 직접 연결할 수도 있음
            # 하지만 기존 DB 구조를 유지하려면 page 0으로 저장하는 방식 가능:
            Illustrations.objects.create(
                story_page=None,
                story=story,
                image=cover_s3_path,
                prompt=cover_prompt,
                style=style
            )

            job.completed_pages = 1
            job.save(update_fields=["completed_pages"])

            # ----------------------------
            # 🎨 1) 본문 페이지 삽화 생성 (Loop)
            # ----------------------------
            for idx, page in enumerate(pages, start=1):
                page_prompt = f"""
            Create an illustration for page {page.page_number} of a children's storybook.
            The illustration MUST be {style_text}.

            Story context for coherence:
            {story_context}

            Page content:
            "{page.text}"

            Keep character appearance, colors, and atmosphere consistent with the cover and other pages.
            """

                page_result = client.images.generate(
                    model="gpt-image-1",
                    prompt=page_prompt,
                    size="1536x1024"
                )

                b64 = page_result.data[0].b64_json
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

                job.completed_pages = idx + 1  # +1 because cover already counted
                job.save(update_fields=["completed_pages"])

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
