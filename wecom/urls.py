from django.urls import path
from . import views
urlpatterns = [
    path('verify/', views.wecom_verify, name='wecom_verify'),
    path('callback/', views.ms_callback, name='ms_callback'),
    path('reset/', views.reset_wecom_verify, name='wecom_reset'),
    path('app/', views.go_app, name='wecom_app'),
    path('app_login/', views.app_login, name='app_login'),
]
