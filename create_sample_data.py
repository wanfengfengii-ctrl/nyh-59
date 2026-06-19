import os
import django
from datetime import date, datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'niter_monitor.settings')
django.setup()

from production.models import (
    RawMaterialBatch, ProcessStage, InspectionRecord,
    CrystallizationResult, AbnormalDisposal
)


def create_sample_data():
    print('正在创建示例数据...')

    batch1 = RawMaterialBatch.objects.create(
        batch_no='XC-2026-001',
        material_source='山西运城盐湖',
        material_weight=100.0,
        start_date=date(2026, 6, 1),
        operator='张师傅',
        remarks='传统工艺试制批次'
    )

    stage1_1 = ProcessStage.objects.create(
        batch=batch1,
        stage_type='leaching',
        start_time=datetime(2026, 6, 1, 8, 0, 0),
        end_time=datetime(2026, 6, 2, 16, 0, 0),
        status='completed',
        operator='张师傅'
    )

    InspectionRecord.objects.create(
        batch=batch1,
        stage_type='leaching',
        inspection_date=date(2026, 6, 1),
        temperature=45.0,
        concentration=12.5,
        ph_value=7.2,
        operator='李检测员',
        remarks='初始检测'
    )

    InspectionRecord.objects.create(
        batch=batch1,
        stage_type='leaching',
        inspection_date=date(2026, 6, 2),
        temperature=60.0,
        concentration=18.0,
        ph_value=7.0,
        operator='李检测员',
        remarks='浸取中期'
    )

    stage1_2 = ProcessStage.objects.create(
        batch=batch1,
        stage_type='filtration',
        start_time=datetime(2026, 6, 2, 16, 30, 0),
        end_time=datetime(2026, 6, 3, 12, 0, 0),
        status='completed',
        operator='王师傅'
    )

    InspectionRecord.objects.create(
        batch=batch1,
        stage_type='filtration',
        inspection_date=date(2026, 6, 3),
        temperature=35.0,
        concentration=16.5,
        ph_value=7.1,
        operator='李检测员',
        remarks='过滤后检测'
    )

    stage1_3 = ProcessStage.objects.create(
        batch=batch1,
        stage_type='evaporation',
        start_time=datetime(2026, 6, 3, 14, 0, 0),
        end_time=datetime(2026, 6, 5, 18, 0, 0),
        status='completed',
        operator='张师傅'
    )

    InspectionRecord.objects.create(
        batch=batch1,
        stage_type='evaporation',
        inspection_date=date(2026, 6, 4),
        temperature=85.0,
        concentration=35.0,
        ph_value=6.8,
        operator='李检测员',
        remarks='蒸发中期'
    )

    InspectionRecord.objects.create(
        batch=batch1,
        stage_type='evaporation',
        inspection_date=date(2026, 6, 5),
        temperature=95.0,
        concentration=52.0,
        ph_value=6.5,
        operator='李检测员',
        remarks='蒸发末期'
    )

    stage1_4 = ProcessStage.objects.create(
        batch=batch1,
        stage_type='crystallization',
        start_time=datetime(2026, 6, 5, 20, 0, 0),
        end_time=datetime(2026, 6, 7, 10, 0, 0),
        status='completed',
        operator='王师傅'
    )

    InspectionRecord.objects.create(
        batch=batch1,
        stage_type='crystallization',
        inspection_date=date(2026, 6, 6),
        temperature=15.0,
        concentration=60.0,
        ph_value=6.3,
        operator='李检测员',
        remarks='结晶初期'
    )

    crystal1 = CrystallizationResult.objects.create(
        batch=batch1,
        crystal_weight=18.5,
        crystal_purity=96.5,
        crystallization_date=date(2026, 6, 7),
        operator='张师傅',
        remarks='第一批成品，质量良好'
    )

    print(f'  - 批次 {batch1.batch_no} 创建完成，结晶率: {crystal1.get_crystallization_rate()}%')

    batch2 = RawMaterialBatch.objects.create(
        batch_no='XC-2026-002',
        material_source='内蒙古锡林郭勒碱湖',
        material_weight=120.0,
        start_date=date(2026, 6, 5),
        operator='王师傅',
        remarks='内蒙原料试生产'
    )

    stage2_1 = ProcessStage.objects.create(
        batch=batch2,
        stage_type='leaching',
        start_time=datetime(2026, 6, 5, 9, 0, 0),
        end_time=datetime(2026, 6, 7, 10, 0, 0),
        status='completed',
        operator='王师傅'
    )

    InspectionRecord.objects.create(
        batch=batch2,
        stage_type='leaching',
        inspection_date=date(2026, 6, 6),
        temperature=55.0,
        concentration=10.0,
        ph_value=8.5,
        operator='李检测员',
        remarks='内蒙原料碱度较高'
    )

    stage2_2 = ProcessStage.objects.create(
        batch=batch2,
        stage_type='filtration',
        start_time=datetime(2026, 6, 7, 11, 0, 0),
        end_time=datetime(2026, 6, 8, 14, 0, 0),
        status='completed',
        operator='张师傅'
    )

    InspectionRecord.objects.create(
        batch=batch2,
        stage_type='filtration',
        inspection_date=date(2026, 6, 8),
        temperature=28.0,
        concentration=14.0,
        ph_value=8.2,
        operator='李检测员'
    )

    stage2_3 = ProcessStage.objects.create(
        batch=batch2,
        stage_type='evaporation',
        start_time=datetime(2026, 6, 8, 16, 0, 0),
        end_time=datetime(2026, 6, 10, 20, 0, 0),
        status='completed',
        operator='王师傅'
    )

    InspectionRecord.objects.create(
        batch=batch2,
        stage_type='evaporation',
        inspection_date=date(2026, 6, 9),
        temperature=90.0,
        concentration=28.0,
        ph_value=8.0,
        operator='李检测员',
        remarks='浓度提升较慢'
    )

    stage2_4 = ProcessStage.objects.create(
        batch=batch2,
        stage_type='crystallization',
        start_time=datetime(2026, 6, 10, 22, 0, 0),
        end_time=datetime(2026, 6, 13, 8, 0, 0),
        status='completed',
        operator='张师傅'
    )

    crystal2 = CrystallizationResult.objects.create(
        batch=batch2,
        crystal_weight=12.0,
        crystal_purity=93.2,
        crystallization_date=date(2026, 6, 13),
        operator='王师傅',
        remarks='内蒙原料产率偏低'
    )

    abnormal1 = AbnormalDisposal.objects.create(
        batch=batch2,
        abnormal_type='low_yield',
        stage_type='crystallization',
        discover_date=date(2026, 6, 13),
        description='结晶率仅为10%，远低于预期的15%，且纯度偏低。',
        reason='原料来源不同，内蒙碱湖含盐量较低，杂质较多，导致最终产率下降。',
        disposal_measure='1. 增加原料预处理工序，去除杂质；2. 延长浸取时间，提高浸取率；3. 调整蒸发温度和时间。',
        disposal_status='resolved',
        handler='李工程师',
        resolve_date=date(2026, 6, 15),
        remarks='已完成工艺调整，下一批次验证中'
    )

    print(f'  - 批次 {batch2.batch_no} 创建完成，结晶率: {crystal2.get_crystallization_rate()}%（异常批次）')

    batch3 = RawMaterialBatch.objects.create(
        batch_no='XC-2026-003',
        material_source='山西运城盐湖',
        material_weight=150.0,
        start_date=date(2026, 6, 10),
        operator='张师傅',
        remarks='扩大生产批次'
    )

    stage3_1 = ProcessStage.objects.create(
        batch=batch3,
        stage_type='leaching',
        start_time=datetime(2026, 6, 10, 7, 0, 0),
        status='in_progress',
        operator='赵师傅'
    )

    InspectionRecord.objects.create(
        batch=batch3,
        stage_type='leaching',
        inspection_date=date(2026, 6, 11),
        temperature=50.0,
        concentration=15.5,
        ph_value=7.1,
        operator='李检测员',
        remarks='正常范围内'
    )

    print(f'  - 批次 {batch3.batch_no} 创建完成（进行中）')

    batch4 = RawMaterialBatch.objects.create(
        batch_no='XC-2026-004',
        material_source='四川自贡井盐',
        material_weight=80.0,
        start_date=date(2026, 6, 15),
        operator='赵师傅',
        remarks='川料试生产'
    )

    stage4_1 = ProcessStage.objects.create(
        batch=batch4,
        stage_type='leaching',
        start_time=datetime(2026, 6, 15, 8, 30, 0),
        end_time=datetime(2026, 6, 16, 12, 0, 0),
        status='completed',
        operator='赵师傅'
    )

    stage4_2 = ProcessStage.objects.create(
        batch=batch4,
        stage_type='filtration',
        start_time=datetime(2026, 6, 16, 14, 0, 0),
        status='in_progress',
        operator='王师傅'
    )

    InspectionRecord.objects.create(
        batch=batch4,
        stage_type='leaching',
        inspection_date=date(2026, 6, 16),
        temperature=62.0,
        concentration=22.0,
        ph_value=6.9,
        operator='李检测员',
        remarks='井盐原料品质优良'
    )

    InspectionRecord.objects.create(
        batch=batch4,
        stage_type='filtration',
        inspection_date=date(2026, 6, 17),
        temperature=30.0,
        concentration=20.5,
        ph_value=6.8,
        operator='李检测员'
    )

    print(f'  - 批次 {batch4.batch_no} 创建完成（过滤阶段）')

    print(f'\n示例数据创建完成！共创建 {RawMaterialBatch.objects.count()} 个批次')
    print(f'  - 已完成批次: {CrystallizationResult.objects.count()} 个')
    print(f'  - 进行中批次: {ProcessStage.objects.filter(status="in_progress").count()} 个')
    print(f'  - 异常记录: {AbnormalDisposal.objects.count()} 条')
    print(f'  - 检测记录: {InspectionRecord.objects.count()} 条')


if __name__ == '__main__':
    if RawMaterialBatch.objects.count() > 0:
        print('数据库中已有数据，是否继续添加示例数据？')
        create_sample_data()
    else:
        create_sample_data()
