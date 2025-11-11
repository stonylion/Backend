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
from accounts.services.openvoice_service import OpenVoiceService
import tempfile
from django.core.files import File
from django.utils import timezone
from django.core.files.base import ContentFile

from .models import User, Child
from mylibrary.models import Library
from story.models import Story, Illustrations
from accounts.models import Child, Voice
from .serializers import *
# Create your views here.

def get_tokens(user):
    token = RefreshToken.for_user(user)
    refresh = str(token)
    access = str(token.access_token)
    return{
        "access_token": access,
    }

class SignupView(views.APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            tokens = get_tokens(user)
            return Response(
                {"message":"회원가입 성공", "user": serializer.data, "token":tokens},
                status=status.HTTP_201_CREATED)
        return Response(
            {"message":"회원가입 실패"},
            serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginView(views.APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data
            tokens = get_tokens(user)
            return Response(
                {"message":"로그인 성공", "user":UserSerializer(user).data, "token":tokens},
                status=status.HTTP_200_OK)
        return Response(
            {"message":"로그인 실패"},
            serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
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
                Voice.objects.filter(user=user).delete()
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
    

class UserProfileView(APIView):
    """
    로그인한 사용자의 프로필 정보를 조회하는 API
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            serializer = UserSerializer(user)

            return Response(
                {
                    "user_id": user.id,
                    "username": user.username,
                    "birth_date": user.birth.strftime("%Y-%m-%d") if user.birth else None,
                    "email": user.email,
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
            if "name" in data:
                user.username = data["name"]

            # 이메일 수정
            if "email" in data:
                user.email = data["email"]

            # 생년월일 수정
            if "birth" in data:
                user.birth = data["birth"]

            # 성별 수정
            if "gender" in data:
                user.gender = data["gender"]

            # 비밀번호 수정
            if "password" in data and data["password"]:
                user.set_password(data["password"])

            # 프로필 이미지 수정
            if "profile_image_url" in data:
                user.profile_image = data["profile_image_url"]

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

    def post(self, request):
        try:
            user = request.user
            data = request.data

            name = data.get("name")
            birth_date = data.get("birth_date")
            gender = data.get("gender")
            profile_image_url = data.get("profile_image_url")

            # 필수 필드 확인
            if not name:
                return Response(
                    {"error": "이름은 필수 항목입니다."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Child 인스턴스 생성
            child = Child.objects.create(
                user=user,
                name=name,
                birth=birth_date,
                gender=gender,
                profile_image=profile_image_url
            )

            return Response(
                {
                    "child_id": child.id,
                    "message": "아이 정보 등록이 완료되었습니다."
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"error": f"아이 프로필 등록 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
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
                    "profile_image_url": (
                        child.profile_image.url if child.profile_image else None
                    ),
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
            if "profile_image_url" in data:
                child.profile_image = data["profile_image_url"]

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
        

class VoiceListView(APIView):
    """
    사용자가 등록한 모든 TTS용 목소리 리스트 조회 API
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            voices = Voice.objects.filter(user=user)

            voice_data = []
            for v in voices:
                voice_data.append({
                    "voice_id": v.id,
                    "name": v.name,
                    "language": getattr(v, "language", "ko"),
                    "created_at": v.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if v.created_at else None,
                    "file_url": v.voice_file.url if v.voice_file else None,
                })

            return Response({"voices": voice_data}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": f"목소리 리스트를 불러오는 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
class VoiceCreateView(APIView):
    """
    새로운 TTS용 목소리 메타데이터를 등록하는 API
    (이름, 프로필 이미지 URL)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            data = request.data

            name = data.get("name")
            profile_image_url = data.get("profile_image_url")

            # ✅ 필수값 체크
            if not name:
                return Response(
                    {"error": "name은 필수 입력 항목입니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Voice 객체 생성
            voice = Voice.objects.create(
                user=user,
                name=name,
                created_at=timezone.now(),
            )

            # 이미지 URL 저장 (optional)
            if profile_image_url:
                voice.profile_image = profile_image_url
                voice.save()

            return Response(
                {
                    "voice_id": voice.id,
                    "message": "목소리 등록이 시작되었습니다. 녹음을 진행해주세요.",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": f"목소리 생성 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
            voice = Voice.objects.get(id=voice_id, user=user)
            data = {
                "voice_id": voice.id,
                "name": voice.name,
                "image_url": voice.profile_image.url if voice.profile_image else None,
                "audio_file_url": voice.voice_file.url if voice.voice_file else None,
                "created_at": voice.created_at.strftime("%Y-%m-%d") if voice.created_at else None,
            }
            return Response(data, status=status.HTTP_200_OK)

        except Voice.DoesNotExist:
            return Response({"error": "해당 목소리 정보를 찾을 수 없습니다."}, status=400)

    def patch(self, request, voice_id):
        try:
            user = request.user
            data = request.data
            voice = Voice.objects.get(id=voice_id, user=user)

            if "name" in data:
                voice.name = data["name"]
            if "image_url" in data:
                voice.profile_image = data["image_url"]
            voice.save()

            return Response(
                {
                    "message": "보이스 정보가 수정되었습니다.",
                    "voice_id": voice.id,
                    "name": voice.name,
                    "image_url": (
                        voice.profile_image.url if voice.profile_image else None
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except Voice.DoesNotExist:
            return Response({"error": "해당 목소리를 찾을 수 없습니다."}, status=400)
        
    def delete(self, request, voice_id):
        """목소리 완전 삭제 (DB + S3 + 외부 모델)"""
        try:
            user = request.user
            voice = Voice.objects.get(id=voice_id, user=user)

            # ✅ 1. S3 음성 파일 삭제
            if voice.voice_file:
                import boto3
                from django.conf import settings

                s3 = boto3.client(
                    "s3",
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_REGION,
                )

                bucket_name = settings.AWS_STORAGE_BUCKET_NAME
                file_key = voice.voice_file.name
                try:
                    s3.delete_object(Bucket=bucket_name, Key=file_key)
                except Exception as e:
                    print(f"S3 삭제 실패: {e}")

            # ✅ 2. 외부 모델 삭제 (MITS/Myshell API 등)
            # (여기서는 placeholder)
            # service = OpenVoiceService()
            # service.delete_model(voice.id)

            # ✅ 3. DB에서 Voice 삭제
            voice.delete()

            return Response(
                {"message": "목소리가 성공적으로 삭제되었습니다."},
                status=status.HTTP_200_OK,
            )
        
        except Voice.DoesNotExist:
            return Response(
                {"error": "해당 목소리를 찾을 수 없습니다."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            return Response(
                {"error": f"삭제 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
class VoiceUploadView(APIView):
    """
    특정 Voice에 오디오 파일을 업로드하고, MITS API에 학습 요청을 보내는 API
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, voice_id):
        try:
            user = request.user
            audio_file = request.FILES.get("audio_file")

            if not audio_file:
                return Response(
                    {"error": "유효하지 않은 오디오 파일입니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Voice 객체 확인
            try:
                voice = Voice.objects.get(id=voice_id, user=user)
            except Voice.DoesNotExist:
                return Response(
                    {"error": "해당 목소리 정보를 찾을 수 없습니다."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ❌❌❌❌❌❌❌S3 업로드
            s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
            )

            bucket_name = settings.AWS_STORAGE_BUCKET_NAME
            file_path = f"voices/user_{user.id}/voice_{voice.id}/original.wav"

            s3.upload_fileobj(audio_file, bucket_name, file_path, ExtraArgs={"ContentType": "audio/wav"})

            s3_url = f"https://{bucket_name}.s3.{settings.AWS_REGION}.amazonaws.com/{file_path}"

            # Voice 모델 업데이트
            voice.voice_file.save(file_path.split("/")[-1], ContentFile(audio_file.read()), save=True)
            voice.save()

            return Response(
                {
                    "message": "음성 파일이 성공적으로 업로드되었습니다.",
                    "file_url": s3_url,
                },
                status=status.HTTP_200_OK,
            )


        except Exception as e:
            return Response(
                {"error": f"업로드 중 오류가 발생했습니다: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
class LocalVoiceCloneAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        input_path = None
        output_path = None

        try:
            user = request.user
            voice_id = request.data.get("voice_id")  # 선택적 (재학습 시)
            voice_file = request.FILES.get("voice_file")
            text = request.data.get("text")
            emotion = request.data.get("emotion", "calm")
            language = request.data.get("language", "ko")

            if not voice_file or not text:
                return Response({"error": "voice_file과 text는 필수입니다."}, status=400)

            # ✅ 1. 임시 파일로 저장
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                for chunk in voice_file.chunks():
                    tmp.write(chunk)
                tmp.flush()
                input_path = tmp.name

            # ✅ 2. OpenVoice 실행
            service = OpenVoiceService()
            output_path = service.clone_and_tts(
                source_path=input_path,
                text=text,
                emotion=emotion,
                language=language
            )

            # ✅ 3. 결과 저장 (새로운 voice or 기존 voice 갱신)
            from django.core.files.base import ContentFile
            with open(output_path, "rb") as f:
                if voice_id:
                    # 기존 Voice 갱신
                    voice_instance = Voice.objects.get(id=voice_id, user=user)
                    voice_instance.emotion = emotion
                    voice_instance.language = language
                    voice_instance.voice_file.save(
                        os.path.basename(output_path),
                        ContentFile(f.read()),
                        save=True
                    )
                    message = "기존 보이스가 재학습되었습니다."
                else:
                    # 새로운 Voice 생성
                    voice_instance = Voice.objects.create(
                        user=user,
                        name=f"Cloned Voice ({emotion})",
                        emotion=emotion,
                        language=language,
                    )
                    voice_instance.voice_file.save(
                        os.path.basename(output_path),
                        ContentFile(f.read()),
                        save=True
                    )
                    message = "새로운 보이스가 생성되었습니다."

            return Response(
                {
                    "message": message,
                    "voice_id": voice_instance.id,
                    "output_audio_url": voice_instance.voice_file.url,
                    "language": language,
                    "emotion": emotion,
                },
                status=status.HTTP_200_OK,
            )

        except Voice.DoesNotExist:
            return Response({"error": "해당 voice_id를 찾을 수 없습니다."}, status=400)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        finally:
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
            if output_path and os.path.exists(output_path):
                os.remove(output_path)



