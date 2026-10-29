"""DeepSeek-only batch policy. Legacy jobs without a snapshot remain at three."""
BATCH_SIZES = (3, 5, 10, 15)


def validate_size(size):
    if type(size) is not int or size not in BATCH_SIZES:
        raise ValueError('Batch DeepSeek phải là 3, 5, 10 hoặc 15 dòng')
    return size


def job_size(provider, config):
    return validate_size(config.get('deepseek_batch_size', 3)) if provider == 'deepseek' else 3


def output_limit(lines, baseline):
    if len(lines) <= 3: return baseline
    # Include JSON IDs/envelope and allow expansion in translated text. A hard
    # finite cap still applies; length-finished replies remain invalid, never retried.
    expanded = 256 + sum(2 * (len(r['source'].encode('utf8')) + len(r['id'].encode('utf8'))) + 64 for r in lines)
    return min(8192, max(baseline, expanded))
