import redis, random, os, json, re, tempfile
import openai
from openai import OpenAI
from pathlib import Path
from django.conf import settings
from django.core.files import File
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from .models import *
from .serializers import *
from mylibrary.models import *
from accounts.models import ClonedVoice
from django.core.files.storage import default_storage
from rest_framework import viewsets, status
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from story.utils import split_into_pages
from dotenv import load_dotenv
from django.utils.text import slugify

from story.services.language_analysis import calculate_ndw_for_month

from story.services.personality_engine import (
    predict_personality_with_adjustment,
)
from story.services.personality_report import generate_personality_report

load_dotenv(settings.BASE_DIR/ ".env")
# openai.api_key = os.getenv("OPENAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

User = get_user_model()

#분량, 연령대 선택
class StoryOptionSaveView(APIView):
    def post(self, request):
        runtime = request.data.get("runtime")
        age_group = request.data.get("age_group")

        valid_runtime = ["0-3분", "3-7분", "7-10분"]
        valid_age = ["0-3세", "4-6세", "7-12세"]

        if not runtime or not age_group:
            return Response(
                {"error": "필수 옵션이 누락되었습니다. runtime와 age_group를 모두 선택해주세요."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if runtime not in valid_runtime or age_group not in valid_age:
            return Response(
                {"error": "잘못된 동화 옵션입니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        redis_client = redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            decode_responses=True,
            ssl=True, 
        )
        redis_client.hset(f"story_option:{request.user.id}", mapping={"runtime": runtime, "age_group": age_group})

        return Response({"next": "/story/record/"}, status=status.HTTP_200_OK)

def append_draft(user_id, new_text):
    redis_client = redis.StrictRedis(
        host=getattr(settings, "REDIS_HOST", "localhost"),
        port=getattr(settings, "REDIS_PORT", 6379),
        db=0,
        decode_responses=True,
        ssl=False,
    )

    key = f"story_draft:{user_id}"
    existing = redis_client.get(key) or ""

    # 기존 draft 뒤에 자연스럽게 이어 붙이기
    if existing:
        updated = existing.rstrip() + " " + new_text.strip()
    else:
        updated = new_text.strip()

    redis_client.set(key, updated)
    return updated

class StoryDraftAudioAppendView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        audio = request.FILES.get("audio")
        if not audio:
            return Response({"error": "audio 파일이 필요합니다."}, status=400)

        # 1) 파일 임시 저장
        suffix = Path(audio.name).suffix or ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            for chunk in audio.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        # 2) Whisper-1 호출
        try:
            with open(tmp_path, "rb") as f:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f
                )
                text = transcript.text.strip()
        except Exception as e:
            return Response({"error": f"STT 실패: {str(e)}"}, status=500)

        # 3) Redis draft에 append
        redis_client = redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            decode_responses=True,
        )

        key = f"story_draft:{request.user.id}"
        existing = redis_client.get(key) or ""

        updated = (existing + " " + text).strip()

        redis_client.set(key, updated)

        return Response({
            "message": "음성이 변환되어 draft에 추가되었습니다.",
            "recognized_text": text,
            "draft": updated
        }, status=200)

class StoryDraftUpdateView(APIView):
    """
    사용자가 텍스트 입력으로 최종 입력한 내용을 Redis에 저장하는 API
    POST /api/story/draft/
    """
    permission_classes = [IsAuthenticated]

    '''def post(self, request):
        text = request.data.get("text")

        if not text:
            return Response(
                {"error": "text는 필수 항목입니다."},
                status=400
            )

        # Redis 연결
        redis_client = redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            decode_responses=True,
            ssl=False, 
        )

        redis_key = f"story_draft:{request.user.id}"

        # 최종 텍스트 저장
        redis_client.set(redis_key, text)

        return Response(
            {"message": "draft 업데이트 완료되었습니다."},
            status=200
        )'''
    
    def put(self, request):
        text = request.data.get("text", "").strip()

        if text is None:
            return Response({"error": "text는 필수 항목입니다."}, status=400)

        redis_client = redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            decode_responses=True,
        )

        redis_client.set(f"story_draft:{request.user.id}", text)

        return Response({
            "message": "Draft 전체가 저장되었습니다.",
            "draft": text
        }, status=200)
    
    def get(self, request):
        redis_client = redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            decode_responses=True,
            ssl=False,
        )
        draft = redis_client.get(f"story_draft:{request.user.id}") or ""
        return Response({"draft": draft}, status=200)


