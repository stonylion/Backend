from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register(r'api/story/draft', StoryDraftViewSet, basename='story-draft')

urlpatterns = [
    path('story/option/', StoryOptionView.as_view(), name='story-option'),
    path('story/keywords/', StoryKeywordSaveView.as_view(), name='story-keyword-save'),
    path('story/style/', StoryStyleSelectView.as_view(), name='story-style-select'),
    path('illustration/regenerate/', IllustrationRegenerateView.as_view(), name='illustration-regenerate'),
    path("user/voice/tts/", ClonedVoiceTTSView.as_view(), name="cloned-voice-tts"),
    path('', include(router.urls)),
]
