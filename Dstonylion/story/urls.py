from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    StoryOptionView,
    StoryDraftViewSet,
    StoryKeywordSaveView,
    StoryStyleSelectView,
    IllustrationRegenerateView,
)

router = DefaultRouter()
router.register(r'api/story/draft', StoryDraftViewSet, basename='story-draft')

urlpatterns = [
    path('story/option/', StoryOptionView.as_view(), name='story-option'),
    path('api/story/keywords/', StoryKeywordSaveView.as_view(), name='story-keyword-save'),
    path('api/story/style/', StoryStyleSelectView.as_view(), name='story-style-select'),
    path('api/illustration/regenerate/', IllustrationRegenerateView.as_view(), name='illustration-regenerate'),
    path('', include(router.urls)),
]
