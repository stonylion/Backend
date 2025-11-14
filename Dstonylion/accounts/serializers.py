from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import *

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "birth", "gender", "profile_image"]

class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "birth", "gender", "profile_image"]

    def create(self, validated_data):
        default_image_url = "profiles/default_profile.png" # static 이미지 링크
        profile_image = validated_data.get("profile_image", default_image_url)
        
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email"),
            password=validated_data["password"],
            birth=validated_data.get("birth"),
            gender=validated_data.get("gender"),
            profile_image=profile_image, 
        )
        return user

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs["username"], password=attrs["password"])

        if not user:
            raise serializers.ValidationError("아이디 또는 비밀번호가 올바르지 않습니다.")

        attrs["user"] = user   
        return attrs 
    