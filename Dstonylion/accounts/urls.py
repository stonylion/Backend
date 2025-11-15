from django.urls import path
from .views import *

urlpatterns = [
    path("signup/", SignupView.as_view()),
    path("login/", LoginView.as_view()),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("delete/", UserDeleteView.as_view(), name="user-delete"),
    path("mypage/", MyPageView.as_view(), name="mypage"),
    path("profile/", UserProfileView.as_view(), name="user-profile"),
    path("child/<int:child_id>/activate/", ChildActivateView.as_view()),
    path("profile/update/", UserProfileUpdateView.as_view(), name="user-profile-update"),
    path("child/", ChildCreateView.as_view(), name="child-create"),
    path("child/detail/<int:child_id>/", ChildDetailView.as_view(), name="child-detail"),
    path("child/<int:child_id>/", ChildUpdateView.as_view(), name="child-update"),
    path("voice/list/", VoiceListView.as_view(), name="voice-list"),
    path("voice/", VoiceCreateView.as_view(), name="voice-create"),
    path("voice/<int:voice_id>/", VoiceDetailView.as_view(), name="voice-detail"),
    path("voice/clone/", VoiceCloneView.as_view(), name="user-voice-clone"),
]