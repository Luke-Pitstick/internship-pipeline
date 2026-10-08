"""Structured JSON contracts for the three supported general LLM APIs."""

from typing import Any

GENERAL_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/responses",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}


def request_headers(endpoint: str, key: str) -> dict[str, str]:
    if endpoint == GENERAL_ENDPOINTS["anthropic"]:
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"}


def structured_payload(
    endpoint: str,
    model: str,
    max_output_tokens: int,
    instructions: str,
    content: str,
    name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    if endpoint == GENERAL_ENDPOINTS["openai"]:
        return {
            "model": model,
            "store": False,
            "max_output_tokens": max_output_tokens,
            "instructions": instructions,
            "input": content,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
    if endpoint == GENERAL_ENDPOINTS["anthropic"]:
        return {
            "model": model,
            "max_tokens": max_output_tokens,
            "system": instructions,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
    if endpoint == GENERAL_ENDPOINTS["openrouter"]:
        return {
            "model": model,
            "max_tokens": max_output_tokens,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": name,
                    "strict": True,
                    "schema": schema,
                },
            },
            "provider": {"require_parameters": True, "allow_fallbacks": False},
        }
    raise ValueError("Unsupported general LLM endpoint")


def response_text(endpoint: str, body: dict[str, Any]) -> str:
    """Accept one complete assistant response; refusals and truncation fail closed."""
    if endpoint == GENERAL_ENDPOINTS["openai"]:
        messages = [item for item in body["output"] if item["type"] == "message"]
        if body.get("status") != "completed" or len(messages) != 1:
            raise ValueError("Incomplete response")
        message = messages[0]
        content = message["content"]
        if (
            message.get("status") != "completed"
            or len(content) != 1
            or content[0]["type"] != "output_text"
        ):
            raise ValueError("Refusal or missing text")
        text = content[0]["text"]
    elif endpoint == GENERAL_ENDPOINTS["anthropic"]:
        content = body["content"]
        if (
            body.get("type") != "message"
            or body.get("role") != "assistant"
            or body.get("stop_reason") != "end_turn"
            or len(content) != 1
            or content[0]["type"] != "text"
        ):
            raise ValueError("Refusal or incomplete response")
        text = content[0]["text"]
    elif endpoint == GENERAL_ENDPOINTS["openrouter"]:
        choices = body["choices"]
        if len(choices) != 1 or choices[0].get("finish_reason") != "stop" or body.get("error"):
            raise ValueError("Incomplete response")
        message = choices[0]["message"]
        if (
            message.get("role") != "assistant"
            or message.get("refusal")
            or message.get("tool_calls")
        ):
            raise ValueError("Refusal or missing text")
        text = message["content"]
    else:
        raise ValueError("Unsupported general LLM endpoint")
    if not isinstance(text, str) or not text:
        raise ValueError("Missing text")
    return text
