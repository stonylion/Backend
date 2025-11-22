import redis, random, os, json, re, base64
import openai
# import torch
import traceback
from django.core.files import File
from django.core.files.base import ContentFile
from django.conf import settings
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
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

load_dotenv(settings.BASE_DIR/ ".env")
# openai.api_key = os.getenv("OPENAI_API_KEY")

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
        )
        redis_client.hmset(f"story_option:{request.user.id}", {"runtime": runtime, "age_group": age_group})

        return Response({"next": "/story/record/"}, status=status.HTTP_200_OK)
    
class StoryDraftUpdateView(APIView):
    """
    사용자가 텍스트 입력으로 최종 입력한 내용을 Redis에 저장하는 API
    POST /api/story/draft/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
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
        )

        redis_key = f"story_draft:{request.user.id}"

        # 최종 텍스트 저장
        redis_client.set(redis_key, text)

        return Response(
            {"message": "draft 업데이트 완료되었습니다."},
            status=200
        )


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
    
VALID_STYLES = {"watercolor", "oil", "crayon", "3d"}
STYLE_CONFIG = {
    "watercolor": {
        "label": "수채화",
        "prompt": "soft watercolor illustration, gentle pastel colors, for children",
        "reference_paths": [
            "illustrations_example/watercolor/watercolor_example1.png",
            "illustrations_example/watercolor/watercolor_example2.png",
            "illustrations_example/watercolor/watercolor_example3.png",
            "illustrations_example/watercolor/watercolor_example4.png"
        ],
    },
    "oil": {
        "label": "유화",
        "prompt": "oil painting illustration, rich texture, for children storybook",
        "reference_paths": [
            "illustrations_example/oil/oil_example1.png",
            "illustrations_example/oil/oil_example2.png",
            "illustrations_example/oil/oil_example3.png",
            "illustrations_example/oil/oil_example4.png"
        ],
    },
    "crayon": {
        "label": "크레파스",
        "prompt": "crayon style drawing, childlike, colorful, for kids",
        "reference_paths": [
            "illustrations_example/crayon/crayon_example1.png",
            "illustrations_example/crayon/crayon_example2.png",
            "illustrations_example/crayon/crayon_example3.png",
            "illustrations_example/crayon/crayon_example4.png"
        ],
    },
    "3d": {
        "label": "3D 애니메이션",
        "prompt": "3D animation style, Pixar-like, bright and cute",
        "reference_paths": [
            "illustrations_example/3d-animation/3d_example1.png",
            "illustrations_example/3d-animation/3d_example2.png",
            "illustrations_example/3d-animation/3d_example3.png",
            "illustrations_example/3d-animation/3d_example4.png"
        ],
    },
}


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
'''
class StoryStyleSelectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        story_id = request.data.get("story_id")
        style = request.data.get("style")

        if not story_id or not style:
            return Response(
                {"error": "story_id와 style은 필수 입력값입니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if style not in VALID_STYLES:
            return Response(
                {"error": "유효하지 않은 스타일입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            story = Story.objects.get(id=story_id, user=request.user)
        except Story.DoesNotExist:
            return Response(
                {"error": "해당 스토리를 찾을 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        story.style = style
        story.updated_at = timezone.now()
        story.save(update_fields=["illustration_style", "updated_at"])

        return Response(
            {
                "message": f"선택된 스타일: {STYLE_CONFIG[style]['label']}",
                "story_id": story.id,
                "style": style,
            },
            status=status.HTTP_200_OK,
        )

def generate_and_save_illustration(story_page: StoryPage):
    story = story_page.story
    style = story.style

    if not style:
        raise ValueError("Story에 style이 설정되어 있지 않습니다.")

    style_conf = STYLE_CONFIG.get(style, {})
    style_prompt = style_conf.get("prompt", "cute children book illustration")
    ref_paths = style_conf.get("reference_paths", [])

    ref_urls = [default_storage.url(path) for path in ref_paths]
    ref_text = ""
    if ref_urls:
        ref_text = "참고 이미지 (스타일 예시): " + ", ".join(ref_urls)

    prompt = f"""
    {style_prompt}.
    어린이 동화의 한 장면을 그립니다.
    장면 설명(텍스트): "{story_page.text[:300]}"
    너무 무섭지 않고, 0~7세를 위한 따뜻하고 안전한 느낌으로 그려주세요.
    {ref_text}
    """

    image_response = openai.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
        n=1,
    )

    image_base64 = image_response.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)

    story_id = story.id
    page_no = story_page.page_number

    folder_prefix = "stories/generated_story"
    filename = f"generated_story_{story_id}/story_{story_id}_page_{page_no}.png"
    relative_path = f"{folder_prefix}/{filename}"

    default_storage.save(relative_path, ContentFile(image_bytes))
    image_url = default_storage.url(relative_path)

    illustration = Illustrations.objects.create(
        story_page=story_page,
        image=relative_path,
        prompt=prompt,
        style=style,
        created_at=timezone.now(),
    )
    return illustration, image_url

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
'''
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
    permission_classes = [IsAuthenticated]

    def get(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)

        serializer = StorySerializer(story)
        return Response(serializer.data, status=200)
    
    def patch(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)
        
        if story.user != request.user:
            return Response({"detail": "권한이 없습니다."},
                            status=status.HTTP_403_FORBIDDEN)
        
        new_title = request.data.get("title")
        new_content = request.data.get("content")

        if not new_content:
            return Response(
                {"error": "content는 필수 입력값입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # 제목 업데이트(옵션)
        if new_title:
            story.title = new_title

        story.content = new_content
        story.updated_at = timezone.now()
        story.save()

        StoryPage.objects.filter(story=story).delete()
        Illustrations.objects.filter(story_page__story=story).delete()

        pages = split_into_pages(new_content)
        for idx, page_text in enumerate(pages, start=1):
            StoryPage.objects.create(
                story=story,
                page_number=idx,
                text=page_text,
            )

        story.page_count = len(pages)
        story.updated_at = timezone.now()
        story.save()

        serializer = StorySerializer(story)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class StoryPageListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)

        lib, created = Library.objects.get_or_create(
            user=request.user,
            story=story,
        )
        if created:
            lib.save()

        pages = StoryPage.objects.filter(story=story).order_by("page_number")
        serializer = StoryPageSerializer(pages, many=True)
        return Response(serializer.data, status=200)
    
    def patch(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)
        
        if story.user != request.user:
            return Response({"detail": "권한이 없습니다."},
                            status=status.HTTP_403_FORBIDDEN)
        
        page_number = request.data.get("page_number")
        new_text = request.data.get("text")

        if page_number is None or new_text is None:
            return Response(
                {"error": "page_number와 text는 필수입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            page_number = int(page_number)
        except ValueError:
            return Response(
                {"error": "page_number는 숫자여야 합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            page = StoryPage.objects.get(story=story, page_number=page_number)
        except StoryPage.DoesNotExist:
            return Response(
                {"error": f"{page_number} 페이지를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        page.text = new_text
        page.save()

        all_pages = StoryPage.objects.filter(story=story).order_by("page_number")
        story.content = "".join(p.text for p in all_pages)
        story.updated_at = timezone.now()
        story.save()

        serializer = StoryPageSerializer(page)
        return Response(serializer.data, status=status.HTTP_200_OK)

class StoryScriptView(APIView):
    def get(self, request, story_id):
        story = Story.objects.filter(id=story_id).first()
        if not story:
            return Response({"detail": "Story not found"}, status=404)
        
        pages = StoryPage.objects.filter(story=story).order_by("page_number")
        serializer = StoryScriptSerializer(pages, many=True)
        return Response(serializer.data, status=200)

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

