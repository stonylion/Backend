from django.shortcuts import render
from rest_framework.response import Response
from rest_framework import status, views
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
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
            {"message":"로그인 실패", "errors":serializer.errors},
            status=status.HTTP_400_BAD_REQUEST)