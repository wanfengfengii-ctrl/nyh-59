from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Avg, Count
from django.utils import timezone
from datetime import datetime
from .models import (
    RawMaterialBatch, ProcessStage, InspectionRecord,
    CrystallizationResult, AbnormalDisposal,
    STAGE_CHOICES, STAGE_ORDER
)


CRYSTALLIZATION_THRESHOLD = 15.0


def dashboard(request):
    total_batches = RawMaterialBatch.objects.count()
    completed_batches = CrystallizationResult.objects.count()
    in_progress_stages = ProcessStage.objects.filter(status='in_progress').count()
    pending_abnormal = AbnormalDisposal.objects.filter(disposal_status='pending').count()

    recent_batches = RawMaterialBatch.objects.all()[:5]
    recent_inspections = InspectionRecord.objects.all()[:10]
    recent_abnormal = AbnormalDisposal.objects.all()[:5]

    context = {
        'total_batches': total_batches,
        'completed_batches': completed_batches,
        'in_progress_stages': in_progress_stages,
        'pending_abnormal': pending_abnormal,
        'recent_batches': recent_batches,
        'recent_inspections': recent_inspections,
        'recent_abnormal': recent_abnormal,
    }
    return render(request, 'production/dashboard.html', context)


def batch_list(request):
    batches = RawMaterialBatch.objects.all()
    
    source_filter = request.GET.get('source', '')
    stage_filter = request.GET.get('stage', '')
    
    if source_filter:
        batches = batches.filter(material_source__icontains=source_filter)
    
    if stage_filter:
        batches = batches.filter(processstage__stage_type=stage_filter, processstage__status='in_progress')
    
    context = {
        'batches': batches,
        'source_filter': source_filter,
        'stage_filter': stage_filter,
        'stage_choices': STAGE_CHOICES,
    }
    return render(request, 'production/batch_list.html', context)


def batch_detail(request, pk):
    batch = get_object_or_404(RawMaterialBatch, pk=pk)
    stages = batch.processstage_set.all().order_by('start_time')
    inspections = batch.inspectionrecord_set.all().order_by('-inspection_date')
    abnormal_list = batch.abnormaldisposal_set.all().order_by('-discover_date')
    
    try:
        crystallization = batch.crystallizationresult
    except CrystallizationResult.DoesNotExist:
        crystallization = None
    
    stage_inspections = {}
    for stage_type, _ in STAGE_CHOICES:
        stage_inspections[stage_type] = inspections.filter(stage_type=stage_type)
    
    timeline_data = []
    for stage in stages:
        item = {
            'stage': stage,
            'inspections': inspections.filter(stage_type=stage.stage_type).order_by('inspection_date'),
        }
        timeline_data.append(item)
    
    context = {
        'batch': batch,
        'stages': stages,
        'inspections': inspections,
        'abnormal_list': abnormal_list,
        'crystallization': crystallization,
        'stage_inspections': stage_inspections,
        'timeline_data': timeline_data,
        'stage_choices': STAGE_CHOICES,
    }
    return render(request, 'production/batch_detail.html', context)


