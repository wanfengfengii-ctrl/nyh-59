from django.contrib import admin
from django.db.models import Sum
from .models import (
    RawMaterialBatch, ProcessStage, InspectionRecord, CrystallizationResult, AbnormalDisposal,
    AlertRule, AlertRecord, StageAudit, ParameterRecommendation, ExportRecord,
    MaterialQualityStats, AbnormalClosure,
    MaterialCategory, MaterialSupplier, Material, MaterialInbound, MaterialOutbound,
    MaterialLoss, BatchMaterialUsage, MaterialStockAlert, MaterialStockHistory,
    ProcessEnergyCost, LaborCost, OtherCost, ProductSale,
    BatchCostSummary, LossWarning, SourceCostStats,
    MATERIAL_UNIT_CHOICES, STOCK_ALERT_STATUS_CHOICES, INBOUND_TYPE_CHOICES,
    OUTBOUND_TYPE_CHOICES, LOSS_REASON_CHOICES,
    ENERGY_TYPE_CHOICES, OTHER_COST_CATEGORY_CHOICES,
    LOSS_WARNING_LEVEL_CHOICES, SALE_STATUS_CHOICES,
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


@admin.register(MaterialCategory)
class MaterialCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'parent', 'sort_order', 'is_active', 'get_full_path')
    search_fields = ('name', 'code', 'description')
    list_filter = ('is_active', 'parent')
    ordering = ['sort_order', 'name']


@admin.register(MaterialSupplier)
class MaterialSupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'contact_person', 'contact_phone', 'is_active')
    search_fields = ('name', 'code', 'contact_person', 'contact_phone', 'address')
    list_filter = ('is_active',)
    ordering = ['name']


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'category', 'specification', 'unit', 
                    'get_current_stock_display', 'min_stock', 'max_stock', 
                    'get_stock_status_badge', 'is_active')
    search_fields = ('name', 'code', 'specification', 'description')
    list_filter = ('category', 'unit', 'is_active')
    ordering = ['code']
    readonly_fields = ('created_at', 'updated_at')

    def get_current_stock_display(self, obj):
        return f'{obj.get_current_stock()} {obj.get_unit_display()}'
    get_current_stock_display.short_description = '当前库存'

    def get_stock_status_badge(self, obj):
        from django.utils.html import format_html
        status = obj.get_stock_status()
        status_map = {
            'normal': ('badge-success', '正常'),
            'low_stock': ('badge-warning', '库存不足'),
            'overstock': ('badge-info', '库存积压'),
            'expired': ('badge-danger', '已过期'),
            'near_expiry': ('badge-warning', '临近过期'),
        }
        badge_class, display_text = status_map.get(status, ('badge-info', '未知'))
        return format_html(f'<span class="badge {badge_class}">{display_text}</span>')
    get_stock_status_badge.short_description = '库存状态'
    get_stock_status_badge.allow_tags = True


@admin.register(MaterialInbound)
class MaterialInboundAdmin(admin.ModelAdmin):
    list_display = ('inbound_no', 'material', 'supplier', 'quantity', 'unit_price', 
                    'total_amount', 'get_remaining_display', 'inbound_date', 
                    'operator', 'get_expiry_status')
    search_fields = ('inbound_no', 'material__name', 'material__code', 
                     'supplier__name', 'batch_no', 'operator')
    list_filter = ('inbound_type', 'inbound_date', 'warehouse')
    date_hierarchy = 'inbound_date'
    readonly_fields = ('created_at', 'updated_at', 'total_amount')
    autocomplete_fields = ('material', 'supplier')

    def get_remaining_display(self, obj):
        return f'{obj.get_remaining_quantity()} / {obj.quantity}'
    get_remaining_display.short_description = '剩余/总量'

    def get_expiry_status(self, obj):
        from django.utils.html import format_html
        if obj.is_expired():
            return format_html('<span class="badge badge-danger">已过期</span>')
        elif obj.is_near_expiry():
            return format_html('<span class="badge badge-warning">临近过期</span>')
        return format_html('<span class="badge badge-success">正常</span>')
    get_expiry_status.short_description = '有效期状态'
    get_expiry_status.allow_tags = True


@admin.register(MaterialOutbound)
class MaterialOutboundAdmin(admin.ModelAdmin):
    list_display = ('outbound_no', 'material', 'quantity', 'outbound_type', 
                    'outbound_date', 'batch', 'receiver', 'operator')
    search_fields = ('outbound_no', 'material__name', 'material__code', 
                     'receiver', 'operator', 'batch__batch_no')
    list_filter = ('outbound_type', 'outbound_date', 'warehouse')
    date_hierarchy = 'outbound_date'
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('material', 'inbound_ref', 'batch')


@admin.register(MaterialLoss)
class MaterialLossAdmin(admin.ModelAdmin):
    list_display = ('loss_no', 'material', 'quantity', 'loss_reason', 
                    'loss_date', 'reported_by', 'approved_by')
    search_fields = ('loss_no', 'material__name', 'material__code', 
                     'reported_by', 'approved_by', 'description')
    list_filter = ('loss_reason', 'loss_date', 'warehouse')
    date_hierarchy = 'loss_date'
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('material', 'inbound_ref')


