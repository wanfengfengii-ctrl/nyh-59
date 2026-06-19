from django.contrib import admin
from .models import (
    RawMaterialBatch, ProcessStage, InspectionRecord, CrystallizationResult, AbnormalDisposal,
    AlertRule, AlertRecord, StageAudit, ParameterRecommendation, ExportRecord,
    MaterialQualityStats, AbnormalClosure
)


@admin.register(RawMaterialBatch)
class RawMaterialBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_no', 'material_source', 'material_weight', 'start_date', 'operator', 'get_stage_display')
    search_fields = ('batch_no', 'material_source', 'operator')
    list_filter = ('start_date', 'material_source')

    def get_stage_display(self, obj):
        return obj.get_stage_display_current()
    get_stage_display.short_description = '当前阶段'


@admin.register(ProcessStage)
class ProcessStageAdmin(admin.ModelAdmin):
    list_display = ('batch', 'stage_type', 'start_time', 'end_time', 'status', 'operator')
    search_fields = ('batch__batch_no', 'operator')
    list_filter = ('stage_type', 'status', 'start_time')


@admin.register(InspectionRecord)
class InspectionRecordAdmin(admin.ModelAdmin):
    list_display = ('batch', 'stage_type', 'inspection_date', 'temperature', 'concentration', 'operator')
    search_fields = ('batch__batch_no', 'operator')
    list_filter = ('stage_type', 'inspection_date')


@admin.register(CrystallizationResult)
class CrystallizationResultAdmin(admin.ModelAdmin):
    list_display = ('batch', 'crystal_weight', 'crystal_purity', 'get_crystallization_rate', 'crystallization_date', 'operator')
    search_fields = ('batch__batch_no', 'operator')
    list_filter = ('crystallization_date',)

    def get_crystallization_rate(self, obj):
        return f'{obj.get_crystallization_rate()}%'
    get_crystallization_rate.short_description = '结晶率'


@admin.register(AbnormalDisposal)
class AbnormalDisposalAdmin(admin.ModelAdmin):
    list_display = ('batch', 'abnormal_type', 'stage_type', 'discover_date', 'disposal_status', 'handler')
    search_fields = ('batch__batch_no', 'handler', 'description')
    list_filter = ('abnormal_type', 'stage_type', 'disposal_status', 'discover_date')


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ('rule_name', 'alert_type', 'stage_type', 'get_threshold_display', 'alert_level', 'is_enabled')
    search_fields = ('rule_name', 'description')
    list_filter = ('alert_type', 'alert_level', 'is_enabled', 'stage_type')


@admin.register(AlertRecord)
class AlertRecordAdmin(admin.ModelAdmin):
    list_display = ('alert_type', 'alert_level', 'alert_title', 'batch', 'alert_status', 'triggered_at', 'get_duration')
    search_fields = ('alert_title', 'alert_message', 'batch__batch_no')
    list_filter = ('alert_type', 'alert_level', 'alert_status', 'triggered_at')


@admin.register(StageAudit)
class StageAuditAdmin(admin.ModelAdmin):
    list_display = ('batch', 'stage', 'submitter', 'submit_time', 'audit_status', 'auditor', 'audit_time')
    search_fields = ('batch__batch_no', 'submitter', 'auditor')
    list_filter = ('audit_status', 'submit_time', 'audit_time')


@admin.register(ParameterRecommendation)
class ParameterRecommendationAdmin(admin.ModelAdmin):
    list_display = ('stage_type', 'material_source', 'recommended_temp', 'recommended_conc', 'sample_count', 'is_active')
    search_fields = ('stage_type', 'material_source', 'remarks')
    list_filter = ('stage_type', 'is_active')


@admin.register(ExportRecord)
class ExportRecordAdmin(admin.ModelAdmin):
    list_display = ('export_type', 'export_name', 'export_status', 'total_records', 'requested_by', 'requested_at')
    search_fields = ('export_name', 'requested_by', 'file_path')
    list_filter = ('export_type', 'export_status', 'requested_at')


@admin.register(MaterialQualityStats)
class MaterialQualityStatsAdmin(admin.ModelAdmin):
    list_display = ('material_source', 'total_batches', 'avg_crystallization_rate', 'avg_crystallization_purity', 'abnormal_rate', 'quality_level', 'quality_score')
    search_fields = ('material_source',)
    list_filter = ('quality_level',)
    readonly_fields = ('last_updated', 'created_at')


@admin.register(AbnormalClosure)
class AbnormalClosureAdmin(admin.ModelAdmin):
    list_display = ('abnormal', 'closed_by', 'closed_at', 'is_effective', 'get_cycle_time')
    search_fields = ('abnormal__batch__batch_no', 'closed_by', 'root_cause_analysis')
    list_filter = ('is_effective', 'closed_at')
