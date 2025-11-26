from django.shortcuts import render
import os, json, base64, re, random, uuid, tempfile
from uuid import uuid4
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from django.conf import settings
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse
from django.db import connection

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.storage import default_storage

from rest_framework.response import Response
from rest_framework import views, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from dotenv import load_dotenv
from openai import OpenAI
import tiktoken

from .models import *
from .serializers import *
from story.models import Story, StoryPage, Illustrations
from story.serializers import *
from story.utils import split_into_pages

load_dotenv(settings.BASE_DIR/ ".env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

def safe_filename(s: str) -> str:
    return SAFE_FILENAME_RE.sub("_", s.strip())[:80] or "story"

def build_illustration_context(story):
    """
    삽화를 위한 전역 컨텍스트(캐릭터/분위기/페이지 요약)를 한 번만 생성해서
    Story.illustration_context에 캐싱하고, 이후에는 재사용한다.
    """
    # 이미 만들어둔 요약이 있으면 그대로 재사용
    if story.illustration_context:
        return story.illustration_context

    pages = story.pages.all().order_by("page_number")
    full_text = "\n".join([f"[Page {p.page_number}] {p.text}" for p in pages])

    system_msg = (
        "You are an assistant helping a children's book illustrator. "
        "Read the story and write a compact English summary that can be reused as a prompt context "
        "to keep characters and world consistent across all illustrations."
    )

    user_msg = f"""
    [Story Title]
    {story.title}

    [Full Story]
    {full_text}

    Please respond in the following structure (plain text, no JSON):

    1. Global style description: (3-5 sentences about overall mood, world, colors, etc.)
    2. Main characters: (bullet-like lines, each with name, age-range, key visual traits, personality)
    3. Background / atmosphere: (1 short paragraph)
    4. Per-page short prompts:
        - Page 1: (1-2 sentences describing the scene to draw)
        - Page 2: ...
        (only up to the number of pages given)
    """

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    )

    context_text = resp.choices[0].message.content.strip()

    story.illustration_context = context_text
    story.save(update_fields=["illustration_context"])

    return context_text


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
        base_dir = f"story_illustrations/{safe_title}"
        illustration_context = build_illustration_context(story)

        # =====================
        # COVER 생성
        # =====================
        cover_prompt = f"""
            Create a safe and friendly whimsical fantasy illustration for a story titled "{story.title}". 
            The illustration MUST be {style_text}.
            - Do NOT depict real children or minors.
            Story context:
            {illustration_context}
        """

        cover_result = client.images.generate(
            model="gpt-image-1-mini",
            prompt=cover_prompt,
            size="1536x1024"
        )
        cover_b64 = cover_result.data[0].b64_json
        cover_bytes = base64.b64decode(cover_b64)

        cover_filename = f"{safe_title}_cover_{uuid4().hex[:8]}.png"
        cover_path = f"{base_dir}/{cover_filename}"
        cover_s3_path = default_storage.save(cover_path, ContentFile(cover_bytes))

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
            Create a warm, child-safe fantasy illustration for page {page.page_number}.
            The style MUST be {style_text}.
            This is for a bedtime story for ages under 10.
            Absolutely no sexual content, no nudity, no graphic violence, and no self-harm.

            Global context (characters & world):
            {illustration_context}

            Focus on this page's scene:
            "{page.text[:400]}"
            """

            result = client.images.generate(
                model="gpt-image-1-mini",
                prompt=page_prompt,
                size="1536x1024"
            )

            img_bytes = base64.b64decode(result.data[0].b64_json)

            filename = f"{safe_title}_p{page.page_number}_{uuid4().hex[:8]}.png"
            s3_path = default_storage.save(f"{base_dir}/{filename}", ContentFile(img_bytes))

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
        base_dir = f"story_illustrations/{safe_title}"

        illustration_context = build_illustration_context(story)

        page_prompt = f"""
        Re-create a child-safe illustration for page {page.page_number}.
        The style MUST be {style_text}.
        This is for a children's story (ages under 10): absolutely no sexual content, no nudity,
        no graphic violence, and no self-harm.

        Global context (characters & world):
        {illustration_context}

        Focus on this page's scene:
        "{page.text[:400]}"
        """

        result = client.images.generate(
            model="gpt-image-1-mini",
            prompt=page_prompt,
            size="1536x1024"
        )

        b64 = result.data[0].b64_json
        img_bytes = base64.b64decode(b64)

        filename = f"{safe_title}_regen_p{page.page_number}_{uuid4().hex[:8]}.png"
        file_obj = ContentFile(img_bytes)
        s3_path = default_storage.save(f"{base_dir}/{filename}", file_obj)

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
        try:
            page = int(page)
        except ValueError:
            return Response(
                {"error": "page는 숫자여야 합니다."},
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

        safe_title = safe_filename(story.title)
        base_dir = f"story_illustrations/{safe_title}"

        # 5) Prompt 생성
        illustration_context = build_illustration_context(story)

        page_prompt = f"""
        Re-generate a child-safe illustration for page {story_page.page_number}.
        The style MUST be {style_text}.
        This is for a children's story (ages under 10): absolutely no sexual content,
        no nudity, no graphic violence, and no self-harm.

        Global context (characters & world):
        {illustration_context}

        Focus on this page's scene:
        "{story_page.text[:400]}"
        """

        # 6) GPT 이미지 생성
        try:
            result = client.images.generate(
                model="gpt-image-1-mini",
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

        filename = f"{safe_title}_page{page}_regen_{uuid4().hex[:8]}.png"
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

HARD_MIN_USER_TOKENS = 200
FINALIZE_SUFFIX = "이제 결말을 확장해도 될까?"

STORY_ENGINE_SYSTEM_PROMPT = r"""
너는 '명작 동화 결말 확장'을 위한 대화형 AI다.
사용자(아이)와의 대화를 통해 기존 동화의 결말 이후 이야기를 확장하기 위한 정보를 수집한다.
아래 규칙들을 반드시 지켜라.

