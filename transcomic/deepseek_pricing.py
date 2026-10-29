"""Editable reference prices, not billing or a translation scheduling policy."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from .deepseek_models import MODEL, PRO_MODEL, MODEL_NAMES, validate_model

VN = timezone(timedelta(hours=7))
DEFAULT = dict(source='https://api-docs.deepseek.com/quick_start/pricing/', verified='2026-10-26',
               peak=dict(input='0.30', cached='0.006', output='1.20'),
               offpeak=dict(input='0.15', cached='0.003', output='0.60'),
               holiday_years=[], holidays=[])
PRO_DEFAULT = {**deepcopy(DEFAULT), 'peak':dict(input='1.32', cached='0.044', output='3.96'),
               'offpeak':dict(input='0.66', cached='0.022', output='1.98')}


def validate(config):
    if not isinstance(config, dict): raise ValueError('Cấu hình giá phải là JSON object')
    try:
        datetime.fromisoformat(config['verified'])
        if not config['source'].startswith('https://'): raise ValueError()
        for period in ('peak', 'offpeak'):
            for key in ('input', 'cached', 'output'):
                value = Decimal(str(config[period][key]))
                if not value.is_finite() or value < 0: raise ValueError()
            if Decimal(str(config[period]['cached'])) > Decimal(str(config[period]['input'])): raise ValueError()
        if any(type(y) is not int for y in config['holiday_years']): raise ValueError()
        for date in config['holidays']: datetime.strptime(date, '%Y-%m-%d')
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise ValueError('Giá, nguồn HTTPS, ngày xác minh hoặc lịch ngày lễ không hợp lệ') from None
    return deepcopy(config)


def validate_catalog(config):
    if not isinstance(config, dict) or set(config.get('models', {})) != set(MODEL_NAMES):
        raise ValueError('Cần cấu hình giá cho cả deepseek-flash và deepseek-v4-pro')
    return {'models':{model:validate(config['models'][model]) for model in MODEL_NAMES}}


def load_catalog(store=None):
    raw = store.setting('deepseek_pricing', '') if store else ''
    config = json.loads(raw) if raw else deepcopy(DEFAULT)
    if isinstance(config, dict) and 'models' in config: return validate_catalog(config)
    # Old flat settings and old per-attempt snapshots remain Flash prices.
    return {'models':{MODEL:validate(config), PRO_MODEL:deepcopy(PRO_DEFAULT)}}


def load(store=None, model=MODEL):
    return load_catalog(store)['models'][validate_model(model)]


def period(config, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('Time must have a timezone')
    local = now.astimezone(VN)
    in_window = local.weekday() < 5 and (8 <= local.hour < 11 or 13 <= local.hour < 17)
    if not in_window: return 'offpeak', 'Giờ thấp điểm'
    if local.year not in config['holiday_years']:
        return 'peak', 'Chưa xác minh ngày lễ · ước tính giá cao điểm'
    if local.date().isoformat() in config['holidays']: return 'offpeak', 'Giờ thấp điểm'
    return 'peak', 'Giờ cao điểm'


def estimate(usage, rates):
    """Cache hits are part of prompt_tokens, never an additional token charge."""
    if not isinstance(usage, dict): return None
    prompt, output = usage.get('prompt_tokens'), usage.get('completion_tokens')
    if type(prompt) is not int or type(output) is not int or min(prompt, output) < 0: return None
    details = usage.get('prompt_tokens_details')
    if not isinstance(details, dict): details = {}
    hit = usage.get('prompt_cache_hit_tokens', details.get('cached_tokens'))
    miss = usage.get('prompt_cache_miss_tokens')
    if hit is None and type(miss) is int: hit = prompt - miss
    conservative = hit is None
    hit = 0 if hit is None else hit
    if type(hit) is not int or not 0 <= hit <= prompt: return None
    if miss is not None and (type(miss) is not int or miss != prompt-hit): return None
    cost = (Decimal(prompt-hit)*Decimal(str(rates['input'])) + Decimal(hit)*Decimal(str(rates['cached']))
            + Decimal(output)*Decimal(str(rates['output']))) / Decimal(1000000)
    return dict(usd=str(cost), input_tokens=prompt, cached_tokens=hit, output_tokens=output,
                conservative=conservative)


def label(config, now=None, model=MODEL):
    key, status = period(config, now)
    rates = config[key]
    return f"{MODEL_NAMES[validate_model(model)]} · {status} · Input ${rates['input']}/M · Cache ${rates['cached']}/M · Output ${rates['output']}/M"
