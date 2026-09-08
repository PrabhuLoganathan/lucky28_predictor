from django.urls import path
from . import views
from . import logger_api

urlpatterns = [
    path('api/logger/health/', logger_api.health, name='logger_health'),
    path('api/logger/events/', logger_api.events, name='logger_events'),
    path("api/games/pre/", views.upsert_pre),
    path("api/games/<str:game_no>/winner/", views.update_winner),
    path("api/games/<str:game_no>/", views.GameRoundRetrieve.as_view()),
    path("api/games/", views.GameRoundList.as_view()),
    
    # UI
    path("", views.game_dashboard, name="home"),
    path("games/dashboard/", views.game_dashboard, name="game_dashboard"),
    path("games/dashboard/rows/", views.game_dashboard_rows, name="game_dashboard_rows"),
    path("games/detail/<str:game_no>/", views.game_detail, name="game_detail"),
    path("days/", views.daily_archive, name="daily_archive"),
    path("days/export/", views.export_day, name="export_day"),
    path("days/delete/", views.delete_day, name="delete_day"),
    
    # Signals
    path("signals/", views.signals_dashboard, name="signals_dashboard"),
    path("signals/config/", views.signals_config, name="signals_config"),
    path("signals/api/config/<str:action>/", views.signals_config_action, name="signals_config_action"),

    # Pro Analysis
    path("analysis/", views.pro_dashboard, name="pro_dashboard"),
    path("analysis/api/simulate/", views.api_analysis_simulate, name="api_analysis_simulate"),
    
    # Import
    path("games/import/", views.import_games, name="import_games"),
]