[챗봇 질문 설계 규칙]
- 매 질문은 100토큰 이상 150토큰 이하로 풍부하고 구체적인 개방형 질문으로 할 것.
- 전체 질문 및 답변은 3문장 이내로 할 것.
- 질문을 할 때는 한 차례에 하나의 질문만 할 것.
- 반드시 결말 시점 이후 확장에 대한 질문을 할 것. (“결말 이후에 ~”, “그 다음엔 ~”)
- 예/아니오 질문 금지. “만약 ~라면?”, “어떻게 될까?”, “무슨 일이 일어날까?”
- 아이 답이 모호하면 사건/배경/감정/의도 등 구체화 후속질문으로 보완.
- 이미 물어본 질문 반복 금지.
- 질문 자체에는 "이제 결말을 확장해도 될까?"를 절대 붙이지 말 것.
- 질문 및 답변 생성 이후 생성된 글이 150토큰 이하인지 확인한 후 150토큰을 넘는다면 답변 재생성할 것.

[서사 생성 프로세스]
① Story Forming
② Story Illustrating
③ Story Weaving

[대화 종료]
- 충분한 정보가 모였다고 판단되면, 사용자의 마지막 답변에 대한 '대답'을 할 때만 1~2단어의 짧은 반응 + "이제 결말을 확장해도 될까?" 를 포함한다.
- 이때 can_finalize=true 상태를 확정한다.
- can_finalize=true 이후 사용자가 "더 대화하기"를 누르면, 질문이 아니라 '대답'일 때마다 위 문구를 같은 규칙으로 계속 붙인다.

출력은 자연스러운 한국어 아동 친화적 말투.
"""

# 동화의 톤을 위해 S3에서 동화 더미데이터 불러오기
def load_tone_dummy_text():
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    key = "media/tone_dummy/story_tone.txt"

    # S3
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", None),
            aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", None),
            region_name=getattr(settings, "AWS_S3_REGION_NAME", None),
        )
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode("utf-8")
    except ClientError:
        pass

    return ""

def get_or_create_chat(user, story, chat_id=None):
    if chat_id:
        chat = ExtendChat.objects.filter(id=chat_id, user=user, story=story).first()
        if chat:
            return chat, False

    chat = ExtendChat.objects.create(
        user=user,
        story=story,
        can_finalize=False,
        created_at=timezone.now(),
        updated_at=timezone.now(),
        user_token_count=0,
    )
    return chat, True

def load_messages(chat):
    qs = chat.messages.order_by("order")
    return [{"role": m.role, "content": m.content} for m in qs]

def save_message(chat, role, content, input_modality=None):
    last = chat.messages.order_by("-order").first()
    next_order = (last.order + 1) if last else 1

    ExtendMessage.objects.create(
        chat=chat,
        role=role,
        content=content,
        input_modality=input_modality,
        order=next_order
    )
    chat.updated_at = timezone.now()
    chat.save()

FINALIZE_CHECK_PROMPT = r"""
너는 결말 확장 가능 여부를 판단하는 심사관이다.

