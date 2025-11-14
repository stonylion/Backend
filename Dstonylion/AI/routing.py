from django.urls import path

from AI import consumers

websocket_urlpatterns = [
    path("ws/room/<int:room_id>/messages/", consumers.ChatConsumer.as_asgi()),
]