DEFAULT_MORALS = [
    {"key": "family", "name": "가족"},
    {"key": "gratitude", "name": "감사"},
    {"key": "empathy", "name": "공감"},
    {"key": "sharing", "name": "나눔"},
    {"key": "effort", "name": "노력"},
    {"key": "diversity", "name": "다양성"},
    {"key": "love", "name": "사랑"},
    {"key": "life", "name": "생명"},
    {"key": "trust", "name": "신뢰"},
    {"key": "courage", "name": "용기"},
    {"key": "friendship", "name": "우정"},
    {"key": "honesty", "name": "정직"},
    {"key": "respect", "name": "존중"},
    {"key": "temperance", "name": "절제"},
    {"key": "responsibility", "name": "책임감"},
    {"key": "hope", "name": "희망"},
]

DEFAULT_MORAL_KEYS = [m["key"] for m in DEFAULT_MORALS]

class RecommendMoralView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # 1. 요청 데이터 검증
        text = request.data.get("text", "").strip()
        if not text:
            return Response({"error": "text는 필수 항목입니다."}, status=400)

        if len(text) < 20:
            return Response({"error": "스토리 내용이 너무 짧아 추천할 수 없습니다."}, status=400)

        # 2. OpenAI 프롬프트 구성
        prompt = f"""
        아래는 사용자가 작성한 동화 내용입니다.

        ---
        {text}
        ---

        위 내용을 읽고 '새로운 교훈 키워드'를 추천해주세요.

        조건:
        - 아래 DEFAULT_MORALS 목록에 포함되지 않은 교훈만 추천하기
        - 최대 3개
        - 영어 key + 한국어 name 형태로 JSON 배열로 반환
        - key는 영어 소문자 슬러그
        - name은 한국어로 가치/교훈을 한 단어로 자연스럽게 표현

        DEFAULT_MORALS = {DEFAULT_MORAL_KEYS}

        예시 답변 형식:
        [
          {{ "key": "forgiveness", "name": "용서" }},
          {{ "key": "wisdom", "name": "지혜" }}
        ]

        반드시 JSON 형식만 반환하세요.
        """

        try:
            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.4,
            )

            raw = response.choices[0].message.content

        except Exception as e:
            return Response({"error": f"AI 요청 실패: {str(e)}"}, status=500)

        # 3. JSON 파싱
        try:
            import json
            recommended = json.loads(raw)
        except Exception:
            return Response({"error": "AI 응답 파싱 실패"}, status=500)

        # 4. DEFAULT_MORALS 중복 제거
        filtered = [m for m in recommended if m["key"] not in DEFAULT_MORAL_KEYS]

        return Response({
            "recommended_morals": filtered[:3]
        }, status=200)
    

def ensure_default_morals():
    for moral in DEFAULT_MORALS:
        MoralTheme.objects.get_or_create(key=moral["key"], defaults={"name": moral["name"]})

class MoralThemeListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ensure_default_morals()
        morals = MoralTheme.objects.all().order_by("id")
        serializer = MoralThemeSerializer(morals, many=True)
        return Response(serializer.data, status=200)

