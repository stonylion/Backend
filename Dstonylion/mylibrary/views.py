from rest_framework import status, views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Library, History
from .serializers import LibrarySerializer, HistorySerializer
from story.models import Story
from django.contrib.auth import get_user_model

User = get_user_model()

class LibraryListView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        libraries = Library.objects.filter(user=request.user).select_related("story").order_by("-last_viewed_time")
        serializer = LibrarySerializer(libraries, many=True)
        return Response({
            "count": libraries.count(),
            "results": serializer.data
        })

    def post(self, request, format=None):
        story_id = request.data.get("story")
        story = get_object_or_404(Story, id=story_id)

        library, created = Library.objects.get_or_create(
            user=request.user,
            story=story,
            defaults={"last_viewed_time": timezone.now()}
        )
        if not created:
            library.last_viewed_time = timezone.now()
            library.save()

        serializer = LibrarySerializer(library)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class LibraryDetailView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, pk, user):
        library = get_object_or_404(Library, pk=pk, user=user)
        return library

    def get(self, request, pk, format=None):
        library = self.get_object(pk, request.user)
        serializer = LibrarySerializer(library)
        return Response(serializer.data)

    def put(self, request, pk, format=None):
        library = self.get_object(pk, request.user)
        serializer = LibrarySerializer(library, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(last_viewed_time=timezone.now())
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, format=None):
        library = self.get_object(pk, request.user)
        library.delete()
        return Response({"message": "삭제되었습니다."}, status=status.HTTP_204_NO_CONTENT)


class HistoryListView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        histories = History.objects.filter(user=request.user).select_related("story").order_by("-viewed_time")
        serializer = HistorySerializer(histories, many=True)
        return Response({
            "count": histories.count(),
            "results": serializer.data
        })

    def post(self, request, format=None):
        story_id = request.data.get("story")
        story = get_object_or_404(Story, id=story_id)

        history = History.objects.create(user=request.user, story=story)

        Library.objects.update_or_create(
            user=request.user,
            story=story,
            defaults={"last_viewed_time": timezone.now()}
        )

        serializer = HistorySerializer(history)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
