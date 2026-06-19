from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import date, datetime
from django.db.models import Avg, Q


STAGE_CHOICES = [
    ('leaching', '浸取'),
    ('filtration', '过滤'),
    ('evaporation', '蒸发'),
    ('crystallization', '结晶'),
]

STAGE_ORDER = ['leaching', 'filtration', 'evaporation', 'crystallization']

ALERT_LEVEL_CHOICES = [
    ('info', '提示'),
    ('warning', '警告'),
    ('danger', '危险'),
]

ALERT_STATUS_CHOICES = [
    ('active', '未处理'),
    ('acknowledged', '已确认'),
    ('resolved', '已解决'),
    ('closed', '已关闭'),
]

ALERT_TYPE_CHOICES = [
    ('temperature', '温度异常'),
    ('concentration', '浓度异常'),
    ('ph_value', 'pH值异常'),
    ('crystallization_rate', '结晶率异常'),
    ('crystallization_purity', '纯度异常'),
    ('process_delay', '进度延迟'),
    ('abnormal_rate', '异常率过高'),
]

AUDIT_STATUS_CHOICES = [
    ('pending', '待审核'),
    ('approved', '已通过'),
    ('rejected', '已驳回'),
]

EXPORT_STATUS_CHOICES = [
    ('pending', '待导出'),
    ('processing', '处理中'),
    ('completed', '已完成'),
    ('failed', '失败'),
]

EXPORT_TYPE_CHOICES = [
    ('batch_summary', '批次汇总报表'),
    ('quality_analysis', '质量分析报表'),
    ('alert_statistics', '预警统计报表'),
    ('abnormal_summary', '异常汇总报表'),
    ('process_efficiency', '工艺效率报表'),
]


class RawMaterialBatch(models.Model):
    batch_no = models.CharField('批次编号', max_length=50, unique=True)
    material_source = models.CharField('原料来源', max_length=100)
    material_weight = models.FloatField('原料重量(kg)')
    start_date = models.DateField('开始日期', default=date.today)
    operator = models.CharField('操作人员', max_length=50)
    remarks = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-start_date']
        verbose_name = '原料批次'
        verbose_name_plural = '原料批次'

    def __str__(self):
        return self.batch_no

    def get_current_stage(self):
        stages = self.processstage_set.all().order_by('-start_time')
        if stages.exists():
            return stages.first()
        return None

    def get_stage_display_current(self):
        stage = self.get_current_stage()
        if stage:
            return stage.get_stage_type_display()
        return '未开始'

    def get_crystallization_rate(self):
        try:
            result = self.crystallizationresult
            if result and self.material_weight > 0:
                return round((result.crystal_weight / self.material_weight) * 100, 2)
        except CrystallizationResult.DoesNotExist:
            pass
        return None

    def clean(self):
        if self.start_date > date.today():
            raise ValidationError('开始日期不能晚于当前日期')
        if self.material_weight <= 0:
            raise ValidationError('原料重量必须大于0')


class ProcessStage(models.Model):
    STATUS_CHOICES = [
        ('in_progress', '进行中'),
        ('completed', '已完成'),
        ('paused', '已暂停'),
    ]

    batch = models.ForeignKey(RawMaterialBatch, on_delete=models.CASCADE, verbose_name='批次')
    stage_type = models.CharField('工序阶段', max_length=20, choices=STAGE_CHOICES)
    start_time = models.DateTimeField('开始时间', default=timezone.now)
    end_time = models.DateTimeField('结束时间', null=True, blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='in_progress')
    operator = models.CharField('操作人员', max_length=50, blank=True)
    remarks = models.TextField('备注', blank=True)

    class Meta:
        ordering = ['start_time']
        verbose_name = '工序阶段'
        verbose_name_plural = '工序阶段'

    def __str__(self):
        return f'{self.batch.batch_no} - {self.get_stage_type_display()}'

    def clean(self):
        if self.end_time and self.end_time < self.start_time:
            raise ValidationError('结束时间不能早于开始时间')

        current_idx = STAGE_ORDER.index(self.stage_type)
        if current_idx > 0:
            prev_stage_type = STAGE_ORDER[current_idx - 1]
            prev_stages = ProcessStage.objects.filter(
                batch=self.batch,
                stage_type=prev_stage_type,
                status='completed'
            )
            if not prev_stages.exists():
                prev_name = STAGE_CHOICES[current_idx - 1][1]
                raise ValidationError(f'未完成{prev_name}阶段不能进入{self.get_stage_type_display()}阶段')


