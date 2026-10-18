"""Kira model choices displayed by the desktop editor."""

KIRA_MODELS: tuple[tuple[str, str], ...] = (
    ("Kira 2.5 Flash", "kira-2.5-flash"),
    ("Kira Auto", "kira-auto"),
    ("Kira Mini 1.0", "kira-mini-1.0"),
    ("Qwen3.8 27B", "qwen3.8-27b"),
    ("Qwen3.8 Flash", "qwen3.8-flash"),
    ("Coding MiMo V2.6 Flash", "coding-mimo-v2.6-flash"),
    ("DeepSeek V4.1 Flash", "deepseek-v4.1-flash"),
    ("GLM 5.3 Flash", "glm-5.3-flash"),
    ("MiMo V2.6 Flash", "mimo-v2.6-flash"),
    # Canonical IDs verified against Kira's own /api/v1/models on 2026-10-18.
    # is_free=True is accompanied by nonzero price metadata; no price guarantee.
    ("Beam Free", "beam-free"),
    ("DeepSeek V4.1 Flash Free", "deepseek-v4.1-flash-free"),
    ("MiMo V2.6 Flash Free", "mimo-v2.6-flash-free"),
    ("LongCat 2.5 Preview Free", "longcat-2.5-preview-free"),
)
