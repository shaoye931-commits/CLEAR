from __future__ import annotations

import re
from typing import Dict, List, Tuple

import requests

from .config import ExperimentConfig, DeepSeekConfig, OpenRouterConfig, load_environment


CODE_BLOCK_RE = re.compile(r"```(?:python)?\n([\s\S]*?)\n```", re.IGNORECASE)


def _extract_code_from_text(text: str) -> Tuple[str, str]:
    """
    Extract the first fenced python code block from a text. If none is found,
    return the full text as code and rationale empty.
    Returns (code, rationale_text)
    """
    match = CODE_BLOCK_RE.search(text)
    if match:
        code = match.group(1).strip()
        rationale = text[: match.start()].strip()
        return code, rationale
    return text.strip(), ""


def _extract_code_from_cot_response(text: str) -> Tuple[str, str]:
    """
    从带思维链的响应中提取代码。
    查找 "**Python Code:**" 或 "**Corrected Python Code:**" 后面的代码块。
    Returns (code, rationale_text)
    """
    # 尝试匹配 "**Python Code:**" 或 "**Corrected Python Code:**" 后面的代码块
    pattern = r"(?:\*\*Python Code:\*\*|\*\*Corrected Python Code:\*\*)[\s\S]*?```(?:python)?\n([\s\S]*?)\n```"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        code = match.group(1).strip()
        rationale = text[: match.start()].strip()
        return code, rationale
    
    # 如果没找到，回退到标准提取
    return _extract_code_from_text(text)


def _extract_multiple_codes_from_response(text: str) -> List[Tuple[str, str]]:
    """
    从多路径探索响应中提取多个代码块。
    查找 "**Code:**" 后面的代码块（可能有多个）。
    Returns list of (code, rationale_text) tuples
    """
    codes = []
    # 匹配所有 "**Code:**" 后面的代码块
    pattern = r"\*\*Code:\*\*[\s\S]*?```(?:python)?\n([\s\S]*?)\n```"
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    
    for i, match in enumerate(matches):
        code = match.group(1).strip()
        # 提取这个代码块之前的内容作为 rationale
        start = match.start()
        if i == 0:
            rationale = text[:start].strip()
        else:
            prev_match = matches[i-1]
            prev_end = prev_match.end()
            rationale = text[prev_end:start].strip()
        codes.append((code, rationale))
    
    # 如果没找到，尝试提取所有代码块
    if not codes:
        matches = list(CODE_BLOCK_RE.finditer(text))
        for i, match in enumerate(matches):
            code = match.group(1).strip()
            if i == 0:
                rationale = text[:match.start()].strip()
            else:
                prev_match = matches[i-1]
                rationale = text[prev_match.end():match.start()].strip()
            codes.append((code, rationale))
    
    return codes if codes else [(text.strip(), "")]


