from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Avg, Count, Q, F, ExpressionWrapper, FloatField
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from datetime import datetime, timedelta
from django.db import transaction
import csv
import io
import json
from .models import (
    RawMaterialBatch, ProcessStage, InspectionRecord,
    CrystallizationResult, AbnormalDisposal,
    STAGE_CHOICES, STAGE_ORDER,
    AlertRule, AlertRecord, StageAudit, ParameterRecommendation,
    ExportRecord, MaterialQualityStats, AbnormalClosure,
    ALERT_LEVEL_CHOICES, ALERT_STATUS_CHOICES, ALERT_TYPE_CHOICES,
    AUDIT_STATUS_CHOICES, EXPORT_TYPE_CHOICES, EXPORT_STATUS_CHOICES
)


CRYSTALLIZATION_THRESHOLD = 15.0


def check_alerts_for_inspection(inspection):
    alerts = []
    rules = AlertRule.objects.filter(
        is_enabled=True,
        stage_type=inspection.stage_type,
        alert_type__in=['temperature', 'concentration', 'ph_value']
    )

    for rule in rules:
        value = None
        if rule.alert_type == 'temperature':
            value = inspection.temperature
        elif rule.alert_type == 'concentration':
            value = inspection.concentration
        elif rule.alert_type == 'ph_value':
            value = inspection.ph_value

        if value is not None and rule.check_value(value):
            threshold = rule.get_threshold_display()
            title = f'{inspection.get_stage_type_display()}{rule.get_alert_type_display()}'
            message = f'批次 {inspection.batch.batch_no} 在{inspection.get_stage_type_display()}阶段检测到{rule.get_alert_type_display()}异常。当前值: {value}，阈值范围: {threshold}'
            
            existing = AlertRecord.objects.filter(
                inspection=inspection,
                alert_type=rule.alert_type,
                alert_status__in=['active', 'acknowledged']
            ).exists()
            
            if not existing:
                alert = AlertRecord.objects.create(
                    batch=inspection.batch,
                    inspection=inspection,
                    alert_type=rule.alert_type,
                    alert_level=rule.alert_level,
                    alert_title=title,
                    alert_message=message,
                    indicator_value=value,
                    threshold=threshold,
                )
                alerts.append(alert)
    
    return alerts


def check_alerts_for_crystallization(crystallization):
    alerts = []
    rate = crystallization.get_crystallization_rate()
    purity = crystallization.crystal_purity

    rules = AlertRule.objects.filter(
        is_enabled=True,
        alert_type__in=['crystallization_rate', 'crystallization_purity']
    )

    for rule in rules:
        value = None
        if rule.alert_type == 'crystallization_rate' and rate:
            value = rate
        elif rule.alert_type == 'crystallization_purity':
            value = purity

        if value is not None and rule.check_value(value):
            threshold = rule.get_threshold_display()
            title = f'{rule.get_alert_type_display()}'
            message = f'批次 {crystallization.batch.batch_no} {rule.get_alert_type_display()}。当前值: {value}%，阈值: {threshold}'
            
            existing = AlertRecord.objects.filter(
                crystallization=crystallization,
                alert_type=rule.alert_type,
                alert_status__in=['active', 'acknowledged']
            ).exists()
            
            if not existing:
                alert = AlertRecord.objects.create(
                    batch=crystallization.batch,
                    crystallization=crystallization,
                    alert_type=rule.alert_type,
                    alert_level=rule.alert_level,
                    alert_title=title,
                    alert_message=message,
                    indicator_value=value,
                    threshold=threshold,
                )
                alerts.append(alert)
    
    return alerts


def check_abnormal_rate_alert():
    total_batches = RawMaterialBatch.objects.count()
    if total_batches == 0:
        return None

    abnormal_batches = AbnormalDisposal.objects.values('batch').distinct().count()
    abnormal_rate = (abnormal_batches / total_batches) * 100

    rules = AlertRule.objects.filter(
        is_enabled=True,
        alert_type='abnormal_rate'
    )

    for rule in rules:
        if rule.check_value(abnormal_rate):
            threshold = rule.get_threshold_display()
            title = '批次异常率过高'
            message = f'当前批次异常率为{abnormal_rate:.2f}%，超过阈值{threshold}。涉及{abnormal_batches}个批次，共{total_batches}个批次。'
            
            existing = AlertRecord.objects.filter(
                alert_type='abnormal_rate',
                alert_status__in=['active', 'acknowledged'],
                triggered_at__gte=timezone.now() - timedelta(hours=24)
            ).exists()
            
            if not existing:
                alert = AlertRecord.objects.create(
                    alert_type=rule.alert_type,
                    alert_level=rule.alert_level,
                    alert_title=title,
                    alert_message=message,
                    indicator_value=round(abnormal_rate, 2),
                    threshold=threshold,
                )
                return alert
    
    return None


