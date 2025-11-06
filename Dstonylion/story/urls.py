from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StoryViewSet, StoryJsonImportView

router = DefaultRouter()
router.register(r"stories", StoryViewSet, basename="story")

urlpatterns = [
    path("", include(router.urls)),
    path("import-json/", StoryJsonImportView.as_view(), name="import-json"),
]
