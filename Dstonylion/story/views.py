import redis
import random
from django.conf import settings
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from .models import Story, StoryPage, Illustrations

from .serializers import StoryDraftSerializer


class StoryOptionView(APIView):
    """
    사용자가 동화 분량(length)과 연령대(age_range)를 선택하면
    다음 단계 URL을 반환하는 API.
    """

    def post(self, request):
        length = request.data.get("length")
        age_range = request.data.get("age_range")

        # 필수 옵션 누락 체크
        if not length or not age_range:
            return Response(
                {"error": "필수 옵션이 누락되었습니다. length와 age_range를 모두 선택해주세요."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 유효하지 않은 값 처리 (예시: 사전에 정의된 옵션만 허용)
        valid_lengths = ["0-3분", "3-5분", "5-10분"]
        valid_ages = ["0-3세", "4-6세", "7-9세"]

        if length not in valid_lengths or age_range not in valid_ages:
            return Response(
                {"error": "잘못된 동화 옵션입니다. length 또는 age_range를 확인해주세요."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 정상 응답
        return Response(
            {"next": "/story/record/"},
            status=status.HTTP_200_OK
        )
    

class StoryDraftViewSet(viewsets.ViewSet):
    """
    Whisper STT 결과 임시 저장 및 복원 API
    - GET: Redis에서 STT 결과 복원
    - POST: WebSocket에서 받은 STT 결과를 Redis에 저장
    """

    permission_classes = [IsAuthenticated]

    def _get_redis_client(self):
        return redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            charset="utf-8",
            decode_responses=True,
        )

    def get_cache_key(self, user_id):
        return f"story_draft:{user_id}"

    # GET /api/story/draft/ (복원)
    def list(self, request):
        redis_client = self._get_redis_client()
        user_id = request.user.id
        redis_key = self.get_cache_key(user_id)

        draft_text = redis_client.get(redis_key)

        if not draft_text:
            return Response(
                {"error": "복원할 임시 텍스트가 없습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = StoryDraftSerializer({"draft_text": draft_text})
        return Response(serializer.data, status=status.HTTP_200_OK)

    # POST /api/story/draft/ (저장)
    def create(self, request):
        serializer = StoryDraftSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        draft_text = serializer.validated_data.get("draft_text")
        user_id = request.user.id
        redis_client = self._get_redis_client()
        redis_key = self.get_cache_key(user_id)

        redis_client.set(redis_key, draft_text)

        return Response({"message": "임시 텍스트가 저장되었습니다."}, status=status.HTTP_200_OK)
    
    # DELETE /api/story/draft/ (초기화)
    def destroy(self, request, pk=None):
        """
        새 이야기 녹음 시작 시 Redis 캐시 초기화
        """
        try:
            redis_client = self._get_redis_client()
            user_id = request.user.id
            redis_key = self.get_cache_key(user_id)

            if not redis_client.exists(redis_key):
                return Response(
                    {"error": "삭제할 캐시가 없습니다."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            redis_client.delete(redis_key)
            return Response(status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": f"서버 오류: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
class StoryKeywordSaveView(APIView):
    """
    사용자가 선택하거나 직접 입력한 교훈 키워드를 저장하는 API
    (추천 기능은 추후 추가 예정)
    """

    permission_classes = [IsAuthenticated]

    def _get_redis_client(self):
        return redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            charset="utf-8",
            decode_responses=True,
        )

    def post(self, request):
        selected_keywords = request.data.get("selected_keywords", [])
        custom_keywords = request.data.get("custom_keywords", [])

        # 타입 유효성 검사
        if not isinstance(selected_keywords, list) or not isinstance(custom_keywords, list):
            return Response(
                {"error": "selected_keywords와 custom_keywords는 리스트 형태여야 합니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 합쳐서 최대 3개 제한
        combined = selected_keywords + custom_keywords
        if len(combined) > 3:
            return Response(
                {"error": "최대 3개의 교훈만 선택할 수 있습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Redis에 저장
        redis_client = self._get_redis_client()
        user_id = request.user.id
        redis_key = f"story_keywords:{user_id}"

        redis_client.set(redis_key, ",".join(combined))  # 콤마로 구분된 문자열로 저장

        return Response(
            {
                "message": "선택한 교훈이 저장되었습니다.",
                "next": "/api/story/generate/"
            },
            status=status.HTTP_200_OK
        )
    
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
