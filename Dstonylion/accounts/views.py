import os
import boto3
from django.conf import settings
from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status, views
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken, OutstandingToken, BlacklistedToken
from django.db import transaction
import tempfile
from django.core.files import File
from django.utils import timezone
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from story.services.openvoice_service import clone_voice

from mylibrary.models import Library
from story.models import Story, Illustrations
from accounts.models import Child, ClonedVoice
from .serializers import *
# Create your views here.

def get_tokens(user):
    token = RefreshToken.for_user(user)
    refresh = str(token)
    access = str(token.access_token)
    return{
        "access_token": access,
        "refresh": refresh
    }

class SignupView(views.APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            tokens = get_tokens(user)
            user_data = {"username": user.username,"avatar_code": user.avatar_code}

            return Response(
                {"message":"회원가입 성공", "user": user_data, "token":tokens},
                status=status.HTTP_201_CREATED)
        return Response(
            {"message":"회원가입 실패", "errors": serializer.errors},
        status=status.HTTP_400_BAD_REQUEST)

class LoginView(views.APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data["user"]
            tokens = get_tokens(user)
            return Response(
                {"message":"로그인 성공", "user": UserSerializer(user).data,  "token":tokens},
                status=status.HTTP_200_OK)
        return Response(
                {"message": "로그인 실패", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
)
    
class LogoutView(APIView):
    """
    사용자의 세션을 종료하고 Access Token을 무효화하는 API
    POST /api/user/logout/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user

            # 사용자의 모든 토큰을 블랙리스트에 등록
            tokens = OutstandingToken.objects.filter(user=user)
            for token in tokens:
                try:
                    BlacklistedToken.objects.get_or_create(token=token)
                except Exception:
                    continue

            return Response(
                {"message": "로그아웃되었습니다."},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"error": f"로그아웃 처리 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

class UserDeleteView(APIView):
    """
    로그인한 사용자의 계정을 영구적으로 삭제하는 API
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user

        try:
            with transaction.atomic():
                # ✅ 자식(Child), 목소리(Voice), 라이브러리, 히스토리, 스토리 삭제
                Child.objects.filter(user=user).delete()
                ClonedVoice.objects.filter(user=user).delete()
                Library.objects.filter(user=user).delete()
                # Story나 History 모델이 User FK를 가지고 있다면 같이 삭제
                Story.objects.filter(user=user).delete()

                # ✅ 마지막으로 사용자 삭제
                user.delete()

            return Response(
                {"message": "계정이 성공적으로 삭제되었습니다."},
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"계정 삭제 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    
class MyPageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # 사용자 정보 구성
        user_data = {
            "username": user.username,
            "avatar_code": user.avatar_code,
        }

        # 아이 목록 구성 (모든 children 포함 — is_active 필드만 반환)
        children_data = []
        for child in user.children.all():
            children_data.append({
                "child_id": child.id,
                "name": child.name,
                "is_active": child.is_active
            })

        return Response(
            {
                "user": user_data,
                "children": children_data
            },
            status=status.HTTP_200_OK
        )
    
class UserProfileView(APIView):
    """
    로그인한 사용자의 프로필 정보를 조회하는 API
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user

            return Response(
                {
                    "user_id": user.id,
                    "username": user.username,
                    "avatar_code": user.avatar_code,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"프로필 조회 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
class UserProfileUpdateView(APIView):
    """
    로그인한 사용자가 자신의 프로필 정보를 수정하는 API
    """
    permission_classes = [IsAuthenticated]

    def put(self, request):
        try:
            user = request.user
            data = request.data

            # username 수정 (name 필드로 들어올 수도 있음)
            if "username" in data:
                user.username = data["username"]

            # 비밀번호 수정
            if "password" in data and data["password"]:
                user.set_password(data["password"])

            # 프로필 이미지 수정
            if "avatar_code" in data:
                user.avatar_code = data["avatar_code"]

            user.save()

            return Response(
                {"message": "프로필이 성공적으로 수정되었습니다."},
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"유효하지 않은 입력 형식입니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
class ChildCreateView(APIView):
    """
    마이페이지에서 새로운 아이 프로필을 등록하는 API
    POST /api/user/child/
    """
    permission_classes = [IsAuthenticated]
    ALLOWED_CODES = ["child1", "child2", "child3", "child4"]

    def post(self, request):
        try:
            user = request.user
            data = request.data

            name = data.get("name")
            birth_date = data.get("birth_date")
            gender = data.get("gender")
            child_image_code = data.get("child_image_code")

            # 필수 필드 확인
            if not name:
                return Response(
                    {"error": "이름은 필수 항목입니다."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if child_image_code not in self.ALLOWED_CODES:
                return Response(
                    {"error": "child_image_code는 child1/child2/child3/child4 중 하나여야 합니다."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if gender not in ["F", "M"]:
                return Response(
                    {"error": "gender는 F(여자) 또는 M(남자)여야 합니다."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Child 인스턴스 생성
            new_child = Child.objects.create(
                user=user,
                name=name,
                birth=birth_date,
                gender=gender,
                child_image_code=child_image_code,
                is_active=True,
            )
            Child.objects.filter(user=user).exclude(id=new_child.id).update(is_active=False)

            return Response(
                {
                    "child_id": new_child.id,
                    "message": "아이 정보 등록이 완료되었습니다."
                },
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            return Response(
                {"error": f"아이 프로필 등록 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
class ChildActivateView(APIView):
    """
    특정 아이를 활성화하는 API
    PUT /api/user/child/<child_id>/activate/
    """
    permission_classes = [IsAuthenticated]

    def put(self, request, child_id):
        
            user = request.user

            # 본인 자녀만 활성화 가능
            try:
                child = Child.objects.get(id=child_id, user=user)
            except Child.DoesNotExist:
                return Response(
                    {"error": "해당 아이 정보를 찾을 수 없습니다."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 선택한 아이 활성화
            child.is_active = True
            child.save()

            # 해당 유저의 다른 아이는 모두 비활성화
            Child.objects.filter(user=user).exclude(id=child_id).update(is_active=False)

            return Response(
                {
                    "child_id": child_id,
                    "message": "아이 활성화가 완료되었습니다."
                },
                status=status.HTTP_200_OK
            )


        
class ChildDetailView(APIView):
    """
    특정 아이의 상세 정보를 조회하는 API
    GET /api/user/child/<child_id>/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, child_id):
        try:
            user = request.user

            # 본인 소유 자녀만 조회 가능
            try:
                child = Child.objects.get(id=child_id, user=user)
            except Child.DoesNotExist:
                return Response(
                    {"error": "해당 아이 정보를 찾을 수 없습니다."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {
                    "child_id": child.id,
                    "name": child.name,
                    "birth_date": child.birth.strftime("%Y-%m-%d") if child.birth else None,
                    "gender": child.gender,
                    "child_image_code": child.child_image_code,
                    "is_active": child.is_active
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"error": f"아이 정보 조회 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
class ChildUpdateView(APIView):
    """
    기존 아이의 정보를 수정하는 API
    PUT /api/user/child/<child_id>/
    """
    permission_classes = [IsAuthenticated]

    def put(self, request, child_id):
        try:
            user = request.user
            data = request.data

            # 수정할 child 가져오기 (본인 소유만 가능)
            try:
                child = Child.objects.get(id=child_id, user=user)
            except Child.DoesNotExist:
                return Response(
                    {"error": "해당 아이 정보를 찾을 수 없습니다."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 필드 업데이트
            if "name" in data:
                child.name = data["name"]
            if "birth_date" in data:
                child.birth = data["birth_date"]
            if "gender" in data:
                child.gender = data["gender"]
            if "child_image_code" in data:
                child.child_image_code = data["child_image_code"]

            child.save()

            return Response(
                {"message": "아이 정보가 성공적으로 수정되었습니다."},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"error": f"아이 정보 수정 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
class ChildDeleteView(APIView):
    """
    특정 아이 프로필을 삭제하는 API
    DELETE /api/accounts/child/<child_id>/delete/
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, child_id):
        try:
            user = request.user

            # 본인 소유 자녀만 삭제 가능
            try:
                child = Child.objects.get(id=child_id, user=user)
            except Child.DoesNotExist:
                return Response(
                    {"error": "해당 아이 정보를 찾을 수 없습니다."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 삭제 수행
            child.delete()

            return Response(
                {"message": "아이 프로필이 성공적으로 삭제되었습니다."},
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"아이 삭제 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        
class VoiceCreateView(APIView):
    """
    새로운 TTS용 목소리 메타데이터를 등록하는 API
    (이름, 프로필 이미지 URL)
    """

    permission_classes = [IsAuthenticated]
    ALLOWED_CODES = ["voice1", "voice2", "voice3", "voice4"]

    def post(self, request):
        try:
            user = request.user
            data = request.data
            voice_name = data.get("voice_name")
            voice_image_code = data.get("voice_image_code", "voice1")

            # 필수값 체크
            if not voice_name:
                return Response(
                    {"error": "voice_name은 필수 입력 항목입니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            # image_code 유효성 체크
            if voice_image_code not in self.ALLOWED_CODES:
                return Response(
                    {"error": "유효하지 않은 voice_image_code 입니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )


            # Voice 객체 생성
            voice = ClonedVoice.objects.create(
                user=user,
                voice_name=voice_name,
                voice_image_code=voice_image_code, 
                created_at=timezone.now(),
            )

            return Response(
                {
                    "voice_id": voice.id,
                    "message": "목소리 메타데이터 등록이 시작되었습니다. 녹음을 진행해주세요.",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"목소리 메타데이터 생성 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class VoiceCloneView(APIView):
    permission_classes = [IsAuthenticated]

    BASE_SPEAKER_AUDIO = os.path.join(
    settings.BASE_DIR.parent, 
    "checkpoints_v2/base_speakers/base_ko.wav"
)

    BASE_SPEAKER_SE = os.path.join(
        settings.BASE_DIR.parent, 
        "checkpoints_v2/base_speakers/ses/kr.pth"
    )

    def post(self, request):
        tmp_ref_path = None
        output_path = None
        se_path = None
        try:
            voice_id = request.data.get("voice_id")
            if not voice_id:
                return Response({"error": "voice_id가 필요합니다."}, status=400)
            try:
                voice = ClonedVoice.objects.get(id=voice_id, user=request.user)
            except ClonedVoice.DoesNotExist:
                return Response({"error": "해당 voice_id를 찾을 수 없습니다."}, status=404)
            
            reference_audio = request.FILES.get("reference_audio")
            if not reference_audio:
                return Response({"error": "reference_audio가 필요합니다."}, status=400)
            
            # reference_audio → S3 업로드
            s3_ref_path = default_storage.save(
                f"reference_audio/{voice_id}.wav", File(reference_audio)
            )
            reference_audio_url = default_storage.url(s3_ref_path)

            # DB에 저장
            voice.reference_audio_url = reference_audio_url
            voice.save()

            # reference_audio 임시 파일로 저장 (OpenVoice 입력용)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_ref:
                for chunk in reference_audio.chunks():
                    tmp_ref.write(chunk)
                tmp_ref_path = tmp_ref.name

            # 출력 경로 준비
            output_dir = "outputs_v2"
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"{request.user.id}_clone.wav")
            se_path = os.path.join(output_dir, f"{request.user.id}_se.pth")

            # 클로닝 수행 (서비스 함수 호출)
            output_path, target_se = clone_voice(
                source_audio_path=self.BASE_SPEAKER_AUDIO,
                reference_audio_path=tmp_ref_path,
                base_speaker_se_path=self.BASE_SPEAKER_SE,
                output_path=output_path
            )
            # SE 벡터 파일로 저장
            import torch
            torch.save(target_se, se_path)

            # S3 업로드
            with open(output_path, "rb") as f:
                s3_voice_path = default_storage.save(
                    f"tts_outputs/{request.user.id}_clone.wav", File(f)
                )
            with open(se_path, "rb") as f:
                s3_se_path = default_storage.save(
                    f"tts_outputs/{request.user.id}_se.pth", File(f)
                )
            cloned_url = default_storage.url(s3_voice_path)
            se_url = default_storage.url(s3_se_path)

            # 기존 Voice 객체 업데이트
            voice.cloned_voice_file = s3_voice_path
            voice.se_file = s3_se_path
            voice.save()

            return Response({
                "voice_id": voice.id,
                "voice_name": voice.voice_name,
                "reference_audio_url": reference_audio_url,
                "cloned_voice_url": cloned_url,
                "se_file_url": se_url
            }, status=200)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

        finally:
            # 🧹 임시 파일 정리 (에러 여부와 관계없이 실행)
            for path in [tmp_ref_path, output_path, se_path]:
                if path and os.path.exists(path):
                    os.remove(path)


class VoiceDetailView(APIView):
    """
    특정 목소리의 상세 정보를 조회하거나 메타데이터를 수정하는 API
    GET /api/voice/<voice_id>/
    PATCH /api/voice/<voice_id>/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, voice_id):
        try:
            user = request.user
            voice = ClonedVoice.objects.get(id=voice_id, user=user)
            data = {
                "voice_id": voice.id,
                "voice_name": voice.voice_name,
                "voice_image_code": voice.voice_image_code,
                "cloned_voice_file": (
                    request.build_absolute_uri(voice.cloned_voice_file.url)
                    if voice.cloned_voice_file else None
                ),
                "created_at": voice.created_at.strftime("%Y-%m-%d")
            }
            return Response(data, status=status.HTTP_200_OK)

        except ClonedVoice.DoesNotExist:
            return Response({"error": "해당 목소리 정보를 찾을 수 없습니다."}, status=400)

    def patch(self, request, voice_id):
        try:
            user = request.user
            data = request.data
            # 수정 가능한 필드 목록
            allowed_fields = {"voice_name", "voice_image_code"}

            # 허용되지 않은 필드가 들어오면 에러 반환
            invalid_fields = set(data.keys()) - allowed_fields
            if invalid_fields:
                return Response(
                    {
                        "error": f"유효하지 않은 필드입니다: {', '.join(invalid_fields)}. "
                                f"허용된 필드는 voice_name, voice_image_code 입니다."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            voice = ClonedVoice.objects.get(id=voice_id, user=user)

            if "voice_name" in data:
                voice.voice_name = data["voice_name"]
            if "voice_image_code" in data:    
                voice.voice_image_code = data["voice_image_code"]
            voice.save()

            return Response(
                {
                    "message": "보이스 정보가 수정되었습니다."
                },
                status=status.HTTP_200_OK,
            )

        except ClonedVoice.DoesNotExist:
            return Response({"error": "해당 목소리를 찾을 수 없습니다."}, status=400)
        
    def delete(self, request, voice_id):
        """목소리 완전 삭제 (DB + S3 파일 전부 삭제)"""
        try:
            user = request.user
            voice = ClonedVoice.objects.get(id=voice_id, user=user)

            import boto3
            from django.conf import settings

            s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME,
            )

            bucket_name = settings.AWS_STORAGE_BUCKET_NAME

            # ----------------------------------------------------
            # 1) S3에서 reference_audio 삭제
            # ----------------------------------------------------
            if voice.reference_audio_url:
                try:
                    # reference_audio_url은 전체 URL → 파일 key만 추출해야 함
                    file_key = voice.reference_audio_url.replace(f"https://{bucket_name}.s3.amazonaws.com/", "")
                    s3.delete_object(Bucket=bucket_name, Key=file_key)
                except Exception as e:
                    print("S3 reference_audio 삭제 실패:", e)

            # ----------------------------------------------------
            # 2) S3에서 cloned_voice_file 삭제
            # ----------------------------------------------------
            if voice.cloned_voice_file:
                try:
                    s3.delete_object(Bucket=bucket_name, Key=voice.cloned_voice_file.name)
                except Exception as e:
                    print("S3 cloned_voice_file 삭제 실패:", e)

            # ----------------------------------------------------
            # 3) S3에서 se_file 삭제
            # ----------------------------------------------------
            if voice.se_file:
                try:
                    s3.delete_object(Bucket=bucket_name, Key=voice.se_file.name)
                except Exception as e:
                    print("S3 se_file 삭제 실패:", e)

            # ----------------------------------------------------
            # 4) DB에서 voice 삭제
            # ----------------------------------------------------
            voice.delete()

            return Response(
                {"message": "목소리가 성공적으로 삭제되었습니다."},
                status=status.HTTP_200_OK,
            )

        except ClonedVoice.DoesNotExist:
            return Response(
                {"error": "해당 목소리를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            return Response(
                {"error": f"삭제 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
class VoiceListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            voices = ClonedVoice.objects.filter(user=user)

            result = []

            for v in voices:
                result.append({
                    "voice_id": v.id,
                    "name": v.voice_name,
                    "cloned_voice_url": (
                        request.build_absolute_uri(v.cloned_voice_file.url)
                        if v.cloned_voice_file else None
                    ),
                    "voice_image_code": v.voice_image_code, 
                })

            return Response({"voices": result}, status=status.HTTP_200_OK)

        except Exception:
            return Response(
                {"error": "목소리 리스트를 불러오는 중 오류가 발생했습니다."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
class ChildrenListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # 사용자 아이 목록 가져오기
        children = user.children.all()

        result = []
        for child in children:
            result.append({
                "child_id": child.id,
                "name": child.name,
                "is_active": child.is_active
            })

        return Response({"children": result}, status=status.HTTP_200_OK)