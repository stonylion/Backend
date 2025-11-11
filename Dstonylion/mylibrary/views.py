from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .models import User


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

