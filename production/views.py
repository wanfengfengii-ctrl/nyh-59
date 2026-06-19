from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Sum, Avg, Count, Q, F, ExpressionWrapper, FloatField
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from datetime import datetime, timedelta, date
from django.db import transaction
import csv
import io
import json
import codecs
from .models import (
    RawMaterialBatch, ProcessStage, InspectionRecord,
    CrystallizationResult, AbnormalDisposal,
    STAGE_CHOICES, STAGE_ORDER,
    AlertRule, AlertRecord, StageAudit, ParameterRecommendation,
    ExportRecord, MaterialQualityStats, AbnormalClosure,
    ALERT_LEVEL_CHOICES, ALERT_STATUS_CHOICES, ALERT_TYPE_CHOICES,
    AUDIT_STATUS_CHOICES, EXPORT_TYPE_CHOICES, EXPORT_STATUS_CHOICES,
    MaterialCategory, MaterialSupplier, Material, MaterialInbound,
    MaterialOutbound, MaterialLoss, BatchMaterialUsage,
    MaterialStockAlert, MaterialStockHistory,
    MATERIAL_UNIT_CHOICES, STOCK_ALERT_STATUS_CHOICES,
    INBOUND_TYPE_CHOICES, OUTBOUND_TYPE_CHOICES, LOSS_REASON_CHOICES,
    ProcessEnergyCost, LaborCost, OtherCost, ProductSale,
    BatchCostSummary, LossWarning, SourceCostStats,
    ENERGY_TYPE_CHOICES, OTHER_COST_CATEGORY_CHOICES,
    LOSS_WARNING_LEVEL_CHOICES, SALE_STATUS_CHOICES,
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
    
    material_usages = batch.batch_materials.all().order_by('-usage_date')
    
    material_summary = {}
    total_material_cost = 0
    for usage in material_usages:
        mat_id = usage.material_id
        if mat_id not in material_summary:
            material_summary[mat_id] = {
                'material': usage.material,
                'total_quantity': 0,
                'usage_count': 0,
                'unit': usage.unit,
            }
        material_summary[mat_id]['total_quantity'] += usage.actual_quantity
        material_summary[mat_id]['usage_count'] += 1
        
        if usage.outbound and usage.outbound.inbound_ref:
            total_material_cost += usage.actual_quantity * usage.outbound.inbound_ref.unit_price
    
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
        'material_usages': material_usages,
        'material_summary': list(material_summary.values()),
        'total_material_cost': round(total_material_cost, 2),
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


def generate_inbound_no():
    today = date.today().strftime('%Y%m%d')
    count = MaterialInbound.objects.filter(inbound_no__startswith=f'RK{today}').count()
    return f'RK{today}{count + 1:04d}'


def generate_outbound_no():
    today = date.today().strftime('%Y%m%d')
    count = MaterialOutbound.objects.filter(outbound_no__startswith=f'CK{today}').count()
    return f'CK{today}{count + 1:04d}'


def generate_loss_no():
    today = date.today().strftime('%Y%m%d')
    count = MaterialLoss.objects.filter(loss_no__startswith=f'SH{today}').count()
    return f'SH{today}{count + 1:04d}'


def check_stock_alerts():
    new_alerts = []
    materials = Material.objects.filter(is_active=True)
    
    for material in materials:
        status = material.get_stock_status()
        if status == 'normal':
            continue
            
        current_stock = material.get_current_stock()
        alert_type = status
        alert_level = 'warning'
        threshold = None
        title = ''
        message = ''
        
        if status == 'low_stock':
            threshold = material.min_stock
            alert_level = 'danger' if current_stock < threshold * 0.5 else 'warning'
            title = f'{material.name} 库存不足'
            message = f'原料 {material.name} 当前库存为 {current_stock} {material.get_unit_display()}，低于预警阈值 {threshold} {material.get_unit_display()}，请及时补充。'
        elif status == 'overstock':
            threshold = material.max_stock
            alert_level = 'info'
            title = f'{material.name} 库存积压'
            message = f'原料 {material.name} 当前库存为 {current_stock} {material.get_unit_display()}，超过最大库存 {threshold} {material.get_unit_display()}，请注意控制采购量。'
        elif status == 'expired':
            alert_level = 'danger'
            title = f'{material.name} 已过期'
            message = f'原料 {material.name} 存在已过期的入库批次，请及时处理。'
        elif status == 'near_expiry':
            alert_level = 'warning'
            title = f'{material.name} 临近过期'
            message = f'原料 {material.name} 存在30天内即将过期的入库批次，请尽快安排使用。'
        
        existing = MaterialStockAlert.objects.filter(
            material=material,
            alert_type=alert_type,
            alert_status__in=['active', 'acknowledged']
        ).exists()
        
        if not existing:
            alert = MaterialStockAlert.objects.create(
                material=material,
                alert_type=alert_type,
                alert_level=alert_level,
                alert_title=title,
                alert_message=message,
                current_stock=current_stock,
                threshold=threshold,
            )
            new_alerts.append(alert)
    
    return new_alerts


def material_stock_dashboard(request):
    total_materials = Material.objects.filter(is_active=True).count()
    total_inbound = MaterialInbound.objects.aggregate(total=Sum('quantity'))['total'] or 0
    total_outbound = MaterialOutbound.objects.aggregate(total=Sum('quantity'))['total'] or 0
    total_loss = MaterialLoss.objects.aggregate(total=Sum('quantity'))['total'] or 0
    current_total_stock = round(total_inbound - total_outbound - total_loss, 2)
    
    low_stock_count = 0
    overstock_count = 0
    expired_count = 0
    near_expiry_count = 0
    
    for material in Material.objects.filter(is_active=True):
        status = material.get_stock_status()
        if status == 'low_stock':
            low_stock_count += 1
        elif status == 'overstock':
            overstock_count += 1
        elif status == 'expired':
            expired_count += 1
        elif status == 'near_expiry':
            near_expiry_count += 1
    
    pending_alerts = MaterialStockAlert.objects.filter(alert_status='active').count()
    
    today = timezone.now().date()
    last_30_days = today - timedelta(days=30)
    
    recent_inbounds = MaterialInbound.objects.filter(inbound_date__gte=last_30_days).count()
    recent_outbounds = MaterialOutbound.objects.filter(outbound_date__gte=last_30_days).count()
    
    category_stats = []
    for category in MaterialCategory.objects.filter(is_active=True):
        cat_materials = category.materials.filter(is_active=True)
        total_cat_stock = sum(m.get_current_stock() for m in cat_materials)
        category_stats.append({
            'category': category,
            'material_count': cat_materials.count(),
            'total_stock': round(total_cat_stock, 2),
        })
    
    recent_inbound_list = MaterialInbound.objects.all()[:10]
    recent_outbound_list = MaterialOutbound.objects.all()[:10]
    recent_alerts = MaterialStockAlert.objects.all()[:10]
    
    stock_trend_data = []
    for i in range(6, -1, -1):
        date_i = today - timedelta(days=i)
        day_inbound = MaterialInbound.objects.filter(inbound_date=date_i).aggregate(
            total=Sum('quantity'))['total'] or 0
        day_outbound = MaterialOutbound.objects.filter(outbound_date=date_i).aggregate(
            total=Sum('quantity'))['total'] or 0
        day_loss = MaterialLoss.objects.filter(loss_date=date_i).aggregate(
            total=Sum('quantity'))['total'] or 0
        stock_trend_data.append({
            'date': date_i.strftime('%m-%d'),
            'inbound': round(day_inbound, 2),
            'outbound': round(day_outbound, 2),
            'net': round(day_inbound - day_outbound - day_loss, 2),
        })
    
    context = {
        'total_materials': total_materials,
        'current_total_stock': current_total_stock,
        'low_stock_count': low_stock_count,
        'overstock_count': overstock_count,
        'expired_count': expired_count,
        'near_expiry_count': near_expiry_count,
        'pending_alerts': pending_alerts,
        'recent_inbounds': recent_inbounds,
        'recent_outbounds': recent_outbounds,
        'category_stats': category_stats,
        'recent_inbound_list': recent_inbound_list,
        'recent_outbound_list': recent_outbound_list,
        'recent_alerts': recent_alerts,
        'stock_trend_data': stock_trend_data,
    }
    return render(request, 'production/material_stock_dashboard.html', context)


def material_category_list(request):
    categories = MaterialCategory.objects.all()
    
    parent_filter = request.GET.get('parent', '')
    if parent_filter:
        if parent_filter == 'root':
            categories = categories.filter(parent__isnull=True)
        else:
            categories = categories.filter(parent_id=parent_filter)
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'create':
            name = request.POST.get('name', '').strip()
            code = request.POST.get('code', '').strip()
            parent_id = request.POST.get('parent_id', '')
            description = request.POST.get('description', '').strip()
            sort_order = request.POST.get('sort_order', '0')
            
            errors = []
            if not name:
                errors.append('请输入分类名称')
            if not code:
                errors.append('请输入分类编码')
            if MaterialCategory.objects.filter(name=name).exists():
                errors.append('分类名称已存在')
            if MaterialCategory.objects.filter(code=code).exists():
                errors.append('分类编码已存在')
            
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                parent = None
                if parent_id:
                    try:
                        parent = MaterialCategory.objects.get(pk=parent_id)
                    except MaterialCategory.DoesNotExist:
                        pass
                
                try:
                    MaterialCategory.objects.create(
                        name=name,
                        code=code,
                        parent=parent,
                        description=description,
                        sort_order=int(sort_order) if sort_order else 0,
                    )
                    messages.success(request, f'分类 {name} 创建成功')
                except Exception as e:
                    messages.error(request, f'创建失败: {str(e)}')
            
            return redirect('production:material_category_list')
        
        elif action == 'edit':
            category_id = request.POST.get('category_id', '')
            if category_id:
                category = get_object_or_404(MaterialCategory, pk=category_id)
                category.name = request.POST.get('name', category.name).strip()
                category.code = request.POST.get('code', category.code).strip()
                category.description = request.POST.get('description', category.description).strip()
                category.sort_order = int(request.POST.get('sort_order', category.sort_order))
                
                parent_id = request.POST.get('parent_id', '')
                if parent_id:
                    try:
                        category.parent = MaterialCategory.objects.get(pk=parent_id)
                    except MaterialCategory.DoesNotExist:
                        category.parent = None
                else:
                    category.parent = None
                
                category.save()
                messages.success(request, f'分类 {category.name} 更新成功')
                return redirect('production:material_category_list')
        
        elif action == 'toggle':
            category_id = request.POST.get('category_id', '')
            if category_id:
                category = get_object_or_404(MaterialCategory, pk=category_id)
                category.is_active = not category.is_active
                category.save()
                return JsonResponse({'success': True, 'is_active': category.is_active})
        
        elif action == 'delete':
            category_id = request.POST.get('category_id', '')
            if category_id:
                category = get_object_or_404(MaterialCategory, pk=category_id)
                if category.materials.exists():
                    messages.error(request, '该分类下存在原料，无法删除')
                elif category.children.exists():
                    messages.error(request, '该分类下存在子分类，无法删除')
                else:
                    category.delete()
                    messages.success(request, '分类删除成功')
                return redirect('production:material_category_list')
    
    context = {
        'categories': categories,
        'parent_filter': parent_filter,
        'all_categories': MaterialCategory.objects.filter(is_active=True),
    }
    return render(request, 'production/material_category_list.html', context)


def material_supplier_list(request):
    suppliers = MaterialSupplier.objects.all()
    
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        suppliers = suppliers.filter(is_active=True)
    elif status_filter == 'inactive':
        suppliers = suppliers.filter(is_active=False)
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'create':
            name = request.POST.get('name', '').strip()
            code = request.POST.get('code', '').strip()
            contact_person = request.POST.get('contact_person', '').strip()
            contact_phone = request.POST.get('contact_phone', '').strip()
            address = request.POST.get('address', '').strip()
            email = request.POST.get('email', '').strip()
            qualification = request.POST.get('qualification', '').strip()
            remarks = request.POST.get('remarks', '').strip()
            
            errors = []
            if not name:
                errors.append('请输入供应商名称')
            if not code:
                errors.append('请输入供应商编码')
            if MaterialSupplier.objects.filter(name=name).exists():
                errors.append('供应商名称已存在')
            if MaterialSupplier.objects.filter(code=code).exists():
                errors.append('供应商编码已存在')
            
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                try:
                    MaterialSupplier.objects.create(
                        name=name,
                        code=code,
                        contact_person=contact_person,
                        contact_phone=contact_phone,
                        address=address,
                        email=email,
                        qualification=qualification,
                        remarks=remarks,
                    )
                    messages.success(request, f'供应商 {name} 创建成功')
                except Exception as e:
                    messages.error(request, f'创建失败: {str(e)}')
            
            return redirect('production:material_supplier_list')
        
        elif action == 'edit':
            supplier_id = request.POST.get('supplier_id', '')
            if supplier_id:
                supplier = get_object_or_404(MaterialSupplier, pk=supplier_id)
                supplier.name = request.POST.get('name', supplier.name).strip()
                supplier.code = request.POST.get('code', supplier.code).strip()
                supplier.contact_person = request.POST.get('contact_person', supplier.contact_person).strip()
                supplier.contact_phone = request.POST.get('contact_phone', supplier.contact_phone).strip()
                supplier.address = request.POST.get('address', supplier.address).strip()
                supplier.email = request.POST.get('email', supplier.email).strip()
                supplier.qualification = request.POST.get('qualification', supplier.qualification).strip()
                supplier.remarks = request.POST.get('remarks', supplier.remarks).strip()
                supplier.save()
                messages.success(request, f'供应商 {supplier.name} 更新成功')
                return redirect('production:material_supplier_list')
        
        elif action == 'toggle':
            supplier_id = request.POST.get('supplier_id', '')
            if supplier_id:
                supplier = get_object_or_404(MaterialSupplier, pk=supplier_id)
                supplier.is_active = not supplier.is_active
                supplier.save()
                return JsonResponse({'success': True, 'is_active': supplier.is_active})
        
        elif action == 'delete':
            supplier_id = request.POST.get('supplier_id', '')
            if supplier_id:
                supplier = get_object_or_404(MaterialSupplier, pk=supplier_id)
                if supplier.inbounds.exists():
                    messages.error(request, '该供应商存在入库记录，无法删除')
                else:
                    supplier.delete()
                    messages.success(request, '供应商删除成功')
                return redirect('production:material_supplier_list')
    
    context = {
        'suppliers': suppliers,
        'status_filter': status_filter,
    }
    return render(request, 'production/material_supplier_list.html', context)


def material_list(request):
    materials = Material.objects.filter(is_active=True)
    
    category_filter = request.GET.get('category', '')
    status_filter = request.GET.get('status', '')
    keyword = request.GET.get('keyword', '')
    
    if category_filter:
        materials = materials.filter(category_id=category_filter)
    if keyword:
        materials = materials.filter(Q(name__icontains=keyword) | Q(code__icontains=keyword) | 
                                      Q(specification__icontains=keyword))
    
    materials_with_stock = []
    for material in materials:
        materials_with_stock.append({
            'material': material,
            'current_stock': material.get_current_stock(),
            'stock_status': material.get_stock_status(),
            'stock_status_display': material.get_stock_status_display(),
        })
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'create':
            name = request.POST.get('name', '').strip()
            code = request.POST.get('code', '').strip()
            category_id = request.POST.get('category_id', '')
            specification = request.POST.get('specification', '').strip()
            unit = request.POST.get('unit', 'kg')
            safety_stock = request.POST.get('safety_stock', '0')
            max_stock = request.POST.get('max_stock', '0')
            min_stock = request.POST.get('min_stock', '0')
            expiry_days = request.POST.get('expiry_days', '0')
            description = request.POST.get('description', '').strip()
            storage_condition = request.POST.get('storage_condition', '').strip()
            
            errors = []
            if not name:
                errors.append('请输入原料名称')
            if not code:
                errors.append('请输入原料编码')
            if not category_id:
                errors.append('请选择原料分类')
            if Material.objects.filter(code=code).exists():
                errors.append('原料编码已存在')
            if Material.objects.filter(name=name, specification=specification).exists():
                errors.append('该名称和规格的原料已存在')
            
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                try:
                    category = MaterialCategory.objects.get(pk=category_id)
                    Material.objects.create(
                        name=name,
                        code=code,
                        category=category,
                        specification=specification,
                        unit=unit,
                        safety_stock=float(safety_stock) if safety_stock else 0,
                        max_stock=float(max_stock) if max_stock else 0,
                        min_stock=float(min_stock) if min_stock else 0,
                        expiry_days=int(expiry_days) if expiry_days else 0,
                        description=description,
                        storage_condition=storage_condition,
                    )
                    
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                        return JsonResponse({
                            'success': True,
                            'message': f'原料 {name} 创建成功',
                        })
                    
                    messages.success(request, f'原料 {name} 创建成功')
                except Exception as e:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                        return JsonResponse({
                            'success': False,
                            'error': str(e),
                        })
                    messages.error(request, f'创建失败: {str(e)}')
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                return JsonResponse({
                    'success': False,
                    'errors': errors,
                })
            
            return redirect('production:material_list')
        
        elif action == 'edit':
            material_id = request.POST.get('material_id', '')
            if material_id:
                material = get_object_or_404(Material, pk=material_id)
                material.name = request.POST.get('name', material.name).strip()
                material.code = request.POST.get('code', material.code).strip()
                
                category_id = request.POST.get('category_id', '')
                if category_id:
                    try:
                        material.category = MaterialCategory.objects.get(pk=category_id)
                    except MaterialCategory.DoesNotExist:
                        pass
                
                material.specification = request.POST.get('specification', material.specification).strip()
                material.unit = request.POST.get('unit', material.unit)
                material.safety_stock = float(request.POST.get('safety_stock', material.safety_stock))
                material.max_stock = float(request.POST.get('max_stock', material.max_stock))
                material.min_stock = float(request.POST.get('min_stock', material.min_stock))
                material.expiry_days = int(request.POST.get('expiry_days', material.expiry_days))
                material.description = request.POST.get('description', material.description).strip()
                material.storage_condition = request.POST.get('storage_condition', material.storage_condition).strip()
                material.save()
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                    return JsonResponse({
                        'success': True,
                        'message': f'原料 {material.name} 更新成功',
                    })
                
                messages.success(request, f'原料 {material.name} 更新成功')
                return redirect('production:material_list')
        
        elif action == 'delete':
            material_id = request.POST.get('material_id', '')
            if material_id:
                material = get_object_or_404(Material, pk=material_id)
                if material.inbounds.exists() or material.outbounds.exists() or material.losses.exists():
                    error_msg = '该原料存在出入库记录，无法删除'
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                        return JsonResponse({
                            'success': False,
                            'error': error_msg,
                        })
                    messages.error(request, error_msg)
                else:
                    material.is_active = False
                    material.save()
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                        return JsonResponse({
                            'success': True,
                            'message': '原料已停用',
                        })
                    messages.success(request, '原料已停用')
                return redirect('production:material_list')
    
    context = {
        'materials': materials_with_stock,
        'category_filter': category_filter,
        'status_filter': status_filter,
        'keyword': keyword,
        'categories': MaterialCategory.objects.filter(is_active=True),
        'unit_choices': MATERIAL_UNIT_CHOICES,
    }
    return render(request, 'production/material_list.html', context)


def material_detail(request, pk):
    material = get_object_or_404(Material, pk=pk)
    current_stock = material.get_current_stock()
    stock_status = material.get_stock_status()
    
    inbounds = material.inbounds.all()
    outbounds = material.outbounds.all()
    losses = material.losses.all()
    batch_usages = material.batch_usages.all()
    
    inbound_total = inbounds.aggregate(total=Sum('quantity'))['total'] or 0
    outbound_total = outbounds.aggregate(total=Sum('quantity'))['total'] or 0
    loss_total = losses.aggregate(total=Sum('quantity'))['total'] or 0
    
    inbound_batches = []
    for inbound in inbounds:
        remaining = inbound.get_remaining_quantity()
        inbound_batches.append({
            'inbound': inbound,
            'remaining': remaining,
            'is_expired': inbound.is_expired(),
            'is_near_expiry': inbound.is_near_expiry(),
        })
    
    today = timezone.now().date()
    last_30_days = today - timedelta(days=30)
    
    trend_data = []
    for i in range(29, -1, -1):
        date_i = today - timedelta(days=i)
        day_inbound = inbounds.filter(inbound_date=date_i).aggregate(total=Sum('quantity'))['total'] or 0
        day_outbound = outbounds.filter(outbound_date=date_i).aggregate(total=Sum('quantity'))['total'] or 0
        day_loss = losses.filter(loss_date=date_i).aggregate(total=Sum('quantity'))['total'] or 0
        trend_data.append({
            'date': date_i.strftime('%m-%d'),
            'inbound': round(day_inbound, 2),
            'outbound': round(day_outbound, 2),
            'loss': round(day_loss, 2),
        })
    
    context = {
        'material': material,
        'current_stock': current_stock,
        'stock_status': stock_status,
        'stock_status_display': material.get_stock_status_display(),
        'inbound_total': round(inbound_total, 2),
        'outbound_total': round(outbound_total, 2),
        'loss_total': round(loss_total, 2),
        'inbound_batches': inbound_batches,
        'outbounds': outbounds[:20],
        'losses': losses[:20],
        'batch_usages': batch_usages[:20],
        'trend_data': trend_data,
        'unit_display': material.get_unit_display(),
    }
    return render(request, 'production/material_detail.html', context)


def material_inbound_list(request):
    inbounds = MaterialInbound.objects.all()
    
    material_filter = request.GET.get('material', '')
    supplier_filter = request.GET.get('supplier', '')
    type_filter = request.GET.get('type', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    if material_filter:
        inbounds = inbounds.filter(material_id=material_filter)
    if supplier_filter:
        inbounds = inbounds.filter(supplier_id=supplier_filter)
    if type_filter:
        inbounds = inbounds.filter(inbound_type=type_filter)
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            inbounds = inbounds.filter(inbound_date__gte=start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            inbounds = inbounds.filter(inbound_date__lte=end)
        except ValueError:
            pass
    
    stats = {
        'total_count': inbounds.count(),
        'total_quantity': round(inbounds.aggregate(total=Sum('quantity'))['total'] or 0, 2),
        'total_amount': round(inbounds.aggregate(total=Sum('total_amount'))['total'] or 0, 2),
    }
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'create':
            material_id = request.POST.get('material_id', '')
            supplier_id = request.POST.get('supplier_id', '')
            quantity = request.POST.get('quantity', '')
            unit_price = request.POST.get('unit_price', '0')
            inbound_type = request.POST.get('inbound_type', 'purchase')
            batch_no = request.POST.get('batch_no', '').strip()
            production_date = request.POST.get('production_date', '')
            expiry_date = request.POST.get('expiry_date', '')
            inbound_date = request.POST.get('inbound_date', '')
            warehouse = request.POST.get('warehouse', '').strip()
            location = request.POST.get('location', '').strip()
            inspector = request.POST.get('inspector', '').strip()
            operator = request.POST.get('operator', '').strip()
            remark = request.POST.get('remark', '').strip()
            
            errors = []
            if not material_id:
                errors.append('请选择原料')
            if not supplier_id:
                errors.append('请选择供应商')
            if not quantity or float(quantity) <= 0:
                errors.append('请输入有效的入库数量')
            if not operator:
                errors.append('请输入经办人')
            
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                try:
                    material = Material.objects.get(pk=material_id)
                    supplier = MaterialSupplier.objects.get(pk=supplier_id)
                    
                    prod_date = None
                    if production_date:
                        prod_date = datetime.strptime(production_date, '%Y-%m-%d').date()
                    
                    exp_date = None
                    if expiry_date:
                        exp_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
                    
                    inb_date = timezone.now().date()
                    if inbound_date:
                        inb_date = datetime.strptime(inbound_date, '%Y-%m-%d').date()
                    
                    inbound = MaterialInbound.objects.create(
                        inbound_no=generate_inbound_no(),
                        material=material,
                        supplier=supplier,
                        quantity=float(quantity),
                        unit_price=float(unit_price) if unit_price else 0,
                        inbound_type=inbound_type,
                        batch_no=batch_no,
                        production_date=prod_date,
                        expiry_date=exp_date,
                        inbound_date=inb_date,
                        warehouse=warehouse,
                        location=location,
                        inspector=inspector,
                        operator=operator,
                        remark=remark,
                    )
                    
                    alerts = check_stock_alerts()
                    if alerts:
                        messages.warning(request, f'入库成功，检测到 {len(alerts)} 条库存预警')
                    else:
                        messages.success(request, f'入库单 {inbound.inbound_no} 创建成功')
                    
                except Exception as e:
                    messages.error(request, f'创建失败: {str(e)}')
            
            return redirect('production:material_inbound_list')
        
        elif action == 'delete':
            inbound_id = request.POST.get('inbound_id', '')
            if inbound_id:
                inbound = get_object_or_404(MaterialInbound, pk=inbound_id)
                if inbound.outbounds.exists() or inbound.losses.exists():
                    messages.error(request, '该入库单存在出库或损耗记录，无法删除')
                else:
                    inbound.delete()
                    messages.success(request, '入库单删除成功')
                return redirect('production:material_inbound_list')
    
    context = {
        'inbounds': inbounds[:100],
        'stats': stats,
        'material_filter': material_filter,
        'supplier_filter': supplier_filter,
        'type_filter': type_filter,
        'start_date': start_date,
        'end_date': end_date,
        'materials': Material.objects.filter(is_active=True),
        'suppliers': MaterialSupplier.objects.filter(is_active=True),
        'inbound_type_choices': INBOUND_TYPE_CHOICES,
    }
    return render(request, 'production/material_inbound_list.html', context)


def material_inbound_detail(request, pk):
    inbound = get_object_or_404(MaterialInbound, pk=pk)
    remaining = inbound.get_remaining_quantity()
    
    outbounds = inbound.outbounds.all()
    losses = inbound.losses.all()
    
    context = {
        'inbound': inbound,
        'remaining': remaining,
        'outbounds': outbounds,
        'losses': losses,
    }
    return render(request, 'production/material_inbound_detail.html', context)


def material_outbound_list(request):
    outbounds = MaterialOutbound.objects.all()
    
    material_filter = request.GET.get('material', '')
    type_filter = request.GET.get('type', '')
    batch_filter = request.GET.get('batch', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    if material_filter:
        outbounds = outbounds.filter(material_id=material_filter)
    if type_filter:
        outbounds = outbounds.filter(outbound_type=type_filter)
    if batch_filter:
        outbounds = outbounds.filter(batch__batch_no__icontains=batch_filter)
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            outbounds = outbounds.filter(outbound_date__gte=start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            outbounds = outbounds.filter(outbound_date__lte=end)
        except ValueError:
            pass
    
    stats = {
        'total_count': outbounds.count(),
        'total_quantity': round(outbounds.aggregate(total=Sum('quantity'))['total'] or 0, 2),
    }
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'create':
            material_id = request.POST.get('material_id', '')
            quantity = request.POST.get('quantity', '')
            outbound_type = request.POST.get('outbound_type', 'production')
            inbound_ref_id = request.POST.get('inbound_ref_id', '')
            batch_id = request.POST.get('batch_id', '')
            outbound_date = request.POST.get('outbound_date', '')
            warehouse = request.POST.get('warehouse', '').strip()
            location = request.POST.get('location', '').strip()
            receiver = request.POST.get('receiver', '').strip()
            operator = request.POST.get('operator', '').strip()
            remark = request.POST.get('remark', '').strip()
            
            usage_stage = request.POST.get('usage_stage', '')
            planned_quantity = request.POST.get('planned_quantity', '0')
            
            errors = []
            if not material_id:
                errors.append('请选择原料')
            if not quantity or float(quantity) <= 0:
                errors.append('请输入有效的出库数量')
            if not operator:
                errors.append('请输入经办人')
            
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                try:
                    material = Material.objects.get(pk=material_id)
                    
                    inbound_ref = None
                    if inbound_ref_id:
                        inbound_ref = MaterialInbound.objects.get(pk=inbound_ref_id)
                    
                    batch = None
                    if batch_id:
                        batch = RawMaterialBatch.objects.get(pk=batch_id)
                    
                    out_date = timezone.now().date()
                    if outbound_date:
                        out_date = datetime.strptime(outbound_date, '%Y-%m-%d').date()
                    
                    with transaction.atomic():
                        outbound = MaterialOutbound.objects.create(
                            outbound_no=generate_outbound_no(),
                            material=material,
                            quantity=float(quantity),
                            outbound_type=outbound_type,
                            outbound_date=out_date,
                            inbound_ref=inbound_ref,
                            batch=batch,
                            warehouse=warehouse,
                            location=location,
                            receiver=receiver,
                            operator=operator,
                            remark=remark,
                        )
                        
                        if batch and outbound_type == 'production':
                            BatchMaterialUsage.objects.create(
                                batch=batch,
                                material=material,
                                outbound=outbound,
                                planned_quantity=float(planned_quantity) if planned_quantity else 0,
                                actual_quantity=float(quantity),
                                unit=material.unit,
                                usage_stage=usage_stage if usage_stage else None,
                                usage_date=out_date,
                                operator=operator,
                                remark=remark,
                            )
                    
                    alerts = check_stock_alerts()
                    if alerts:
                        messages.warning(request, f'出库成功，检测到 {len(alerts)} 条库存预警')
                    else:
                        messages.success(request, f'出库单 {outbound.outbound_no} 创建成功')
                    
                except Exception as e:
                    messages.error(request, f'创建失败: {str(e)}')
            
            return redirect('production:material_outbound_list')
        
        elif action == 'delete':
            outbound_id = request.POST.get('outbound_id', '')
            if outbound_id:
                outbound = get_object_or_404(MaterialOutbound, pk=outbound_id)
                if hasattr(outbound, 'batch_usage'):
                    outbound.batch_usage.delete()
                outbound.delete()
                messages.success(request, '出库单删除成功')
                return redirect('production:material_outbound_list')
    
    context = {
        'outbounds': outbounds[:100],
        'stats': stats,
        'material_filter': material_filter,
        'type_filter': type_filter,
        'batch_filter': batch_filter,
        'start_date': start_date,
        'end_date': end_date,
        'materials': Material.objects.filter(is_active=True),
        'batches': RawMaterialBatch.objects.all(),
        'outbound_type_choices': OUTBOUND_TYPE_CHOICES,
        'stage_choices': STAGE_CHOICES,
    }
    return render(request, 'production/material_outbound_list.html', context)


def material_loss_list(request):
    losses = MaterialLoss.objects.all()
    
    material_filter = request.GET.get('material', '')
    reason_filter = request.GET.get('reason', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    if material_filter:
        losses = losses.filter(material_id=material_filter)
    if reason_filter:
        losses = losses.filter(loss_reason=reason_filter)
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            losses = losses.filter(loss_date__gte=start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            losses = losses.filter(loss_date__lte=end)
        except ValueError:
            pass
    
    stats = {
        'total_count': losses.count(),
        'total_quantity': round(losses.aggregate(total=Sum('quantity'))['total'] or 0, 2),
    }
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'create':
            material_id = request.POST.get('material_id', '')
            quantity = request.POST.get('quantity', '')
            loss_reason = request.POST.get('loss_reason', 'natural')
            inbound_ref_id = request.POST.get('inbound_ref_id', '')
            loss_date = request.POST.get('loss_date', '')
            warehouse = request.POST.get('warehouse', '').strip()
            location = request.POST.get('location', '').strip()
            reported_by = request.POST.get('reported_by', '').strip()
            approved_by = request.POST.get('approved_by', '').strip()
            description = request.POST.get('description', '').strip()
            remark = request.POST.get('remark', '').strip()
            
            errors = []
            if not material_id:
                errors.append('请选择原料')
            if not quantity or float(quantity) <= 0:
                errors.append('请输入有效的损耗数量')
            if not reported_by:
                errors.append('请输入上报人')
            if not description:
                errors.append('请填写损耗说明')
            
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                try:
                    material = Material.objects.get(pk=material_id)
                    
                    inbound_ref = None
                    if inbound_ref_id:
                        inbound_ref = MaterialInbound.objects.get(pk=inbound_ref_id)
                    
                    l_date = timezone.now().date()
                    if loss_date:
                        l_date = datetime.strptime(loss_date, '%Y-%m-%d').date()
                    
                    loss = MaterialLoss.objects.create(
                        loss_no=generate_loss_no(),
                        material=material,
                        quantity=float(quantity),
                        loss_reason=loss_reason,
                        loss_date=l_date,
                        inbound_ref=inbound_ref,
                        warehouse=warehouse,
                        location=location,
                        reported_by=reported_by,
                        approved_by=approved_by,
                        description=description,
                        remark=remark,
                    )
                    
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                        return JsonResponse({
                            'success': True,
                            'message': '损耗记录创建成功',
                            'loss_id': loss.pk,
                        })
                    
                    messages.success(request, '损耗记录创建成功')
                    
                except Exception as e:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                        return JsonResponse({
                            'success': False,
                            'error': str(e),
                        })
                    messages.error(request, f'创建失败: {str(e)}')
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                return JsonResponse({
                    'success': False,
                    'errors': errors,
                })
            
            return redirect('production:material_loss_list')
        
        elif action == 'delete':
            loss_id = request.POST.get('loss_id', '')
            if loss_id:
                loss = get_object_or_404(MaterialLoss, pk=loss_id)
                loss.delete()
                messages.success(request, '损耗记录删除成功')
                return redirect('production:material_loss_list')
    
    context = {
        'losses': losses[:100],
        'stats': stats,
        'material_filter': material_filter,
        'reason_filter': reason_filter,
        'start_date': start_date,
        'end_date': end_date,
        'materials': Material.objects.filter(is_active=True),
        'loss_reason_choices': LOSS_REASON_CHOICES,
    }
    return render(request, 'production/material_loss_list.html', context)


def batch_material_trace(request, batch_id):
    batch = get_object_or_404(RawMaterialBatch, pk=batch_id)
    material_usages = batch.batch_materials.all()
    
    usage_summary = {}
    for usage in material_usages:
        mat_id = usage.material_id
        if mat_id not in usage_summary:
            usage_summary[mat_id] = {
                'material': usage.material,
                'total_quantity': 0,
                'usage_count': 0,
                'usages': [],
            }
        usage_summary[mat_id]['total_quantity'] += usage.actual_quantity
        usage_summary[mat_id]['usage_count'] += 1
        usage_summary[mat_id]['usages'].append(usage)
    
    total_material_cost = 0
    for summary in usage_summary.values():
        for usage in summary['usages']:
            if usage.outbound and usage.outbound.inbound_ref:
                total_material_cost += usage.actual_quantity * usage.outbound.inbound_ref.unit_price
    
    context = {
        'batch': batch,
        'material_usages': material_usages,
        'usage_summary': list(usage_summary.values()),
        'total_material_cost': round(total_material_cost, 2),
    }
    return render(request, 'production/batch_material_trace.html', context)


def material_stock_alert_list(request):
    alerts = MaterialStockAlert.objects.all()
    
    type_filter = request.GET.get('type', '')
    level_filter = request.GET.get('level', '')
    status_filter = request.GET.get('status', '')
    
    if type_filter:
        alerts = alerts.filter(alert_type=type_filter)
    if level_filter:
        alerts = alerts.filter(alert_level=level_filter)
    if status_filter:
        alerts = alerts.filter(alert_status=status_filter)
    
    stats = {
        'total': alerts.count(),
        'active': MaterialStockAlert.objects.filter(alert_status='active').count(),
        'acknowledged': MaterialStockAlert.objects.filter(alert_status='acknowledged').count(),
        'resolved': MaterialStockAlert.objects.filter(alert_status='resolved').count(),
        'danger': MaterialStockAlert.objects.filter(alert_level='danger', 
                                                   alert_status__in=['active', 'acknowledged']).count(),
        'warning': MaterialStockAlert.objects.filter(alert_level='warning', 
                                                    alert_status__in=['active', 'acknowledged']).count(),
        'info': MaterialStockAlert.objects.filter(alert_level='info', 
                                                 alert_status__in=['active', 'acknowledged']).count(),
    }
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'check':
            new_alerts = check_stock_alerts()
            messages.success(request, f'库存预警检查完成，新增 {len(new_alerts)} 条预警')
            return redirect('production:material_stock_alert_list')
        
        elif action == 'process':
            alert_id = request.POST.get('alert_id', '')
            process_action = request.POST.get('process_action', '')
            handler = request.POST.get('handler', '').strip()
            notes = request.POST.get('handle_notes', '').strip()
            
            if alert_id:
                alert = get_object_or_404(MaterialStockAlert, pk=alert_id)
                
                if process_action == 'acknowledge':
                    alert.alert_status = 'acknowledged'
                    alert.acknowledged_at = timezone.now()
                    alert.acknowledged_by = handler or '系统管理员'
                    alert.handle_notes = notes
                    alert.save()
                    messages.success(request, '预警已确认')
                elif process_action == 'resolve':
                    alert.alert_status = 'resolved'
                    alert.resolved_at = timezone.now()
                    alert.resolved_by = handler or '系统管理员'
                    alert.handle_notes = notes
                    alert.save()
                    messages.success(request, '预警已解决')
                elif process_action == 'close':
                    alert.alert_status = 'closed'
                    alert.resolved_at = timezone.now()
                    alert.resolved_by = handler or '系统管理员'
                    alert.handle_notes = notes
                    alert.save()
                    messages.success(request, '预警已关闭')
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'multipart/form-data':
                    return JsonResponse({
                        'success': True,
                        'message': f'预警已{process_action}成功',
                    })
                
                return redirect('production:material_stock_alert_list')
    
    context = {
        'alerts': alerts[:50],
        'stats': stats,
        'type_filter': type_filter,
        'level_filter': level_filter,
        'status_filter': status_filter,
        'stock_alert_type_choices': STOCK_ALERT_STATUS_CHOICES,
        'alert_level_choices': ALERT_LEVEL_CHOICES,
        'alert_status_choices': ALERT_STATUS_CHOICES,
    }
    return render(request, 'production/material_stock_alert_list.html', context)


def material_stock_alert_detail(request, pk):
    alert = get_object_or_404(MaterialStockAlert, pk=pk)
    
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
            alert.closed_at = timezone.now() if hasattr(alert, 'closed_at') else None
            alert.resolved_by = handler or '系统管理员'
            alert.handle_notes = notes
            alert.save()
            messages.success(request, '预警已关闭')
        
        return redirect('production:material_stock_alert_detail', pk=pk)
    
    context = {
        'alert': alert,
    }
    return render(request, 'production/material_stock_alert_detail.html', context)


def material_ledger(request):
    materials = Material.objects.filter(is_active=True)
    
    material_filter = request.GET.get('material', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    if material_filter:
        materials = materials.filter(pk=material_filter)
    
    date_q_inbound = Q()
    date_q_outbound = Q()
    date_q_loss = Q()
    
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            date_q_inbound &= Q(inbound_date__gte=start)
            date_q_outbound &= Q(outbound_date__gte=start)
            date_q_loss &= Q(loss_date__gte=start)
        except ValueError:
            pass
    
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            date_q_inbound &= Q(inbound_date__lte=end)
            date_q_outbound &= Q(outbound_date__lte=end)
            date_q_loss &= Q(loss_date__lte=end)
        except ValueError:
            pass
    
    ledger_data = []
    for material in materials:
        before_start_inbound = 0
        before_start_outbound = 0
        before_start_loss = 0
        
        if start_date:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            before_start_inbound = material.inbounds.filter(inbound_date__lt=start).aggregate(
                total=Sum('quantity'))['total'] or 0
            before_start_outbound = material.outbounds.filter(outbound_date__lt=start).aggregate(
                total=Sum('quantity'))['total'] or 0
            before_start_loss = material.losses.filter(loss_date__lt=start).aggregate(
                total=Sum('quantity'))['total'] or 0
        
        opening_stock = round(before_start_inbound - before_start_outbound - before_start_loss, 2)
        
        period_inbound = material.inbounds.filter(date_q_inbound).aggregate(
            total=Sum('quantity'))['total'] or 0
        period_outbound = material.outbounds.filter(date_q_outbound).aggregate(
            total=Sum('quantity'))['total'] or 0
        period_loss = material.losses.filter(date_q_loss).aggregate(
            total=Sum('quantity'))['total'] or 0
        
        closing_stock = round(opening_stock + period_inbound - period_outbound - period_loss, 2)
        
        inbounds = material.inbounds.filter(date_q_inbound)
        outbounds = material.outbounds.filter(date_q_outbound)
        losses = material.losses.filter(date_q_loss)
        
        records = []
        for ib in inbounds:
            records.append({
                'date': ib.inbound_date,
                'type': '入库',
                'type_class': 'success',
                'ref_no': ib.inbound_no,
                'supplier': ib.supplier.name if ib.supplier else '',
                'in_quantity': ib.quantity,
                'out_quantity': 0,
                'loss_quantity': 0,
                'operator': ib.operator,
                'remark': ib.remark,
            })
        
        for ob in outbounds:
            records.append({
                'date': ob.outbound_date,
                'type': '出库',
                'type_class': 'warning',
                'ref_no': ob.outbound_no,
                'supplier': ob.batch.batch_no if ob.batch else '',
                'in_quantity': 0,
                'out_quantity': ob.quantity,
                'loss_quantity': 0,
                'operator': ob.operator,
                'remark': ob.remark,
            })
        
        for ls in losses:
            records.append({
                'date': ls.loss_date,
                'type': '损耗',
                'type_class': 'danger',
                'ref_no': ls.loss_no,
                'supplier': ls.get_loss_reason_display(),
                'in_quantity': 0,
                'out_quantity': 0,
                'loss_quantity': ls.quantity,
                'operator': ls.reported_by,
                'remark': ls.description,
            })
        
        records.sort(key=lambda x: x['date'])
        
        running_balance = opening_stock
        for record in records:
            running_balance = round(running_balance + record['in_quantity'] - record['out_quantity'] - record['loss_quantity'], 2)
            record['balance'] = running_balance
        
        ledger_data.append({
            'material': material,
            'opening_stock': opening_stock,
            'period_inbound': round(period_inbound, 2),
            'period_outbound': round(period_outbound, 2),
            'period_loss': round(period_loss, 2),
            'closing_stock': closing_stock,
            'records': records,
            'unit_display': material.get_unit_display(),
        })
    
    totals = {
        'opening': round(sum(d['opening_stock'] for d in ledger_data), 2),
        'inbound': round(sum(d['period_inbound'] for d in ledger_data), 2),
        'outbound': round(sum(d['period_outbound'] for d in ledger_data), 2),
        'loss': round(sum(d['period_loss'] for d in ledger_data), 2),
        'closing': round(sum(d['closing_stock'] for d in ledger_data), 2),
    }
    
    if request.method == 'POST' and request.POST.get('action') == 'export':
        export_type = 'material_ledger'
        export_name = request.POST.get('export_name', '原料台账').strip()
        requested_by = request.POST.get('requested_by', '').strip()
        
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{export_name}.csv"'
        response.write('\ufeff')
        
        writer = csv.writer(response)
        writer.writerow(['原料台账报表'])
        writer.writerow(['统计期间', f'{start_date or "不限"} 至 {end_date or "不限"}'])
        writer.writerow([])
        
        for data in ledger_data:
            writer.writerow([f'原料: {data["material"].name} ({data["material"].code})'])
            writer.writerow(['期初库存', data['opening_stock'], data['unit_display']])
            writer.writerow(['本期入库', data['period_inbound'], data['unit_display']])
            writer.writerow(['本期出库', data['period_outbound'], data['unit_display']])
            writer.writerow(['本期损耗', data['period_loss'], data['unit_display']])
            writer.writerow(['期末库存', data['closing_stock'], data['unit_display']])
            writer.writerow([])
            writer.writerow(['日期', '类型', '单号', '关联', '入库数量', '出库数量', '损耗数量', '结存', '操作人', '备注'])
            
            running = data['opening_stock']
            writer.writerow([start_date or '期初', '期初', '', '', '', '', '', running, '', ''])
            
            for record in data['records']:
                running = round(running + record['in_quantity'] - record['out_quantity'] - record['loss_quantity'], 2)
                writer.writerow([
                    record['date'],
                    record['type'],
                    record['ref_no'],
                    record['supplier'],
                    record['in_quantity'] if record['in_quantity'] > 0 else '',
                    record['out_quantity'] if record['out_quantity'] > 0 else '',
                    record['loss_quantity'] if record['loss_quantity'] > 0 else '',
                    running,
                    record['operator'],
                    record['remark'],
                ])
            
            writer.writerow([])
            writer.writerow([])
        
        return response
    
    context = {
        'ledger_data': ledger_data,
        'totals': totals,
        'material_filter': material_filter,
        'start_date': start_date,
        'end_date': end_date,
        'materials': Material.objects.filter(is_active=True),
    }
    return render(request, 'production/material_ledger.html', context)


def material_statistics(request):
    materials = Material.objects.filter(is_active=True)
    
    category_filter = request.GET.get('category', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    date_q_inbound = Q()
    date_q_outbound = Q()
    date_q_loss = Q()
    
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            date_q_inbound &= Q(inbound_date__gte=start)
            date_q_outbound &= Q(outbound_date__gte=start)
            date_q_loss &= Q(loss_date__gte=start)
        except ValueError:
            pass
    
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            date_q_inbound &= Q(inbound_date__lte=end)
            date_q_outbound &= Q(outbound_date__lte=end)
            date_q_loss &= Q(loss_date__lte=end)
        except ValueError:
            pass
    
    if category_filter:
        materials = materials.filter(category_id=category_filter)
    
    material_stats = []
    for material in materials:
        period_inbound = material.inbounds.filter(date_q_inbound).aggregate(
            total=Sum('quantity'))['total'] or 0
        period_outbound = material.outbounds.filter(date_q_outbound).aggregate(
            total=Sum('quantity'))['total'] or 0
        period_loss = material.losses.filter(date_q_loss).aggregate(
            total=Sum('quantity'))['total'] or 0
        period_amount = material.inbounds.filter(date_q_inbound).aggregate(
            total=Sum('total_amount'))['total'] or 0
        
        current_stock = material.get_current_stock()
        
        usage_batches = material.batch_usages.count()
        
        loss_rate = round((period_loss / (period_inbound + 0.001)) * 100, 2)
        
        material_stats.append({
            'material': material,
            'period_inbound': round(period_inbound, 2),
            'period_outbound': round(period_outbound, 2),
            'period_loss': round(period_loss, 2),
            'period_amount': round(period_amount, 2),
            'current_stock': current_stock,
            'usage_batches': usage_batches,
            'loss_rate': loss_rate,
            'unit_display': material.get_unit_display(),
        })
    
    category_stats = []
    for category in MaterialCategory.objects.filter(is_active=True):
        if category_filter and str(category.id) != category_filter:
            continue
            
        cat_materials = category.materials.filter(is_active=True)
        cat_inbound = 0
        cat_outbound = 0
        cat_loss = 0
        cat_amount = 0
        for mat in cat_materials:
            cat_inbound += mat.inbounds.filter(date_q_inbound).aggregate(
                total=Sum('quantity'))['total'] or 0
            cat_outbound += mat.outbounds.filter(date_q_outbound).aggregate(
                total=Sum('quantity'))['total'] or 0
            cat_loss += mat.losses.filter(date_q_loss).aggregate(
                total=Sum('quantity'))['total'] or 0
            cat_amount += mat.inbounds.filter(date_q_inbound).aggregate(
                total=Sum('total_amount'))['total'] or 0
        
        category_stats.append({
            'category': category,
            'material_count': cat_materials.count(),
            'total_inbound': round(cat_inbound, 2),
            'total_outbound': round(cat_outbound, 2),
            'total_loss': round(cat_loss, 2),
            'total_amount': round(cat_amount, 2),
        })
    
    supplier_stats = []
    for supplier in MaterialSupplier.objects.filter(is_active=True):
        sup_inbounds = supplier.inbounds.filter(date_q_inbound)
        sup_total = sup_inbounds.aggregate(total=Sum('total_amount'))['total'] or 0
        sup_quantity = sup_inbounds.aggregate(total=Sum('quantity'))['total'] or 0
        
        supplier_stats.append({
            'supplier': supplier,
            'inbound_count': sup_inbounds.count(),
            'total_quantity': round(sup_quantity, 2),
            'total_amount': round(sup_total, 2),
        })
    supplier_stats.sort(key=lambda x: x['total_amount'], reverse=True)
    
    today = timezone.now().date()
    monthly_data = []
    for i in range(11, -1, -1):
        month_date = today - timedelta(days=i * 30)
        month_start = month_date.replace(day=1)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        
        month_inbound = MaterialInbound.objects.filter(
            inbound_date__gte=month_start,
            inbound_date__lt=next_month
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        month_outbound = MaterialOutbound.objects.filter(
            outbound_date__gte=month_start,
            outbound_date__lt=next_month
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        month_loss = MaterialLoss.objects.filter(
            loss_date__gte=month_start,
            loss_date__lt=next_month
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        monthly_data.append({
            'month': month_start.strftime('%Y-%m'),
            'inbound': round(month_inbound, 2),
            'outbound': round(month_outbound, 2),
            'loss': round(month_loss, 2),
            'net': round(month_inbound - month_outbound - month_loss, 2),
        })
    
    chart_data = {
        'category_labels': [s['category'].name for s in category_stats],
        'category_inbound': [s['total_inbound'] for s in category_stats],
        'category_outbound': [s['total_outbound'] for s in category_stats],
        'monthly_labels': [m['month'] for m in monthly_data],
        'monthly_inbound': [m['inbound'] for m in monthly_data],
        'monthly_outbound': [m['outbound'] for m in monthly_data],
        'top_supplier_labels': [s['supplier'].name for s in supplier_stats[:10]],
        'top_supplier_amounts': [s['total_amount'] for s in supplier_stats[:10]],
    }
    
    context = {
        'material_stats': material_stats,
        'category_stats': category_stats,
        'supplier_stats': supplier_stats[:10],
        'monthly_data': monthly_data,
        'chart_data': chart_data,
        'category_filter': category_filter,
        'start_date': start_date,
        'end_date': end_date,
        'categories': MaterialCategory.objects.filter(is_active=True),
    }
    return render(request, 'production/material_statistics.html', context)


def run_stock_alert_check(request):
    if request.method == 'POST':
        try:
            new_alerts = check_stock_alerts()
            return JsonResponse({
                'success': True,
                'new_alerts': len(new_alerts),
                'total_alerts': MaterialStockAlert.objects.count(),
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': '仅支持POST请求'})


def material_toggle_status(request, pk):
    if request.method == 'POST':
        try:
            material = get_object_or_404(Material, pk=pk)
            material.is_active = not material.is_active
            material.save()
            return JsonResponse({
                'success': True,
                'is_active': material.is_active,
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': '仅支持POST请求'})


def material_outbound_detail(request, pk):
    outbound = get_object_or_404(MaterialOutbound, pk=pk)
    
    batch_usage = BatchMaterialUsage.objects.filter(outbound=outbound).first()
    
    context = {
        'outbound': outbound,
        'batch_usage': batch_usage,
    }
    return render(request, 'production/material_outbound_detail.html', context)


def material_loss_detail(request, pk):
    loss = get_object_or_404(MaterialLoss, pk=pk)
    
    context = {
        'loss': loss,
    }
    return render(request, 'production/material_loss_detail.html', context)


def material_ledger_export(request):
    if request.method == 'POST':
        material_filter = request.POST.get('material', '')
        start_date = request.POST.get('start_date', '')
        end_date = request.POST.get('end_date', '')
        report_name = request.POST.get('report_name', '原料台账')
        applicant = request.POST.get('applicant', '')
        
        ledger_data = []
        
        materials = Material.objects.all()
        if material_filter:
            materials = materials.filter(pk=material_filter)
        
        for material in materials:
            inbounds = MaterialInbound.objects.filter(material=material)
            outbounds = MaterialOutbound.objects.filter(material=material)
            losses = MaterialLoss.objects.filter(material=material)
            
            if start_date:
                try:
                    start = datetime.strptime(start_date, '%Y-%m-%d').date()
                    inbounds = inbounds.filter(inbound_date__gte=start)
                    outbounds = outbounds.filter(outbound_date__gte=start)
                    losses = losses.filter(loss_date__gte=start)
                except ValueError:
                    pass
            
            if end_date:
                try:
                    end = datetime.strptime(end_date, '%Y-%m-%d').date()
                    inbounds = inbounds.filter(inbound_date__lte=end)
                    outbounds = outbounds.filter(outbound_date__lte=end)
                    losses = losses.filter(loss_date__lte=end)
                except ValueError:
                    pass
            
            inbound_total = inbounds.aggregate(total=Sum('quantity'))['total'] or 0
            outbound_total = outbounds.aggregate(total=Sum('quantity'))['total'] or 0
            loss_total = losses.aggregate(total=Sum('quantity'))['total'] or 0
            
            current_stock = material.get_current_stock()
            opening_stock = current_stock - inbound_total + outbound_total + loss_total
            
            records = []
            for inbound in inbounds:
                records.append({
                    'date': inbound.inbound_date,
                    'type': '入库',
                    'no': inbound.inbound_no,
                    'ref': inbound.supplier.name if inbound.supplier else '',
                    'inbound': inbound.quantity,
                    'outbound': 0,
                    'loss': 0,
                    'operator': inbound.operator or '',
                    'remark': inbound.remark or '',
                })
            
            for outbound in outbounds:
                records.append({
                    'date': outbound.outbound_date,
                    'type': '出库',
                    'no': outbound.outbound_no,
                    'ref': outbound.batch.batch_no if outbound.batch else (outbound.reference or ''),
                    'inbound': 0,
                    'outbound': outbound.quantity,
                    'loss': 0,
                    'operator': outbound.operator or '',
                    'remark': outbound.remark or '',
                })
            
            for loss in losses:
                records.append({
                    'date': loss.loss_date,
                    'type': '损耗',
                    'no': loss.loss_no,
                    'ref': loss.get_loss_reason_display(),
                    'inbound': 0,
                    'outbound': 0,
                    'loss': loss.quantity,
                    'operator': loss.reported_by or '',
                    'remark': loss.remark or '',
                })
            
            records.sort(key=lambda x: x['date'])
            
            balance = opening_stock
            for record in records:
                balance = balance + record['inbound'] - record['outbound'] - record['loss']
                record['balance'] = round(balance, 2)
            
            ledger_data.append({
                'material': material,
                'opening_stock': round(opening_stock, 2),
                'inbound_total': round(inbound_total, 2),
                'outbound_total': round(outbound_total, 2),
                'loss_total': round(loss_total, 2),
                'closing_stock': round(current_stock, 2),
                'records': records,
            })
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{report_name}_{timezone.now().strftime("%Y%m%d%H%M%S")}.csv"'
        
        response.write(codecs.BOM_UTF8)
        writer = csv.writer(response)
        
        writer.writerow([f'原料台账 - {report_name}'])
        writer.writerow([f'申请人: {applicant}', f'导出时间: {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}'])
        writer.writerow([f'日期范围: {start_date or "全部"} 至 {end_date or "全部"}'])
        writer.writerow([])
        
        for data in ledger_data:
            writer.writerow([
                f'原料: {data["material"].name} ({data["material"].code})',
                '', '', '', '', '',
                f'期初: {data["opening_stock"]} {data["material"].get_unit_display()}',
                f'入库: {data["inbound_total"]} {data["material"].get_unit_display()}',
                f'出库: {data["outbound_total"]} {data["material"].get_unit_display()}',
                f'损耗: {data["loss_total"]} {data["material"].get_unit_display()}',
                f'期末: {data["closing_stock"]} {data["material"].get_unit_display()}',
            ])
            writer.writerow(['日期', '类型', '单号', '关联', '入库', '出库', '损耗', '结存', '操作人', '备注'])
            
            for record in data['records']:
                writer.writerow([
                    record['date'],
                    record['type'],
                    record['no'],
                    record['ref'],
                    record['inbound'],
                    record['outbound'],
                    record['loss'],
                    record['balance'],
                    record['operator'],
                    record['remark'],
                ])
            
            writer.writerow([])
        
        return response
    
    return redirect('production:material_ledger')


def cost_dashboard(request):
    total_batches = RawMaterialBatch.objects.count()
    summaries = BatchCostSummary.objects.all()

    source_filter = request.GET.get('source', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date')

    filtered_batches = RawMaterialBatch.objects.all()
    if source_filter:
        filtered_batches = filtered_batches.filter(material_source__icontains=source_filter)
    if start_date:
        try:
            s = datetime.strptime(start_date, '%Y-%m-%d').date()
            filtered_batches = filtered_batches.filter(start_date__gte=s)
        except ValueError:
            pass
    if end_date:
        try:
            e = datetime.strptime(end_date, '%Y-%m-%d').date()
            filtered_batches = filtered_batches.filter(start_date__lte=e)
        except ValueError:
            pass

    summaries = BatchCostSummary.objects.filter(batch__in=filtered_batches)

    total_cost = summaries.aggregate(s=Sum('total_cost'))['s'] or 0
    total_revenue = summaries.aggregate(s=Sum('revenue'))['s'] or 0
    total_profit = summaries.aggregate(s=Sum('profit'))['s'] or 0
    avg_profit_margin = summaries.aggregate(avg=Avg('profit_margin'))['avg'] or 0
    avg_unit_cost = summaries.aggregate(avg=Avg('unit_cost'))['avg'] or 0
    loss_count = summaries.filter(is_loss=True).count()
    summary_count = summaries.count()

    avg_material_cost = summaries.aggregate(avg=Avg('material_cost'))['avg'] or 0
    avg_energy_cost = summaries.aggregate(avg=Avg('energy_cost'))['avg'] or 0
    avg_labor_cost = summaries.aggregate(avg=Avg('labor_cost'))['avg'] or 0
    avg_other_cost = summaries.aggregate(avg=Avg('other_cost'))['avg'] or 0
    avg_loss_cost = summaries.aggregate(avg=Avg('loss_cost'))['avg'] or 0

    cost_warning_count = LossWarning.objects.filter(warning_status='active').count()

    today = timezone.now().date()
    cost_trend = []
    unit_cost_trend = []
    for i in range(5, -1, -1):
        month_date = today - timedelta(days=i * 30)
        month_start = month_date.replace(day=1)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)

        month_summaries = BatchCostSummary.objects.filter(
            batch__start_date__gte=month_start,
            batch__start_date__lt=next_month
        )
        month_cost = month_summaries.aggregate(s=Sum('total_cost'))['s'] or 0
        month_revenue = month_summaries.aggregate(s=Sum('revenue'))['s'] or 0
        month_profit = month_summaries.aggregate(s=Sum('profit'))['s'] or 0
        month_unit_cost = month_summaries.aggregate(avg=Avg('unit_cost'))['avg'] or 0

        cost_trend.append({
            'month': month_start.strftime('%Y-%m'),
            'cost': round(month_cost, 2),
            'revenue': round(month_revenue, 2),
            'profit': round(month_profit, 2),
        })
        unit_cost_trend.append({
            'month': month_start.strftime('%Y-%m'),
            'unit_cost': round(month_unit_cost, 2),
        })

    source_cost_data = []
    sources = RawMaterialBatch.objects.filter(
        pk__in=filtered_batches.values_list('pk', flat=True)
    ).values_list('material_source', flat=True).distinct()
    for source in sources:
        source_summaries = summaries.filter(batch__material_source=source)
        if source_summaries.exists():
            source_cost_data.append({
                'source': source,
                'total_cost': round(source_summaries.aggregate(s=Sum('total_cost'))['s'] or 0, 2),
                'total_revenue': round(source_summaries.aggregate(s=Sum('revenue'))['s'] or 0, 2),
                'total_profit': round(source_summaries.aggregate(s=Sum('profit'))['s'] or 0, 2),
                'avg_profit_margin': round(source_summaries.aggregate(avg=Avg('profit_margin'))['avg'] or 0, 2),
                'batch_count': source_summaries.count(),
                'loss_count': source_summaries.filter(is_loss=True).count(),
            })

    recent_summaries = summaries[:10]
    active_warnings = LossWarning.objects.filter(warning_status='active')[:5]

    chart_data = {
        'cost_labels': ['原料成本', '能耗成本', '人工成本', '其他费用', '损耗费用'],
        'cost_values': [round(avg_material_cost, 2), round(avg_energy_cost, 2),
                        round(avg_labor_cost, 2), round(avg_other_cost, 2),
                        round(avg_loss_cost, 2)],
        'trend_labels': [t['month'] for t in cost_trend],
        'trend_cost': [t['cost'] for t in cost_trend],
        'trend_revenue': [t['revenue'] for t in cost_trend],
        'trend_profit': [t['profit'] for t in cost_trend],
        'unit_cost_labels': [t['month'] for t in unit_cost_trend],
        'unit_cost_values': [t['unit_cost'] for t in unit_cost_trend],
        'source_labels': [s['source'] for s in source_cost_data],
        'source_costs': [s['total_cost'] for s in source_cost_data],
        'source_profits': [s['total_profit'] for s in source_cost_data],
        'source_margins': [s['avg_profit_margin'] for s in source_cost_data],
    }

    context = {
        'total_batches': total_batches,
        'summary_count': summary_count,
        'total_cost': round(total_cost, 2),
        'total_revenue': round(total_revenue, 2),
        'total_profit': round(total_profit, 2),
        'avg_profit_margin': round(avg_profit_margin, 2),
        'avg_unit_cost': round(avg_unit_cost, 2),
        'loss_count': loss_count,
        'cost_warning_count': cost_warning_count,
        'recent_summaries': recent_summaries,
        'active_warnings': active_warnings,
        'cost_trend': cost_trend,
        'unit_cost_trend': unit_cost_trend,
        'source_cost_data': source_cost_data,
        'chart_data': chart_data,
        'source_filter': source_filter,
        'start_date': start_date,
        'end_date': end_date,
        'sources': RawMaterialBatch.objects.values_list('material_source', flat=True).distinct(),
    }
    return render(request, 'production/cost_dashboard.html', context)


def energy_cost_list(request):
    costs = ProcessEnergyCost.objects.all()

    batch_filter = request.GET.get('batch', '')
    stage_filter = request.GET.get('stage', '')
    energy_filter = request.GET.get('energy', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    if batch_filter:
        costs = costs.filter(batch__batch_no__icontains=batch_filter)
    if stage_filter:
        costs = costs.filter(stage_type=stage_filter)
    if energy_filter:
        costs = costs.filter(energy_type=energy_filter)
    if start_date:
        try:
            s = datetime.strptime(start_date, '%Y-%m-%d').date()
            costs = costs.filter(record_date__gte=s)
        except ValueError:
            pass
    if end_date:
        try:
            e = datetime.strptime(end_date, '%Y-%m-%d').date()
            costs = costs.filter(record_date__lte=e)
        except ValueError:
            pass

    stats = {
        'total_count': costs.count(),
        'total_amount': round(costs.aggregate(s=Sum('total_amount'))['s'] or 0, 2),
        'total_consumption': round(costs.aggregate(s=Sum('consumption'))['s'] or 0, 2),
    }

    stage_stats = []
    for stage_type, stage_name in STAGE_CHOICES:
        stage_costs = costs.filter(stage_type=stage_type)
        if stage_costs.exists():
            stage_stats.append({
                'stage': stage_name,
                'amount': round(stage_costs.aggregate(s=Sum('total_amount'))['s'] or 0, 2),
                'count': stage_costs.count(),
            })

    context = {
        'costs': costs[:100],
        'stats': stats,
        'stage_stats': stage_stats,
        'batch_filter': batch_filter,
        'stage_filter': stage_filter,
        'energy_filter': energy_filter,
        'start_date': start_date,
        'end_date': end_date,
        'stage_choices': STAGE_CHOICES,
        'energy_type_choices': ENERGY_TYPE_CHOICES,
        'batches': RawMaterialBatch.objects.all(),
    }
    return render(request, 'production/energy_cost_list.html', context)


def energy_cost_create(request, batch_id):
    batch = get_object_or_404(RawMaterialBatch, pk=batch_id)

    if request.method == 'POST':
        stage_type = request.POST.get('stage_type', '')
        energy_type = request.POST.get('energy_type', '')
        consumption = request.POST.get('consumption', '')
        unit = request.POST.get('unit', '').strip()
        unit_price = request.POST.get('unit_price', '0')
        record_date = request.POST.get('record_date', '')
        meter_reading = request.POST.get('meter_reading', '').strip()
        operator = request.POST.get('operator', '').strip()
        remark = request.POST.get('remark', '').strip()

        errors = []
        if not stage_type:
            errors.append('请选择工序阶段')
        if not energy_type:
            errors.append('请选择能源类型')
        if not consumption or float(consumption) <= 0:
            errors.append('请输入有效的消耗量')
        if not unit:
            errors.append('请输入计量单位')
        if not operator:
            errors.append('请输入记录人员')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            try:
                rec_date = datetime.strptime(record_date, '%Y-%m-%d').date() if record_date else date.today()
                ProcessEnergyCost.objects.create(
                    batch=batch,
                    stage_type=stage_type,
                    energy_type=energy_type,
                    consumption=float(consumption),
                    unit=unit,
                    unit_price=float(unit_price) if unit_price else 0,
                    record_date=rec_date,
                    operator=operator,
                    meter_reading=meter_reading,
                    remark=remark,
                )
                BatchCostSummary.calculate_for_batch(batch)
                SourceCostStats.update_stats(batch.material_source)
                messages.success(request, '能耗记录添加成功')
            except Exception as e:
                messages.error(request, f'添加失败: {str(e)}')
        return redirect('production:batch_cost_detail', pk=batch.pk)

    context = {
        'batch': batch,
        'stage_choices': STAGE_CHOICES,
        'energy_type_choices': ENERGY_TYPE_CHOICES,
    }
    return render(request, 'production/energy_cost_form.html', context)


def energy_cost_delete(request, pk):
    cost = get_object_or_404(ProcessEnergyCost, pk=pk)
    batch_pk = cost.batch.pk
    if request.method == 'POST':
        batch = cost.batch
        cost.delete()
        BatchCostSummary.calculate_for_batch(batch)
        SourceCostStats.update_stats(batch.material_source)
        messages.success(request, '能耗记录已删除')
    return redirect('production:batch_cost_detail', pk=batch_pk)


def labor_cost_list(request):
    costs = LaborCost.objects.all()

    batch_filter = request.GET.get('batch', '')
    stage_filter = request.GET.get('stage', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    if batch_filter:
        costs = costs.filter(batch__batch_no__icontains=batch_filter)
    if stage_filter:
        costs = costs.filter(stage_type=stage_filter)
    if start_date:
        try:
            s = datetime.strptime(start_date, '%Y-%m-%d').date()
            costs = costs.filter(work_date__gte=s)
        except ValueError:
            pass
    if end_date:
        try:
            e = datetime.strptime(end_date, '%Y-%m-%d').date()
            costs = costs.filter(work_date__lte=e)
        except ValueError:
            pass

    stats = {
        'total_count': costs.count(),
        'total_amount': round(costs.aggregate(s=Sum('total_amount'))['s'] or 0, 2),
        'total_hours': round(costs.aggregate(s=Sum('work_hours'))['s'] or 0, 2),
    }

    context = {
        'costs': costs[:100],
        'stats': stats,
        'batch_filter': batch_filter,
        'stage_filter': stage_filter,
        'start_date': start_date,
        'end_date': end_date,
        'stage_choices': STAGE_CHOICES,
        'batches': RawMaterialBatch.objects.all(),
    }
    return render(request, 'production/labor_cost_list.html', context)


def labor_cost_create(request, batch_id):
    batch = get_object_or_404(RawMaterialBatch, pk=batch_id)

    if request.method == 'POST':
        stage_type = request.POST.get('stage_type', '') or None
        worker_name = request.POST.get('worker_name', '').strip()
        work_type = request.POST.get('work_type', '').strip()
        work_hours = request.POST.get('work_hours', '')
        hourly_rate = request.POST.get('hourly_rate', '0')
        overtime_hours = request.POST.get('overtime_hours', '0')
        overtime_rate = request.POST.get('overtime_rate', '0')
        subsidy = request.POST.get('subsidy', '0')
        deduction = request.POST.get('deduction', '0')
        work_date = request.POST.get('work_date', '')
        operator = request.POST.get('operator', '').strip()
        remark = request.POST.get('remark', '').strip()

        errors = []
        if not worker_name:
            errors.append('请输入工人姓名')
        if not work_type:
            errors.append('请输入工作类型')
        if not work_hours or float(work_hours) <= 0:
            errors.append('请输入有效的工时')
        if not operator:
            errors.append('请输入记录人员')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            try:
                w_date = datetime.strptime(work_date, '%Y-%m-%d').date() if work_date else date.today()
                LaborCost.objects.create(
                    batch=batch,
                    stage_type=stage_type,
                    worker_name=worker_name,
                    work_type=work_type,
                    work_hours=float(work_hours),
                    hourly_rate=float(hourly_rate) if hourly_rate else 0,
                    overtime_hours=float(overtime_hours) if overtime_hours else 0,
                    overtime_rate=float(overtime_rate) if overtime_rate else 0,
                    subsidy=float(subsidy) if subsidy else 0,
                    deduction=float(deduction) if deduction else 0,
                    work_date=w_date,
                    operator=operator,
                    remark=remark,
                )
                BatchCostSummary.calculate_for_batch(batch)
                SourceCostStats.update_stats(batch.material_source)
                messages.success(request, '人工费用记录添加成功')
            except Exception as e:
                messages.error(request, f'添加失败: {str(e)}')
        return redirect('production:batch_cost_detail', pk=batch.pk)

    context = {
        'batch': batch,
        'stage_choices': STAGE_CHOICES,
    }
    return render(request, 'production/labor_cost_form.html', context)


def labor_cost_delete(request, pk):
    cost = get_object_or_404(LaborCost, pk=pk)
    batch_pk = cost.batch.pk
    if request.method == 'POST':
        batch = cost.batch
        cost.delete()
        BatchCostSummary.calculate_for_batch(batch)
        SourceCostStats.update_stats(batch.material_source)
        messages.success(request, '人工费用记录已删除')
    return redirect('production:batch_cost_detail', pk=batch_pk)


def other_cost_list(request):
    costs = OtherCost.objects.all()

    batch_filter = request.GET.get('batch', '')
    category_filter = request.GET.get('category', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    if batch_filter:
        costs = costs.filter(batch__batch_no__icontains=batch_filter)
    if category_filter:
        costs = costs.filter(cost_category=category_filter)
    if start_date:
        try:
            s = datetime.strptime(start_date, '%Y-%m-%d').date()
            costs = costs.filter(cost_date__gte=s)
        except ValueError:
            pass
    if end_date:
        try:
            e = datetime.strptime(end_date, '%Y-%m-%d').date()
            costs = costs.filter(cost_date__lte=e)
        except ValueError:
            pass

    stats = {
        'total_count': costs.count(),
        'total_amount': round(costs.aggregate(s=Sum('amount'))['s'] or 0, 2),
    }

    category_stats = []
    for cat_val, cat_name in OTHER_COST_CATEGORY_CHOICES:
        cat_costs = costs.filter(cost_category=cat_val)
        if cat_costs.exists():
            category_stats.append({
                'category': cat_name,
                'amount': round(cat_costs.aggregate(s=Sum('amount'))['s'] or 0, 2),
                'count': cat_costs.count(),
            })

    context = {
        'costs': costs[:100],
        'stats': stats,
        'category_stats': category_stats,
        'batch_filter': batch_filter,
        'category_filter': category_filter,
        'start_date': start_date,
        'end_date': end_date,
        'cost_category_choices': OTHER_COST_CATEGORY_CHOICES,
        'batches': RawMaterialBatch.objects.all(),
    }
    return render(request, 'production/other_cost_list.html', context)


def other_cost_create(request, batch_id):
    batch = get_object_or_404(RawMaterialBatch, pk=batch_id)

    if request.method == 'POST':
        cost_category = request.POST.get('cost_category', '')
        cost_name = request.POST.get('cost_name', '').strip()
        amount = request.POST.get('amount', '')
        quantity = request.POST.get('quantity', '1')
        unit_price = request.POST.get('unit_price', '0')
        cost_date = request.POST.get('cost_date', '')
        operator = request.POST.get('operator', '').strip()
        invoice_no = request.POST.get('invoice_no', '').strip()
        remark = request.POST.get('remark', '').strip()

        errors = []
        if not cost_category:
            errors.append('请选择费用类别')
        if not cost_name:
            errors.append('请输入费用名称')
        if not amount or float(amount) <= 0:
            errors.append('请输入有效的金额')
        if not operator:
            errors.append('请输入记录人员')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            try:
                c_date = datetime.strptime(cost_date, '%Y-%m-%d').date() if cost_date else date.today()
                OtherCost.objects.create(
                    batch=batch,
                    cost_category=cost_category,
                    cost_name=cost_name,
                    amount=float(amount),
                    quantity=float(quantity) if quantity else 1,
                    unit_price=float(unit_price) if unit_price else 0,
                    cost_date=c_date,
                    operator=operator,
                    invoice_no=invoice_no,
                    remark=remark,
                )
                BatchCostSummary.calculate_for_batch(batch)
                SourceCostStats.update_stats(batch.material_source)
                messages.success(request, '其他费用记录添加成功')
            except Exception as e:
                messages.error(request, f'添加失败: {str(e)}')
        return redirect('production:batch_cost_detail', pk=batch.pk)

    context = {
        'batch': batch,
        'cost_category_choices': OTHER_COST_CATEGORY_CHOICES,
    }
    return render(request, 'production/other_cost_form.html', context)


def other_cost_delete(request, pk):
    cost = get_object_or_404(OtherCost, pk=pk)
    batch_pk = cost.batch.pk
    if request.method == 'POST':
        batch = cost.batch
        cost.delete()
        BatchCostSummary.calculate_for_batch(batch)
        SourceCostStats.update_stats(batch.material_source)
        messages.success(request, '其他费用记录已删除')
    return redirect('production:batch_cost_detail', pk=batch_pk)


def product_sale_create(request, batch_id):
    batch = get_object_or_404(RawMaterialBatch, pk=batch_id)

    try:
        sale = batch.product_sale
        editing = True
    except ProductSale.DoesNotExist:
        sale = None
        editing = False

    if request.method == 'POST':
        sale_quantity = request.POST.get('sale_quantity', '0')
        unit_price = request.POST.get('unit_price', '0')
        customer_name = request.POST.get('customer_name', '').strip()
        sale_date = request.POST.get('sale_date', '')
        discount = request.POST.get('discount', '0')
        shipping_fee = request.POST.get('shipping_fee', '0')
        other_income = request.POST.get('other_income', '0')
        sale_status = request.POST.get('sale_status', 'pending')
        operator = request.POST.get('operator', '').strip()
        remark = request.POST.get('remark', '').strip()

        errors = []
        if not operator:
            errors.append('请输入录入人员')

        try:
            sale_quantity = float(sale_quantity)
            if sale_quantity < 0:
                errors.append('销售数量不能为负数')
        except (ValueError, TypeError):
            errors.append('请输入有效的销售数量')

        try:
            unit_price = float(unit_price)
            if unit_price < 0:
                errors.append('销售单价不能为负数')
        except (ValueError, TypeError):
            errors.append('请输入有效的销售单价')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            try:
                s_date = None
                if sale_date:
                    s_date = datetime.strptime(sale_date, '%Y-%m-%d').date()

                if editing:
                    sale.sale_quantity = sale_quantity
                    sale.unit_price = unit_price
                    sale.customer_name = customer_name
                    sale.sale_date = s_date
                    sale.discount = float(discount) if discount else 0
                    sale.shipping_fee = float(shipping_fee) if shipping_fee else 0
                    sale.other_income = float(other_income) if other_income else 0
                    sale.sale_status = sale_status
                    sale.operator = operator
                    sale.remark = remark
                    sale.save()
                    BatchCostSummary.calculate_for_batch(batch)
                    SourceCostStats.update_stats(batch.material_source)
                    messages.success(request, '销售记录更新成功')
                else:
                    ProductSale.objects.create(
                        batch=batch,
                        sale_quantity=sale_quantity,
                        unit_price=unit_price,
                        customer_name=customer_name,
                        sale_date=s_date,
                        discount=float(discount) if discount else 0,
                        shipping_fee=float(shipping_fee) if shipping_fee else 0,
                        other_income=float(other_income) if other_income else 0,
                        sale_status=sale_status,
                        operator=operator,
                        remark=remark,
                    )
                    BatchCostSummary.calculate_for_batch(batch)
                    SourceCostStats.update_stats(batch.material_source)
                    messages.success(request, '销售记录添加成功')
            except Exception as e:
                messages.error(request, f'保存失败: {str(e)}')
        return redirect('production:batch_cost_detail', pk=batch.pk)

    context = {
        'batch': batch,
        'sale': sale,
        'editing': editing,
        'sale_status_choices': SALE_STATUS_CHOICES,
    }
    return render(request, 'production/product_sale_form.html', context)


def batch_cost_detail(request, pk):
    batch = get_object_or_404(RawMaterialBatch, pk=pk)

    energy_costs = batch.energy_costs.all().order_by('-record_date')
    labor_costs = batch.labor_costs.all().order_by('-work_date')
    other_costs = batch.other_costs.all().order_by('-cost_date')

    try:
        sale = batch.product_sale
    except ProductSale.DoesNotExist:
        sale = None

    try:
        cost_summary = batch.cost_summary
    except BatchCostSummary.DoesNotExist:
        cost_summary = None

    try:
        crystallization = batch.crystallizationresult
    except CrystallizationResult.DoesNotExist:
        crystallization = None

    energy_by_stage = {}
    for cost in energy_costs:
        key = cost.stage_type
        if key not in energy_by_stage:
            energy_by_stage[key] = {'amount': 0, 'count': 0, 'name': cost.get_stage_type_display()}
        energy_by_stage[key]['amount'] += cost.total_amount
        energy_by_stage[key]['count'] += 1

    other_by_category = {}
    for cost in other_costs:
        key = cost.cost_category
        if key not in other_by_category:
            other_by_category[key] = {'amount': 0, 'count': 0, 'name': cost.get_cost_category_display()}
        other_by_category[key]['amount'] += cost.amount
        other_by_category[key]['count'] += 1

    total_energy = sum(c.total_amount for c in energy_costs)
    total_labor = sum(c.total_amount for c in labor_costs)
    total_other = sum(c.amount for c in other_costs)

    material_cost = 0
    for usage in batch.batch_materials.all():
        if usage.outbound and usage.outbound.inbound_ref:
            material_cost += usage.actual_quantity * usage.outbound.inbound_ref.unit_price

    loss_cost = 0
    for usage in batch.batch_materials.all():
        if usage.outbound and usage.outbound.inbound_ref:
            loss_records = MaterialLoss.objects.filter(
                material=usage.material,
                inbound_ref=usage.outbound.inbound_ref
            )
            for loss in loss_records:
                loss_cost += loss.quantity * usage.outbound.inbound_ref.unit_price

    abnormal_count = AbnormalDisposal.objects.filter(batch=batch).count()

    context = {
        'batch': batch,
        'energy_costs': energy_costs,
        'labor_costs': labor_costs,
        'other_costs': other_costs,
        'sale': sale,
        'cost_summary': cost_summary,
        'crystallization': crystallization,
        'energy_by_stage': list(energy_by_stage.values()),
        'other_by_category': list(other_by_category.values()),
        'total_energy': round(total_energy, 2),
        'total_labor': round(total_labor, 2),
        'total_other': round(total_other, 2),
        'total_material': round(material_cost, 2),
        'total_loss': round(loss_cost, 2),
        'total_cost': round(material_cost + total_energy + total_labor + total_other + loss_cost, 2),
        'abnormal_count': abnormal_count,
        'stage_choices': STAGE_CHOICES,
        'energy_type_choices': ENERGY_TYPE_CHOICES,
        'cost_category_choices': OTHER_COST_CATEGORY_CHOICES,
        'sale_status_choices': SALE_STATUS_CHOICES,
    }
    return render(request, 'production/batch_cost_detail.html', context)


def cost_recalculate(request, pk):
    batch = get_object_or_404(RawMaterialBatch, pk=pk)
    if request.method == 'POST':
        try:
            BatchCostSummary.calculate_for_batch(batch)
            messages.success(request, f'批次 {batch.batch_no} 成本已重新核算')
        except Exception as e:
            messages.error(request, f'核算失败: {str(e)}')
    return redirect('production:batch_cost_detail', pk=pk)


def cost_recalculate_all(request):
    if request.method == 'POST':
        try:
            batches = RawMaterialBatch.objects.all()
            count = 0
            for batch in batches:
                BatchCostSummary.calculate_for_batch(batch)
                count += 1
            SourceCostStats.update_stats()
            messages.success(request, f'已完成 {count} 个批次的成本核算')
        except Exception as e:
            messages.error(request, f'核算失败: {str(e)}')
    return redirect('production:cost_dashboard')


def cost_comparison(request):
    batches = RawMaterialBatch.objects.all()
    selected_batches = request.GET.getlist('batches', [])

    comparison_data = []
    if selected_batches:
        for batch_pk in selected_batches:
            batch = RawMaterialBatch.objects.filter(pk=batch_pk).first()
            if not batch:
                continue

            try:
                cost_summary = batch.cost_summary
            except BatchCostSummary.DoesNotExist:
                cost_summary = None

            try:
                crystal = batch.crystallizationresult
                rate = crystal.get_crystallization_rate()
                purity = crystal.crystal_purity
            except CrystallizationResult.DoesNotExist:
                rate = None
                purity = None

            abnormal_count = batch.abnormaldisposal_set.count()

            comparison_data.append({
                'batch': batch,
                'cost_summary': cost_summary,
                'rate': rate,
                'purity': purity,
                'abnormal_count': abnormal_count,
            })

    chart_data = {
        'labels': [d['batch'].batch_no for d in comparison_data],
        'material_costs': [d['cost_summary'].material_cost if d['cost_summary'] else 0 for d in comparison_data],
        'energy_costs': [d['cost_summary'].energy_cost if d['cost_summary'] else 0 for d in comparison_data],
        'labor_costs': [d['cost_summary'].labor_cost if d['cost_summary'] else 0 for d in comparison_data],
        'other_costs': [d['cost_summary'].other_cost if d['cost_summary'] else 0 for d in comparison_data],
        'loss_costs': [d['cost_summary'].loss_cost if d['cost_summary'] else 0 for d in comparison_data],
        'total_costs': [d['cost_summary'].total_cost if d['cost_summary'] else 0 for d in comparison_data],
        'unit_costs': [d['cost_summary'].unit_cost if d['cost_summary'] else 0 for d in comparison_data],
        'revenues': [d['cost_summary'].revenue if d['cost_summary'] else 0 for d in comparison_data],
        'profits': [d['cost_summary'].profit if d['cost_summary'] else 0 for d in comparison_data],
        'profit_margins': [d['cost_summary'].profit_margin if d['cost_summary'] else 0 for d in comparison_data],
        'rates': [d['rate'] or 0 for d in comparison_data],
        'purities': [d['purity'] or 0 for d in comparison_data],
        'abnormal_counts': [d['abnormal_count'] for d in comparison_data],
    }

    context = {
        'batches': batches,
        'selected_batches': [int(b) for b in selected_batches],
        'comparison_data': comparison_data,
        'chart_data': chart_data,
    }
    return render(request, 'production/cost_comparison.html', context)


def benefit_ranking(request):
    SourceCostStats.update_stats()

    summaries = BatchCostSummary.objects.all()

    source_filter = request.GET.get('source', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    sort_by = request.GET.get('sort', 'profit_margin')

    filtered_batches = RawMaterialBatch.objects.all()
    if source_filter:
        filtered_batches = filtered_batches.filter(material_source__icontains=source_filter)
    if start_date:
        try:
            s = datetime.strptime(start_date, '%Y-%m-%d').date()
            filtered_batches = filtered_batches.filter(start_date__gte=s)
        except ValueError:
            pass
    if end_date:
        try:
            e = datetime.strptime(end_date, '%Y-%m-%d').date()
            filtered_batches = filtered_batches.filter(start_date__lte=e)
        except ValueError:
            pass

    summaries = BatchCostSummary.objects.filter(batch__in=filtered_batches)

    if sort_by == 'profit':
        summaries = summaries.order_by('-profit')
    elif sort_by == 'profit_margin':
        summaries = summaries.order_by('-profit_margin')
    elif sort_by == 'total_cost':
        summaries = summaries.order_by('total_cost')
    elif sort_by == 'unit_cost':
        summaries = summaries.order_by('unit_cost')
    else:
        summaries = summaries.order_by('-profit_margin')

    source_stats = SourceCostStats.objects.all()
    if source_filter:
        source_stats = source_stats.filter(material_source__icontains=source_filter)

    batch_ranking = []
    for idx, s in enumerate(summaries):
        try:
            crystal = s.batch.crystallizationresult
            rate = crystal.get_crystallization_rate()
            purity = crystal.crystal_purity
        except CrystallizationResult.DoesNotExist:
            rate = None
            purity = None

        abnormal_count = s.batch.abnormaldisposal_set.count()

        batch_ranking.append({
            'rank': idx + 1,
            'summary': s,
            'rate': rate,
            'purity': purity,
            'abnormal_count': abnormal_count,
        })

    context = {
        'batch_ranking': batch_ranking,
        'source_stats': source_stats,
        'source_filter': source_filter,
        'start_date': start_date,
        'end_date': end_date,
        'sort_by': sort_by,
        'sources': RawMaterialBatch.objects.values_list('material_source', flat=True).distinct(),
    }
    return render(request, 'production/benefit_ranking.html', context)


def loss_warning_list(request):
    warnings = LossWarning.objects.all()

    level_filter = request.GET.get('level', '')
    status_filter = request.GET.get('status', '')
    batch_filter = request.GET.get('batch', '')

    if level_filter:
        warnings = warnings.filter(warning_level=level_filter)
    if status_filter:
        warnings = warnings.filter(warning_status=status_filter)
    if batch_filter:
        warnings = warnings.filter(batch__batch_no__icontains=batch_filter)

    stats = {
        'total': warnings.count(),
        'active': LossWarning.objects.filter(warning_status='active').count(),
        'acknowledged': LossWarning.objects.filter(warning_status='acknowledged').count(),
        'resolved': LossWarning.objects.filter(warning_status='resolved').count(),
        'severe': LossWarning.objects.filter(warning_level='severe', warning_status__in=['active', 'acknowledged']).count(),
        'moderate': LossWarning.objects.filter(warning_level='moderate', warning_status__in=['active', 'acknowledged']).count(),
        'mild': LossWarning.objects.filter(warning_level='mild', warning_status__in=['active', 'acknowledged']).count(),
    }

    context = {
        'warnings': warnings[:50],
        'stats': stats,
        'level_filter': level_filter,
        'status_filter': status_filter,
        'batch_filter': batch_filter,
        'warning_level_choices': LOSS_WARNING_LEVEL_CHOICES,
        'alert_status_choices': ALERT_STATUS_CHOICES,
    }
    return render(request, 'production/loss_warning_list.html', context)


def loss_warning_detail(request, pk):
    warning = get_object_or_404(LossWarning, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action', '')
        handler = request.POST.get('handler', '').strip()
        notes = request.POST.get('handle_notes', '').strip()

        if action == 'acknowledge':
            warning.warning_status = 'acknowledged'
            warning.acknowledged_at = timezone.now()
            warning.acknowledged_by = handler or '系统管理员'
            warning.handle_notes = notes
            warning.save()
            messages.success(request, '预警已确认')
        elif action == 'resolve':
            warning.warning_status = 'resolved'
            warning.resolved_at = timezone.now()
            warning.resolved_by = handler or '系统管理员'
            warning.handle_notes = notes
            warning.save()
            messages.success(request, '预警已解决')
        elif action == 'close':
            warning.warning_status = 'closed'
            warning.resolved_at = timezone.now()
            warning.resolved_by = handler or '系统管理员'
            warning.handle_notes = notes
            warning.save()
            messages.success(request, '预警已关闭')

        return redirect('production:loss_warning_detail', pk=pk)

    context = {
        'warning': warning,
    }
    return render(request, 'production/loss_warning_detail.html', context)


def source_cost_stats(request):
    SourceCostStats.update_stats()

    stats = SourceCostStats.objects.all()

    source_filter = request.GET.get('source', '')
    level_filter = request.GET.get('level', '')

    if source_filter:
        stats = stats.filter(material_source__icontains=source_filter)
    if level_filter:
        stats = stats.filter(benefit_level=level_filter)

    chart_data = {
        'sources': [s.material_source for s in stats],
        'avg_total_costs': [s.avg_total_cost or 0 for s in stats],
        'avg_profits': [s.avg_profit or 0 for s in stats],
        'avg_profit_margins': [s.avg_profit_margin or 0 for s in stats],
        'benefit_scores': [s.benefit_score or 0 for s in stats],
        'loss_rates': [s.loss_rate for s in stats],
        'avg_crystallization_rates': [s.avg_crystallization_rate or 0 for s in stats],
        'avg_crystallization_purities': [s.avg_crystallization_purity or 0 for s in stats],
        'abnormal_counts': [s.abnormal_count or 0 for s in stats],
        'avg_material_costs': [s.avg_material_cost or 0 for s in stats],
        'avg_energy_costs': [s.avg_energy_cost or 0 for s in stats],
        'avg_labor_costs': [s.avg_labor_cost or 0 for s in stats],
        'avg_other_costs': [s.avg_other_cost or 0 for s in stats],
        'avg_loss_costs': [s.avg_loss_cost or 0 for s in stats],
    }

    context = {
        'stats': stats,
        'chart_data': chart_data,
        'source_filter': source_filter,
        'level_filter': level_filter,
    }
    return render(request, 'production/source_cost_stats.html', context)
