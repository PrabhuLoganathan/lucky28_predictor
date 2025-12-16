from django.contrib import admin
from django.urls import path, include

urlpatterns=[
    path('admin/',admin.site.urls),
    path('history/', include('gameapp.urls')),
    path('', include('games.urls')),
]
