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
