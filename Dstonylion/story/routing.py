from django.urls import path
from .consumers import *

websocket_urlpatterns = [
    path("story/draft-stt/", DraftConsumer.as_asgi(), name="draft-stt"),
]