def batch_create(request):
    if request.method == 'POST':
        batch_no = request.POST.get('batch_no', '').strip()
        material_source = request.POST.get('material_source', '').strip()
        material_weight = request.POST.get('material_weight', '')
        start_date = request.POST.get('start_date', '')
        operator = request.POST.get('operator', '').strip()
        remarks = request.POST.get('remarks', '').strip()
        
        errors = []
        
        if not batch_no:
            errors.append('请输入批次编号')
        elif RawMaterialBatch.objects.filter(batch_no=batch_no).exists():
            errors.append('批次编号已存在，不能重复')
        
        if not material_source:
            errors.append('请输入原料来源')
        
        try:
            material_weight = float(material_weight)
            if material_weight <= 0:
                errors.append('原料重量必须大于0')
        except (ValueError, TypeError):
            errors.append('请输入有效的原料重量')
            material_weight = 0
        
        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                if start_date > datetime.now().date():
                    errors.append('开始日期不能晚于当前日期')
            except ValueError:
                errors.append('请输入有效的开始日期')
                start_date = None
        else:
            start_date = datetime.now().date()
        
        if not operator:
            errors.append('请输入操作人员')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'batch_no': batch_no,
                'material_source': material_source,
                'material_weight': material_weight,
                'start_date': start_date,
                'operator': operator,
                'remarks': remarks,
            }
            return render(request, 'production/batch_form.html', context)
        
        batch = RawMaterialBatch.objects.create(
            batch_no=batch_no,
            material_source=material_source,
            material_weight=material_weight,
            start_date=start_date,
            operator=operator,
            remarks=remarks,
        )
        
        messages.success(request, f'批次 {batch_no} 创建成功')
        return redirect('production:batch_detail', pk=batch.pk)
    
    return render(request, 'production/batch_form.html')


def batch_edit(request, pk):
    batch = get_object_or_404(RawMaterialBatch, pk=pk)
    
    if request.method == 'POST':
        material_source = request.POST.get('material_source', '').strip()
        material_weight = request.POST.get('material_weight', '')
        start_date = request.POST.get('start_date', '')
        operator = request.POST.get('operator', '').strip()
        remarks = request.POST.get('remarks', '').strip()
        
        errors = []
        
        if not material_source:
            errors.append('请输入原料来源')
        
        try:
            material_weight = float(material_weight)
            if material_weight <= 0:
                errors.append('原料重量必须大于0')
        except (ValueError, TypeError):
            errors.append('请输入有效的原料重量')
            material_weight = batch.material_weight
        
        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                if start_date > datetime.now().date():
                    errors.append('开始日期不能晚于当前日期')
            except ValueError:
                errors.append('请输入有效的开始日期')
                start_date = batch.start_date
        else:
            start_date = batch.start_date
        
        if not operator:
            errors.append('请输入操作人员')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'batch': batch,
                'material_source': material_source,
                'material_weight': material_weight,
                'start_date': start_date,
                'operator': operator,
                'remarks': remarks,
                'editing': True,
            }
            return render(request, 'production/batch_form.html', context)
        
        batch.material_source = material_source
        batch.material_weight = material_weight
        batch.start_date = start_date
        batch.operator = operator
        batch.remarks = remarks
        batch.save()
        
        messages.success(request, f'批次 {batch.batch_no} 更新成功')
        return redirect('production:batch_detail', pk=batch.pk)
    
    context = {
        'batch': batch,
        'batch_no': batch.batch_no,
        'material_source': batch.material_source,
        'material_weight': batch.material_weight,
        'start_date': batch.start_date,
        'operator': batch.operator,
        'remarks': batch.remarks,
        'editing': True,
    }
    return render(request, 'production/batch_form.html', context)


def inspection_list(request):
    inspections = InspectionRecord.objects.all()
    
    stage_filter = request.GET.get('stage', '')
    batch_filter = request.GET.get('batch', '')
    
    if stage_filter:
        inspections = inspections.filter(stage_type=stage_filter)
    
    if batch_filter:
        inspections = inspections.filter(batch__batch_no__icontains=batch_filter)
    
    context = {
        'inspections': inspections,
        'stage_filter': stage_filter,
        'batch_filter': batch_filter,
        'stage_choices': STAGE_CHOICES,
    }
    return render(request, 'production/inspection_list.html', context)


