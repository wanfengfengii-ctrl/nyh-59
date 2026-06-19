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
    path('stages/<int:pk>/complete-audit/', views.stage_complete_with_audit, name='stage_complete_with_audit'),
    path('crystallization/<int:batch_id>/', views.crystallization_create, name='crystallization_create'),
    path('abnormal/', views.abnormal_list, name='abnormal_list'),
    path('abnormal/create/<int:batch_id>/', views.abnormal_create, name='abnormal_create'),
    path('abnormal/<int:pk>/edit/', views.abnormal_edit, name='abnormal_edit'),
    path('comparison/', views.batch_comparison, name='batch_comparison'),
    
    path('alerts/', views.alert_center, name='alert_center'),
    path('alerts/<int:pk>/', views.alert_detail, name='alert_detail'),
    path('alert-rules/', views.alert_rules, name='alert_rules'),
    path('alert-check/', views.run_alert_check, name='run_alert_check'),
    
    path('audits/', views.stage_audit_list, name='stage_audit_list'),
    path('audits/<int:stage_id>/submit/', views.stage_audit_submit, name='stage_audit_submit'),
    path('audits/<int:pk>/process/', views.stage_audit_process, name='stage_audit_process'),
    
    path('quality-analysis/', views.material_quality_analysis, name='material_quality_analysis'),
    
    path('parameter-recommendation/', views.parameter_recommendation, name='parameter_recommendation'),
    
    path('abnormal-closure/', views.abnormal_closure_list, name='abnormal_closure_list'),
    path('abnormal-closure/create/<int:abnormal_id>/', views.abnormal_closure_create, name='abnormal_closure_create'),
    path('abnormal-closure/<int:pk>/', views.abnormal_closure_detail, name='abnormal_closure_detail'),
    
    path('exports/', views.export_list, name='export_list'),
    path('exports/create/', views.export_create, name='export_create'),
    path('exports/<int:pk>/download/', views.export_download, name='export_download'),
    
    path('visual-dashboard/', views.visual_dashboard, name='visual_dashboard'),
]
