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
from django.db import connection

from story.models import Story, StoryPage, Illustrations
from .models import IllustrationJob, IllustrationJobPage, ChatRoom
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

    try:
        style = story.illustration_style or "watercolor"

        style_map = {
            "watercolor": "in soft watercolor whimsical fantasy illustration style",
            "oil": "in warm classic oil painting fantasy style",
            "crayon": "in cute crayon-style whimsical illustration",
            "3d": "in stylized 3D fantasy cartoon illustration style"
        }
        style_text = style_map.get(style, style_map["watercolor"])

        pages = story.pages.all().order_by("page_number")

        safe_title = safe_filename(story.title)
        story_context = "\n".join([f"Page {p.page_number}: {p.text}" for p in pages])

        # =====================
        # COVER 생성
        # =====================
        cover_prompt = f"""
            Create a safe and friendly whimsical fantasy illustration for a story titled "{story.title}". 
            The illustration MUST be {style_text}.
            - Do NOT depict real children or minors.
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
        cover_s3_path = default_storage.save(cover_filename, ContentFile(cover_bytes))

        Illustrations.objects.create(
            story_page=None,
            story=story,
            image=cover_s3_path,
            prompt=cover_prompt,
            style=style
        )

        # COVER 상태 업데이트
        cover_status = job.page_status.get(page_number=0)
        cover_status.status = "SUCCESS"
        cover_status.save()

        job.completed_pages = 1
        job.save()

        # =====================
        # 페이지 삽화 생성 루프
        # =====================
        for idx, page in enumerate(pages, start=1):

            page_prompt = f"""
            Create a whimsical fantasy illustration for page {page.page_number}.
            MUST be {style_text}.
            - Do NOT depict real children.
            Story context:
            {story_context}
            """

            result = client.images.generate(
                model="gpt-image-1",
                prompt=page_prompt,
                size="1536x1024"
            )

            img_bytes = base64.b64decode(result.data[0].b64_json)

            filename = f"{safe_title}_p{page.page_number}_{uuid4().hex[:8]}.png"
            s3_path = default_storage.save(filename, ContentFile(img_bytes))

            Illustrations.objects.create(
                story=story,
                story_page=page,
                image=s3_path,
                prompt=page_prompt,
                style=style
            )

            # ===============================
            # 페이지 상태 업데이트
            # ===============================
            page_status = job.page_status.get(page_number=page.page_number)
            page_status.status = "SUCCESS"
            page_status.save()

            job.completed_pages = idx + 1
            job.save()

        job.status = "SUCCESS"
        job.finished_at = timezone.now()
        job.save()

    except Exception as e:
        import traceback
        traceback.print_exc()
        job.status = "FAILED"
        job.error_message = str(e)
        job.finished_at = timezone.now()
        job.save()



def run_single_page_job(job_id, page_number):
    job = IllustrationJob.objects.get(id=job_id)
    story = job.story

    job.status = "RUNNING"
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])

    try:
        style = story.illustration_style or "watercolor"

        style_map = {
            "watercolor": "in soft watercolor storybook illustration style",
            "oil": "in warm classic oil painting fairy-tale style",
            "crayon": "in cute crayon drawing style for toddlers",
            "3d": "in rich 3D Pixar-like digital art style"
        }
        style_text = style_map.get(style, style_map["watercolor"])

        # 페이지 가져오기
        page = StoryPage.objects.get(story=story, page_number=page_number)

        safe_title = safe_filename(story.title)

        page_prompt = f"""
        Re-create an illustration for page {page.page_number}.
        MUST be {style_text}.
        Page text: "{page.text}"
        """

        result = client.images.generate(
            model="gpt-image-1",
            prompt=page_prompt,
            size="1536x1024"
        )

        b64 = result.data[0].b64_json
        img_bytes = base64.b64decode(b64)

        filename = f"{safe_title}_regen_p{page.page_number}_{uuid4().hex[:8]}.png"
        file_obj = ContentFile(img_bytes)
        s3_path = default_storage.save(filename, file_obj)

        # 기존 삽화 덮어쓰기 or 새로 생성
        Illustrations.objects.create(
            story=story,
            story_page=page,
            image=s3_path,
            prompt=page_prompt,
            style=style
        )

        page_status = job.page_status.get(page_number=page_number)
        page_status.status = "SUCCESS"
        page_status.save()

        job.status = "SUCCESS"
        job.completed_pages = 1
        job.finished_at = timezone.now()
        job.save()

    except Exception as e:
        job.status = "FAILED"
        page_status = job.page_status.get(page_number=page_number)
        page_status.status = "FAILED"
        page_status.save()
        job.error_message = str(e)
        job.finished_at = timezone.now()
        job.save()


class GenerateIllustrationsView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        story_id = request.data.get("story_id")
        story = Story.objects.filter(id=story_id, user=request.user).first()

        if not story:
            return Response({"detail": "Story not found"}, status=404)

        pages = story.pages.all().order_by("page_number")
        total_pages = len(pages)

        if total_pages == 0:
            return Response({"detail": "No pages in story"}, status=400)

        job = IllustrationJob.objects.create(
            story=story,
            total_pages=total_pages + 1,
            status="PENDING",
        )

        IllustrationJobPage.objects.create(job=job, page_number=0, status="PENDING")
        for p in pages:
            IllustrationJobPage.objects.create(job=job, page_number=p.page_number, status="PENDING")

        # 실행
        run_illustration_job(job.id)

        # ===============================
        # 🔥 수정됨: job 상태 즉시 갱신
        # ===============================
        job.refresh_from_db()

        return Response({
            "job_id": job.id,
            "status": job.status   # 🔥 수정됨: 항상 최신 상태로 응답
        }, status=200)

    
class IllustrationJobStatusView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        job = get_object_or_404(IllustrationJob, id=job_id, story__user=request.user)
        story = job.story

        result_pages = []

        for p in job.page_status.all():

            # COVER
            if p.page_number == 0:
                illust = Illustrations.objects.filter(story=story, story_page=None).last()
            else:
                page_obj = story.pages.filter(page_number=p.page_number).first()
                illust = Illustrations.objects.filter(story_page=page_obj).last() if page_obj else None

            image_url = None
            if p.status == "SUCCESS" and illust:
                image_url = request.build_absolute_uri(illust.image.url)

            result_pages.append({
                "page_number": p.page_number,
                "type": "cover" if p.page_number == 0 else "page",
                "status": p.status,
                "image_url": image_url
            })

        return Response({
            "job_id": job.id,
            "status": job.status,
            "pages": result_pages
        })
    

class ReGenerateIllustrationView(views.APIView):
    """
    특정 페이지의 삽화를 '실제로' GPT 이미지 모델을 이용해 다시 생성하는 API
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        story_id = request.data.get("story_id")
        page = request.data.get("page")

        if not story_id or page is None:
            return Response(
                {"error": "story_id와 page는 필수 입력값입니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1) 스토리 확인
        try:
            story = Story.objects.get(id=story_id, user=request.user)
        except Story.DoesNotExist:
            return Response(
                {"error": "해당 스토리를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 2) 페이지 확인
        try:
            story_page = StoryPage.objects.get(story=story, page_number=page)
        except StoryPage.DoesNotExist:
            return Response(
                {"error": f"{page}페이지를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 3) 기존 삽화 제거
        Illustrations.objects.filter(story_page=story_page).delete()

        # 4) 스타일 적용
        style = story.illustration_style or "watercolor"
        style_map = {
            "watercolor": "in soft watercolor storybook illustration style",
            "oil": "in warm classic oil painting fairy-tale style",
            "crayon": "in cute crayon drawing style for toddlers",
            "3d": "in rich 3D Pixar-like digital art style"
        }
        style_text = style_map.get(style, style_map["watercolor"])

        # 5) Prompt 생성
        story_context = "\n".join([f"Page {p.page_number}: {p.text}"
                                   for p in story.pages.all().order_by("page_number")])

        page_prompt = f"""
        Re-generate an illustration for page {story_page.page_number}.
        The style MUST be {style_text}.
        Full Story Context:
        {story_context}
        Page text: "{story_page.text}"
        """

        # 6) GPT 이미지 생성
        try:
            result = client.images.generate(
                model="gpt-image-1",
                prompt=page_prompt,
                size="1536x1024"
            )
        except Exception as e:
            return Response(
                {"error": f"AI 이미지 생성 실패: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Base64 → 파일 변환
        b64 = result.data[0].b64_json
        img_bytes = base64.b64decode(b64)

        filename = f"story{story_id}_page{page}_regen_{uuid4().hex[:8]}.png"
        file_obj = ContentFile(img_bytes)

        # 7) S3 업로드
        s3_path = default_storage.save(filename, file_obj)

        # 8) 새로운 삽화 DB 등록
        illustration = Illustrations.objects.create(
            story=story,
            story_page=story_page,
            image=s3_path,
            prompt=page_prompt,
            style=style
        )

        # 9) 최종 응답
        return Response({
            "story_id": story_id,
            "page": page,
            "status": "SUCCESS",
            "new_image_url": request.build_absolute_uri(illustration.image.url)
        }, status=200)
    
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
                ExpiresIn=60 * 10  # 10분 유효
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