def inspection_create(request, batch_id):
    batch = get_object_or_404(RawMaterialBatch, pk=batch_id)
    
    if request.method == 'POST':
        stage_type = request.POST.get('stage_type', '')
        inspection_date = request.POST.get('inspection_date', '')
        temperature = request.POST.get('temperature', '')
        concentration = request.POST.get('concentration', '')
        ph_value = request.POST.get('ph_value', '')
        operator = request.POST.get('operator', '').strip()
        remarks = request.POST.get('remarks', '').strip()
        
        errors = []
        
        if not stage_type:
            errors.append('请选择工序阶段')
        
        valid_stages = [s[0] for s in STAGE_CHOICES]
        if stage_type not in valid_stages:
            errors.append('无效的工序阶段')
        
        if inspection_date:
            try:
                inspection_date = datetime.strptime(inspection_date, '%Y-%m-%d').date()
                if inspection_date > datetime.now().date():
                    errors.append('检测日期不能晚于当前日期')
            except ValueError:
                errors.append('请输入有效的检测日期')
                inspection_date = None
        else:
            inspection_date = datetime.now().date()
        
        try:
            temperature = float(temperature)
        except (ValueError, TypeError):
            errors.append('请输入有效的温度值')
            temperature = 0
        
        try:
            concentration = float(concentration)
        except (ValueError, TypeError):
            errors.append('请输入有效的浓度值')
            concentration = 0
        
        ph_value_parsed = None
        if ph_value:
            try:
                ph_value_parsed = float(ph_value)
                if not (0 <= ph_value_parsed <= 14):
                    errors.append('pH值应在0-14范围内')
            except (ValueError, TypeError):
                errors.append('请输入有效的pH值')
        
        if not operator:
            errors.append('请输入检测人员')
        
        if stage_type and not errors:
            if stage_type == 'leaching':
                if not (20 <= temperature <= 100):
                    errors.append('浸取阶段温度应在20-100°C范围内')
                if not (5 <= concentration <= 30):
                    errors.append('浸取阶段浓度应在5-30%范围内')
            elif stage_type == 'filtration':
                if not (15 <= temperature <= 80):
                    errors.append('过滤阶段温度应在15-80°C范围内')
                if not (5 <= concentration <= 35):
                    errors.append('过滤阶段浓度应在5-35%范围内')
            elif stage_type == 'evaporation':
                if not (60 <= temperature <= 120):
                    errors.append('蒸发阶段温度应在60-120°C范围内')
                if not (20 <= concentration <= 60):
                    errors.append('蒸发阶段浓度应在20-60%范围内')
            elif stage_type == 'crystallization':
                if not (0 <= temperature <= 50):
                    errors.append('结晶阶段温度应在0-50°C范围内')
                if not (30 <= concentration <= 80):
                    errors.append('结晶阶段浓度应在30-80%范围内')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'batch': batch,
                'stage_type': stage_type,
                'inspection_date': inspection_date,
                'temperature': temperature,
                'concentration': concentration,
                'ph_value': ph_value,
                'operator': operator,
                'remarks': remarks,
                'stage_choices': STAGE_CHOICES,
            }
            return render(request, 'production/inspection_form.html', context)
        
        InspectionRecord.objects.create(
            batch=batch,
            stage_type=stage_type,
            inspection_date=inspection_date,
            temperature=temperature,
            concentration=concentration,
            ph_value=ph_value_parsed,
            operator=operator,
            remarks=remarks,
        )
        
        messages.success(request, '检测记录添加成功')
        return redirect('production:batch_detail', pk=batch.pk)
    
    context = {
        'batch': batch,
        'stage_choices': STAGE_CHOICES,
    }
    return render(request, 'production/inspection_form.html', context)


