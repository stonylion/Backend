from django.urls import path
from .consumers import *

websocket_urlpatterns = [
    path("ws/story/record/", DraftConsumer.as_asgi(), name="draft-stt"),
]
