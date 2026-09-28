from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

ANALYSIS_AGENT_SYSTEM_PROMPT = """You are InsightOS, a rigorous data analysis assistant.

Core rules you must follow in every response:
1. NEVER invent or hallucinate numbers. Every numeric claim must be backed by an evidence ID.
2. Reference evidence by ID (e.g. "Evidence abc12345 shows..."), not by restating the raw data.
3. Use associational language only: "is associated with", "corresponds with", "accounts for".
   NEVER use causal language: "caused", "led to", "because", "due to", "driven by", "resulted in".
4. Disclose all assumptions and data caveats upfront.
5. If data is insufficient to answer a question, say so clearly.
6. When uncertain, use hedging language: "suggests", "appears to", "is consistent with".
7. Distinguish between statistical significance and practical significance.
8. Never state a conclusion that is not supported by the evidence records provided to you.
"""


class LLMClient:
    """
    LLM abstraction supporting OpenAI and Anthropic.
    Provider is selected via LLM_PROVIDER env var (default: openai).
    """

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self.strong_model = os.getenv("STRONG_MODEL", "gpt-4o")
        self.fast_model = os.getenv("FAST_MODEL", "gpt-4o-mini")

        if self.provider == "openai":
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        elif self.provider == "anthropic":
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider!r}. Use 'openai' or 'anthropic'.")

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """
        Send a chat completion request and return the text response.
        Injects the ANALYSIS_AGENT_SYSTEM_PROMPT if no system message is present.
        """
        resolved_model = model or self.fast_model

        # Inject system prompt if not present
        has_system = any(m.get("role") == "system" for m in messages)
        if not has_system:
            messages = [
                {"role": "system", "content": ANALYSIS_AGENT_SYSTEM_PROMPT}
            ] + list(messages)

        if self.provider == "openai":
            return await self._openai_completion(
                messages, resolved_model, response_format, temperature, max_tokens
            )
        elif self.provider == "anthropic":
            return await self._anthropic_completion(
                messages, resolved_model, temperature, max_tokens
            )

        raise ValueError(f"Unsupported provider: {self.provider}")

    async def _openai_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        response_format: Optional[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        response = await self._client.chat.completions.create(**kwargs)  # type: ignore[attr-defined]
        return response.choices[0].message.content or ""

    async def _anthropic_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        # Anthropic separates system from human/assistant messages
        system_content = ""
        filtered_messages = []
        for m in messages:
            if m["role"] == "system":
                system_content = m["content"]
            else:
                filtered_messages.append(m)

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": filtered_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_content:
            kwargs["system"] = system_content

        response = await self._client.messages.create(**kwargs)  # type: ignore[attr-defined]
        return response.content[0].text if response.content else ""


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
