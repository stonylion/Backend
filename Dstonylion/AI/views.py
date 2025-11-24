from django.shortcuts import render
import os, json, base64, re, random, uuid
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError

from django.conf import settings
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from rest_framework.response import Response
from rest_framework import views, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from dotenv import load_dotenv
from openai import OpenAI

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
        
STORY_ENGINE_SYSTEM_PROMPT = r"""
너는 '명작 동화 결말 확장'을 위한 대화형 AI다.
사용자(아이)와의 대화를 통해 기존 동화의 결말 이후 이야기를 확장하기 위한 정보를 수집한다.
아래 규칙들을 반드시 지켜라.

[챗봇 질문 설계 규칙]
- 매 질문은 100토큰 이상이 생성될 정도로 풍부하고 구체적인 개방형 질문으로 할 것.
- 반드시 결말 시점 이후 확장에 대한 질문을 할 것. (“결말 이후에 ~”, “그 다음엔 ~”)
- 예/아니오 질문 금지. “만약 ~라면?”, “어떻게 될까?”, “무슨 일이 일어날까?”
- 아이 답이 모호하면 사건/배경/감정/의도 등 구체화 후속질문으로 보완.
- 이미 물어본 질문 반복 금지.
- 질문 자체에는 "이제 결말을 확장해도 될까?"를 절대 붙이지 말 것.

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
너는 대화 로그를 보고 결말 확장에 필요한 정보가 충분한지 판단하는 심사관이다.
JSON 한 줄:
{"can_finalize": true/false, "reason": "짧은 이유"}
"""

def check_can_finalize(messages):
    try:
        resp = client.responses.create(
            model="gpt-5.1",
            input=[
                {"role": "system", "content": FINALIZE_CHECK_PROMPT},
                {"role": "user", "content": json.dumps(messages, ensure_ascii=False)}
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
            model="gpt-5 nano",
            input=[
                {"role": "system", "content": QUESTION_CHECK_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0,
            max_output_tokens=20,
        )
        data = json.loads(resp.output_text.strip())
        return bool(data.get("is_question"))
    except Exception:
        t = text.strip()
        return ("?" in t[-3:]) or t.endswith(("까", "니", "나요", "까요", "할래", "어때"))

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

        if not user_text:
            return Response({"detail": "user_message required"}, status=400)

        chat, _ = get_or_create_chat(request.user, story, chat_id=chat_id)

        # (1) user 메시지 DB 저장
        save_message(chat, "user", user_text, input_modality=modality)

        # (2) 대화 로그 로딩
        messages = load_messages(chat)
        can_finalize = chat.can_finalize

        # (3) 톤 더미 로딩 (정적 prefix에 포함되므로 항상 같은 내용이어야 캐시됨)
        tone_dummy = load_tone_dummy_text()

        # (4) ✅ 정적 prefix를 항상 동일한 순서/형태로 구성
        #     (OpenAI Prompt Caching은 같은 prefix 반복 시 자동으로 캐시 적용) :contentReference[oaicite:1]{index=1}
        static_prefix = [
            {"role": "system", "content": STORY_ENGINE_SYSTEM_PROMPT},
            {"role": "system", "content": f"원작 동화 제목: {story.title}\n원작 동화 내용(결말 포함):\n{story.content}"},
        ]
        if tone_dummy.strip():
            static_prefix.append({"role": "system", "content": f"[톤 참고 더미 동화]\n{tone_dummy}"})

        model_input = static_prefix + messages

        def sse_gen():
            nonlocal can_finalize, messages
            assistant_accum = []

            try:
                stream = client.responses.create(
                    model="gpt-5.1",
                    input=model_input,
                    temperature=0.8,
                    max_output_tokens=700,
                    stream=True,
                )

                # chunk 스트리밍
                for event in stream:
                    if event.type == "response.output_text.delta":
                        delta = event.delta or ""
                        assistant_accum.append(delta)
                        yield f"data: {json.dumps({'type':'chunk','text':delta}, ensure_ascii=False)}\n\n"

                assistant_text = "".join(assistant_accum).strip()

                # can_finalize 사후 판정 (false일 때만)
                if not can_finalize:
                    can_finalize, reason = check_can_finalize(
                        messages + [{"role": "assistant", "content": assistant_text}]
                    )
                else:
                    reason = "already true"

                # 질문/대답 구분 후 문구 붙이기
                suffix = "이제 결말을 확장해도 될까?"
                is_question = is_question_text(assistant_text)

                if can_finalize and (not is_question):
                    if suffix not in assistant_text:
                        assistant_text = (assistant_text + "\n\n" + suffix).strip()

                # assistant 메시지 DB 저장
                save_message(chat, "assistant", assistant_text)

                # can_finalize DB 반영
                if can_finalize and not chat.can_finalize:
                    chat.can_finalize = True
                    chat.save()

                yield f"data: {json.dumps({'type':'meta','chat_id':str(chat.id),'can_finalize':can_finalize,'reason':reason}, ensure_ascii=False)}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'type':'error','message':str(e)}, ensure_ascii=False)}\n\n"

        return StreamingHttpResponse(sse_gen(), content_type="text/event-stream")
    
class STTView(views.APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        audio = request.FILES.get("audio")
        if not audio:
            return Response({"detail": "audio file required"}, status=400)

        try:
            transcript = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio
            )
            return Response({"text": transcript.text}, status=200)
        except Exception as e:
            return Response({"detail": f"STT failed: {e}"}, status=500)
        
class TTSView(views.APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request):
        text = (request.data.get("text") or "").strip()
        voice = request.data.get("voice") or "alloy"
        if not text:
            return Response({"detail": "text required"}, status=400)

        try:
            audio_resp = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=voice,
                input=text,
                format="mp3",
            )
            audio_bytes = audio_resp.read()

            filename = f"tts/{uuid.uuid4()}.mp3"
            saved_path = default_storage.save(filename, ContentFile(audio_bytes))
            audio_url = default_storage.url(saved_path)

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

        conv_id = request.data.get("conversation_id")
        if not conv_id:
            return Response({"detail": "conversation_id required"}, status=400)

        conv = ExtendChat.objects.filter(id=conv_id, user=request.user, story=original).first()
        if not conv:
            return Response({"detail": "Conversation not found"}, status=404)

        messages = load_messages(conv)
        tone_dummy = load_tone_dummy_text()

        static_prefix = [
            {"role": "system", "content": EXTEND_STORY_PROMPT},
            {"role": "system", "content": f"원작 동화 제목: {original.title}\n원작 동화 내용(결말 포함):\n{original.content}"},
        ]
        if tone_dummy.strip():
            static_prefix.append({"role": "system", "content": f"[톤 참고 더미 동화]\n{tone_dummy}"})

        try:
            resp = client.responses.create(
                model="gpt-5 nano",
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

        new_story = Story.objects.create(
            user=request.user,
            child=original.child,
            voice=original.voice,
            title=ext_title,
            author=request.user.username,
            content=ext_content,
            category="extended",
            runtime=runtime,
            age_group=age_group,
            illustration_style=request.data.get("illustration_style") or original.illustration_style
        )

        pages = split_into_pages(ext_content)
        for idx, page_text in enumerate(pages, start=1):
            StoryPage.objects.create(
                story=new_story,
                page_number=idx,
                text=page_text
            )

        new_story.page_count = len(pages)
        new_story.save()

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