class InspectionRecord(models.Model):
    batch = models.ForeignKey(RawMaterialBatch, on_delete=models.CASCADE, verbose_name='批次')
    stage_type = models.CharField('工序阶段', max_length=20, choices=STAGE_CHOICES)
    inspection_date = models.DateField('检测日期', default=date.today)
    temperature = models.FloatField('温度(°C)')
    concentration = models.FloatField('浓度(%)')
    ph_value = models.FloatField('pH值', null=True, blank=True)
    operator = models.CharField('检测人员', max_length=50)
    remarks = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-inspection_date']
        verbose_name = '检测记录'
        verbose_name_plural = '检测记录'

    def __str__(self):
        return f'{self.batch.batch_no} - {self.get_stage_type_display()} - {self.inspection_date}'

    def clean(self):
        if self.inspection_date > date.today():
            raise ValidationError('检测日期不能晚于当前日期')

        stage_exists = ProcessStage.objects.filter(
            batch=self.batch,
            stage_type=self.stage_type
        ).exists()
        if not stage_exists:
            stage_name = dict(STAGE_CHOICES).get(self.stage_type, self.stage_type)
            raise ValidationError(f'批次尚未进入{stage_name}阶段，请先创建该工序阶段')

        if self.stage_type == 'leaching':
            if not (20 <= self.temperature <= 100):
                raise ValidationError('浸取阶段温度应在20-100°C范围内')
            if not (5 <= self.concentration <= 30):
                raise ValidationError('浸取阶段浓度应在5-30%范围内')
        elif self.stage_type == 'filtration':
            if not (15 <= self.temperature <= 80):
                raise ValidationError('过滤阶段温度应在15-80°C范围内')
            if not (5 <= self.concentration <= 35):
                raise ValidationError('过滤阶段浓度应在5-35%范围内')
        elif self.stage_type == 'evaporation':
            if not (60 <= self.temperature <= 120):
                raise ValidationError('蒸发阶段温度应在60-120°C范围内')
            if not (20 <= self.concentration <= 60):
                raise ValidationError('蒸发阶段浓度应在20-60%范围内')
        elif self.stage_type == 'crystallization':
            if not (0 <= self.temperature <= 50):
                raise ValidationError('结晶阶段温度应在0-50°C范围内')
            if not (30 <= self.concentration <= 80):
                raise ValidationError('结晶阶段浓度应在30-80%范围内')

        if self.ph_value is not None and not (0 <= self.ph_value <= 14):
            raise ValidationError('pH值应在0-14范围内')


class CrystallizationResult(models.Model):
    batch = models.OneToOneField(RawMaterialBatch, on_delete=models.CASCADE, verbose_name='批次')
    crystal_weight = models.FloatField('结晶重量(kg)')
    crystal_purity = models.FloatField('结晶纯度(%)', default=95.0)
    crystallization_date = models.DateField('结晶日期', default=date.today)
    operator = models.CharField('操作人员', max_length=50)
    remarks = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '结晶结果'
        verbose_name_plural = '结晶结果'

    def __str__(self):
        return f'{self.batch.batch_no} - 结晶结果'

    def get_crystallization_rate(self):
        if self.batch.material_weight > 0:
            return round((self.crystal_weight / self.batch.material_weight) * 100, 2)
        return 0

    def clean(self):
        if self.crystallization_date > date.today():
            raise ValidationError('结晶日期不能晚于当前日期')

        if self.crystal_weight <= 0:
            raise ValidationError('结晶重量必须大于0')

        if self.crystal_weight > self.batch.material_weight:
            raise ValidationError('结晶重量不能超过原料重量')

        if not (0 <= self.crystal_purity <= 100):
            raise ValidationError('结晶纯度应在0-100%范围内')

        evaporation_completed = ProcessStage.objects.filter(
            batch=self.batch,
            stage_type='evaporation',
            status='completed'
        ).exists()
        if not evaporation_completed:
            raise ValidationError('未完成蒸发阶段不能录入结晶结果')


class AbnormalDisposal(models.Model):
    ABNORMAL_TYPE_CHOICES = [
        ('low_yield', '产率偏低'),
        ('low_purity', '纯度偏低'),
        ('equipment', '设备故障'),
        ('process', '工艺异常'),
        ('other', '其他'),
    ]

    DISPOSAL_STATUS_CHOICES = [
        ('pending', '待处理'),
        ('processing', '处理中'),
        ('resolved', '已解决'),
        ('closed', '已关闭'),
    ]

    batch = models.ForeignKey(RawMaterialBatch, on_delete=models.CASCADE, verbose_name='批次')
    abnormal_type = models.CharField('异常类型', max_length=20, choices=ABNORMAL_TYPE_CHOICES)
    stage_type = models.CharField('发生阶段', max_length=20, choices=STAGE_CHOICES)
    discover_date = models.DateField('发现日期', default=date.today)
    description = models.TextField('异常描述')
    reason = models.TextField('异常原因')
    disposal_measure = models.TextField('处置措施', blank=True)
    disposal_status = models.CharField('处置状态', max_length=20, choices=DISPOSAL_STATUS_CHOICES, default='pending')
    handler = models.CharField('处理人员', max_length=50, blank=True)
    resolve_date = models.DateField('解决日期', null=True, blank=True)
    remarks = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-discover_date']
        verbose_name = '异常处置'
        verbose_name_plural = '异常处置'

    def __str__(self):
        return f'{self.batch.batch_no} - {self.get_abnormal_type_display()}'

    def clean(self):
        if self.discover_date > date.today():
            raise ValidationError('发现日期不能晚于当前日期')
        if self.resolve_date and self.resolve_date < self.discover_date:
            raise ValidationError('解决日期不能早于发现日期')

    def get_cycle_time(self):
        if self.resolve_date and self.discover_date:
            return (self.resolve_date - self.discover_date).days
        return None