def stage_create(request, batch_id):
    batch = get_object_or_404(RawMaterialBatch, pk=batch_id)
    
    if request.method == 'POST':
        stage_type = request.POST.get('stage_type', '')
        operator = request.POST.get('operator', '').strip()
        remarks = request.POST.get('remarks', '').strip()
        
        errors = []
        
        valid_stages = [s[0] for s in STAGE_CHOICES]
        if stage_type not in valid_stages:
            errors.append('请选择有效的工序阶段')
        
        current_idx = STAGE_ORDER.index(stage_type) if stage_type in STAGE_ORDER else -1
        if current_idx > 0:
            prev_stage_type = STAGE_ORDER[current_idx - 1]
            prev_stages = ProcessStage.objects.filter(
                batch=batch,
                stage_type=prev_stage_type,
                status='completed'
            )
            if not prev_stages.exists():
                prev_name = STAGE_CHOICES[current_idx - 1][1]
                current_name = STAGE_CHOICES[current_idx][1]
                errors.append(f'未完成{prev_name}阶段不能进入{current_name}阶段')
        
        existing_stage = ProcessStage.objects.filter(
            batch=batch,
            stage_type=stage_type
        ).exists()
        if existing_stage:
            errors.append('该阶段已存在')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'batch': batch,
                'stage_type': stage_type,
                'operator': operator,
                'remarks': remarks,
                'stage_choices': STAGE_CHOICES,
            }
            return render(request, 'production/stage_form.html', context)
        
        ProcessStage.objects.create(
            batch=batch,
            stage_type=stage_type,
            operator=operator,
            remarks=remarks,
        )
        
        messages.success(request, '工序阶段创建成功')
        return redirect('production:batch_detail', pk=batch.pk)
    
    context = {
        'batch': batch,
        'stage_choices': STAGE_CHOICES,
    }
    return render(request, 'production/stage_form.html', context)


def stage_complete(request, pk):
    stage = get_object_or_404(ProcessStage, pk=pk)
    
    if request.method == 'POST':
        stage.status = 'completed'
        stage.end_time = timezone.now()
        stage.save()
        
        messages.success(request, f'{stage.get_stage_type_display()}阶段已完成')
        return redirect('production:batch_detail', pk=stage.batch.pk)
    
    return redirect('production:batch_detail', pk=stage.batch.pk)


def crystallization_create(request, batch_id):
    batch = get_object_or_404(RawMaterialBatch, pk=batch_id)
    
    try:
        crystallization = batch.crystallizationresult
        editing = True
    except CrystallizationResult.DoesNotExist:
        crystallization = None
        editing = False
    
    if request.method == 'POST':
        crystal_weight = request.POST.get('crystal_weight', '')
        crystal_purity = request.POST.get('crystal_purity', '')
        crystallization_date = request.POST.get('crystallization_date', '')
        operator = request.POST.get('operator', '').strip()
        remarks = request.POST.get('remarks', '').strip()
        
        errors = []
        
        try:
            crystal_weight = float(crystal_weight)
            if crystal_weight <= 0:
                errors.append('结晶重量必须大于0')
            elif crystal_weight > batch.material_weight:
                errors.append('结晶重量不能超过原料重量')
        except (ValueError, TypeError):
            errors.append('请输入有效的结晶重量')
            crystal_weight = 0
        
        try:
            crystal_purity = float(crystal_purity)
            if not (0 <= crystal_purity <= 100):
                errors.append('结晶纯度应在0-100%范围内')
        except (ValueError, TypeError):
            errors.append('请输入有效的结晶纯度')
            crystal_purity = 95.0
        
        if crystallization_date:
            try:
                crystallization_date = datetime.strptime(crystallization_date, '%Y-%m-%d').date()
                if crystallization_date > datetime.now().date():
                    errors.append('结晶日期不能晚于当前日期')
            except ValueError:
                errors.append('请输入有效的结晶日期')
                crystallization_date = None
        else:
            crystallization_date = datetime.now().date()
        
        if not operator:
            errors.append('请输入操作人员')
        
        crystallization_rate = 0
        if crystal_weight > 0 and batch.material_weight > 0:
            crystallization_rate = (crystal_weight / batch.material_weight) * 100
        
        need_abnormal = crystallization_rate < CRYSTALLIZATION_THRESHOLD
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'batch': batch,
                'crystallization': crystallization,
                'crystal_weight': crystal_weight,
                'crystal_purity': crystal_purity,
                'crystallization_date': crystallization_date,
                'operator': operator,
                'remarks': remarks,
                'editing': editing,
                'threshold': CRYSTALLIZATION_THRESHOLD,
            }
            return render(request, 'production/crystallization_form.html', context)
        
        if crystallization:
            crystallization.crystal_weight = crystal_weight
            crystallization.crystal_purity = crystal_purity
            crystallization.crystallization_date = crystallization_date
            crystallization.operator = operator
            crystallization.remarks = remarks
            crystallization.save()
            messages.success(request, '结晶结果更新成功')
        else:
            CrystallizationResult.objects.create(
                batch=batch,
                crystal_weight=crystal_weight,
                crystal_purity=crystal_purity,
                crystallization_date=crystallization_date,
                operator=operator,
                remarks=remarks,
            )
            messages.success(request, '结晶结果添加成功')
        
        if need_abnormal:
            messages.warning(request, f'结晶率为{crystallization_rate:.2f}%，低于阈值{CRYSTALLIZATION_THRESHOLD}%，请填写异常处置记录')
            return redirect('production:abnormal_create', batch_id=batch.pk)
        
        return redirect('production:batch_detail', pk=batch.pk)
    
    if crystallization:
        context = {
            'batch': batch,
            'crystallization': crystallization,
            'crystal_weight': crystallization.crystal_weight,
            'crystal_purity': crystallization.crystal_purity,
            'crystallization_date': crystallization.crystallization_date,
            'operator': crystallization.operator,
            'remarks': crystallization.remarks,
            'editing': editing,
            'threshold': CRYSTALLIZATION_THRESHOLD,
        }
    else:
        context = {
            'batch': batch,
            'crystal_purity': 95.0,
            'editing': editing,
            'threshold': CRYSTALLIZATION_THRESHOLD,
        }
    return render(request, 'production/crystallization_form.html', context)


