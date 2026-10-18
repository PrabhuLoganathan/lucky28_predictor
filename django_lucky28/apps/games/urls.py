from django.urls import path
from . import views
from . import logger_api
from . import alert_views
from . import alert_management

urlpatterns = [
    path('alerts/', alert_views.monitor, name='alerts_dashboard'),
    path('alerts/rules/', alert_management.rules, name='alert_rules'),
    path('alerts/rules/new/', alert_management.rule_edit, name='alert_rule_new'),
    path('alerts/rules/defaults/', alert_management.rule_defaults, name='alert_rule_defaults'),
    path('alerts/rules/<int:pk>/edit/', alert_management.rule_edit, name='alert_rule_edit'),
    path('alerts/rules/<int:pk>/toggle/', alert_management.rule_toggle, name='alert_rule_toggle'),
    path('alerts/rules/<int:pk>/delete/', alert_management.rule_delete, name='alert_rule_delete'),
    path('alerts/destinations/', alert_management.destinations, name='alert_destinations'),
    path('alerts/destinations/new/', alert_management.destination_edit, name='alert_destination_new'),
    path('alerts/destinations/<int:pk>/edit/', alert_management.destination_edit, name='alert_destination_edit'),
    path('alerts/destinations/<int:pk>/toggle/', alert_management.destination_toggle, name='alert_destination_toggle'),
    path('alerts/destinations/<int:pk>/delete/', alert_management.destination_delete, name='alert_destination_delete'),
    path('alerts/destinations/<int:pk>/test/', alert_management.destination_test, name='alert_destination_test'),
    path('alerts/settings/', alert_management.configuration, name='alert_settings'),
    path('alerts/worker/<str:action>/', alert_management.worker_action, name='alert_worker_action'),
    path('alerts/deliveries/', alert_management.deliveries, name='alert_deliveries'),
    path('alerts/deliveries/<int:pk>/', alert_management.delivery_detail, name='alert_delivery_detail'),
    path('alerts/deliveries/<int:pk>/image/', alert_management.delivery_image, name='alert_delivery_image'),
    path('alerts/deliveries/<int:pk>/<str:action>/', alert_management.delivery_action, name='alert_delivery_action'),
    path('alerts/history/<int:pk>/', alert_management.evidence_detail, name='alert_evidence_detail'),
    path('alerts/history/<int:pk>/card/', alert_management.evidence_card, name='alert_evidence_card'),
    path('alerts/evidence/<int:pk>/', alert_views.evidence, name='alert_evidence'),
    path('api/alerts/latest/', alert_views.latest_alerts, name='alerts_latest'),
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
    
    # Live Gaps
    path("gaps/", views.live_gaps_dashboard, name="live_gaps_dashboard"),
    path("api/gaps/", views.api_live_gaps, name="api_live_gaps"),
    
    # Import
    path("games/import/", views.import_games, name="import_games"),
]
