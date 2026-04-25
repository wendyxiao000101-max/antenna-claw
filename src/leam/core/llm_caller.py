from typing import List, Optional
import time

import openai

from ..config import ensure_openai_api_key
from ..utils.constants import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT
from ..utils.image_utils import encode_images
from ..utils.file_io import process_text_files


class LLMCaller:
    def __init__(
        self,
        default_model: str = DEFAULT_MODEL,
        reasoning_effort: Optional[str] = DEFAULT_REASONING_EFFORT,
        timeout: int = 120,
        max_retries: int = 3,
    ):
        """
        Initialize the LLM caller with a client and defaults.
        """
        api_key = ensure_openai_api_key()
        self.client = openai.OpenAI(api_key=api_key)
        self.default_model = default_model
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self.max_retries = max_retries

    def _build_content(
        self,
        prompt_text: str,
        description: Optional[str],
        image_paths: Optional[List[str]],
    ) -> List[dict]:
        """
        Build the content payload for the API call.
        """
        content: List[dict] = [{"type": "text", "text": prompt_text}]

        if description:
            content.append({"type": "text", "text": description})

        if image_paths:
            content.extend(encode_images(image_paths))

        return content

    def call_llm(
        self,
        prompt_files: List[str],
        model: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        description: Optional[str] = None,
        json_schema_hint: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Optional[str]:
        """
        Call the LLM with the given prompts and inputs.
        """
        prompt = process_text_files(prompt_files)
        if json_schema_hint:
            prompt = (
                f"{prompt}\n\n"
                "You must return valid JSON that follows this schema. "
                "Respond with JSON only, no prose.\n"
                f"{json_schema_hint}"
            )

        content = self._build_content(prompt, description, image_paths)
        messages = [{"role": "user", "content": content}]

        effort = (
            reasoning_effort
            if reasoning_effort is not None
            else self.reasoning_effort
        )

        completion_args = {
            "model": model or self.default_model,
            "messages": messages,
            "timeout": self.timeout,
        }
        if effort:
            completion_args["reasoning_effort"] = effort

        last_exc: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**completion_args)
                return response.choices[0].message.content

            except Exception as exc:
                last_exc = exc
                print(
                    f"Failed to call LLM "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )

                if attempt < self.max_retries:
                    time.sleep(2 * attempt)

        print(f"LLM call failed after {self.max_retries} attempts: {last_exc}")
        return None