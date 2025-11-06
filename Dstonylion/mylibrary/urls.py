from django.urls import path
from .views import LibraryListView, LibraryDetailView, HistoryListView

urlpatterns = [
    path("library/", LibraryListView.as_view(), name="library-list"),
    path("library/<int:pk>/", LibraryDetailView.as_view(), name="library-detail"),
    path("history/", HistoryListView.as_view(), name="history-list"),
]