def alert_center(request):
    alerts = AlertRecord.objects.all()
    
    level_filter = request.GET.get('level', '')
    status_filter = request.GET.get('status', '')
    type_filter = request.GET.get('type', '')
    
    if level_filter:
        alerts = alerts.filter(alert_level=level_filter)
    if status_filter:
        alerts = alerts.filter(alert_status=status_filter)
    if type_filter:
        alerts = alerts.filter(alert_type=type_filter)
    
    stats = {
        'total': AlertRecord.objects.count(),
        'active': AlertRecord.objects.filter(alert_status='active').count(),
        'acknowledged': AlertRecord.objects.filter(alert_status='acknowledged').count(),
        'resolved': AlertRecord.objects.filter(alert_status='resolved').count(),
        'danger': AlertRecord.objects.filter(alert_level='danger', alert_status__in=['active', 'acknowledged']).count(),
        'warning': AlertRecord.objects.filter(alert_level='warning', alert_status__in=['active', 'acknowledged']).count(),
        'info': AlertRecord.objects.filter(alert_level='info', alert_status__in=['active', 'acknowledged']).count(),
    }
    
    context = {
        'alerts': alerts[:50],
        'stats': stats,
        'level_filter': level_filter,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'alert_level_choices': ALERT_LEVEL_CHOICES,
        'alert_status_choices': ALERT_STATUS_CHOICES,
        'alert_type_choices': ALERT_TYPE_CHOICES,
    }
    return render(request, 'production/alert_center.html', context)


def alert_detail(request, pk):
    alert = get_object_or_404(AlertRecord, pk=pk)
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        notes = request.POST.get('handle_notes', '').strip()
        handler = request.POST.get('handler', '').strip()
        
        if action == 'acknowledge':
            alert.alert_status = 'acknowledged'
            alert.acknowledged_at = timezone.now()
            alert.acknowledged_by = handler or '系统管理员'
            alert.handle_notes = notes
            alert.save()
            messages.success(request, '预警已确认')
        elif action == 'resolve':
            alert.alert_status = 'resolved'
            alert.resolved_at = timezone.now()
            alert.resolved_by = handler or '系统管理员'
            alert.handle_notes = notes
            alert.save()
            messages.success(request, '预警已解决')
        elif action == 'close':
            alert.alert_status = 'closed'
            alert.closed_at = timezone.now()
            alert.closed_by = handler or '系统管理员'
            alert.handle_notes = notes
            alert.save()
            messages.success(request, '预警已关闭')
        
        return redirect('production:alert_detail', pk=pk)
    
    context = {
        'alert': alert,
    }
    return render(request, 'production/alert_detail.html', context)


def alert_rules(request):
    rules = AlertRule.objects.all()
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        rule_id = request.POST.get('rule_id', '')
        
        if action == 'toggle' and rule_id:
            rule = get_object_or_404(AlertRule, pk=rule_id)
            rule.is_enabled = not rule.is_enabled
            rule.save()
            return JsonResponse({'success': True, 'is_enabled': rule.is_enabled})
        
        elif action == 'create':
            rule_name = request.POST.get('rule_name', '').strip()
            alert_type = request.POST.get('alert_type', '')
            stage_type = request.POST.get('stage_type', '') or None
            min_value = request.POST.get('min_value', '')
            max_value = request.POST.get('max_value', '')
            alert_level = request.POST.get('alert_level', 'warning')
            description = request.POST.get('description', '').strip()
            
            if not rule_name or not alert_type:
                messages.error(request, '请填写规则名称和预警类型')
            else:
                try:
                    rule = AlertRule.objects.create(
                        rule_name=rule_name,
                        alert_type=alert_type,
                        stage_type=stage_type,
                        min_value=float(min_value) if min_value else None,
                        max_value=float(max_value) if max_value else None,
                        alert_level=alert_level,
                        description=description,
                    )
                    messages.success(request, f'预警规则 {rule_name} 创建成功')
                except Exception as e:
                    messages.error(request, f'创建失败: {str(e)}')
            return redirect('production:alert_rules')
    
    context = {
        'rules': rules,
        'alert_type_choices': ALERT_TYPE_CHOICES,
        'alert_level_choices': ALERT_LEVEL_CHOICES,
        'stage_choices': STAGE_CHOICES,
    }
    return render(request, 'production/alert_rules.html', context)


