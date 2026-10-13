"""Shared public provider presets; private credentials stay in Settings."""
PROVIDERS = [
    {'id': 'compatible', 'name': '自定义 Chat Completions 兼容服务', 'base_url': '', 'model': '', 'hint': '填写准确 API 前缀或完整 Chat Completions 地址，以及服务提供的模型 ID。'},
    {'id': 'bailian', 'name': '阿里云百炼 · 按量付费（北京）', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'qwen-plus', 'hint': '使用北京地域百炼 API Key；其它地域或业务空间请修改服务地址。'},
    {'id': 'bailian-coding', 'name': '阿里云百炼 · Coding Plan', 'base_url': 'https://coding.dashscope.aliyuncs.com/v1', 'model': '', 'hint': '填写订阅支持的准确模型 ID。使用 Coding Plan 专属 API Key，模型需在订阅支持列表中。'},
    {'id': 'bailian-token', 'name': '阿里云百炼 · Token Plan（北京）', 'base_url': 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', 'model': 'qwen3.8-flash', 'hint': '使用 Token Plan 对应地域的密钥及已授权模型；不能混用 Coding Plan 密钥。'},
    {'id': 'deepseek', 'name': 'DeepSeek', 'base_url': 'https://api.deepseek.com', 'model': 'deepseek-chat', 'hint': '使用 DeepSeek API Key 和服务端支持的模型 ID。'},
    {'id': 'openai', 'name': 'OpenAI', 'base_url': 'https://api.openai.com/v1', 'model': '', 'hint': '填写账号可用的准确模型 ID。'},
    {'id': 'ollama', 'name': 'Ollama / 本地服务', 'base_url': 'http://127.0.0.1:11434/v1', 'model': '', 'hint': '填写本地已安装模型 ID，本地服务可不填密钥。'},
]


def model_id_hint(base_url):
    from urllib.parse import urlsplit
    if urlsplit(base_url).hostname == 'token-plan.cn-beijing.maas.aliyuncs.com':
        return '填写 Token Plan 已授权的准确模型 ID，例如 qwen3.8-flash；不能填写“阿里百炼”等服务商名称。'
    return '填写服务已授权的准确模型 ID；不能填写服务商名称。'


def is_model_not_found(response):
    # Interpret only known error codes; never return arbitrary provider text.
    try:
        data=response.json()
        error=data.get('error',{}) if isinstance(data,dict) else {}
        code=error.get('code') if isinstance(error,dict) else None
        return isinstance(code,str) and code.lower() in {'model_not_found','modelnotfound','invalid_model','invalidmodel'}
    except (ValueError,TypeError):
        return False
