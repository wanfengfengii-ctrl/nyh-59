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
    
    path('stock/', views.material_stock_dashboard, name='material_stock_dashboard'),
    path('stock/categories/', views.material_category_list, name='material_category_list'),
    path('stock/suppliers/', views.material_supplier_list, name='material_supplier_list'),
    path('stock/materials/', views.material_list, name='material_list'),
    path('stock/materials/<int:pk>/', views.material_detail, name='material_detail'),
    path('stock/inbound/', views.material_inbound_list, name='material_inbound_list'),
    path('stock/inbound/<int:pk>/', views.material_inbound_detail, name='material_inbound_detail'),
    path('stock/outbound/', views.material_outbound_list, name='material_outbound_list'),
    path('stock/loss/', views.material_loss_list, name='material_loss_list'),
    path('stock/ledger/', views.material_ledger, name='material_ledger'),
    path('stock/statistics/', views.material_statistics, name='material_statistics'),
    path('stock/alerts/', views.material_stock_alert_list, name='material_stock_alert_list'),
    path('stock/alerts/<int:pk>/', views.material_stock_alert_detail, name='material_stock_alert_detail'),
    path('stock/alert-check/', views.run_stock_alert_check, name='run_stock_alert_check'),
    
    path('batches/<int:batch_id>/materials/', views.batch_material_trace, name='batch_material_trace'),
    
    path('stock/materials/<int:pk>/toggle-status/', views.material_toggle_status, name='material_toggle_status'),
    path('stock/outbound/<int:pk>/', views.material_outbound_detail, name='material_outbound_detail'),
    path('stock/loss/<int:pk>/', views.material_loss_detail, name='material_loss_detail'),
    path('stock/ledger/export/', views.material_ledger_export, name='material_ledger_export'),
]