def run_alert_check(request):
    if request.method == 'POST':
        try:
            total_new = 0
            
            inspections = InspectionRecord.objects.all()
            for inspection in inspections:
                alerts = check_alerts_for_inspection(inspection)
                total_new += len(alerts)
            
            crystallizations = CrystallizationResult.objects.all()
            for crystal in crystallizations:
                alerts = check_alerts_for_crystallization(crystal)
                total_new += len(alerts)
            
            abnormal_alert = check_abnormal_rate_alert()
            if abnormal_alert:
                total_new += 1
            
            return JsonResponse({
                'success': True,
                'new_alerts': total_new,
                'total_alerts': AlertRecord.objects.count(),
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': '仅支持POST请求'})


def dashboard(request):
    total_batches = RawMaterialBatch.objects.count()
    completed_batches = CrystallizationResult.objects.count()
    in_progress_stages = ProcessStage.objects.filter(status='in_progress').count()
    pending_abnormal = AbnormalDisposal.objects.filter(disposal_status='pending').count()
    
    pending_alerts = AlertRecord.objects.filter(alert_status='active').count()
    pending_audits = StageAudit.objects.filter(audit_status='pending').count()
    unclosed_abnormals = AbnormalDisposal.objects.filter(
        disposal_status='resolved',
        closure__isnull=True
    ).count()

    recent_batches = RawMaterialBatch.objects.all()[:5]
    recent_inspections = InspectionRecord.objects.all()[:10]
    recent_abnormal = AbnormalDisposal.objects.all()[:5]
    recent_alerts = AlertRecord.objects.all()[:5]

    context = {
        'total_batches': total_batches,
        'completed_batches': completed_batches,
        'in_progress_stages': in_progress_stages,
        'pending_abnormal': pending_abnormal,
        'pending_alerts': pending_alerts,
        'pending_audits': pending_audits,
        'unclosed_abnormals': unclosed_abnormals,
        'recent_batches': recent_batches,
        'recent_inspections': recent_inspections,
        'recent_abnormal': recent_abnormal,
        'recent_alerts': recent_alerts,
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
    
    evaporation_completed = ProcessStage.objects.filter(
        batch=batch,
        stage_type='evaporation',
        status='completed'
    ).exists()
    
    context = {
        'batch': batch,
        'stages': stages,
        'inspections': inspections,
        'abnormal_list': abnormal_list,
        'crystallization': crystallization,
        'stage_inspections': stage_inspections,
        'timeline_data': timeline_data,
        'stage_choices': STAGE_CHOICES,
        'evaporation_completed': evaporation_completed,
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
            stage_exists = ProcessStage.objects.filter(
                batch=batch,
                stage_type=stage_type
            ).exists()
            if not stage_exists:
                stage_name = dict(STAGE_CHOICES).get(stage_type, stage_type)
                errors.append(f'批次尚未进入{stage_name}阶段，请先创建该工序阶段')
        
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
        
        inspection = InspectionRecord.objects.create(
            batch=batch,
            stage_type=stage_type,
            inspection_date=inspection_date,
            temperature=temperature,
            concentration=concentration,
            ph_value=ph_value_parsed,
            operator=operator,
            remarks=remarks,
        )
        
        alerts = check_alerts_for_inspection(inspection)
        if alerts:
            messages.warning(request, f'检测记录添加成功，检测到 {len(alerts)} 条预警信息，请前往预警中心查看')
        else:
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
        
        evaporation_completed = ProcessStage.objects.filter(
            batch=batch,
            stage_type='evaporation',
            status='completed'
        ).exists()
        if not evaporation_completed:
            errors.append('未完成蒸发阶段不能录入结晶结果')
        
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
        
        if need_abnormal:
            pending_data = {
                'batch_id': batch.pk,
                'crystal_weight': crystal_weight,
                'crystal_purity': crystal_purity,
                'crystallization_date': crystallization_date.strftime('%Y-%m-%d') if crystallization_date else None,
                'operator': operator,
                'remarks': remarks,
                'crystallization_rate': round(crystallization_rate, 2),
                'editing': editing,
                'crystallization_id': crystallization.pk if crystallization else None,
                'prefill_abnormal_type': 'low_yield',
                'prefill_stage_type': 'crystallization',
            }
            request.session['pending_crystallization'] = pending_data
            if editing:
                messages.warning(request, f'结晶率为{crystallization_rate:.2f}%，低于阈值{CRYSTALLIZATION_THRESHOLD}%，请填写异常处置记录后修改才会保存')
            else:
                messages.warning(request, f'结晶率为{crystallization_rate:.2f}%，低于阈值{CRYSTALLIZATION_THRESHOLD}%，请填写异常处置记录后结晶结果才会保存')
            return redirect('production:abnormal_create', batch_id=batch.pk)
        
        if crystallization:
            crystallization.crystal_weight = crystal_weight
            crystallization.crystal_purity = crystal_purity
            crystallization.crystallization_date = crystallization_date
            crystallization.operator = operator
            crystallization.remarks = remarks
            crystallization.save()
            crystal_obj = crystallization
            messages.success(request, '结晶结果更新成功')
        else:
            crystal_obj = CrystallizationResult.objects.create(
                batch=batch,
                crystal_weight=crystal_weight,
                crystal_purity=crystal_purity,
                crystallization_date=crystallization_date,
                operator=operator,
                remarks=remarks,
            )
            messages.success(request, '结晶结果添加成功')
        
        alerts = check_alerts_for_crystallization(crystal_obj)
        if alerts:
            messages.warning(request, f'检测到 {len(alerts)} 条质量预警信息，请前往预警中心查看')
        
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
        
        pending_data = request.session.pop('pending_crystallization', None)
        if pending_data and pending_data.get('batch_id') == batch.pk:
            try:
                cryst_date = pending_data.get('crystallization_date')
                if cryst_date:
                    cryst_date = datetime.strptime(cryst_date, '%Y-%m-%d').date()
                else:
                    cryst_date = datetime.now().date()
                
                crystal_obj = None
                if pending_data.get('editing') and pending_data.get('crystallization_id'):
                    crystal_obj = CrystallizationResult.objects.get(pk=pending_data['crystallization_id'])
                    crystal_obj.crystal_weight = pending_data['crystal_weight']
                    crystal_obj.crystal_purity = pending_data['crystal_purity']
                    crystal_obj.crystallization_date = cryst_date
                    crystal_obj.operator = pending_data['operator']
                    crystal_obj.remarks = pending_data.get('remarks', '')
                    crystal_obj.save()
                    messages.success(request, f'异常处置记录添加成功，结晶结果已更新（结晶率{pending_data.get("crystallization_rate", 0):.2f}%）')
                else:
                    crystal_obj = CrystallizationResult.objects.create(
                        batch=batch,
                        crystal_weight=pending_data['crystal_weight'],
                        crystal_purity=pending_data['crystal_purity'],
                        crystallization_date=cryst_date,
                        operator=pending_data['operator'],
                        remarks=pending_data.get('remarks', ''),
                    )
                    messages.success(request, f'异常处置记录添加成功，结晶结果已同步保存（结晶率{pending_data.get("crystallization_rate", 0):.2f}%）')
                
                alerts = check_alerts_for_crystallization(crystal_obj)
                if alerts:
                    messages.warning(request, f'检测到 {len(alerts)} 条质量预警信息，请前往预警中心查看')
            except Exception as e:
                messages.error(request, f'异常处置记录添加成功，但结晶结果保存失败：{str(e)}')
        else:
            messages.success(request, '异常处置记录添加成功')
        return redirect('production:batch_detail', pk=batch.pk)
    
    prefill_abnormal_type = None
    prefill_stage_type = None
    pending_data = request.session.get('pending_crystallization')
    if pending_data and pending_data.get('batch_id') == batch.pk:
        prefill_abnormal_type = pending_data.get('prefill_abnormal_type')
        prefill_stage_type = pending_data.get('prefill_stage_type')
    
    context = {
        'batch': batch,
        'abnormal_type': prefill_abnormal_type,
        'stage_type': prefill_stage_type,
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


def stage_audit_list(request):
    audits = StageAudit.objects.all()
    
    status_filter = request.GET.get('status', '')
    stage_filter = request.GET.get('stage', '')
    
    if status_filter:
        audits = audits.filter(audit_status=status_filter)
    if stage_filter:
        audits = audits.filter(stage__stage_type=stage_filter)
    
    stats = {
        'total': audits.count(),
        'pending': StageAudit.objects.filter(audit_status='pending').count(),
        'approved': StageAudit.objects.filter(audit_status='approved').count(),
        'rejected': StageAudit.objects.filter(audit_status='rejected').count(),
    }
    
    context = {
        'audits': audits,
        'stats': stats,
        'status_filter': status_filter,
        'stage_filter': stage_filter,
        'audit_status_choices': AUDIT_STATUS_CHOICES,
        'stage_choices': STAGE_CHOICES,
    }
    return render(request, 'production/stage_audit_list.html', context)


def stage_audit_submit(request, stage_id):
    stage = get_object_or_404(ProcessStage, pk=stage_id)
    
    if request.method == 'POST':
        submitter = request.POST.get('submitter', '').strip()
        
        if not submitter:
            messages.error(request, '请填写提交人')
            return redirect('production:batch_detail', pk=stage.batch.pk)
        
        existing_audit = StageAudit.objects.filter(stage=stage).first()
        if existing_audit:
            if existing_audit.audit_status == 'pending':
                messages.warning(request, '该阶段已提交审核，请勿重复提交')
            else:
                existing_audit.audit_status = 'pending'
                existing_audit.submitter = submitter
                existing_audit.submit_time = timezone.now()
                existing_audit.auditor = ''
                existing_audit.audit_time = None
                existing_audit.audit_opinion = ''
                existing_audit.reject_reason = ''
                existing_audit.save()
                messages.success(request, f'{stage.get_stage_type_display()}阶段已重新提交审核')
            return redirect('production:batch_detail', pk=stage.batch.pk)
        
        StageAudit.objects.create(
            batch=stage.batch,
            stage=stage,
            submitter=submitter,
        )
        
        messages.success(request, f'{stage.get_stage_type_display()}阶段已提交审核')
        return redirect('production:batch_detail', pk=stage.batch.pk)
    
    return redirect('production:batch_detail', pk=stage.batch.pk)


def stage_audit_process(request, pk):
    audit = get_object_or_404(StageAudit, pk=pk)
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        auditor = request.POST.get('auditor', '').strip()
        opinion = request.POST.get('audit_opinion', '').strip()
        reject_reason = request.POST.get('reject_reason', '').strip()
        
        if not auditor:
            messages.error(request, '请填写审核人')
            return redirect('production:stage_audit_process', pk=pk)
        
        if action == 'approve':
            audit.audit_status = 'approved'
            audit.auditor = auditor
            audit.audit_time = timezone.now()
            audit.audit_opinion = opinion
            audit.save()
            messages.success(request, '审核通过')
        elif action == 'reject':
            if not reject_reason:
                messages.error(request, '驳回时请填写驳回原因')
                return redirect('production:stage_audit_process', pk=pk)
            audit.audit_status = 'rejected'
            audit.auditor = auditor
            audit.audit_time = timezone.now()
            audit.audit_opinion = opinion
            audit.reject_reason = reject_reason
            audit.save()
            messages.warning(request, '审核已驳回')
        
        return redirect('production:stage_audit_list')
    
    context = {
        'audit': audit,
    }
    return render(request, 'production/stage_audit_process.html', context)


def stage_complete_with_audit(request, pk):
    stage = get_object_or_404(ProcessStage, pk=pk)
    
    if request.method == 'POST':
        audit_needed = request.POST.get('audit_needed') == 'on'
        submitter = request.POST.get('submitter', '').strip()
        
        if audit_needed and not submitter:
            messages.error(request, '需要审核时请填写提交人')
            return redirect('production:batch_detail', pk=stage.batch.pk)
        
        if audit_needed:
            existing_audit = StageAudit.objects.filter(stage=stage).first()
            if not existing_audit:
                StageAudit.objects.create(
                    batch=stage.batch,
                    stage=stage,
                    submitter=submitter,
                    is_required=True,
                )
                messages.info(request, f'{stage.get_stage_type_display()}阶段已提交审核，待审核通过后可完成')
                return redirect('production:batch_detail', pk=stage.batch.pk)
            elif existing_audit.audit_status != 'approved':
                messages.warning(request, '该阶段审核尚未通过，不能完成')
                return redirect('production:batch_detail', pk=stage.batch.pk)
        
        stage.status = 'completed'
        stage.end_time = timezone.now()
        stage.save()
        
        messages.success(request, f'{stage.get_stage_type_display()}阶段已完成')
        return redirect('production:batch_detail', pk=stage.batch.pk)
    
    return redirect('production:batch_detail', pk=stage.batch.pk)


def material_quality_analysis(request):
    MaterialQualityStats.update_stats()
    
    stats = MaterialQualityStats.objects.all()
    
    source_filter = request.GET.get('source', '')
    level_filter = request.GET.get('level', '')
    
    if source_filter:
        stats = stats.filter(material_source__icontains=source_filter)
    if level_filter:
        stats = stats.filter(quality_level=level_filter)
    
    chart_data = {
        'sources': [s.material_source for s in stats],
        'rates': [s.avg_crystallization_rate or 0 for s in stats],
        'purities': [s.avg_crystallization_purity or 0 for s in stats],
        'abnormal_rates': [s.abnormal_rate for s in stats],
        'scores': [s.quality_score or 0 for s in stats],
    }

    from datetime import timedelta
    today = timezone.now().date()
    trend_data_list = []
    for i in range(5, -1, -1):
        month_date = today - timedelta(days=i * 30)
        month_start = month_date.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        
        month_batches = RawMaterialBatch.objects.filter(
            created_at__gte=month_start,
            created_at__lt=next_month
        )
        month_crystal = CrystallizationResult.objects.filter(
            batch__in=month_batches
        )
        
        if month_crystal.exists():
            rates = [r.get_crystallization_rate() for r in month_crystal if r.batch.material_weight > 0]
            avg_rate = round(sum(rates) / len(rates), 2) if rates else 0
            avg_purity = round(month_crystal.aggregate(avg=Avg('crystal_purity'))['avg'] or 0, 2)
            abnormal_count = AbnormalDisposal.objects.filter(batch__in=month_batches).count()
            abnormal_rate = round(abnormal_count / month_batches.count() * 100, 2) if month_batches.count() > 0 else 0
        else:
            avg_rate = 0
            avg_purity = 0
            abnormal_rate = 0
        
        trend_data_list.append({
            'month': month_start.strftime('%Y-%m'),
            'avg_crystallization': avg_rate,
            'avg_purity': avg_purity,
            'abnormal_rate': abnormal_rate,
        })

    trend_chart_data = {
        'labels': [t['month'] for t in trend_data_list],
        'crystallization': [t['avg_crystallization'] for t in trend_data_list],
        'purity': [t['avg_purity'] for t in trend_data_list],
        'abnormal': [t['abnormal_rate'] for t in trend_data_list],
    }

    context = {
        'stats': stats,
        'chart_data': chart_data,
        'trend_chart_data': trend_chart_data,
        'source_filter': source_filter,
        'level_filter': level_filter,
    }
    return render(request, 'production/material_quality_analysis.html', context)


def parameter_recommendation(request):
    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'generate':
            stage_type = request.POST.get('stage_type', '')
            material_source = request.POST.get('material_source', '')
            
            try:
                recommendation = ParameterRecommendation.generate_recommendations(
                    stage_type=stage_type or None,
                    material_source=material_source or None
                )
                if recommendation:
                    messages.success(request, '参数推荐已生成/更新')
                else:
                    messages.warning(request, '暂无足够数据生成参数推荐')
            except Exception as e:
                messages.error(request, f'生成失败: {str(e)}')
            
            return redirect('production:parameter_recommendation')
        
        elif action == 'generate_all':
            sources = list(RawMaterialBatch.objects.values_list('material_source', flat=True).distinct())
            count = 0
            for stage_type, _ in STAGE_CHOICES:
                rec = ParameterRecommendation.generate_recommendations(stage_type=stage_type)
                if rec:
                    count += 1
                for source in sources:
                    rec = ParameterRecommendation.generate_recommendations(stage_type=stage_type, material_source=source)
                    if rec:
                        count += 1
            
            messages.success(request, f'已生成/更新 {count} 条参数推荐')
            return redirect('production:parameter_recommendation')
    
    recommendations = ParameterRecommendation.objects.filter(is_active=True)
    
    stage_filter = request.GET.get('stage', '')
    source_filter = request.GET.get('source', '')
    
    if stage_filter:
        recommendations = recommendations.filter(stage_type=stage_filter)
    if source_filter:
        recommendations = recommendations.filter(material_source__icontains=source_filter)
    
    chart_data = {
        'labels': [f'{r.material_source or "全部来源"} - {r.get_stage_type_display()}' for r in recommendations],
        'temps': [r.recommended_temp for r in recommendations],
        'concs': [r.recommended_conc for r in recommendations],
        'phs': [r.recommended_ph for r in recommendations],
    }

    context = {
        'recommendations': recommendations,
        'chart_data': chart_data,
        'stage_filter': stage_filter,
        'source_filter': source_filter,
        'stage_choices': STAGE_CHOICES,
        'sources': RawMaterialBatch.objects.values_list('material_source', flat=True).distinct(),
    }
    return render(request, 'production/parameter_recommendation.html', context)


def abnormal_closure_list(request):
    closures = AbnormalClosure.objects.all()
    
    status_filter = request.GET.get('status', '')
    effective_filter = request.GET.get('effective', '')
    
    if effective_filter == 'yes':
        closures = closures.filter(is_effective=True)
    elif effective_filter == 'no':
        closures = closures.filter(is_effective=False)
    
    unclosed_abnormals = AbnormalDisposal.objects.filter(
        disposal_status__in=['resolved'],
        closure__isnull=True
    )
    
    total_closures = closures.count()
    closed_count = closures.filter(is_effective=True).count()
    pending_count = unclosed_abnormals.count()
    closure_rate = round(closed_count / total_closures * 100, 2) if total_closures > 0 else 0
    
    stats = {
        'total': total_closures,
        'closed': closed_count,
        'pending': pending_count,
        'closure_rate': closure_rate,
    }
    
    context = {
        'closures': closures,
        'unclosed_abnormals': unclosed_abnormals,
        'stats': stats,
        'status_filter': status_filter,
        'effective_filter': effective_filter,
    }
    return render(request, 'production/abnormal_closure_list.html', context)


def abnormal_closure_create(request, abnormal_id):
    abnormal = get_object_or_404(AbnormalDisposal, pk=abnormal_id)
    
    if request.method == 'POST':
        root_cause = request.POST.get('root_cause_analysis', '').strip()
        corrective = request.POST.get('corrective_action', '').strip()
        preventive = request.POST.get('preventive_action', '').strip()
        verification = request.POST.get('verification_method', '').strip()
        verification_result = request.POST.get('verification_result', '').strip()
        is_effective = request.POST.get('is_effective') == 'on'
        closed_by = request.POST.get('closed_by', '').strip()
        closure_opinion = request.POST.get('closure_opinion', '').strip()
        
        errors = []
        
        if not root_cause:
            errors.append('请填写根本原因分析')
        if not corrective:
            errors.append('请填写纠正措施')
        if not preventive:
            errors.append('请填写预防措施')
        if not verification:
            errors.append('请填写验证方法')
        if not closed_by:
            errors.append('请填写闭环人')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect('production:abnormal_closure_create', abnormal_id=abnormal_id)
        
        AbnormalClosure.objects.create(
            abnormal=abnormal,
            root_cause_analysis=root_cause,
            corrective_action=corrective,
            preventive_action=preventive,
            verification_method=verification,
            verification_result=verification_result,
            is_effective=is_effective,
            closed_by=closed_by,
            closure_opinion=closure_opinion,
        )
        
        abnormal.disposal_status = 'closed'
        abnormal.save()
        
        messages.success(request, '异常已完成闭环管理')
        return redirect('production:abnormal_closure_list')
    
    context = {
        'abnormal': abnormal,
    }
    return render(request, 'production/abnormal_closure_form.html', context)


def abnormal_closure_detail(request, pk):
    closure = get_object_or_404(AbnormalClosure, pk=pk)
    
    if request.method == 'POST':
        verification_result = request.POST.get('verification_result', '').strip()
        is_effective = request.POST.get('is_effective') == 'on'
        closure_opinion = request.POST.get('closure_opinion', '').strip()
        
        if verification_result:
            closure.verification_result = verification_result
        closure.is_effective = is_effective
        if closure_opinion:
            closure.closure_opinion = closure_opinion
        closure.save()
        
        messages.success(request, '闭环信息已更新')
        return redirect('production:abnormal_closure_detail', pk=pk)
    
    context = {
        'closure': closure,
    }
    return render(request, 'production/abnormal_closure_detail.html', context)


def export_list(request):
    exports = ExportRecord.objects.all()
    
    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', '')
    
    if type_filter:
        exports = exports.filter(export_type=type_filter)
    if status_filter:
        exports = exports.filter(export_status=status_filter)
    
    context = {
        'exports': exports,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'export_type_choices': EXPORT_TYPE_CHOICES,
        'export_status_choices': EXPORT_STATUS_CHOICES,
    }
    return render(request, 'production/export_list.html', context)


def export_create(request):
    if request.method == 'POST':
        export_type = request.POST.get('export_type', '')
        export_name = request.POST.get('export_name', '').strip()
        requested_by = request.POST.get('requested_by', '').strip()
        start_date = request.POST.get('start_date', '')
        end_date = request.POST.get('end_date', '')
        source_filter = request.POST.get('source', '')
        
        errors = []
        
        if not export_type:
            errors.append('请选择报表类型')
        if not export_name:
            errors.append('请填写报表名称')
        if not requested_by:
            errors.append('请填写申请人')
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect('production:export_create')
        
        filters = {}
        if start_date:
            filters['start_date'] = start_date
        if end_date:
            filters['end_date'] = end_date
        if source_filter:
            filters['source'] = source_filter
        
        export = ExportRecord.objects.create(
            export_type=export_type,
            export_name=export_name,
            filters=filters,
            requested_by=requested_by,
        )
        
        try:
            data = generate_export_data(export_type, filters)
            csv_content = generate_csv(data)
            
            export.export_status = 'completed'
            export.total_records = len(data.get('rows', []))
            export.completed_at = timezone.now()
            export.file_size = len(csv_content.encode('utf-8')) // 1024
            export.save()
            
            messages.success(request, f'报表 {export_name} 生成成功，共 {export.total_records} 条记录')
            
            response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{export_name}.csv"'
            return response
            
        except Exception as e:
            export.export_status = 'failed'
            export.error_message = str(e)
            export.save()
            messages.error(request, f'报表生成失败: {str(e)}')
            return redirect('production:export_list')
    
    context = {
        'export_type_choices': EXPORT_TYPE_CHOICES,
        'sources': RawMaterialBatch.objects.values_list('material_source', flat=True).distinct(),
    }
    return render(request, 'production/export_form.html', context)


def generate_export_data(export_type, filters):
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    source = filters.get('source')
    
    date_filter = Q()
    if start_date:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        date_filter &= Q(start_date__gte=start)
    if end_date:
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        date_filter &= Q(start_date__lte=end)
    
    source_filter = Q()
    if source:
        source_filter = Q(material_source__icontains=source)
    
    if export_type == 'batch_summary':
        batches = RawMaterialBatch.objects.filter(date_filter & source_filter)
        headers = ['批次编号', '原料来源', '原料重量(kg)', '开始日期', '操作人员', '当前阶段', '结晶率(%)', '结晶纯度(%)', '状态']
        rows = []
        for batch in batches:
            try:
                crystal = batch.crystallizationresult
                rate = crystal.get_crystallization_rate()
                purity = crystal.crystal_purity
            except CrystallizationResult.DoesNotExist:
                rate = None
                purity = None
            
            status = '已完成' if rate else batch.get_stage_display_current()
            
            rows.append([
                batch.batch_no,
                batch.material_source,
                batch.material_weight,
                batch.start_date.strftime('%Y-%m-%d'),
                batch.operator,
                batch.get_stage_display_current(),
                rate or '-',
                purity or '-',
                status,
            ])
        return {'headers': headers, 'rows': rows}
    
    elif export_type == 'quality_analysis':
        MaterialQualityStats.update_stats()
        stats = MaterialQualityStats.objects.all()
        if source:
            stats = stats.filter(material_source__icontains=source)
        
        headers = ['原料来源', '总批次数', '已完成批次', '平均结晶率(%)', '平均纯度(%)', '最低结晶率(%)', '最高结晶率(%)', '异常次数', '异常率(%)', '质量等级', '质量评分']
        rows = []
        for s in stats:
            rows.append([
                s.material_source,
                s.total_batches,
                s.completed_batches,
                s.avg_crystallization_rate or '-',
                s.avg_crystallization_purity or '-',
                s.min_crystallization_rate or '-',
                s.max_crystallization_rate or '-',
                s.abnormal_count,
                s.abnormal_rate,
                s.quality_level or '-',
                s.quality_score or '-',
            ])
        return {'headers': headers, 'rows': rows}
    
    elif export_type == 'alert_statistics':
        date_q = Q()
        if start_date:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            date_q &= Q(triggered_at__gte=start)
        if end_date:
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            date_q &= Q(triggered_at__lt=end)
        
        alerts = AlertRecord.objects.filter(date_q)
        headers = ['预警类型', '预警级别', '预警标题', '关联批次', '指标数值', '阈值范围', '预警状态', '触发时间', '处理时长(小时)']
        rows = []
        for alert in alerts:
            rows.append([
                alert.get_alert_type_display(),
                alert.get_alert_level_display(),
                alert.alert_title,
                alert.batch.batch_no if alert.batch else '-',
                alert.indicator_value or '-',
                alert.threshold or '-',
                alert.get_alert_status_display(),
                alert.triggered_at.strftime('%Y-%m-%d %H:%M:%S'),
                alert.get_duration() or '-',
            ])
        return {'headers': headers, 'rows': rows}
    
    elif export_type == 'abnormal_summary':
        date_q = Q()
        if start_date:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            date_q &= Q(discover_date__gte=start)
        if end_date:
            end = datetime.strptime(end_date, '%Y-%m-%d')
            date_q &= Q(discover_date__lte=end)
        
        abnormals = AbnormalDisposal.objects.filter(date_q)
        if source:
            abnormals = abnormals.filter(batch__material_source__icontains=source)
        
        headers = ['批次编号', '原料来源', '异常类型', '发生阶段', '发现日期', '异常描述', '处置状态', '处理人', '解决日期', '处理周期(天)']
        rows = []
        for abnormal in abnormals:
            rows.append([
                abnormal.batch.batch_no,
                abnormal.batch.material_source,
                abnormal.get_abnormal_type_display(),
                abnormal.get_stage_type_display(),
                abnormal.discover_date.strftime('%Y-%m-%d'),
                abnormal.description,
                abnormal.get_disposal_status_display(),
                abnormal.handler or '-',
                abnormal.resolve_date.strftime('%Y-%m-%d') if abnormal.resolve_date else '-',
                abnormal.get_cycle_time() or '-',
            ])
        return {'headers': headers, 'rows': rows}
    
    elif export_type == 'process_efficiency':
        batches = RawMaterialBatch.objects.filter(date_filter & source_filter)
        headers = ['批次编号', '原料来源', '总时长(小时)', '浸取时长(小时)', '过滤时长(小时)', '蒸发时长(小时)', '结晶时长(小时)', '结晶率(%)', '纯度(%)']
        rows = []
        for batch in batches:
            stages = batch.processstage_set.filter(status='completed')
            durations = {}
            total_duration = 0
            for stage in stages:
                if stage.start_time and stage.end_time:
                    duration = (stage.end_time - stage.start_time).total_seconds() / 3600
                    durations[stage.stage_type] = round(duration, 2)
                    total_duration += duration
            
            try:
                crystal = batch.crystallizationresult
                rate = crystal.get_crystallization_rate()
                purity = crystal.crystal_purity
            except CrystallizationResult.DoesNotExist:
                rate = None
                purity = None
            
            rows.append([
                batch.batch_no,
                batch.material_source,
                round(total_duration, 2),
                durations.get('leaching', '-'),
                durations.get('filtration', '-'),
                durations.get('evaporation', '-'),
                durations.get('crystallization', '-'),
                rate or '-',
                purity or '-',
            ])
        return {'headers': headers, 'rows': rows}
    
    return {'headers': [], 'rows': []}


def generate_csv(data):
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(data['headers'])
    for row in data['rows']:
        writer.writerow(row)
    return output.getvalue()


def export_download(request, pk):
    export = get_object_or_404(ExportRecord, pk=pk)
    
    if export.export_status != 'completed':
        messages.error(request, '报表尚未生成完成')
        return redirect('production:export_list')
    
    try:
        data = generate_export_data(export.export_type, export.filters)
        csv_content = generate_csv(data)
        
        response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{export.export_name}.csv"'
        return response
    except Exception as e:
        messages.error(request, f'下载失败: {str(e)}')
        return redirect('production:export_list')


def visual_dashboard(request):
    total_batches = RawMaterialBatch.objects.count()
    completed_batches = CrystallizationResult.objects.count()
    success_rate = (completed_batches / total_batches * 100) if total_batches > 0 else 0
    
    crystal_results = CrystallizationResult.objects.all()
    rates = [r.get_crystallization_rate() for r in crystal_results if r.batch.material_weight > 0]
    avg_crystallization_rate = round(sum(rates) / len(rates), 2) if rates else 0
    avg_purity = round(crystal_results.aggregate(avg=Avg('crystal_purity'))['avg'] or 0, 2)
    
    total_alerts = AlertRecord.objects.count()
    active_alerts = AlertRecord.objects.filter(alert_status__in=['active', 'acknowledged']).count()
    resolved_rate = ((total_alerts - active_alerts) / total_alerts * 100) if total_alerts > 0 else 0
    
    total_abnormal = AbnormalDisposal.objects.count()
    closed_abnormal = AbnormalDisposal.objects.filter(disposal_status='closed').count()
    closure_rate = (closed_abnormal / total_abnormal * 100) if total_abnormal > 0 else 0
    
    alert_trend_data = []
    today = timezone.now().date()
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        count = AlertRecord.objects.filter(
            triggered_at__date=date
        ).count()
        alert_trend_data.append({
            'date': date.strftime('%m-%d'),
            'count': count,
        })
    
    stage_distribution = []
    for stage_type, stage_name in STAGE_CHOICES:
        count = ProcessStage.objects.filter(stage_type=stage_type, status='completed').count()
        stage_distribution.append({
            'name': stage_name,
            'value': count,
        })
    
    alert_type_distribution = []
    for alert_type, type_name in ALERT_TYPE_CHOICES:
        count = AlertRecord.objects.filter(alert_type=alert_type).count()
        if count > 0:
            alert_type_distribution.append({
                'name': type_name,
                'value': count,
            })
    
    recent_batches = RawMaterialBatch.objects.all()[:5]
    recent_alerts = AlertRecord.objects.all()[:10]
    
    MaterialQualityStats.update_stats()
    quality_ranking = MaterialQualityStats.objects.all()[:5]
    
    process_efficiency = []
    for stage_type, stage_name in STAGE_CHOICES:
        stages = ProcessStage.objects.filter(
            stage_type=stage_type,
            status='completed',
            start_time__isnull=False,
            end_time__isnull=False
        )
        if stages.exists():
            durations = [(s.end_time - s.start_time).total_seconds() / 3600 for s in stages]
            avg_duration = round(sum(durations) / len(durations), 2)
            process_efficiency.append({
                'stage': stage_name,
                'avg_duration': avg_duration,
                'count': stages.count(),
            })
    
    in_progress = ProcessStage.objects.filter(status__in=['pending', 'in_progress']).count()
    pending_alerts = AlertRecord.objects.filter(alert_status='active').count()
    completion_rate = round(success_rate, 2)
    completion_rate_remaining = 100 - completion_rate

    stats = {
        'total_batches': total_batches,
        'completed_batches': completed_batches,
        'in_progress': in_progress,
        'pending_alerts': pending_alerts,
        'completion_rate': completion_rate,
        'completion_rate_remaining': completion_rate_remaining,
    }

    context = {
        'stats': stats,
        'total_batches': total_batches,
        'completed_batches': completed_batches,
        'success_rate': round(success_rate, 2),
        'avg_crystallization_rate': avg_crystallization_rate,
        'avg_purity': avg_purity,
        'total_alerts': total_alerts,
        'active_alerts': active_alerts,
        'resolved_rate': round(resolved_rate, 2),
        'total_abnormal': total_abnormal,
        'closed_abnormal': closed_abnormal,
        'closure_rate': round(closure_rate, 2),
        'alert_trend_data': alert_trend_data,
        'stage_distribution': stage_distribution,
        'alert_type_distribution': alert_type_distribution,
        'recent_batches': recent_batches,
        'recent_alerts': recent_alerts,
        'quality_ranking': quality_ranking,
        'process_efficiency': process_efficiency,
    }
    return render(request, 'production/visual_dashboard.html', context)
