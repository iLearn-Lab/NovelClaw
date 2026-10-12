"""Chat and Responses transports for OpenAI-compatible writing providers."""

from __future__ import annotations

from copy import deepcopy
import json
import re
import time
from typing import Any
from uuid import uuid4

from openai import APIStatusError, BadRequestError, OpenAI

from config import Config


class ModelResponseError(ValueError):
    """The provider replied, but did not return usable text or a valid tool call."""


class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        timeout = getattr(config, "llm_timeout_seconds", 0)
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.api_base_url,
            timeout=None if timeout <= 0 else timeout,
            max_retries=getattr(config, "llm_max_retries", 1),
        )
        self._text_only_models: set[str] = set()

    def close(self) -> None:
        self.client.close()

    def _is_en(self) -> bool:
        return str(getattr(self.config, "language", "auto")).lower().startswith("en")

    def _text(self, zh: str, en: str) -> str:
        return en if self._is_en() else zh

    def _messages(self, messages: list[dict]) -> list[dict]:
        prepared = deepcopy(messages)
        language = str(getattr(self.config, "language", "auto")).lower()
        if language.startswith(("en", "zh")):
            prepared.insert(
                0,
                {
                    "role": "system",
                    "content": "Always respond in English."
                    if language.startswith("en")
                    else "请始终使用中文回答。",
                },
            )
        return prepared

    @staticmethod
    def _responses_input(messages: list[dict]) -> list[dict]:
        items = []
        for message in messages:
            # Preserve reasoning items and native call IDs on subsequent tool turns.
            if message.get("_response_items") is not None:
                items.extend(deepcopy(message["_response_items"]))
            elif message.get("role") == "tool":
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message["tool_call_id"],
                        "output": str(message.get("content") or ""),
                    }
                )
            else:
                if message.get("content") is not None:
                    items.append(
                        {
                            "role": message.get("role", "user"),
                            "content": message["content"],
                        }
                    )
                for call in message.get("tool_calls") or []:
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": call["id"],
                            "name": call["function"]["name"],
                            "arguments": call["function"]["arguments"],
                        }
                    )
        return items

    @staticmethod
    def _plain_history(messages: list[dict]) -> list[dict]:
        """Text-only providers cannot accept native tool messages in the history."""
        result = []
        for message in messages:
            content = str(message.get("content") or "")
            if message.get("tool_calls"):
                content += "\nTool requests: " + json.dumps(
                    message["tool_calls"], ensure_ascii=False
                )
            role = message.get("role", "user")
            if role == "tool":
                role = "user"
                content = f"Tool result ({message.get('tool_call_id', '')}): {content}"
            if content:
                result.append({"role": role, "content": content})
        return result

    def _request(self, messages, *, model, temperature, max_tokens, tools=None):
        wire = getattr(self.config, "wire_api", "chat")
        payload: dict[str, Any] = {"model": model, "temperature": temperature}
        if wire == "responses":
            create = self.client.responses.create
            payload.update(
                input=self._responses_input(messages),
                max_output_tokens=max_tokens,
                store=False,
            )
            effort = getattr(self.config, "model_reasoning_effort", "")
            if effort:
                payload["reasoning"] = {"effort": effort}
            if tools is not None:
                payload["tools"] = [
                    {"type": "function", **deepcopy(tool["function"]), "strict": False}
                    for tool in tools
                ]
                payload["include"] = ["reasoning.encrypted_content"]
        else:
            create = self.client.chat.completions.create
            payload.update(
                messages=[
                    {k: v for k, v in item.items() if not k.startswith("_")}
                    for item in messages
                ],
                max_tokens=max_tokens,
            )
            if tools is not None:
                payload["tools"] = tools
        if tools is not None:
            # The writing loop executes one action at a time.
            payload["parallel_tool_calls"] = False

        # Adapt only when the provider explicitly rejects an optional parameter.
        # Authentication, connection, rate-limit and server errors retain SDK retries
        # and propagate to the job; none of them means "this model cannot use tools".
        for _ in range(3):
            try:
                return create(**payload)
            except BadRequestError as exc:
                unsupported = (
                    "not support" in str(exc).lower()
                    or getattr(exc, "code", "") == "unsupported_parameter"
                )
                parameter = getattr(exc, "param", None)
                if (
                    unsupported
                    and parameter == "temperature"
                    and "temperature" in payload
                ):
                    payload.pop("temperature")
                elif (
                    unsupported
                    and parameter == "max_tokens"
                    and "max_tokens" in payload
                ):
                    payload["max_completion_tokens"] = payload.pop("max_tokens")
                else:
                    raise
        raise ModelResponseError("Provider rejected the supported request parameters")

    @staticmethod
    def _tool_arguments(raw: str, name: str, allowed: set[str]) -> dict:
        if name not in allowed:
            raise ModelResponseError(f"Provider requested an unavailable tool: {name}")
        try:
            arguments = json.loads(raw or "{}")
        except (TypeError, ValueError) as exc:
            raise ModelResponseError(
                f"Invalid JSON arguments for tool: {name}"
            ) from exc
        if not isinstance(arguments, dict):
            raise ModelResponseError(f"Tool arguments must be an object: {name}")
        return arguments

    @staticmethod
    def _unsupported_tools(exc: APIStatusError) -> bool:
        message = str(exc).lower()
        parameter = str(getattr(exc, "param", "") or "").split(".")[0].split("[")[0]
        if parameter and parameter not in {
            "tools",
            "functions",
            "tool_choice",
            "function_call",
            "parallel_tool_calls",
        }:
            return False
        if getattr(exc, "code", "") in {
            "invalid_function_parameters",
            "invalid_json_schema",
        }:
            return False
        return (
            exc.status_code in {400, 404, 422, 501}
            and bool(re.search(r"tools?|function", message))
            and any(
                term in message
                for term in (
                    "not support",
                    "unsupported",
                    "not implemented",
                    "unknown parameter",
                    "unrecognized",
                )
            )
        )

    def chat(self, messages, temperature=None, max_tokens=None, model=None) -> str:
        target = model or self.config.model_name
        started = time.perf_counter()
        if getattr(self.config, "llm_call_log", True):
            print(
                f"[LLM] start model={target} wire={getattr(self.config, 'wire_api', 'chat')}"
            )
        response = self._request(
            self._messages(messages),
            model=target,
            temperature=self.config.temperature if temperature is None else temperature,
            max_tokens=max(
                1,
                int(
                    (self.config.max_tokens if max_tokens is None else max_tokens)
                    or 2000
                ),
            ),
        )
        if getattr(self.config, "wire_api", "chat") == "responses":
            output = response.output_text
        else:
            if not response.choices:
                raise ModelResponseError("Provider returned no completion choices")
            output = response.choices[0].message.content
        if not isinstance(output, str) or not output.strip():
            raise ModelResponseError(
                "Provider returned no text; check model availability and output limits"
            )
        if getattr(self.config, "llm_call_log", True):
            print(
                f"[LLM] done model={target} elapsed={time.perf_counter() - started:.2f}s"
            )
        return output

    def chat_with_tools(
        self, messages, tools, temperature=0.2, max_tokens=1200, model=None
    ) -> dict[str, Any]:
        target = model or self.config.model_name
        allowed = {tool["function"]["name"] for tool in tools}
        if target not in self._text_only_models:
            try:
                response = self._request(
                    self._messages(messages),
                    model=target,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                )
            except APIStatusError as exc:
                if not self._unsupported_tools(exc):
                    raise
                self._text_only_models.add(target)
            else:
                calls = []
                result = {}
                if getattr(self.config, "wire_api", "chat") == "responses":
                    result["response_items"] = [
                        item.model_dump(exclude_none=True) for item in response.output
                    ]
                    content = response.output_text
                    for item in response.output:
                        if item.type == "function_call":
                            calls.append(
                                {
                                    "id": item.call_id,
                                    "name": item.name,
                                    "args": self._tool_arguments(
                                        item.arguments, item.name, allowed
                                    ),
                                }
                            )
                else:
                    if not response.choices:
                        raise ModelResponseError(
                            "Provider returned no completion choices"
                        )
                    message = response.choices[0].message
                    content = message.content or ""
                    for call in message.tool_calls or []:
                        calls.append(
                            {
                                "id": call.id,
                                "name": call.function.name,
                                "args": self._tool_arguments(
                                    call.function.arguments, call.function.name, allowed
                                ),
                            }
                        )
                if len(calls) > 1:
                    raise ModelResponseError(
                        "Provider returned parallel tool calls although parallel_tool_calls is disabled"
                    )
                if not calls and not content.strip():
                    raise ModelResponseError(
                        "Provider returned neither text nor a tool call"
                    )
                return {**result, "content": content, "tool_calls": calls}

        prompt = {
            "role": "user",
            "content": "Available functions and argument schemas:\n"
            + json.dumps(tools, ensure_ascii=False)
            + '\nReply only with JSON: {"tool": "function_name", "args": {...}}',
        }
        raw = self.chat(
            self._plain_history(messages) + [prompt],
            temperature=temperature,
            max_tokens=max_tokens,
            model=target,
        )
        match = re.search(r"\{.*\}", raw, re.S)
        try:
            parsed = json.loads(match.group(0) if match else raw)
        except ValueError as exc:
            raise ModelResponseError(
                "Text-only provider did not return a JSON tool call"
            ) from exc
        if not isinstance(parsed, dict):
            raise ModelResponseError("Text-only provider did not return a tool object")
        name = str(parsed.get("tool") or "")
        args = self._tool_arguments(json.dumps(parsed.get("args", {})), name, allowed)
        return {
            "content": "",
            "tool_calls": [
                {"id": f"fallback_{uuid4().hex}", "name": name, "args": args}
            ],
        }

    def generate(
        self, prompt, system_prompt=None, temperature=None, max_tokens=None
    ) -> str:
        messages = (
            [{"role": "system", "content": system_prompt}] if system_prompt else []
        )
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, temperature, max_tokens)
