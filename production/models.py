from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import date


STAGE_CHOICES = [
    ('leaching', '浸取'),
    ('filtration', '过滤'),
    ('evaporation', '蒸发'),
    ('crystallization', '结晶'),
]

STAGE_ORDER = ['leaching', 'filtration', 'evaporation', 'crystallization']


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
