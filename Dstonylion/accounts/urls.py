from django.urls import path
from .views import *

urlpatterns = [
    path("signup/", SignupView.as_view()),
    path("login/", LoginView.as_view()),
    path("user/logout/", LogoutView.as_view(), name="logout"),
    path("user/delete/", UserDeleteView.as_view(), name="user-delete"),
    path("mypage/", MyPageView.as_view(), name="mypage"),
    path("user/profile/", UserProfileView.as_view(), name="user-profile"),
    path("user/profile/update/", UserProfileUpdateView.as_view(), name="user-profile-update"),
    path("user/child/", ChildCreateView.as_view(), name="child-create"),
    path("user/child/detail/<int:child_id>/", ChildDetailView.as_view(), name="child-detail"),
    path("user/child/<int:child_id>/", ChildUpdateView.as_view(), name="child-update"),
    path("voice/list/", VoiceListView.as_view(), name="voice-list"),
    path("voice/", VoiceCreateView.as_view(), name="voice-create"),
    path("voice/<int:voice_id>/", VoiceDetailView.as_view(), name="voice-detail"),
    path("user/voice/clone/", VoiceCloneView.as_view(), name="user-voice-clone"),
]