입력은 '사용자(user) 발화 목록'만 주어진다.
assistant의 질문/답변은 절대 고려하지 마라.

판정 기준:
- 사용자가 결말 이후에 대해 충분히 구체적으로 상상/설명했는가?
- 등장인물, 사건, 배경, 감정/목표 중 2가지 이상이 실제로 언급되었는가?
- 단답/짧은 반응 위주면 false.

JSON 한 줄:
{"can_finalize": true/false, "reason": "짧은 이유"}
"""
def user_only(messages):
    return [m for m in messages if m.get("role") == "user"]

def check_can_finalize(messages):
    user_msgs = [m for m in messages if m.get("role") == "user"]

    try:
        resp = client.responses.create(
            model="gpt-5.1",
            input=[
                {"role": "system", "content": FINALIZE_CHECK_PROMPT},
                {"role": "user", "content": json.dumps(user_msgs, ensure_ascii=False)}
            ],
            temperature=0.2,
            max_output_tokens=120,
        )
        data = json.loads(resp.output_text.strip())
        return bool(data.get("can_finalize")), data.get("reason", "")
    except Exception:
        return False, "판정 실패"
    
QUESTION_CHECK_PROMPT = r"""
다음 텍스트가 '사용자에게 던지는 질문'인가요?
질문이면 true, 아니면 false.
JSON 한 줄:
{"is_question": true/false}
"""

def is_question_text(text: str) -> bool:
    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": QUESTION_CHECK_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0,
            max_output_tokens=100,
        )
        data = json.loads(resp.output_text.strip())
        return bool(data.get("is_question"))
    except Exception:
        t = text.strip()
        return ("?" in t[-3:]) or t.endswith(("까", "니", "나요", "까요", "할래", "어때"))

def count_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))

OPENING_PROMPT = r"""
너는 아이에게 '결말 확장 대화'를 시작하는 친근한 오프닝을 만드는 도우미다.

요구사항:
- 반드시 원작 동화의 마지막 결말 이후를 떠올리게 하는 말이 포함될 것.
- 아이가 바로 상상해서 말할 수 있도록 결말 이후 질문 1개를 포함할 것.
- 2~3문장, 아동 친화적, 자연스러운 한국어.
- 특정 캐릭터/사건 언급은 '주어진 동화 내용에 실제로 등장하는 것만' 사용.
- 출력은 오프닝 문장 텍스트만.

