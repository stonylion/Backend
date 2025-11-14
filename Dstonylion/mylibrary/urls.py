from django.urls import path
from .views import *

urlpatterns = [
    path("recentread/", RecentReadView.as_view()),
    path("recentgenerated/", RecentGeneratedView.as_view()),
    path("<int:library_id>/", LibraryDetailView.as_view()),
]