from django.urls import path
from .views import *

urlpatterns = [
    path("signup/", SignupView.as_view()),
    path("login/", LoginView.as_view()),
    path("api/user/logout/", LogoutView.as_view(), name="logout"),
    path("delete/", UserDeleteView.as_view(), name="user-delete"),
    path("user/profile/", UserProfileView.as_view(), name="user-profile"),
    path("api/user/profile/update/", UserProfileUpdateView.as_view(), name="user-profile-update"),
    path("api/user/child/", ChildCreateView.as_view(), name="child-create"),
    path("api/user/child/detail/<int:child_id>/", ChildDetailView.as_view(), name="child-detail"),
    path("api/user/child/<int:child_id>/", ChildUpdateView.as_view(), name="child-update"),
    path("api/voice/clone/", LocalVoiceCloneAPIView.as_view(), name="voice-clone"),
    path("api/voice/list/", VoiceListView.as_view(), name="voice-list"),
    path("api/voice/", VoiceCreateView.as_view(), name="voice-create"),
    path("api/voice/<int:voice_id>/", VoiceDetailView.as_view(), name="voice-detail"),
    path("api/voice/<int:voice_id>/", VoiceUpdateView.as_view(), name="voice-update"),
]