#교훈 키워드 기존 선택, 추천 선택, 혹은 추가
class StoryMoralSaveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        selected_ids = request.data.get("selected_morals", [])
        custom_morals = request.data.get("custom_morals", [])

        if not isinstance(selected_ids, list) or not isinstance(custom_morals, list):
            return Response({"error": "selected_ids와 custom_keywords는 리스트 형태여야 합니다."}, status=400)

        total_count = len(selected_ids) + len(custom_morals)
        if total_count == 0:
            return Response({"error": "최소 1개의 교훈을 선택해주세요."}, status=400)
        if total_count > 3:
            return Response({"error": "최대 3개의 교훈만 선택할 수 있습니다."}, status=400)
        
        created_custom_ids = []
        
        # custom_morals = ["용서", "지혜"] 같은 문자열 리스트
        for name in custom_morals:
            if not isinstance(name, str) or not name.strip():
                return Response({"error": "custom_morals는 문자열 리스트여야 합니다."}, status=400)

            key = slugify(name, allow_unicode=False)  # "용서" → "yong-seo" 같은 슬러그 자동 생성

            obj, _ = MoralTheme.objects.get_or_create(
                key=key,
                defaults={"name": name}
            )
            created_custom_ids.append(obj.id)

        # Redis 저장
        redis_client = redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            decode_responses=True,
            ssl=False, 
        )
        user_id = request.user.id
        redis_key = f"story_morals:{user_id}"

        redis_client.hset(redis_key, mapping={
            "selected_ids": ",".join(map(str, selected_ids)),
            "custom_morals": ",".join(custom_morals)
        })

        return Response({
            "message": "교훈이 저장되었습니다.",
            "next": "/api/story/generate/"
        }, status=200)

def extract_title_and_body(text):
    title_match = re.search(r"제목\s*[:\-]\s*(.+)", text)
    
    if title_match:
        title = title_match.group(1).strip()
        
        body = re.sub(r"제목\s*[:\-]\s*.+", "", text, count=1).strip()
        return title, body

    lines = text.strip().split("\n")
    if len(lines) > 1:
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        return title, body
    
    return "제목 없음", text.strip()

class StoryGenerateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ensure_default_morals()

        redis_client = redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            decode_responses=True,
            ssl=False, 
        )

        user_id = request.user.id
        option = redis_client.hgetall(f"story_option:{user_id}")
        draft = redis_client.get(f"story_draft:{user_id}")
        moral_data = redis_client.hgetall(f"story_morals:{user_id}")

        if not option or not moral_data:
            return Response({"error": "필요한 데이터가 모두 준비되지 않았습니다."}, status=400)

        selected_ids = [int(i) for i in moral_data.get("selected_ids", "").split(",") if i]
        custom_morals = [k.strip() for k in moral_data.get("custom_morals", "").split(",") if k.strip()]

        themes = list(MoralTheme.objects.filter(id__in=selected_ids))
        all_moral_texts = [t.name for t in themes] + custom_morals

        runtime = option.get("runtime")
        age_group = option.get("age_group")
        morals = ", ".join(all_moral_texts)

        prompt = f"""
        당신은 0~7세 아이들을 위한 짧고 명확한 창작 동화를 만드는 동화 작가입니다.

        아래 조건에 맞춰 동화를 작성하세요.

        [출력 형식 - 매우 중요]
        제목: 한 줄 제목
        본문:

        [금지 규칙]
        - Markdown 문법(###, **, *, ``` 등) 절대 금지
        - "본문:, 제목:, \n"이라는 단어를 본문 안에 쓰지 말 것
        - "###", "-", 번호 목록 등 리스트 문법 금지
        - JSON, 코드블록 금지
        - AI 설명, 주석 금지
        - \n 문자 그대로 출력 금지(자연스러운 줄바꿈만 사용)
        - 절대 줄바꿈을 하지 말고, 모든 문장을 한 줄로 이어서 작성하세요.

        [본문 스타일]
        - 어린이용 동화체
        - 짧고 쉬운 문장
        - {age_group} 수준의 난이도
        - 전체 길이는 {runtime} 분량
        - 교훈 키워드: {morals}
        - 아래 초안을 참고하되, 내용은 부드럽게 재창작
        - 초안을 그대로 복붙하지 말고 흐름을 자연스럽게 구성
        - 마무리를 동화스럽게 교훈 키워드를 잘 활용
        [사용자 초안]
        {draft}
        """


        try:
            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "당신은 부모님의 에피소드를 기반으로 아이에게 들려줄 이야기를 창작하는 동화 작가입니다."},
                    {"role": "user", "content": prompt}
                ],
            )
            ai_text = response.choices[0].message.content.strip()
            title, body = extract_title_and_body(ai_text)

        except Exception as e:
            return Response({"error": f"AI 생성 오류: {str(e)}"}, status=500)

        story = Story.objects.create(
            user=request.user,
            title=title,
            author=request.user.username,
            content=body,
            category="custom",
            runtime=runtime,
            age_group=age_group,
        )

        for theme in themes:
            story.morals.add(theme)

        for kw in custom_morals:
            custom_theme, _ = MoralTheme.objects.get_or_create(name=kw, defaults={"key": f"custom_{kw}"})
            story.morals.add(custom_theme)

        pages = split_into_pages(body)

        for id, page_text in enumerate(pages, start=1):
            StoryPage.objects.create(
                story=story,
                page_number=id,
                text=page_text
            )
        
        story.page_count = len(pages)
        story.save()

        serializer = StorySerializer(story)
        return Response(serializer.data, status=201)
    
class StoryResetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_id = request.user.id
        
        try:
            redis_client = redis.StrictRedis(
                host=getattr(settings, "REDIS_HOST", "localhost"),
                port=getattr(settings, "REDIS_PORT", 6379),
                db=0,
                decode_responses=True,
                ssl=False, 
            )

            keys = [
                f"story_option:{user_id}",
                f"story_draft:{user_id}",
                f"story_morals:{user_id}",
            ]

            for key in keys:
                redis_client.delete(key)

        except Exception:
            return Response({"error": "Redis 연결에 실패했습니다."}, status=400)

        return Response({
            "message": "스토리 생성 흐름 데이터가 초기화되었습니다."
        }, status=200)
    

class ClonedVoiceTTSView(APIView):
    """
    사용자가 지정한 클로닝된 voice_id의 SE 벡터로
    title/author 또는 단일 page.text 중 하나만 TTS로 변환하여
    단일 오디오 파일을 생성하는 API (timeout-safe)
    """
    permission_classes = [IsAuthenticated]

    MODEL_DIR = "/app/models/checkpoints_v2"
    BASE_SPEAKER_AUDIO = os.path.join(MODEL_DIR, "base_speakers", "base_ko.wav")
    BASE_SPEAKER_SE    = os.path.join(MODEL_DIR, "base_speakers", "ses", "kr.pth")

    def post(self, request):
        from story.services.openvoice_service import (
            get_tts,
            convert_voice,
        )

        try:
            data = request.data

            # -----------------------------
            # 1) Body 파라미터 로드
            # -----------------------------
            voice_id = data.get("voice_id")
            title = data.get("title", "")
            author = data.get("author", "")
            pages = data.get("pages", [])

            if not voice_id:
                return Response({"error": "voice_id가 필요합니다."}, status=400)

            # pages는 빈 리스트일 수 있음
            if not isinstance(pages, list) or len(pages) == 0:
                return Response({"error": "pages는 최소 빈 배열이라도 필요합니다."}, status=400)

            # -----------------------------
            # 2) 클로닝된 화자 정보 조회
            # -----------------------------
            try:
                cloned = ClonedVoice.objects.get(id=voice_id, user=request.user)
            except ClonedVoice.DoesNotExist:
                return Response({"error": "해당 voice_id를 찾을 수 없거나 권한이 없습니다."}, status=404)

            if not cloned.se_file:
                return Response(
                    {"error": "해당 voice_id는 SE 벡터가 없습니다. 먼저 /voice/clone/ 실행 필요."},
                    status=400
                )

            user_id = request.user.id

            # -----------------------------
            # 3) SE 벡터 로드
            # -----------------------------
            import torch
            device = "cuda:0" if torch.cuda.is_available() else "cpu"

            se_path = cloned.se_file.name   # S3 경로 그대로
            with default_storage.open(se_path, "rb") as f:
                reference_se = torch.load(f, map_location=device)

            if isinstance(reference_se, dict):
                reference_se = reference_se.get("se") or reference_se.get("speaker_embed")

            base_se = torch.load(self.BASE_SPEAKER_SE, map_location=device)

            # -----------------------------
            # 4) TTS 모델 로드
            # -----------------------------
            tts = get_tts("KR")
            speaker_id = list(tts.hps.data.spk2id.values())[0]

            os.makedirs("outputs_v2", exist_ok=True)

            # ============================================================
            # 🔥 핵심: title/author 있으면 intro만 생성
            # ============================================================
            if title or author:
                tts_text = f"제목, {title}. 지은이, {author}."
                output_filename = f"{user_id}_{voice_id}_intro.wav"
            else:
                # ============================================================
                # 🔥 title/author 없으면 → pages[0].text만 TTS 생성
                # ============================================================
                page = pages[0]
                page_text = page.get("text", "")
                page_num = page.get("page", 1)

                if not page_text:
                    return Response({"error": "title/author 또는 pages[0].text 중 하나는 필요합니다."}, status=400)

                tts_text = page_text
                output_filename = f"{user_id}_{voice_id}_page_{page_num}.wav"

            # -----------------------------
            # 5) base audio 생성
            # -----------------------------
            base_path = f"outputs_v2/{output_filename.replace('.wav', '_base.wav')}"
            clone_path = f"outputs_v2/{output_filename.replace('.wav', '_clone.wav')}"

            tts.tts_to_file(tts_text, speaker_id, base_path, speed=1.0)

            # -----------------------------
            # 6) voice convert
            # -----------------------------
            convert_voice(base_path, reference_se, clone_path, base_se)

            # -----------------------------
            # 7) S3 저장
            # -----------------------------
            s3_path = default_storage.save(
                f"tts_outputs/user_{user_id}/voice_{voice_id}/{output_filename}",
                File(open(clone_path, "rb"))
            )

            # Cleanup
            os.remove(base_path)
            os.remove(clone_path)

            # -----------------------------
            # 8) 응답
            # -----------------------------
            return Response(
                {"tts_audio_url": default_storage.url(s3_path)},
                status=200
            )

        except Exception as e:
            import traceback
            print("🔥 [TTS ERROR TRACEBACK START]")
            print(traceback.format_exc())
            print("🔥 [TTS ERROR TRACEBACK END]")
            return Response({"error": str(e)}, status=500)



