from django.urls import path
from .views import *

urlpatterns = [
    path("illustration/generate/", GenerateIllustrationsView.as_view()),
    path("AI/illustration/job/<int:job_id>/", IllustrationJobStatusView.as_view()),
    path("illustration/download/<int:story_id>/<int:page_id>/", IllustrationDownloadView.as_view()),
    #path("extention/generate/", GenerateExtentionView.as_view()),
    path("extention/generate/", CreateChatRoomView.as_view()),
    path("chatroom/<int:pk>/", ChatRoomView.as_view())
]
