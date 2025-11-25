from django.urls import path
from .views import *

urlpatterns = [
    path("illustration/generate/", GenerateIllustrationsView.as_view()),
    path("illustration/download/<int:story_id>/<int:page_id>/", IllustrationDownloadView.as_view()),
    
    path("stories/<int:story_id>/extend-chat/stream/", ExtendChatStreamView.as_view()),
    path("stories/<int:story_id>/extend/", ExtendStoryCreateView.as_view()),
    path("stories/<int:extended_id>/continue-from/<int:original_id>/", ContinueFromView.as_view()),

    path("extend-chat-stt/", STTView.as_view()),
    path("extend-chat-tts/", TTSView.as_view()),
]