class IllustrationStyleView(APIView):
    
    permission_classes = [IsAuthenticated]

    def post(self, request, story_id):
        style = request.data.get("style")

        if style not in ["watercolor", "oil", "crayon", "3d"]:
            return Response(
                {"error": "유효하지 않은 스타일입니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 스토리 조회
        try:
            story = Story.objects.get(id=story_id, user=request.user)
        except Story.DoesNotExist:
            return Response(
                {"error": "스토리를 찾을 수 없거나 권한이 없습니다."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 스타일 저장
        story.illustration_style = style
        story.save()

        return Response(
            {
                "story_id": story.id,
                "style": style,
                "message": "삽화 스타일이 저장되었습니다."
            },
            status=status.HTTP_200_OK
        )
    
class IllustrationRegenerateView(APIView):
    """
    특정 페이지의 삽화를 다시 생성하는 API
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        story_id = request.data.get("story_id")
        page = request.data.get("page")

        # 🔹 필수 값 확인
        if not story_id or page is None:
            return Response(
                {"error": "story_id와 page는 필수 입력값입니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 스토리 존재 여부 확인
            story = Story.objects.get(id=story_id, user=request.user)
        except Story.DoesNotExist:
            return Response(
                {"error": "해당 스토리를 찾을 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 해당 페이지 찾기
            story_page = StoryPage.objects.get(story=story, page_number=page)
        except StoryPage.DoesNotExist:
            return Response(
                {"error": f"{page}페이지를 찾을 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 기존 삽화가 있다면 삭제 또는 버전 증가 처리
            Illustrations.objects.filter(story_page=story_page).delete()

            # ❌❌❌❌❌❌❌❌더미단계
            new_image_url = (
                f"https://cdn.example.com/illustrations/"
                f"story{story_id}_page{page}_v{random.randint(2, 99)}.png"
            )

            # 새로운 삽화 객체 생성
            Illustrations.objects.create(
                story_page=story_page,
                image=new_image_url,
                prompt=f"AI 재생성된 삽화 (Story {story_id}, Page {page})",
                style="재생성",
            )

            return Response(
                {
                    "page": page,
                    "new_image_url": new_image_url,
                    "status": "completed",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"재생성 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

class StoryListView(APIView):
    def get(self, request):
        category = request.query_params.get("category")
        stories = Story.objects.all()

        if category in ["classic", "custom", "extended"]:
            stories = stories.filter(category=category)
        
        stories = stories.order_by("-created_at")
        
        serializer = StoryInfoSerializer(stories, many=True)

        return Response(serializer.data, status=200)
    
class StoryDetailView(APIView):
    def get(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)

        serializer = StorySerializer(story)
        return Response(serializer.data, status=200)
    
class StoryPageListView(APIView):
    def get(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)

        if request.user.is_authenticated:
            lib, created = Library.objects.get_or_create(
                user=request.user,
                story=story,
            )
            print("created:", created)
            lib.last_viewed_time = timezone.now()
            lib.save()

        pages = StoryPage.objects.filter(story=story).order_by("page_number")
        serializer = StoryPageSerializer(pages, many=True)
        return Response(serializer.data, status=200)

class StoryScriptView(APIView):
    def get(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)
        
        pages = StoryPage.objects.filter(story=story).order_by("page_number")
        serializer = StoryScriptSerializer(pages, many=True)
        return Response(serializer.data, status=200)

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

import chardet  
class ClassicStoryUploadView(APIView):

    def post(self, request):
        
        filename = request.data.get("filename")
        title = request.data.get("title")
        author = request.data.get("author", "Unknown")

        if not filename:
            return Response({"error": "filename is required"}, status=400)

        possible_paths = [
            f"stories/{filename}",
            f"media/stories/{filename}",
            filename,
        ]

        file_path = None
        for path in possible_paths:
            if default_storage.exists(path):
                file_path = path
                break

        if not file_path:
            return Response({"detail": f"{filename} not found in S3"}, status=404)


        with default_storage.open(file_path, "rb") as f:
            raw_bytes = f.read()
        
        detected = chardet.detect(raw_bytes)
        encoding = detected.get("encoding", "utf-8")

        raw_text = raw_bytes.decode(encoding, errors="ignore")

        story = Story.objects.create(
            user=request.user,
            child=None,
            voice=None,
            title=title,
            author=author,
            content=raw_text,
            category="classic",
            created_at=timezone.now(),
        )

        pages = split_into_pages(raw_text)

        for i, page_text in enumerate(pages, start=1):
            StoryPage.objects.create(
                story=story,
                page_number=i,
                text=page_text
            )

        story.page_count = len(pages)
        story.save()

        return Response({
            "story_id": story.id,
            "title": story.title,
            "page_count": story.page_count
        }, status=201)

class MonthlyNDWReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        days = int(request.query_params.get("days", 30))

        result = calculate_ndw_for_month(request.user, days)

        if result is None:
            return Response(
                {"error": f"최근 {days}일 동안 user 발화가 존재하지 않습니다."},
                status=404
            )

        # Response 포맷 → 너가 원하는 JSON 형태와 1:1 일치하도록 구성
        response = {
            "period": result["period"],
            "level": result["level"],
            "monthly_statistics": result["stats"],
            "top_words": [
                {"word": w, "count": c}
                for w, c in result["top_words"]
            ]
        }

        return Response(response, status=200)

class StoryNDWReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, story_id):
        from story.services.language_analysis import calculate_ndw_for_story

        # story 존재 여부 + 권한
        story = Story.objects.filter(id=story_id, user=request.user).first()
        if not story:
            return Response({"error": "해당 스토리를 찾을 수 없거나 권한이 없습니다."}, status=404)

        result = calculate_ndw_for_story(request.user, story_id)

        if result is None:
            return Response({"error": "해당 동화에 대한 user 발화 기록이 없습니다."}, status=404)

        # Response 포맷을 너가 원하는 리포트 형식 그대로 맞춤
        response = {
            "story": {
                "story_id": story.id,
                "title": story.title,
                "date": story.created_at.date().isoformat()
            },
            "level": result["level"],
            "statistics": result["stats"],
            "top_words": [
                {"word": w, "count": c}
                for w, c in result["top_words"]
            ],
            "total_user_utterances": result["utterance_count"]
        }

        return Response(response, status=200)

class PersonalityReportGlobalView(APIView):
    """
    최근 30일 user 발화 기반 성격 분석 (NEO Big5)
    story_id 없음
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # body의 utterances (추가 발화) - optional
        extra = request.data.get("utterances", [])

        # 최근 30일 모든 발화 수집
        from AI.models import Message, ExtendMessage
        from datetime import timedelta
        from django.utils import timezone

        since = timezone.now() - timedelta(days=30)

        msg1 = Message.objects.filter(
            sender="user",
            timestamp__gte=since,
            story__user=request.user
        ).values_list("text", flat=True)

        msg2 = ExtendMessage.objects.filter(
            role="user",
            created_at__gte=since,
            chat__user=request.user
        ).values_list("content", flat=True)

        all_utterances = list(msg1) + list(msg2) + extra

        # NEO 성격 분석
        result, rationale = predict_personality_with_adjustment(all_utterances)

        report = generate_personality_report(result, rationale)

        return Response({
            "result": result,
            "rationale": rationale,
            "report": report
        })
    


# ------------------------------------------------------
# 1) 반응 저장 API (좋아요/아쉬워요)
# POST /api/stories/{story_id}/reaction/
# ------------------------------------------------------
class StoryReactionCreateView(APIView):
    """
    StoryReaction 저장/업데이트
    story + child 기준 하나만 존재하도록 update_or_create 사용
    """

    def post(self, request, story_id):
        child_id = request.data.get("child_id")
        reaction = request.data.get("reaction")

        if not child_id:
            return Response({"error": "child_id is required."}, status=400)

        if reaction not in ["like", "dislike"]:
            return Response({"error": "reaction must be 'like' or 'dislike'."}, status=400)

        story = get_object_or_404(Story, id=story_id)
        child = get_object_or_404(Child, id=child_id)

        reaction_obj, created = StoryReaction.objects.update_or_create(
            story=story,
            child=child,
            defaults={"reaction": reaction},
        )

        serializer = StoryReactionSerializer(reaction_obj)

        return Response(
            {
                "message": "반응이 저장되었습니다.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )



# ------------------------------------------------------
# 2) 좋아요 스토리 목록
# GET /api/stories/reactions/like/?child_id=3
# ------------------------------------------------------
class StoryLikeListView(APIView):
    """
    특정 child가 '좋아요'한 스토리 목록 반환
    """

    def get(self, request):
        child_id = request.GET.get("child_id")

        if not child_id:
            return Response({"error": "child_id is required."}, status=400)

        child = get_object_or_404(Child, id=child_id)

        reactions = StoryReaction.objects.filter(
            child=child,
            reaction="like"
        ).select_related("story").order_by("-created_at")

        # Story 객체에 reaction timestamp를 주입
        story_list = []
        for r in reactions:
            story = r.story
            story.liked_at = r.created_at
            story.disliked_at = None
            story_list.append(story)

        serializer = StoryReactionListSerializer(story_list, many=True)

        return Response(
            {
                "child_id": child.id,
                "reaction": "like",
                "count": len(story_list),
                "results": serializer.data,
            }
        )



# ------------------------------------------------------
# 3) 아쉬워요 스토리 목록
# GET /api/stories/reactions/dislike/?child_id=3
# ------------------------------------------------------
class StoryDislikeListView(APIView):
    """
    특정 child가 '아쉬워요'한 스토리 목록 반환
    """

    def get(self, request):
        child_id = request.GET.get("child_id")

        if not child_id:
            return Response({"error": "child_id is required."}, status=400)

        child = get_object_or_404(Child, id=child_id)

        reactions = StoryReaction.objects.filter(
            child=child,
            reaction="dislike"
        ).select_related("story").order_by("-created_at")

        story_list = []
        for r in reactions:
            story = r.story
            story.disliked_at = r.created_at
            story.liked_at = None
            story_list.append(story)

        serializer = StoryReactionListSerializer(story_list, many=True)

        return Response(
            {
                "child_id": child.id,
                "reaction": "dislike",
                "count": len(story_list),
                "results": serializer.data,
            }
        )