def _call_siliconflow(
    messages: List[Dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    model_name: str,
) -> Dict[str, str]:
    """
    调用硅基流动（SiliconFlow）Chat Completions API（OpenAI 兼容格式）。
    Returns JSON dict (already parsed).
    """
    load_environment()
    sf_cfg = DeepSeekConfig.from_env()

    url = sf_cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": float(max(0.0, min(1.0, temperature))),
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {sf_cfg.api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=payload, timeout=300)
    response.raise_for_status()
    data = response.json()
    if not data.get("choices"):
        raise RuntimeError(f"SiliconFlow response missing choices: {data}")
    return data


def _call_openrouter(
    messages: List[Dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    model_name: str,
) -> Dict[str, str]:
    """
    调用 OpenRouter Chat Completions API（OpenAI 兼容格式）。
    Returns JSON dict (already parsed).
    """
    load_environment()
    or_cfg = OpenRouterConfig.from_env()

    url = or_cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": float(max(0.0, min(1.0, temperature))),
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {or_cfg.api_key}",
        "Content-Type": "application/json",
        # 这两个 header 是 OpenRouter 推荐的，但不是强制的
        # 可以按需在 .env 里配置也可以直接改这里
        # "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", ""),
        # "X-Title": os.getenv("OPENROUTER_X_TITLE", "TD-IR-Experiment"),
    }

    response = requests.post(url, headers=headers, json=payload, timeout=300)
    response.raise_for_status()
    data = response.json()
    if not data.get("choices"):
        raise RuntimeError(f"OpenRouter response missing choices: {data}")
    return data


def _clean_generated_code(content: str, *, use_cot: bool) -> Tuple[str, str]:
    if use_cot:
        code, rationale = _extract_code_from_cot_response(content)
    else:
        code, rationale = _extract_code_from_text(content)
    
    # ========== 强制清洗：提取所有 ```python ... ``` 代码块并合并 ==========
    # 使用 findall 提取所有代码块，然后合并（对于 1-shot，应该包含 Base 和 Pro 两个函数）
    all_code_blocks = re.findall(r'```(?:python)?\s*\n(.*?)```', content, re.DOTALL)
    if all_code_blocks:
        # 合并所有代码块（通常最后一个是最新生成的代码，但为了完整性，合并所有）
        # 如果只有一个代码块，直接使用；如果有多个，合并它们
        if len(all_code_blocks) == 1:
            code = all_code_blocks[0].strip()
        else:
            # 合并所有代码块，去重相同的函数定义
            merged_code = []
            seen_functions = set()
            for block in all_code_blocks:
                block = block.strip()
                if not block:
                    continue
                # 提取函数名，避免重复添加相同的函数
                func_matches = re.findall(r'^def\s+(\w+)\s*\(', block, re.MULTILINE)
                is_new = False
                for func_name in func_matches:
                    if func_name not in seen_functions:
                        is_new = True
                        seen_functions.add(func_name)
                if is_new or not func_matches:
                    merged_code.append(block)
            code = '\n\n'.join(merged_code).strip() if merged_code else all_code_blocks[-1].strip()
    else:
        # 如果没有代码块标记，尝试从纯文本中提取
        code = content.replace("```python", "").replace("```", "").strip()
        code = re.sub(
            r'^(Here is the code|Here\'s the code|Root Cause Analysis|Analysis|Explanation|The issue|The problem|BEGIN CODE|Code):?\s*\n?',
            '',
            code,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    
    code = re.sub(r'```(?:python)?\s*\n?', '', code)
    code = re.sub(r'```\s*$', '', code, flags=re.MULTILINE)
    
    # 提取所有函数定义（确保包含 Base 和 Pro 函数）
    lines = code.split('\n')
    cleaned_lines = []
    code_started = False
    
    for line in lines:
        line_stripped = line.strip()
        if line_stripped.startswith(('def ', 'class ', 'import ', 'from ')):
            code_started = True
        if code_started or line_stripped.startswith('#') or line_stripped == '' or any(
            keyword in line_stripped for keyword in ['def ', 'class ', 'import ', 'from ', 'return ', 'if ', 'for ', 'while ', '=']
        ):
            cleaned_lines.append(line)
    
    code = '\n'.join(cleaned_lines).strip()
    code = re.sub(r'\n\s*\n\s*\n+', '\n\n', code)
    code = code.strip()
    return code, rationale


def generate_code(
    prompt: str,
    *,
    temperature: float = 0,
    max_tokens: int = 2048,
    use_cot: bool = False,
    system_prompt: str = None,
) -> Dict[str, str]:
    """
    Send a prompt to LLM endpoint and extract code from the response.
    
    Args:
        use_cot: If True, use CoT extraction (looks for "**Python Code:**" section)
        system_prompt: Optional system prompt to inject as system role message
    """
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if prompt:
        messages.append({"role": "user", "content": prompt})

    exp_cfg = ExperimentConfig.from_env()

    # 根据配置选择后端
    if exp_cfg.use_openrouter:
        data = _call_openrouter(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model_name=exp_cfg.model_to_test,
        )
    else:
        data = _call_siliconflow(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model_name=exp_cfg.model_to_test,
        )

    content = data["choices"][0]["message"].get("content", "") or ""
    code, rationale = _clean_generated_code(content, use_cot=use_cot)
    return {"code": code, "rationale": rationale, "raw_response": content}


def generate_multiple_codes(
    prompt: str,
    *,
    temperature: float = 0,
    max_tokens: int = 4096,
) -> List[Dict[str, str]]:
    """
    生成多个代码方案（用于多路径探索）。
    Returns a list of dicts with keys: code, rationale, raw_response.
    """
    messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
    exp_cfg = ExperimentConfig.from_env()
    
    # 根据配置选择后端
    if exp_cfg.use_openrouter:
        data = _call_openrouter(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model_name=exp_cfg.model_to_test,
        )
    else:
        data = _call_siliconflow(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model_name=exp_cfg.model_to_test,
        )

    content = data["choices"][0]["message"].get("content", "") or ""
    codes_with_rationale = _extract_multiple_codes_from_response(content)
    
    results = []
    for code, rationale in codes_with_rationale:
        results.append({
            "code": code,
            "rationale": rationale,
            "raw_response": content,
        })
    
    return results


def generate_code_1shot(
    prompt: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    system_prompt: str = None,
) -> Dict[str, str]:
    """
    1-shot代码生成方法：使用包含示例的prompt生成代码。
    
    Args:
        prompt: 包含1-shot示例的完整prompt
        temperature: 采样温度
        max_tokens: 最大token数
        system_prompt: 可选的系统提示词
    
    Returns:
        包含code, rationale, raw_response的字典
    """
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if prompt:
        messages.append({"role": "user", "content": prompt})

    exp_cfg = ExperimentConfig.from_env()

    # 根据配置选择后端
    if exp_cfg.use_openrouter:
        data = _call_openrouter(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model_name=exp_cfg.model_to_test,
        )
    else:
        data = _call_siliconflow(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model_name=exp_cfg.model_to_test,
        )

    content = data["choices"][0]["message"].get("content", "") or ""
    # 1-shot不需要CoT提取，直接提取代码
    code, rationale = _clean_generated_code(content, use_cot=False)
    return {"code": code, "rationale": rationale, "raw_response": content}


