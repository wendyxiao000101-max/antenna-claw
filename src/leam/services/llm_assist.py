"""Small helper for one-shot inline system-prompt LLM calls."""

from typing import Optional

import openai

from ..config import ensure_openai_api_key
from ..utils.constants import DEFAULT_MODEL


def quick_llm(system_prompt: str, user_message: str, timeout: int = 60) -> Optional[str]:
    try:
        client = openai.OpenAI(api_key=ensure_openai_api_key())
        resp = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            timeout=timeout,
        )
        return resp.choices[0].message.content
    except Exception as exc:
        print(f"  [LLM] 调用失败: {exc}")
        return None