def abnormal_list(request):
    abnormal_list = AbnormalDisposal.objects.all()
    
    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', '')
    
    if type_filter:
        abnormal_list = abnormal_list.filter(abnormal_type=type_filter)
    
    if status_filter:
        abnormal_list = abnormal_list.filter(disposal_status=status_filter)
    
    context = {
        'abnormal_list': abnormal_list,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'abnormal_type_choices': AbnormalDisposal.ABNORMAL_TYPE_CHOICES,
        'disposal_status_choices': AbnormalDisposal.DISPOSAL_STATUS_CHOICES,
    }
    return render(request, 'production/abnormal_list.html', context)


def abnormal_create(request, batch_id):
    batch = get_object_or_404(RawMaterialBatch, pk=batch_id)
    
    if request.method == 'POST':
        abnormal_type = request.POST.get('abnormal_type', '')
        stage_type = request.POST.get('stage_type', '')
        discover_date = request.POST.get('discover_date', '')
        description = request.POST.get('description', '').strip()
        reason = request.POST.get('reason', '').strip()
        disposal_measure = request.POST.get('disposal_measure', '').strip()
        disposal_status = request.POST.get('disposal_status', 'pending')
        handler = request.POST.get('handler', '').strip()
        resolve_date = request.POST.get('resolve_date', '')
        remarks = request.POST.get('remarks', '').strip()
        
        errors = []
        
        if not abnormal_type:
            errors.append('请选择异常类型')
        
        if not stage_type:
            errors.append('请选择发生阶段')
        
        if discover_date:
            try:
                discover_date = datetime.strptime(discover_date, '%Y-%m-%d').date()
                if discover_date > datetime.now().date():
                    errors.append('发现日期不能晚于当前日期')
            except ValueError:
                errors.append('请输入有效的发现日期')
                discover_date = None
        else:
            discover_date = datetime.now().date()
        
        if not description:
            errors.append('请输入异常描述')
        
        if not reason:
            errors.append('请填写异常原因')
        
        resolve_date_parsed = None
        if resolve_date:
            try:
                resolve_date_parsed = datetime.strptime(resolve_date, '%Y-%m-%d').date()
                if resolve_date_parsed < discover_date:
                    errors.append('解决日期不能早于发现日期')
            except ValueError:
                errors.append('请输入有效的解决日期')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'batch': batch,
                'abnormal_type': abnormal_type,
                'stage_type': stage_type,
                'discover_date': discover_date,
                'description': description,
                'reason': reason,
                'disposal_measure': disposal_measure,
                'disposal_status': disposal_status,
                'handler': handler,
                'resolve_date': resolve_date,
                'remarks': remarks,
                'abnormal_type_choices': AbnormalDisposal.ABNORMAL_TYPE_CHOICES,
                'stage_choices': STAGE_CHOICES,
                'disposal_status_choices': AbnormalDisposal.DISPOSAL_STATUS_CHOICES,
            }
            return render(request, 'production/abnormal_form.html', context)
        
        AbnormalDisposal.objects.create(
            batch=batch,
            abnormal_type=abnormal_type,
            stage_type=stage_type,
            discover_date=discover_date,
            description=description,
            reason=reason,
            disposal_measure=disposal_measure,
            disposal_status=disposal_status,
            handler=handler,
            resolve_date=resolve_date_parsed,
            remarks=remarks,
        )
        
        messages.success(request, '异常处置记录添加成功')
        return redirect('production:batch_detail', pk=batch.pk)
    
    context = {
        'batch': batch,
        'abnormal_type_choices': AbnormalDisposal.ABNORMAL_TYPE_CHOICES,
        'stage_choices': STAGE_CHOICES,
        'disposal_status_choices': AbnormalDisposal.DISPOSAL_STATUS_CHOICES,
    }
    return render(request, 'production/abnormal_form.html', context)