@admin.register(BatchMaterialUsage)
class BatchMaterialUsageAdmin(admin.ModelAdmin):
    list_display = ('batch', 'material', 'planned_quantity', 'actual_quantity', 
                    'unit', 'usage_stage', 'usage_date', 'operator')
    search_fields = ('batch__batch_no', 'material__name', 'material__code', 'operator')
    list_filter = ('usage_stage', 'usage_date')
    date_hierarchy = 'usage_date'
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('batch', 'material', 'outbound')


@admin.register(MaterialStockAlert)
class MaterialStockAlertAdmin(admin.ModelAdmin):
    list_display = ('material', 'alert_type', 'alert_level', 'alert_title', 
                    'current_stock', 'threshold', 'alert_status', 
                    'triggered_at', 'get_duration')
    search_fields = ('material__name', 'material__code', 'alert_title', 'alert_message')
    list_filter = ('alert_type', 'alert_level', 'alert_status', 'triggered_at')
    date_hierarchy = 'triggered_at'
    readonly_fields = ('created_at',)
    autocomplete_fields = ('material',)

    def get_duration(self, obj):
        return obj.get_duration()
    get_duration.short_description = '处理时长(小时)'


@admin.register(MaterialStockHistory)
class MaterialStockHistoryAdmin(admin.ModelAdmin):
    list_display = ('material', 'record_date', 'opening_stock', 
                    'inbound_quantity', 'outbound_quantity', 'loss_quantity', 
                    'closing_stock')
    search_fields = ('material__name', 'material__code')
    list_filter = ('record_date',)
    date_hierarchy = 'record_date'
    readonly_fields = ('created_at', 'closing_stock')
    autocomplete_fields = ('material',)


@admin.register(ProcessEnergyCost)
class ProcessEnergyCostAdmin(admin.ModelAdmin):
    list_display = ('batch', 'stage_type', 'energy_type', 'consumption', 'unit',
                    'unit_price', 'total_amount', 'record_date', 'operator')
    search_fields = ('batch__batch_no', 'operator', 'meter_reading')
    list_filter = ('stage_type', 'energy_type', 'record_date')
    date_hierarchy = 'record_date'
    readonly_fields = ('created_at', 'updated_at', 'total_amount')
    autocomplete_fields = ('batch',)


@admin.register(LaborCost)
class LaborCostAdmin(admin.ModelAdmin):
    list_display = ('batch', 'stage_type', 'worker_name', 'work_type',
                    'work_hours', 'hourly_rate', 'total_amount', 'work_date', 'operator')
    search_fields = ('batch__batch_no', 'worker_name', 'work_type', 'operator')
    list_filter = ('stage_type', 'work_date')
    date_hierarchy = 'work_date'
    readonly_fields = ('created_at', 'updated_at', 'total_amount')
    autocomplete_fields = ('batch',)


@admin.register(OtherCost)
class OtherCostAdmin(admin.ModelAdmin):
    list_display = ('batch', 'cost_category', 'cost_name', 'amount',
                    'cost_date', 'operator', 'invoice_no')
    search_fields = ('batch__batch_no', 'cost_name', 'operator', 'invoice_no')
    list_filter = ('cost_category', 'cost_date')
    date_hierarchy = 'cost_date'
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('batch',)


@admin.register(ProductSale)
class ProductSaleAdmin(admin.ModelAdmin):
    list_display = ('batch', 'sale_quantity', 'unit_price', 'total_revenue',
                    'actual_revenue', 'customer_name', 'sale_status', 'operator')
    search_fields = ('batch__batch_no', 'customer_name', 'operator')
    list_filter = ('sale_status', 'sale_date')
    readonly_fields = ('created_at', 'updated_at', 'total_revenue', 'actual_revenue')
    autocomplete_fields = ('batch',)


@admin.register(BatchCostSummary)
class BatchCostSummaryAdmin(admin.ModelAdmin):
    list_display = ('batch', 'material_cost', 'energy_cost', 'labor_cost',
                    'other_cost', 'total_cost', 'unit_cost', 'revenue',
                    'profit', 'profit_margin', 'is_loss')
    search_fields = ('batch__batch_no',)
    list_filter = ('is_loss', 'loss_warning_level', 'warning_triggered')
    readonly_fields = ('created_at', 'updated_at', 'last_calculated')


@admin.register(LossWarning)
class LossWarningAdmin(admin.ModelAdmin):
    list_display = ('batch', 'warning_level', 'warning_type', 'warning_title',
                    'indicator_value', 'warning_status', 'triggered_at')
    search_fields = ('batch__batch_no', 'warning_title', 'warning_message')
    list_filter = ('warning_level', 'warning_status', 'warning_type', 'triggered_at')
    date_hierarchy = 'triggered_at'
    readonly_fields = ('created_at', 'triggered_at')
    autocomplete_fields = ('batch', 'cost_summary')


@admin.register(SourceCostStats)
class SourceCostStatsAdmin(admin.ModelAdmin):
    list_display = ('material_source', 'total_batches', 'completed_batches',
                    'avg_total_cost', 'avg_profit', 'avg_profit_margin',
                    'total_profit', 'loss_rate', 'benefit_score', 'benefit_level')
    search_fields = ('material_source',)
    list_filter = ('benefit_level',)
    readonly_fields = ('last_updated', 'created_at')
