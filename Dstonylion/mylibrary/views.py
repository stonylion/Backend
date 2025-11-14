from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status, views
from django.shortcuts import get_object_or_404

from .models import Library, User
from .serializers import *
from story.models import *
from story.serializers import *
from django.contrib.auth import get_user_model

User = get_user_model()

class RecentReadView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        category = request.query_params.get("category")

        libraries = Library.objects.filter(user=request.user).select_related("story")

        if category in ["classic", "custom", "extended"]:
            libraries = libraries.filter(story__category=category)

        libraries = libraries.order_by("-last_viewed_time")
        
        serializer = LibrarySerializer(libraries, many=True)

        return Response({
            "count": libraries.count(),
            "results": serializer.data
        })
    
class RecentGeneratedView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        category = request.query_params.get("category")

        libraries = Library.objects.filter(user=request.user).select_related("story")

        if category in ["classic", "custom", "extended"]:
            libraries = libraries.filter(story__category=category)

        libraries = libraries.order_by("-story__created_at")

        serializer = LibrarySerializer(libraries, many=True)

        return Response({
            "count": libraries.count(),
            "results":serializer.data
        })

class LibraryDetailView(views.APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, library_id):
        library = get_object_or_404(Library, id=library_id, user=request.user)
        story = library.story
        
        if story.category == "classic":
            library.delete()
            return Response({"detail": "내 서재에서 삭제되었습니다."}, status=status.HTTP_204_NO_CONTENT)
        
        story.delete()
        return Response({"detail": "동화가 삭제되었습니다."})

class UserProfileView(APIView):
    """
    로그인한 사용자의 프로필 정보를 조회하는 API
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user  # JWT 인증된 사용자 객체

            return Response(
                {
                    "user_id": user.id,
                    "name": user.first_name if user.first_name else user.username,
                    "birth_date": user.birth.strftime("%Y-%m-%d") if user.birth else None,
                    "username": user.username,
                    "gender": user.gender,
                    "profile_image_url": (
                        user.profile_image.url
                        if user.profile_image
                        else None
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"프로필 조회 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