동화 제목과 내용이 주어진다.
"""

def generate_opening(story: Story) -> str:
    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": OPENING_PROMPT},
                {"role": "user", "content": f"동화 제목: {story.title}\n동화 내용:\n{story.content}"}
            ],
            temperature=0.8,
            max_output_tokens=180,
        )
        text = resp.output_text.strip()
        return text or f"<{story.title}> 재미있었니? 결말 이후엔 어떤 일이 일어날지 상상해볼까?"
    except Exception:
        return f"<{story.title}> 재미있었니? 결말 이후엔 어떤 일이 일어날지 상상해볼까?"

class ExtendChatStreamView(views.APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)

        chat_id = request.data.get("chat_id")
        user_text = (request.data.get("user_message") or "").strip()
        modality = request.data.get("input_modality") or "text"
        action = request.data.get("action")

        if chat_id and action == "continue" and not user_text:
            chat, _ = get_or_create_chat(request.user, story, chat_id=chat_id)

            messages = load_messages(chat)
            tone_dummy = load_tone_dummy_text()

            static_prefix = [
                {"role": "system", "content": STORY_ENGINE_SYSTEM_PROMPT},
                {"role": "system", "content": f"원작 동화 제목: {story.title}\n원작 동화 내용(결말 포함):\n{story.content}"},
            ]
            if tone_dummy.strip():
                static_prefix.append({"role": "system", "content": f"[톤 참고 더미 동화]\n{tone_dummy}"})

            continue_directive = {
                "role": "system",
                "content": "지금은 사용자가 '더 대화하기'를 눌렀다. 반드시 새 질문을 1개만 하라."
            }

            resp = client.responses.create(
                model="gpt-5.1",
                input=static_prefix + messages + [continue_directive],
                temperature=0.8,
                max_output_tokens=200,
                stream=False,
            )
            assistant_text = resp.output_text.strip()

            if not is_question_text(assistant_text):
                assistant_text = (assistant_text + "\n\n그 다음엔 어떤 일이 더 일어날까?").strip()

            assistant_text = f"그럼 조금 더 이야기해보자!\n\n{assistant_text}".strip()

            save_message(chat, "assistant", assistant_text)

            return Response({
                "text": assistant_text,
                "chat_id": str(chat.id),
                "can_finalize": False,
                "reason": "continue_question",
                "user_token_count": chat.user_token_count
            }, status=200)

        if not chat_id and not user_text:
            chat, _ = get_or_create_chat(request.user, story, chat_id=None)

            opening = generate_opening(story)   # 동화 커스터마이징 오프닝
            save_message(chat, "assistant", opening)

            return Response({
                "text": opening,
                "chat_id": str(chat.id),
                "can_finalize": False,
                "reason": "first_opening",
                "user_token_count": getattr(chat, "user_token_count", 0)
            }, status=200)

        if not user_text:
            return Response({"detail": "user_message required"}, status=400)

        chat, _ = get_or_create_chat(request.user, story, chat_id=chat_id)

        token_count = count_tokens(user_text)
        chat.user_token_count = getattr(chat, "user_token_count", 0) + token_count
        chat.save()

        # (1) user 메시지 DB 저장
        save_message(chat, "user", user_text, input_modality=modality)

        # (2) 대화 로그 로딩
        messages = load_messages(chat)
        can_finalize = chat.can_finalize

        # (3) 톤 더미 로딩 (정적 prefix에 포함되므로 항상 같은 내용이어야 캐시됨)
        tone_dummy = load_tone_dummy_text()

        # (4) 정적 prefix를 항상 동일한 순서/형태로 구성
        #     (OpenAI Prompt Caching은 같은 prefix 반복 시 자동으로 캐시 적용) :contentReference[oaicite:1]{index=1}
        static_prefix = [
            {"role": "system", "content": STORY_ENGINE_SYSTEM_PROMPT},
            {"role": "system", "content": f"원작 동화 제목: {story.title}\n원작 동화 내용(결말 포함):\n{story.content}"},
        ]
        if tone_dummy.strip():
            static_prefix.append({"role": "system", "content": f"[톤 참고 더미 동화]\n{tone_dummy}"})

        model_input = static_prefix + messages

        stream_flag = modality == "voice"
        qp = request.query_params.get("stream")
        if qp is not None:
            stream_flag = qp.lower() == "true"

        # (6) 텍스트 모드일 때 → 풀 문장 응답(JSON)
        if not stream_flag:
            resp = client.responses.create(
                model="gpt-5.1",
                input=model_input,
                temperature=0.8,
                max_output_tokens=200,
                stream=False,
            )

            assistant_text = resp.output_text.strip()

            if chat.user_token_count < HARD_MIN_USER_TOKENS:
                can_finalize = False
                reason = f"user_tokens<{HARD_MIN_USER_TOKENS}"
            else:
                if not can_finalize:
                    user_msgs = user_only(messages)
                    can_finalize, reason = check_can_finalize(user_msgs)
                else:
                    reason = "already true"

            is_q = is_question_text(assistant_text)
            if can_finalize:
                if is_q:
                    assistant_text = f"좋아!\n\n{FINALIZE_SUFFIX}"
                else:
                    if FINALIZE_SUFFIX not in assistant_text:
                        assistant_text = (assistant_text + "\n\n" + FINALIZE_SUFFIX).strip()

            save_message(chat, "assistant", assistant_text)

            if can_finalize and not chat.can_finalize:
                chat.can_finalize = True
                chat.save()

            return Response({
                "text": assistant_text,
                "chat_id": str(chat.id),
                "can_finalize": can_finalize,
                "reason": reason,
                "user_token_count": chat.user_token_count
            }, status=200)

        # (7) 음성 모드 → 기존 SSE(chunk) 스트리밍
        def sse_gen():
            nonlocal can_finalize, messages
            assistant_accum = []

            try:
                stream = client.responses.create(
                    model="gpt-5.1",
                    input=model_input,
                    temperature=0.8,
                    max_output_tokens=200,
                    stream=True,
                )

                for event in stream:
                    if event.type == "response.output_text.delta":
                        delta = event.delta or ""
                        assistant_accum.append(delta)
                        yield (
                            "data: "
                            + json.dumps({"type": "chunk", "text": delta}, ensure_ascii=False)
                            + "\n\n"
                        )

                assistant_text = "".join(assistant_accum).strip()

                # (A) 하드 게이트
                if chat.user_token_count < HARD_MIN_USER_TOKENS:
                    can_finalize = False
                    reason = f"user_tokens<{HARD_MIN_USER_TOKENS}"
                else:
                    # (B) 200 이상일 때만 판정(user_only)
                    if not can_finalize:
                        user_msgs = user_only(messages)
                        can_finalize, reason = check_can_finalize(user_msgs)
                    else:
                        reason = "already true"

                # (C) true면 suffix 강제 + 질문 제거
                is_q = is_question_text(assistant_text)
                if can_finalize:
                    if is_q:
                        assistant_text = f"좋아!\n\n{FINALIZE_SUFFIX}"
                    else:
                        if FINALIZE_SUFFIX not in assistant_text:
                            assistant_text = (assistant_text + "\n\n" + FINALIZE_SUFFIX).strip()

                save_message(chat, "assistant", assistant_text)

                if can_finalize and not chat.can_finalize:
                    chat.can_finalize = True
                    chat.save()

                # meta 이벤트
                yield (
                    "data: "
                    + json.dumps({
                        "type": "meta",
                        "chat_id": str(chat.id),
                        "can_finalize": can_finalize,
                        "reason": reason,
                        "user_token_count": chat.user_token_count
                    }, ensure_ascii=False)
                    + "\n\n"
                )

            except Exception as e:
                yield (
                    "data: "
                    + json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
                    + "\n\n"
                )

        return StreamingHttpResponse(sse_gen(), content_type="text/event-stream")

def delete_chat_audio_folder(chat_id):
    """
    default_storage에서 extendchat/<chat_id>/ 아래의 파일들을 모두 삭제.
    (S3든 로컬이든 Storage API 기준으로 동작)
    """
    base_dir = f"extendchat/{chat_id}"

    if not default_storage.exists(base_dir):
        return

    def _delete_dir(path):
        # dirs: 하위 폴더 목록, files: 해당 경로의 파일 목록
        dirs, files = default_storage.listdir(path)

        # 파일 삭제
        for name in files:
            file_path = f"{path}/{name}"
            if default_storage.exists(file_path):
                default_storage.delete(file_path)

        for d in dirs:
            _delete_dir(f"{path}/{d}")

    _delete_dir(base_dir)


class VoiceExtendChatView(views.APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)

        chat_id = request.data.get("chat_id")
        voice = request.data.get("voice") or "alloy"  # TTS 목소리 선택 (옵션)
        audio = request.FILES.get("audio")
        if not audio:
            return Response({"detail": "audio file required"}, status=400)

        # 1) STT (whisper-1 + 임시 파일)
        try:
            suffix = Path(audio.name).suffix or ".mp3"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                for chunk in audio.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            with open(tmp_path, "rb") as f:
                stt_resp = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                )
            os.remove(tmp_path)

            user_text = (stt_resp.text or "").strip()
            if not user_text:
                return Response({"detail": "empty transcript"}, status=400)

        except Exception as e:
            return Response({"detail": f"STT failed: {e}"}, status=500)

        # 2) ExtendChat 로직 (텍스트 기반과 동일)
        chat, _ = get_or_create_chat(request.user, story, chat_id=chat_id)

        token_count = count_tokens(user_text)
        chat.user_token_count = getattr(chat, "user_token_count", 0) + token_count
        chat.save()

        save_message(chat, "user", user_text, input_modality="voice")

        messages = load_messages(chat)
        can_finalize = chat.can_finalize

        tone_dummy = load_tone_dummy_text()
        static_prefix = [
            {"role": "system", "content": STORY_ENGINE_SYSTEM_PROMPT},
            {
                "role": "system",
                "content": f"원작 동화 제목: {story.title}\n원작 동화 내용(결말 포함):\n{story.content}"
            },
        ]
        if tone_dummy.strip():
            static_prefix.append(
                {"role": "system", "content": f"[톤 참고 더미 동화]\n{tone_dummy}"}
            )

        model_input = static_prefix + messages

        try:
            resp = client.responses.create(
                model="gpt-5.1",
                input=model_input,
                temperature=0.8,
                max_output_tokens=200,
                stream=False,
            )
            assistant_text = resp.output_text.strip()
        except Exception as e:
            return Response({"detail": f"Chat failed: {e}"}, status=500)

        if chat.user_token_count < HARD_MIN_USER_TOKENS:
            can_finalize = False
            reason = f"user_tokens<{HARD_MIN_USER_TOKENS}"
        else:
            if not can_finalize:
                user_msgs = user_only(messages)
                can_finalize, reason = check_can_finalize(user_msgs)
            else:
                reason = "already true"

        is_q = is_question_text(assistant_text)
        if can_finalize:
            if is_q:
                assistant_text = f"좋아!\n\n{FINALIZE_SUFFIX}"
            else:
                if FINALIZE_SUFFIX not in assistant_text:
                    assistant_text = (assistant_text + "\n\n" + FINALIZE_SUFFIX).strip()

        save_message(chat, "assistant", assistant_text)

        if can_finalize and not chat.can_finalize:
            chat.can_finalize = True
            chat.save()

        # 3) TTS (assistant_text → mp3 → URL)
        audio_url = None
        try:
            audio_url = generate_tts_audio_http(
                text=assistant_text,
                voice=voice,
                chat_id=str(chat.id),
            )
        except Exception as e:
            reason = f"{reason} (TTS failed: {e})"
            audio_url = None

        return Response({
            "text": assistant_text,          # AI 텍스트 답변
            "user_text": user_text,          # STT 결과 (아이 발화)
            "audio_url": audio_url,          # mp3 경로 (없을 수도 있음)
            "chat_id": str(chat.id),
            "can_finalize": can_finalize,
            "reason": reason,
            "user_token_count": chat.user_token_count
        }, status=200)

class STTView(views.APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        audio = request.FILES.get("audio")
        if not audio:
            return Response({"detail": "audio file required"}, status=400)

        try:
            print("=== STT DEBUG ===")
            print("name:", audio.name)
            print("size:", audio.size)
            print("type:", type(audio))
            print("content_type:", audio.content_type)

            # 1) 확장자 추출 (없으면 기본 .mp3)
            suffix = Path(audio.name).suffix or ".mp3"

            # 2) 임시파일에 저장
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                for chunk in audio.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            # 3) whisper-1 호출 (SDK가 100% 읽을 수 있는 “진짜 파일”로)
            with open(tmp_path, "rb") as f:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f
                )

            # 4) 정리
            os.remove(tmp_path)

            return Response({"text": transcript.text}, status=200)

        except Exception as e:
            return Response({"detail": f"STT failed: {e}"}, status=500)

import requests
def generate_tts_audio_http(text: str, voice: str = "alloy", chat_id: str | None = None) -> str:
    """
    OpenAI TTS를 SDK 안 쓰고 HTTP로 직접 호출해서
    default_storage에 저장 후 URL을 반환한다.
    - chat_id가 있으면: extendchat/<chat_id>/ 아래에 저장
    - chat_id가 없으면: tts/ 아래에 저장
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise Exception("OPENAI_API_KEY not set in settings")

    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o-mini-tts",
        "voice": voice,
        "input": text,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"OpenAI TTS HTTP error {resp.status_code}: {resp.text}")

    audio_bytes = resp.content  # 여기에 mp3 바이너리 그대로 옴

    # 저장 경로: extendchat/<chat_id>/ or tts/
    if chat_id:
        folder = f"extendchat/{chat_id}"
    else:
        folder = "tts"

    filename = f"{folder}/{uuid.uuid4()}.mp3"
    saved_path = default_storage.save(filename, ContentFile(audio_bytes))
    audio_url = default_storage.url(saved_path)
    return audio_url

