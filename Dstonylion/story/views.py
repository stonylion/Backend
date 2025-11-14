import redis, random, os, json, openai, re
from django.conf import settings
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import *
from .serializers import *
from mylibrary.models import *
from django.core.files.storage import default_storage
from rest_framework import viewsets, status
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from story.utils import split_into_pages

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
    
class StoryDraftView(APIView):
    permission_classes = [IsAuthenticated]

    def _redis(self):
        return redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            decode_responses=True
        )
    
    def _normalize_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        text = text.strip()
        if not text:
            return ""
        if not text.endswith((".", "?", "!")):
            text += "."
        return text.strip()

    def get(self, request):
        redis_client = self._redis()
        text = redis_client.get(f"story_draft:{request.user.id}") or ""
        return Response({"draft_text": text}, status=200)

    def post(self, request):
        redis_client = self._redis()
        draft_key = f"story_draft:{request.user.id}"
        draft_text = request.data.get("draft_text", "")
        mode = request.data.get("mode")

        if draft_text:
            draft_text = self._normalize_text(draft_text)

        if mode is None:
            redis_client.set(draft_key, draft_text)
            return Response({"message": "Draft 저장 완료"}, status=200)

        elif mode == "switch_to_text":
            # WebSocket에 'pause' 명령 전송은 프론트가 수행
            current_draft = redis_client.get(draft_key) or ""
            return Response({
                "message": "음성 입력이 일시정지되었습니다. 텍스트 모드로 전환합니다.",
                "draft_text": current_draft
            }, status=200)

        elif mode == "switch_to_voice":
            redis_client.set(draft_key, draft_text)
            # 프론트가 이 응답을 받으면 WebSocket을 재연결하여 resume
            return Response({
                "message": "텍스트가 저장되었습니다. 이어서 말하기로 전환합니다.",
                "next_ws": "story/draft-stt/"
            }, status=200)

        else:
            return Response({"error": "유효하지 않은 mode입니다."}, status=400)

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

#교훈 키워드 선택 혹은 추가
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
'''    
class StoryStyleSelectView(APIView):
    """
    사용자가 동화의 삽화 스타일을 선택하는 API
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        story_id = request.data.get("story_id")
        style = request.data.get("style")

        # 필수 값 확인
        if not story_id or not style:
            return Response(
                {"error": "story_id와 style은 필수 입력값입니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 유효한 스타일 목록 (명세에 따라 사전 정의)
        valid_styles = ["수채화", "연필화", "유화", "디지털", "동양화", "파스텔"]

        if style not in valid_styles:
            return Response(
                {"error": "유효하지 않은 스타일입니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            story = Story.objects.get(id=story_id, user=request.user)
        except Story.DoesNotExist:
            return Response(
                {"error": "해당 스토리를 찾을 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 선택한 스타일 저장
        story.status = "style_selected"
        story.save()

        # 삽화 스타일을 별도로 저장하고 싶으면 Redis나 별도 테이블 사용 가능
        # 예시: story.illustrations.update(style=style) 도 가능

        return Response(
            {"message": f"선택된 스타일: {style}"},
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
'''
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
        다음 조건에 맞는 창작 동화를 작성해주세요.
        - 분량: {runtime}
        - 대상 연령: {age_group}
        - 교훈 키워드: {morals}
        - 사용자가 입력한 에피소드 초안: {draft}
        결과는 제목과 본문으로 구성해주세요.
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

        Library.objects.get_or_create(
                user=request.user,
                story=story,
            )

        # 캐시 초기화
        redis_client.delete(f"story_option:{user_id}")
        redis_client.delete(f"story_draft:{user_id}")
        redis_client.delete(f"story_keywords:{user_id}")

        return Response(serializer.data, status=201)

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

'''
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
'''
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