def abnormal_edit(request, pk):
    abnormal = get_object_or_404(AbnormalDisposal, pk=pk)
    
    if request.method == 'POST':
        abnormal_type = request.POST.get('abnormal_type', '')
        stage_type = request.POST.get('stage_type', '')
        discover_date = request.POST.get('discover_date', '')
        description = request.POST.get('description', '').strip()
        reason = request.POST.get('reason', '').strip()
        disposal_measure = request.POST.get('disposal_measure', '').strip()
        disposal_status = request.POST.get('disposal_status', 'pending')
        handler = request.POST.get('handler', '').strip()
        resolve_date = request.POST.get('resolve_date', '')
        remarks = request.POST.get('remarks', '').strip()
        
        errors = []
        
        if not abnormal_type:
            errors.append('请选择异常类型')
        
        if not stage_type:
            errors.append('请选择发生阶段')
        
        if discover_date:
            try:
                discover_date = datetime.strptime(discover_date, '%Y-%m-%d').date()
                if discover_date > datetime.now().date():
                    errors.append('发现日期不能晚于当前日期')
            except ValueError:
                errors.append('请输入有效的发现日期')
                discover_date = abnormal.discover_date
        else:
            discover_date = abnormal.discover_date
        
        if not description:
            errors.append('请输入异常描述')
        
        if not reason:
            errors.append('请填写异常原因')
        
        resolve_date_parsed = None
        if resolve_date:
            try:
                resolve_date_parsed = datetime.strptime(resolve_date, '%Y-%m-%d').date()
                if resolve_date_parsed < discover_date:
                    errors.append('解决日期不能早于发现日期')
            except ValueError:
                errors.append('请输入有效的解决日期')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'abnormal': abnormal,
                'batch': abnormal.batch,
                'abnormal_type': abnormal_type,
                'stage_type': stage_type,
                'discover_date': discover_date,
                'description': description,
                'reason': reason,
                'disposal_measure': disposal_measure,
                'disposal_status': disposal_status,
                'handler': handler,
                'resolve_date': resolve_date,
                'remarks': remarks,
                'editing': True,
                'abnormal_type_choices': AbnormalDisposal.ABNORMAL_TYPE_CHOICES,
                'stage_choices': STAGE_CHOICES,
                'disposal_status_choices': AbnormalDisposal.DISPOSAL_STATUS_CHOICES,
            }
            return render(request, 'production/abnormal_form.html', context)
        
        abnormal.abnormal_type = abnormal_type
        abnormal.stage_type = stage_type
        abnormal.discover_date = discover_date
        abnormal.description = description
        abnormal.reason = reason
        abnormal.disposal_measure = disposal_measure
        abnormal.disposal_status = disposal_status
        abnormal.handler = handler
        abnormal.resolve_date = resolve_date_parsed
        abnormal.remarks = remarks
        abnormal.save()
        
        messages.success(request, '异常处置记录更新成功')
        return redirect('production:batch_detail', pk=abnormal.batch.pk)
    
    context = {
        'abnormal': abnormal,
        'batch': abnormal.batch,
        'abnormal_type': abnormal.abnormal_type,
        'stage_type': abnormal.stage_type,
        'discover_date': abnormal.discover_date,
        'description': abnormal.description,
        'reason': abnormal.reason,
        'disposal_measure': abnormal.disposal_measure,
        'disposal_status': abnormal.disposal_status,
        'handler': abnormal.handler,
        'resolve_date': abnormal.resolve_date,
        'remarks': abnormal.remarks,
        'editing': True,
        'abnormal_type_choices': AbnormalDisposal.ABNORMAL_TYPE_CHOICES,
        'stage_choices': STAGE_CHOICES,
        'disposal_status_choices': AbnormalDisposal.DISPOSAL_STATUS_CHOICES,
    }
    return render(request, 'production/abnormal_form.html', context)