class AlertRule(models.Model):
    rule_name = models.CharField('规则名称', max_length=100, unique=True)
    alert_type = models.CharField('预警类型', max_length=30, choices=ALERT_TYPE_CHOICES)
    stage_type = models.CharField('适用阶段', max_length=20, choices=STAGE_CHOICES, blank=True, null=True)
    min_value = models.FloatField('最小值阈值', null=True, blank=True)
    max_value = models.FloatField('最大值阈值', null=True, blank=True)
    alert_level = models.CharField('预警级别', max_length=20, choices=ALERT_LEVEL_CHOICES, default='warning')
    is_enabled = models.BooleanField('是否启用', default=True)
    description = models.TextField('规则描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['alert_type', 'stage_type']
        verbose_name = '预警规则'
        verbose_name_plural = '预警规则'

    def __str__(self):
        return self.rule_name

    def check_value(self, value):
        if self.min_value is not None and value < self.min_value:
            return True
        if self.max_value is not None and value > self.max_value:
            return True
        return False

    def get_threshold_display(self):
        parts = []
        if self.min_value is not None:
            parts.append(f'≥ {self.min_value}')
        if self.max_value is not None:
            parts.append(f'≤ {self.max_value}')
        return ' 且 '.join(parts) if parts else '无阈值'


class AlertRecord(models.Model):
    batch = models.ForeignKey(RawMaterialBatch, on_delete=models.CASCADE, verbose_name='批次', null=True, blank=True)
    inspection = models.ForeignKey(InspectionRecord, on_delete=models.CASCADE, verbose_name='检测记录', null=True, blank=True)
    crystallization = models.ForeignKey(CrystallizationResult, on_delete=models.CASCADE, verbose_name='结晶结果', null=True, blank=True)
    abnormal = models.ForeignKey(AbnormalDisposal, on_delete=models.CASCADE, verbose_name='异常记录', null=True, blank=True)
    alert_type = models.CharField('预警类型', max_length=30, choices=ALERT_TYPE_CHOICES)
    alert_level = models.CharField('预警级别', max_length=20, choices=ALERT_LEVEL_CHOICES)
    alert_title = models.CharField('预警标题', max_length=200)
    alert_message = models.TextField('预警详情')
    indicator_value = models.FloatField('指标数值', null=True, blank=True)
    threshold = models.CharField('阈值范围', max_length=100, blank=True)
    alert_status = models.CharField('预警状态', max_length=20, choices=ALERT_STATUS_CHOICES, default='active')
    triggered_at = models.DateTimeField('触发时间', default=timezone.now)
    acknowledged_at = models.DateTimeField('确认时间', null=True, blank=True)
    resolved_at = models.DateTimeField('解决时间', null=True, blank=True)
    closed_at = models.DateTimeField('关闭时间', null=True, blank=True)
    acknowledged_by = models.CharField('确认人', max_length=50, blank=True)
    resolved_by = models.CharField('处理人', max_length=50, blank=True)
    closed_by = models.CharField('关闭人', max_length=50, blank=True)
    handle_notes = models.TextField('处理备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-triggered_at']
        verbose_name = '预警记录'
        verbose_name_plural = '预警记录'

    def __str__(self):
        return f'{self.get_alert_type_display()} - {self.alert_title}'

    def get_duration(self):
        if self.resolved_at and self.triggered_at:
            duration = self.resolved_at - self.triggered_at
            hours = duration.total_seconds() / 3600
            return round(hours, 2)
        return None


class StageAudit(models.Model):
    batch = models.ForeignKey(RawMaterialBatch, on_delete=models.CASCADE, verbose_name='批次')
    stage = models.OneToOneField(ProcessStage, on_delete=models.CASCADE, verbose_name='工序阶段', related_name='audit')
    submitter = models.CharField('提交人', max_length=50)
    submit_time = models.DateTimeField('提交时间', default=timezone.now)
    audit_status = models.CharField('审核状态', max_length=20, choices=AUDIT_STATUS_CHOICES, default='pending')
    auditor = models.CharField('审核人', max_length=50, blank=True)
    audit_time = models.DateTimeField('审核时间', null=True, blank=True)
    audit_opinion = models.TextField('审核意见', blank=True)
    reject_reason = models.TextField('驳回原因', blank=True)
    is_required = models.BooleanField('是否需要审核', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-submit_time']
        verbose_name = '阶段流转审核'
        verbose_name_plural = '阶段流转审核'

    def __str__(self):
        return f'{self.batch.batch_no} - {self.stage.get_stage_type_display()} 审核'


class ParameterRecommendation(models.Model):
    stage_type = models.CharField('工序阶段', max_length=20, choices=STAGE_CHOICES)
    material_source = models.CharField('原料来源', max_length=100, blank=True)
    recommended_temp = models.FloatField('推荐温度(°C)', null=True, blank=True)
    recommended_conc = models.FloatField('推荐浓度(%)', null=True, blank=True)
    recommended_ph = models.FloatField('推荐pH值', null=True, blank=True)
    temp_range = models.CharField('温度范围', max_length=50, blank=True)
    conc_range = models.CharField('浓度范围', max_length=50, blank=True)
    ph_range = models.CharField('pH范围', max_length=50, blank=True)
    success_rate = models.FloatField('成功率(%)', default=0)
    sample_count = models.IntegerField('样本数量', default=0)
    avg_crystallization_rate = models.FloatField('平均结晶率(%)', null=True, blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    remarks = models.TextField('备注说明', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['stage_type', 'material_source']
        verbose_name = '历史参数推荐'
        verbose_name_plural = '历史参数推荐'
        unique_together = ['stage_type', 'material_source']

    def __str__(self):
        source = f'- {self.material_source}' if self.material_source else ''
        return f'{self.get_stage_type_display()}{source} 参数推荐'

    @classmethod
    def generate_recommendations(cls, stage_type=None, material_source=None):
        queryset = InspectionRecord.objects.all()
        if stage_type:
            queryset = queryset.filter(stage_type=stage_type)
        if material_source:
            queryset = queryset.filter(batch__material_source=material_source)

        if not queryset.exists():
            return None

        good_batches = CrystallizationResult.objects.filter(
            batch__crystallizationresult__crystal_weight__gt=0
        ).annotate(
            rate=100 * models.F('crystal_weight') / models.F('batch__material_weight')
        ).filter(rate__gte=15).values_list('batch_id', flat=True)

        good_inspections = queryset.filter(batch_id__in=good_batches)

        if not good_inspections.exists():
            return None

        avg_temp = good_inspections.aggregate(avg=Avg('temperature'))['avg']
        avg_conc = good_inspections.aggregate(avg=Avg('concentration'))['avg']
        avg_ph = good_inspections.exclude(ph_value__isnull=True).aggregate(avg=Avg('ph_value'))['avg']

        temps = good_inspections.values_list('temperature', flat=True)
        concs = good_inspections.values_list('concentration', flat=True)
        phs = good_inspections.exclude(ph_value__isnull=True).values_list('ph_value', flat=True)

        recommendation, created = cls.objects.get_or_create(
            stage_type=stage_type,
            material_source=material_source or '',
            defaults={
                'recommended_temp': round(avg_temp, 2) if avg_temp else None,
                'recommended_conc': round(avg_conc, 2) if avg_conc else None,
                'recommended_ph': round(avg_ph, 2) if avg_ph else None,
                'temp_range': f'{round(min(temps), 2)} - {round(max(temps), 2)}' if temps else '',
                'conc_range': f'{round(min(concs), 2)} - {round(max(concs), 2)}' if concs else '',
                'ph_range': f'{round(min(phs), 2)} - {round(max(phs), 2)}' if phs else '',
                'sample_count': good_inspections.count(),
            }
        )

        if not created:
            recommendation.recommended_temp = round(avg_temp, 2) if avg_temp else None
            recommendation.recommended_conc = round(avg_conc, 2) if avg_conc else None
            recommendation.recommended_ph = round(avg_ph, 2) if avg_ph else None
            recommendation.temp_range = f'{round(min(temps), 2)} - {round(max(temps), 2)}' if temps else ''
            recommendation.conc_range = f'{round(min(concs), 2)} - {round(max(concs), 2)}' if concs else ''
            recommendation.ph_range = f'{round(min(phs), 2)} - {round(max(phs), 2)}' if phs else ''
            recommendation.sample_count = good_inspections.count()
            recommendation.save()

        return recommendation


class ExportRecord(models.Model):
    export_type = models.CharField('报表类型', max_length=50, choices=EXPORT_TYPE_CHOICES)
    export_name = models.CharField('报表名称', max_length=200)
    filters = models.JSONField('筛选条件', default=dict, blank=True)
    export_status = models.CharField('导出状态', max_length=20, choices=EXPORT_STATUS_CHOICES, default='pending')
    file_path = models.CharField('文件路径', max_length=500, blank=True)
    file_size = models.IntegerField('文件大小(KB)', null=True, blank=True)
    total_records = models.IntegerField('记录总数', default=0)
    requested_by = models.CharField('申请人', max_length=50)
    requested_at = models.DateTimeField('申请时间', default=timezone.now)
    completed_at = models.DateTimeField('完成时间', null=True, blank=True)
    error_message = models.TextField('错误信息', blank=True)
    remarks = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-requested_at']
        verbose_name = '报表导出记录'
        verbose_name_plural = '报表导出记录'

    def __str__(self):
        return f'{self.get_export_type_display()} - {self.export_name}'

    def get_file_size_display(self):
        if self.file_size:
            if self.file_size > 1024:
                return f'{self.file_size / 1024:.2f} MB'
            return f'{self.file_size} KB'
        return '-'


class MaterialQualityStats(models.Model):
    material_source = models.CharField('原料来源', max_length=100, unique=True)
    total_batches = models.IntegerField('总批次数', default=0)
    completed_batches = models.IntegerField('已完成批次', default=0)
    avg_crystallization_rate = models.FloatField('平均结晶率(%)', null=True, blank=True)
    avg_crystallization_purity = models.FloatField('平均纯度(%)', null=True, blank=True)
    min_crystallization_rate = models.FloatField('最低结晶率(%)', null=True, blank=True)
    max_crystallization_rate = models.FloatField('最高结晶率(%)', null=True, blank=True)
    abnormal_count = models.IntegerField('异常次数', default=0)
    abnormal_rate = models.FloatField('异常率(%)', default=0)
    avg_process_duration = models.FloatField('平均处理时长(小时)', null=True, blank=True)
    quality_score = models.FloatField('质量评分', null=True, blank=True)
    quality_level = models.CharField('质量等级', max_length=20, blank=True)
    last_updated = models.DateTimeField('最后更新', auto_now=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-avg_crystallization_rate']
        verbose_name = '原料来源质量统计'
        verbose_name_plural = '原料来源质量统计'

    def __str__(self):
        return f'{self.material_source} - 质量统计'

    @classmethod
    def update_stats(cls, material_source=None):
        sources = [material_source] if material_source else RawMaterialBatch.objects.values_list('material_source', flat=True).distinct()

        for source in sources:
            batches = RawMaterialBatch.objects.filter(material_source=source)
            total = batches.count()
            if total == 0:
                continue

            crystal_results = CrystallizationResult.objects.filter(batch__material_source=source)
            completed = crystal_results.count()

            rates = []
            purities = []
            for cr in crystal_results:
                rate = cr.get_crystallization_rate()
                if rate:
                    rates.append(rate)
                purities.append(cr.crystal_purity)

            abnormal_count = AbnormalDisposal.objects.filter(batch__material_source=source).count()
            abnormal_rate = (abnormal_count / total * 100) if total > 0 else 0

            durations = []
            for batch in batches:
                stages = batch.processstage_set.filter(status='completed')
                if stages.exists() and stages.first().start_time and stages.last().end_time:
                    duration = (stages.last().end_time - stages.first().start_time).total_seconds() / 3600
                    durations.append(duration)

            stats, created = cls.objects.get_or_create(
                material_source=source,
                defaults={
                    'total_batches': total,
                    'completed_batches': completed,
                    'avg_crystallization_rate': round(sum(rates) / len(rates), 2) if rates else None,
                    'avg_crystallization_purity': round(sum(purities) / len(purities), 2) if purities else None,
                    'min_crystallization_rate': round(min(rates), 2) if rates else None,
                    'max_crystallization_rate': round(max(rates), 2) if rates else None,
                    'abnormal_count': abnormal_count,
                    'abnormal_rate': round(abnormal_rate, 2),
                    'avg_process_duration': round(sum(durations) / len(durations), 2) if durations else None,
                }
            )

            if not created:
                stats.total_batches = total
                stats.completed_batches = completed
                stats.avg_crystallization_rate = round(sum(rates) / len(rates), 2) if rates else None
                stats.avg_crystallization_purity = round(sum(purities) / len(purities), 2) if purities else None
                stats.min_crystallization_rate = round(min(rates), 2) if rates else None
                stats.max_crystallization_rate = round(max(rates), 2) if rates else None
                stats.abnormal_count = abnormal_count
                stats.abnormal_rate = round(abnormal_rate, 2)
                stats.avg_process_duration = round(sum(durations) / len(durations), 2) if durations else None

            avg_rate = stats.avg_crystallization_rate or 0
            avg_purity = stats.avg_crystallization_purity or 0
            stats.quality_score = round(avg_rate * 0.6 + avg_purity * 0.3 - stats.abnormal_rate * 0.1, 2)

            if stats.quality_score >= 80:
                stats.quality_level = '优秀'
            elif stats.quality_score >= 60:
                stats.quality_level = '良好'
            elif stats.quality_score >= 40:
                stats.quality_level = '一般'
            else:
                stats.quality_level = '较差'

            stats.save()

        return cls.objects.all()


class AbnormalClosure(models.Model):
    abnormal = models.OneToOneField(AbnormalDisposal, on_delete=models.CASCADE, verbose_name='异常记录', related_name='closure')
    root_cause_analysis = models.TextField('根本原因分析')
    corrective_action = models.TextField('纠正措施')
    preventive_action = models.TextField('预防措施')
    verification_method = models.TextField('验证方法')
    verification_result = models.TextField('验证结果', blank=True)
    is_effective = models.BooleanField('是否有效', null=True, blank=True)
    closed_by = models.CharField('闭环人', max_length=50)
    closed_at = models.DateTimeField('闭环时间', default=timezone.now)
    closure_opinion = models.TextField('闭环意见', blank=True)
    related_documents = models.TextField('相关文件', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-closed_at']
        verbose_name = '异常闭环管理'
        verbose_name_plural = '异常闭环管理'

    def __str__(self):
        return f'{self.abnormal.batch.batch_no} - 异常闭环'

    def get_cycle_time(self):
        if self.abnormal.discover_date and self.closed_at:
            return (self.closed_at.date() - self.abnormal.discover_date).days
        return None


MATERIAL_UNIT_CHOICES = [
    ('kg', '千克(kg)'),
    ('ton', '吨(t)'),
    ('bag', '袋'),
    ('barrel', '桶'),
    ('piece', '件'),
    ('box', '箱'),
]

STOCK_ALERT_STATUS_CHOICES = [
    ('normal', '正常'),
    ('low_stock', '库存不足'),
    ('overstock', '库存积压'),
    ('expired', '已过期'),
    ('near_expiry', '临近过期'),
]

INBOUND_TYPE_CHOICES = [
    ('purchase', '采购入库'),
    ('return', '退货入库'),
    ('transfer', '调拨入库'),
    ('other', '其他入库'),
]

OUTBOUND_TYPE_CHOICES = [
    ('production', '生产领用'),
    ('transfer', '调拨出库'),
    ('scrap', '报废出库'),
    ('other', '其他出库'),
]

LOSS_REASON_CHOICES = [
    ('natural', '自然损耗'),
    ('breakage', '破损损耗'),
    ('expired', '过期损耗'),
    ('theft', '失窃损耗'),
    ('other', '其他损耗'),
]


class MaterialCategory(models.Model):
    name = models.CharField('分类名称', max_length=50, unique=True)
    code = models.CharField('分类编码', max_length=20, unique=True)
    description = models.TextField('分类描述', blank=True)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, 
                               verbose_name='上级分类', related_name='children')
    sort_order = models.IntegerField('排序', default=0)
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = '原料分类'
        verbose_name_plural = '原料分类'

    def __str__(self):
        return self.name

    def get_full_path(self):
        path = [self.name]
        parent = self.parent
        while parent:
            path.insert(0, parent.name)
            parent = parent.parent
        return ' / '.join(path)


class MaterialSupplier(models.Model):
    name = models.CharField('供应商名称', max_length=100, unique=True)
    code = models.CharField('供应商编码', max_length=20, unique=True)
    contact_person = models.CharField('联系人', max_length=50, blank=True)
    contact_phone = models.CharField('联系电话', max_length=20, blank=True)
    address = models.CharField('地址', max_length=200, blank=True)
    email = models.EmailField('邮箱', blank=True)
    qualification = models.TextField('资质说明', blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    remarks = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = '供应商'
        verbose_name_plural = '供应商'

    def __str__(self):
        return self.name


class Material(models.Model):
    name = models.CharField('原料名称', max_length=100)
    code = models.CharField('原料编码', max_length=30, unique=True)
    category = models.ForeignKey(MaterialCategory, on_delete=models.PROTECT, 
                                  verbose_name='原料分类', related_name='materials')
    specification = models.CharField('规格型号', max_length=100, blank=True)
    unit = models.CharField('计量单位', max_length=20, choices=MATERIAL_UNIT_CHOICES, default='kg')
    safety_stock = models.FloatField('安全库存', default=0)
    max_stock = models.FloatField('最大库存', default=0, help_text='0表示不限制')
    min_stock = models.FloatField('最低库存预警', default=0)
    expiry_days = models.IntegerField('保质期(天)', default=0, help_text='0表示无保质期限制')
    description = models.TextField('原料描述', blank=True)
    storage_condition = models.TextField('存储条件', blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name = '原料档案'
        verbose_name_plural = '原料档案'
        unique_together = ['name', 'specification']

    def __str__(self):
        spec = f'({self.specification})' if self.specification else ''
        return f'{self.name}{spec}'

    def get_current_stock(self):
        from django.db.models import Sum
        inbound = MaterialInbound.objects.filter(material=self).aggregate(
            total=Sum('quantity'))['total'] or 0
        outbound = MaterialOutbound.objects.filter(material=self).aggregate(
            total=Sum('quantity'))['total'] or 0
        loss = MaterialLoss.objects.filter(material=self).aggregate(
            total=Sum('quantity'))['total'] or 0
        return round(inbound - outbound - loss, 2)

    def get_stock_status(self):
        current_stock = self.get_current_stock()
        if self.expiry_days > 0:
            from datetime import date, timedelta
            near_expiry_date = date.today() + timedelta(days=30)
            expired_count = MaterialInbound.objects.filter(
                material=self, expiry_date__lte=date.today()
            ).exists()
            near_expiry_count = MaterialInbound.objects.filter(
                material=self, expiry_date__gt=date.today(), 
                expiry_date__lte=near_expiry_date
            ).exists()
            if expired_count:
                return 'expired'
            if near_expiry_count:
                return 'near_expiry'
        if current_stock <= self.min_stock and self.min_stock > 0:
            return 'low_stock'
        if self.max_stock > 0 and current_stock >= self.max_stock:
            return 'overstock'
        return 'normal'

    def get_stock_status_display(self):
        status = self.get_stock_status()
        status_map = dict(STOCK_ALERT_STATUS_CHOICES)
        return status_map.get(status, '未知')


class MaterialInbound(models.Model):
    inbound_no = models.CharField('入库单号', max_length=30, unique=True)
    material = models.ForeignKey(Material, on_delete=models.PROTECT, 
                                  verbose_name='原料', related_name='inbounds')
    supplier = models.ForeignKey(MaterialSupplier, on_delete=models.PROTECT, 
                                  verbose_name='供应商', related_name='inbounds')
    quantity = models.FloatField('入库数量')
    unit_price = models.FloatField('单价', default=0)
    total_amount = models.FloatField('总金额', default=0)
    inbound_type = models.CharField('入库类型', max_length=20, choices=INBOUND_TYPE_CHOICES, default='purchase')
    batch_no = models.CharField('原料批次号', max_length=50, blank=True)
    production_date = models.DateField('生产日期', null=True, blank=True)
    expiry_date = models.DateField('有效期至', null=True, blank=True)
    inbound_date = models.DateField('入库日期', default=date.today)
    warehouse = models.CharField('仓库', max_length=50, blank=True)
    location = models.CharField('库位', max_length=50, blank=True)
    inspector = models.CharField('验收人', max_length=50, blank=True)
    operator = models.CharField('经办人', max_length=50)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-inbound_date', '-inbound_no']
        verbose_name = '原料入库'
        verbose_name_plural = '原料入库'

    def __str__(self):
        return f'{self.inbound_no} - {self.material.name}'

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError('入库数量必须大于0')
        if self.unit_price < 0:
            raise ValidationError('单价不能为负数')
        if self.inbound_date > date.today():
            raise ValidationError('入库日期不能晚于当前日期')
        if self.production_date and self.production_date > date.today():
            raise ValidationError('生产日期不能晚于当前日期')
        if self.expiry_date and self.production_date and self.expiry_date < self.production_date:
            raise ValidationError('有效期不能早于生产日期')
        if self.expiry_date and self.expiry_date < self.inbound_date:
            raise ValidationError('有效期不能早于入库日期')

    def save(self, *args, **kwargs):
        self.total_amount = round(self.quantity * self.unit_price, 2)
        super().save(*args, **kwargs)

    def get_remaining_quantity(self):
        used = MaterialOutbound.objects.filter(
            material=self.material,
            inbound_ref=self
        ).aggregate(total=models.Sum('quantity'))['total'] or 0
        lost = MaterialLoss.objects.filter(
            material=self.material,
            inbound_ref=self
        ).aggregate(total=models.Sum('quantity'))['total'] or 0
        return round(self.quantity - used - lost, 2)

    def is_expired(self):
        if not self.expiry_date:
            return False
        return self.expiry_date < date.today()

    def is_near_expiry(self, days=30):
        if not self.expiry_date:
            return False
        from datetime import timedelta
        return date.today() <= self.expiry_date <= (date.today() + timedelta(days=days))


class MaterialOutbound(models.Model):
    outbound_no = models.CharField('出库单号', max_length=30, unique=True)
    material = models.ForeignKey(Material, on_delete=models.PROTECT, 
                                  verbose_name='原料', related_name='outbounds')
    quantity = models.FloatField('出库数量')
    outbound_type = models.CharField('出库类型', max_length=20, choices=OUTBOUND_TYPE_CHOICES, default='production')
    outbound_date = models.DateField('出库日期', default=date.today)
    inbound_ref = models.ForeignKey(MaterialInbound, on_delete=models.PROTECT, 
                                     verbose_name='入库批次', related_name='outbounds',
                                     null=True, blank=True)
    batch = models.ForeignKey(RawMaterialBatch, on_delete=models.SET_NULL, 
                               verbose_name='生产批次', related_name='material_usages',
                               null=True, blank=True)
    warehouse = models.CharField('仓库', max_length=50, blank=True)
    location = models.CharField('库位', max_length=50, blank=True)
    receiver = models.CharField('领用人', max_length=50, blank=True)
    operator = models.CharField('经办人', max_length=50)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-outbound_date', '-outbound_no']
        verbose_name = '原料出库'
        verbose_name_plural = '原料出库'

    def __str__(self):
        return f'{self.outbound_no} - {self.material.name}'

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError('出库数量必须大于0')
        if self.outbound_date > date.today():
            raise ValidationError('出库日期不能晚于当前日期')
        
        if self.inbound_ref:
            if self.inbound_ref.material != self.material:
                raise ValidationError('入库批次的原料与出库原料不一致')
            remaining = self.inbound_ref.get_remaining_quantity()
            if self.quantity > remaining:
                raise ValidationError(f'该入库批次剩余数量不足，当前剩余: {remaining} {self.material.get_unit_display()}')
        else:
            current_stock = self.material.get_current_stock()
            if self.quantity > current_stock:
                raise ValidationError(f'库存不足，当前库存: {current_stock} {self.material.get_unit_display()}')


class MaterialLoss(models.Model):
    loss_no = models.CharField('损耗单号', max_length=30, unique=True)
    material = models.ForeignKey(Material, on_delete=models.PROTECT, 
                                  verbose_name='原料', related_name='losses')
    quantity = models.FloatField('损耗数量')
    loss_reason = models.CharField('损耗原因', max_length=20, choices=LOSS_REASON_CHOICES, default='natural')
    loss_date = models.DateField('损耗日期', default=date.today)
    inbound_ref = models.ForeignKey(MaterialInbound, on_delete=models.PROTECT, 
                                     verbose_name='入库批次', related_name='losses',
                                     null=True, blank=True)
    warehouse = models.CharField('仓库', max_length=50, blank=True)
    location = models.CharField('库位', max_length=50, blank=True)
    reported_by = models.CharField('上报人', max_length=50)
    approved_by = models.CharField('审批人', max_length=50, blank=True)
    description = models.TextField('损耗说明')
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-loss_date', '-loss_no']
        verbose_name = '原料损耗'
        verbose_name_plural = '原料损耗'

    def __str__(self):
        return f'{self.loss_no} - {self.material.name}'

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError('损耗数量必须大于0')
        if self.loss_date > date.today():
            raise ValidationError('损耗日期不能晚于当前日期')
        if self.inbound_ref and self.inbound_ref.material != self.material:
            raise ValidationError('入库批次的原料与损耗原料不一致')


class BatchMaterialUsage(models.Model):
    batch = models.ForeignKey(RawMaterialBatch, on_delete=models.CASCADE, 
                               verbose_name='生产批次', related_name='batch_materials')
    material = models.ForeignKey(Material, on_delete=models.PROTECT, 
                                  verbose_name='原料', related_name='batch_usages')
    outbound = models.OneToOneField(MaterialOutbound, on_delete=models.PROTECT, 
                                     verbose_name='出库记录', related_name='batch_usage')
    planned_quantity = models.FloatField('计划用量', default=0)
    actual_quantity = models.FloatField('实际用量')
    unit = models.CharField('计量单位', max_length=20, choices=MATERIAL_UNIT_CHOICES)
    usage_stage = models.CharField('使用工序', max_length=20, choices=STAGE_CHOICES, blank=True, null=True)
    usage_date = models.DateField('使用日期', default=date.today)
    operator = models.CharField('操作人员', max_length=50)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-usage_date']
        verbose_name = '批次原料使用'
        verbose_name_plural = '批次原料使用'
        unique_together = ['batch', 'material', 'outbound']

    def __str__(self):
        return f'{self.batch.batch_no} - {self.material.name}'

    def clean(self):
        if self.actual_quantity <= 0:
            raise ValidationError('实际用量必须大于0')
        if self.outbound and self.outbound.material != self.material:
            raise ValidationError('出库记录的原料与使用原料不一致')
        if self.outbound and self.outbound.batch and self.outbound.batch != self.batch:
            raise ValidationError('出库记录已关联其他生产批次')

    def save(self, *args, **kwargs):
        if self.outbound:
            self.unit = self.outbound.material.unit
            self.actual_quantity = self.outbound.quantity
        super().save(*args, **kwargs)


class MaterialStockAlert(models.Model):
    material = models.ForeignKey(Material, on_delete=models.CASCADE, 
                                  verbose_name='原料', related_name='stock_alerts')
    alert_type = models.CharField('预警类型', max_length=20, choices=STOCK_ALERT_STATUS_CHOICES)
    alert_level = models.CharField('预警级别', max_length=20, choices=ALERT_LEVEL_CHOICES, default='warning')
    alert_title = models.CharField('预警标题', max_length=200)
    alert_message = models.TextField('预警详情')
    current_stock = models.FloatField('当前库存', null=True, blank=True)
    threshold = models.FloatField('阈值', null=True, blank=True)
    alert_status = models.CharField('预警状态', max_length=20, choices=ALERT_STATUS_CHOICES, default='active')
    triggered_at = models.DateTimeField('触发时间', default=timezone.now)
    acknowledged_at = models.DateTimeField('确认时间', null=True, blank=True)
    resolved_at = models.DateTimeField('解决时间', null=True, blank=True)
    acknowledged_by = models.CharField('确认人', max_length=50, blank=True)
    resolved_by = models.CharField('处理人', max_length=50, blank=True)
    handle_notes = models.TextField('处理备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-triggered_at']
        verbose_name = '库存预警记录'
        verbose_name_plural = '库存预警记录'

    def __str__(self):
        return f'{self.get_alert_type_display()} - {self.material.name}'

    def get_duration(self):
        if self.resolved_at and self.triggered_at:
            duration = self.resolved_at - self.triggered_at
            hours = duration.total_seconds() / 3600
            return round(hours, 2)
        return None


class MaterialStockHistory(models.Model):
    material = models.ForeignKey(Material, on_delete=models.PROTECT, 
                                  verbose_name='原料', related_name='stock_history')
    record_date = models.DateField('记录日期', default=date.today)
    opening_stock = models.FloatField('期初库存', default=0)
    inbound_quantity = models.FloatField('入库数量', default=0)
    outbound_quantity = models.FloatField('出库数量', default=0)
    loss_quantity = models.FloatField('损耗数量', default=0)
    closing_stock = models.FloatField('期末库存', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        ordering = ['-record_date']
        verbose_name = '库存收发存记录'
        verbose_name_plural = '库存收发存记录'
        unique_together = ['material', 'record_date']

    def __str__(self):
        return f'{self.material.name} - {self.record_date}'

    def save(self, *args, **kwargs):
        self.closing_stock = round(
            self.opening_stock + self.inbound_quantity - self.outbound_quantity - self.loss_quantity, 2
        )
        super().save(*args, **kwargs)
