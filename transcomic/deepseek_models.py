"""DeepSeek model allowlist; Flash remains the legacy/default model."""
MODEL = 'deepseek-flash'
PRO_MODEL = 'deepseek-v4-pro'
MODELS = ((MODEL, 'DeepSeek Flash'), (PRO_MODEL, 'DeepSeek V4 Pro'))
MODEL_NAMES = dict(MODELS)


def validate_model(model):
    if model not in MODEL_NAMES: raise ValueError('Chọn DeepSeek Flash hoặc DeepSeek V4 Pro')
    return model
