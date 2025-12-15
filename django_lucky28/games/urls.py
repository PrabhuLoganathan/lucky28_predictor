from django.urls import path
from . import views

urlpatterns = [
    path("api/games/pre/", views.upsert_pre),
    path("api/games/<str:game_no>/winner/", views.update_winner),
    path("api/games/<str:game_no>/", views.GameRoundRetrieve.as_view()),
    path("api/games/", views.GameRoundList.as_view()),
    
    # UI
    path("games/dashboard/", views.game_dashboard, name="game_dashboard"),
    path("games/detail/<str:game_no>/", views.game_detail, name="game_detail"),
]
