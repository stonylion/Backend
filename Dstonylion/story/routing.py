from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/story/transcribe/$", consumers.AudioTranscriptionConsumer.as_asgi()),
]
