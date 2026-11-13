from django.urls import path

from . import views

app_name = 'api'

urlpatterns = [
    path('catalog/', views.catalog, name='catalog'),
    path('genres/', views.genres, name='genres'),
    path('titles/<int:pk>/', views.title_detail, name='title-detail'),
    path('titles/<int:pk>/similar/', views.similar, name='title-similar'),
    path('similarity-matrix/', views.matrix, name='similarity-matrix'),
    path('map/points/', views.map_points, name='map-points'),
    path('profile/', views.profile, name='profile'),
    path('profile/interactions/', views.add_interaction, name='interaction-add'),
    path('profile/interactions/<int:title_id>/', views.remove_interaction, name='interaction-remove'),
    path('profile/insights/', views.profile_insights, name='profile-insights'),
    path('profile/account-offer/dismiss/', views.dismiss_account_offer, name='account-offer-dismiss'),
    path('preferences/', views.user_preferences, name='preferences'),
    path('recommendations/', views.recommendations, name='recommendations'),
    path('cron/purge-anonymous/', views.cron_purge_anonymous, name='cron-purge-anonymous'),
]
