from django.contrib import admin
from .models import RawMaterialBatch, ProcessStage, InspectionRecord, CrystallizationResult, AbnormalDisposal


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
