from django.urls import path
from . import views

app_name = 'production'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('batches/', views.batch_list, name='batch_list'),
    path('batches/<int:pk>/', views.batch_detail, name='batch_detail'),
    path('batches/create/', views.batch_create, name='batch_create'),
    path('batches/<int:pk>/edit/', views.batch_edit, name='batch_edit'),
    path('inspections/', views.inspection_list, name='inspection_list'),
    path('inspections/create/<int:batch_id>/', views.inspection_create, name='inspection_create'),
    path('stages/create/<int:batch_id>/', views.stage_create, name='stage_create'),
    path('stages/<int:pk>/complete/', views.stage_complete, name='stage_complete'),
    path('crystallization/<int:batch_id>/', views.crystallization_create, name='crystallization_create'),
    path('abnormal/', views.abnormal_list, name='abnormal_list'),
    path('abnormal/create/<int:batch_id>/', views.abnormal_create, name='abnormal_create'),
    path('abnormal/<int:pk>/edit/', views.abnormal_edit, name='abnormal_edit'),
    path('comparison/', views.batch_comparison, name='batch_comparison'),
]