def batch_comparison(request):
    batches = RawMaterialBatch.objects.all()
    selected_batches = request.GET.getlist('batches', [])
    
    comparison_data = []
    
    if selected_batches:
        selected_batch_objs = RawMaterialBatch.objects.filter(pk__in=selected_batches)
        
        for batch in selected_batch_objs:
            try:
                crystal = batch.crystallizationresult
                rate = crystal.get_crystallization_rate()
            except CrystallizationResult.DoesNotExist:
                crystal = None
                rate = None
            
            inspections = batch.inspectionrecord_set.all()
            avg_temp = inspections.aggregate(avg=Avg('temperature'))['avg']
            avg_conc = inspections.aggregate(avg=Avg('concentration'))['avg']
            
            stages = batch.processstage_set.filter(status='completed')
            total_duration = None
            if stages.exists() and stages.first().start_time and stages.last().end_time:
                total_duration = (stages.last().end_time - stages.first().start_time).total_seconds() / 3600
            
            comparison_data.append({
                'batch': batch,
                'crystal': crystal,
                'rate': rate,
                'avg_temp': round(avg_temp, 2) if avg_temp else None,
                'avg_conc': round(avg_conc, 2) if avg_conc else None,
                'total_duration': round(total_duration, 2) if total_duration else None,
                'stage_count': stages.count(),
            })
    
    sources = RawMaterialBatch.objects.values_list('material_source', flat=True).distinct()
    
    source_stats = []
    for source in sources:
        source_batches = RawMaterialBatch.objects.filter(material_source=source)
        crystal_results = CrystallizationResult.objects.filter(batch__material_source=source)
        rates = [r.get_crystallization_rate() for r in crystal_results if r.batch.material_weight > 0]
        
        if rates:
            avg_rate = sum(rates) / len(rates)
            source_stats.append({
                'source': source,
                'batch_count': source_batches.count(),
                'completed_count': crystal_results.count(),
                'avg_rate': round(avg_rate, 2),
                'min_rate': round(min(rates), 2),
                'max_rate': round(max(rates), 2),
            })
    
    context = {
        'batches': batches,
        'selected_batches': selected_batches,
        'comparison_data': comparison_data,
        'source_stats': source_stats,
    }
    return render(request, 'production/batch_comparison.html', context)
