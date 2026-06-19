import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'niter_monitor.settings')
django.setup()

from production.models import AlertRule


def init_alert_rules():
    print('正在初始化预警规则...')
    
    rules_data = [
        {
            'rule_name': '浸取温度上限',
            'alert_type': 'temperature',
            'stage_type': 'leaching',
            'max_value': 100.0,
            'alert_level': 'warning',
            'description': '浸取阶段温度超过100°C时触发预警'
        },
        {
            'rule_name': '浸取温度下限',
            'alert_type': 'temperature',
            'stage_type': 'leaching',
            'min_value': 20.0,
            'alert_level': 'warning',
            'description': '浸取阶段温度低于20°C时触发预警'
        },
        {
            'rule_name': '浸取浓度上限',
            'alert_type': 'concentration',
            'stage_type': 'leaching',
            'max_value': 30.0,
            'alert_level': 'warning',
            'description': '浸取阶段浓度超过30%时触发预警'
        },
        {
            'rule_name': '浸取浓度下限',
            'alert_type': 'concentration',
            'stage_type': 'leaching',
            'min_value': 5.0,
            'alert_level': 'warning',
            'description': '浸取阶段浓度低于5%时触发预警'
        },
        {
            'rule_name': '浸取pH值范围',
            'alert_type': 'ph_value',
            'stage_type': 'leaching',
            'min_value': 6.0,
            'max_value': 8.5,
            'alert_level': 'info',
            'description': '浸取阶段pH值超出6-8.5范围时触发预警'
        },
        {
            'rule_name': '过滤温度上限',
            'alert_type': 'temperature',
            'stage_type': 'filtration',
            'max_value': 80.0,
            'alert_level': 'warning',
            'description': '过滤阶段温度超过80°C时触发预警'
        },
        {
            'rule_name': '过滤温度下限',
            'alert_type': 'temperature',
            'stage_type': 'filtration',
            'min_value': 15.0,
            'alert_level': 'warning',
            'description': '过滤阶段温度低于15°C时触发预警'
        },
        {
            'rule_name': '过滤浓度上限',
            'alert_type': 'concentration',
            'stage_type': 'filtration',
            'max_value': 35.0,
            'alert_level': 'warning',
            'description': '过滤阶段浓度超过35%时触发预警'
        },
        {
            'rule_name': '过滤浓度下限',
            'alert_type': 'concentration',
            'stage_type': 'filtration',
            'min_value': 5.0,
            'alert_level': 'warning',
            'description': '过滤阶段浓度低于5%时触发预警'
        },
        {
            'rule_name': '蒸发温度上限',
            'alert_type': 'temperature',
            'stage_type': 'evaporation',
            'max_value': 120.0,
            'alert_level': 'danger',
            'description': '蒸发阶段温度超过120°C时触发危险预警'
        },
        {
            'rule_name': '蒸发温度下限',
            'alert_type': 'temperature',
            'stage_type': 'evaporation',
            'min_value': 60.0,
            'alert_level': 'warning',
            'description': '蒸发阶段温度低于60°C时触发预警'
        },
        {
            'rule_name': '蒸发浓度上限',
            'alert_type': 'concentration',
            'stage_type': 'evaporation',
            'max_value': 60.0,
            'alert_level': 'warning',
            'description': '蒸发阶段浓度超过60%时触发预警'
        },
        {
            'rule_name': '蒸发浓度下限',
            'alert_type': 'concentration',
            'stage_type': 'evaporation',
            'min_value': 20.0,
            'alert_level': 'warning',
            'description': '蒸发阶段浓度低于20%时触发预警'
        },
        {
            'rule_name': '蒸发pH值范围',
            'alert_type': 'ph_value',
            'stage_type': 'evaporation',
            'min_value': 6.0,
            'max_value': 8.0,
            'alert_level': 'info',
            'description': '蒸发阶段pH值超出6-8范围时触发预警'
        },
        {
            'rule_name': '结晶温度上限',
            'alert_type': 'temperature',
            'stage_type': 'crystallization',
            'max_value': 50.0,
            'alert_level': 'warning',
            'description': '结晶阶段温度超过50°C时触发预警'
        },
        {
            'rule_name': '结晶温度下限',
            'alert_type': 'temperature',
            'stage_type': 'crystallization',
            'min_value': 0.0,
            'alert_level': 'warning',
            'description': '结晶阶段温度低于0°C时触发预警'
        },
        {
            'rule_name': '结晶浓度上限',
            'alert_type': 'concentration',
            'stage_type': 'crystallization',
            'max_value': 80.0,
            'alert_level': 'warning',
            'description': '结晶阶段浓度超过80%时触发预警'
        },
        {
            'rule_name': '结晶浓度下限',
            'alert_type': 'concentration',
            'stage_type': 'crystallization',
            'min_value': 30.0,
            'alert_level': 'warning',
            'description': '结晶阶段浓度低于30%时触发预警'
        },
        {
            'rule_name': '结晶率过低',
            'alert_type': 'crystallization_rate',
            'stage_type': None,
            'min_value': 15.0,
            'alert_level': 'danger',
            'description': '结晶率低于15%时触发危险预警'
        },
        {
            'rule_name': '结晶纯度过低',
            'alert_type': 'crystallization_purity',
            'stage_type': None,
            'min_value': 90.0,
            'alert_level': 'warning',
            'description': '结晶纯度低于90%时触发预警'
        },
        {
            'rule_name': '批次异常率过高',
            'alert_type': 'abnormal_rate',
            'stage_type': None,
            'max_value': 20.0,
            'alert_level': 'warning',
            'description': '批次异常率超过20%时触发预警'
        },
    ]
    
    created_count = 0
    updated_count = 0
    
    for rule_data in rules_data:
        rule, created = AlertRule.objects.get_or_create(
            rule_name=rule_data['rule_name'],
            defaults=rule_data
        )
        
        if created:
            created_count += 1
            print(f'  + 创建: {rule.rule_name}')
        else:
            for key, value in rule_data.items():
                if key != 'rule_name':
                    setattr(rule, key, value)
            rule.save()
            updated_count += 1
            print(f'  ~ 更新: {rule.rule_name}')
    
    print(f'\n预警规则初始化完成！')
    print(f'  - 新建规则: {created_count} 条')
    print(f'  - 更新规则: {updated_count} 条')
    print(f'  - 总规则数: {AlertRule.objects.count()} 条')
    print(f'  - 已启用规则: {AlertRule.objects.filter(is_enabled=True).count()} 条')


if __name__ == '__main__':
    init_alert_rules()
