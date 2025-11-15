from django.urls import path, include
from .views import *

urlpatterns = [
    path('options/', StoryOptionSaveView.as_view()),
    path("draft/", StoryDraftUpdateView.as_view()), 
    path('morals/', MoralThemeListView.as_view()),
    path('story-morals/', StoryMoralSaveView.as_view()),
    path('story-morals/recommend/', RecommendMoralView.as_view()),
    path('generate/', StoryGenerateView.as_view()),
    path('', StoryListView.as_view()),
    path('reset/', StoryResetView.as_view()),

    #path('api/illustration/regenerate/', IllustrationRegenerateView.as_view(), name='illustration-regenerate'),
    #path('generate/illustrations/', StoryJsonImportView.as_view()),

    path('classic/upload/', ClassicStoryUploadView.as_view()),
    path('<int:story_id>/', StoryDetailView.as_view()),
    path('<int:story_id>/pages/', StoryPageListView.as_view()),
    path('<int:story_id>/script/', StoryScriptView.as_view())
]