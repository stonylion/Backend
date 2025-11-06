from django.urls import path
from .views import GenerateIllustrationsView

urlpatterns = [
    path("illustration/generate/", GenerateIllustrationsView.as_view()),
]