class TTSView(views.APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request):
        text = (request.data.get("text") or "").strip()
        voice = request.data.get("voice") or "alloy"
        if not text:
            return Response({"detail": "text required"}, status=400)

        try:
            audio_url = generate_tts_audio_http(
                text=text,
                voice=voice,
                chat_id=None,
            )
            return Response({"audio_url": audio_url}, status=200)

        except Exception as e:
            return Response({"detail": f"TTS failed: {e}"}, status=500)

EXTEND_STORY_PROMPT = r"""
너는 명작 동화의 결말을 확장해 새 동화를 만드는 작가형 AI다.
입력 대화 로그와 원작 동화를 바탕으로 '결말 이후 확장 동화'를 완성하라.

- 드라마티카/질문 규칙을 최대한 반영.
- 결말 이후 사건 확장.
- 아동 친화적 톤.
- 3막(Signpost/Journey)을 갖춘 이야기.
- 확장 동화 텍스트에서 제목, '1막:', '2막:', '3막:'과 같은 불필요한 단어 및 문장부호는 생략.

출력 JSON:
{
    "title": "확장 동화 제목",
    "content": "확장 동화 전체 텍스트",
    "runtime": "선택",
    "age_group": "선택",
    "morals": ["선택"]
}
"""

class ExtendStoryCreateView(views.APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, story_id):
        original = Story.objects.filter(id=story_id).first()
        if not original:
            return Response({"detail": "Story not found"}, status=404)

        chat_id = request.data.get("chat_id")
        if not chat_id:
            return Response({"detail": "chat_id required"}, status=400)

        chat = ExtendChat.objects.filter(id=chat_id, user=request.user, story=original).first()
        if not chat:
            return Response({"detail": "Chat not found"}, status=404)

        messages = load_messages(chat)
        tone_dummy = load_tone_dummy_text()

        static_prefix = [
            {"role": "system", "content": EXTEND_STORY_PROMPT},
            {"role": "system", "content": f"원작 동화 제목: {original.title}\n원작 동화 내용(결말 포함):\n{original.content}"},
        ]
        if tone_dummy.strip():
            static_prefix.append({"role": "system", "content": f"[톤 참고 더미 동화]\n{tone_dummy}"})

        try:
            resp = client.responses.create(
                model="gpt-4.1-mini",
                input=static_prefix + [{"role": "user", "content": json.dumps(messages, ensure_ascii=False)}],
                temperature=0.9,
                max_output_tokens=2000,
            )
            data = json.loads(resp.output_text.strip())
        except Exception as e:
            return Response({"detail": f"Extend generation failed: {e}"}, status=500)

        ext_title = data.get("title") or f"{original.title} (확장동화)"
        ext_content = (data.get("content") or "").strip()
        if not ext_content:
            return Response({"detail": "Empty extended content"}, status=500)

        runtime = data.get("runtime") or original.runtime
        age_group = data.get("age_group") or original.age_group

        combined_content = (
            (original.content or "").strip()
            + "\n\n"
            + ext_content
        ).strip()

        new_story = Story.objects.create(
            user=request.user,
            child=original.child,
            voice=original.voice,
            title=ext_title,
            author=request.user.username,
            content=combined_content,
            category="extended",
            runtime=runtime,
            age_group=age_group,
            illustration_style=request.data.get("illustration_style") or original.illustration_style
        )

        pages = split_into_pages(combined_content)
        for idx, page_text in enumerate(pages, start=1):
            StoryPage.objects.create(
                story=new_story,
                page_number=idx,
                text=page_text
            )

        new_story.page_count = len(pages)
        new_story.save()

        delete_chat_audio_folder(chat_id)

        return Response(
            {"extended_story": StorySerializer(new_story).data},
            status=status.HTTP_201_CREATED
        )
    
class ContinueFromView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, extended_id, original_id):
        extended = Story.objects.filter(id=extended_id, category="extended").first()
        original = Story.objects.filter(id=original_id).first()
        if not extended or not original:
            return Response({"detail": "Story not found"}, status=404)

        return Response(
            {"continue_from_page": (original.page_count or 0) + 1},
            status=200
        )