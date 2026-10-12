from __future__ import annotations

from copy import deepcopy
import importlib
from types import SimpleNamespace

import pytest
from openai import APIStatusError

from provider_server import completion, provider_server, response

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "draft_chapter",
            "description": "Write the current chapter",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


@pytest.fixture
def model_client(workspace):
    module = importlib.import_module("utils.llm_client")
    clients = []

    def create(url, wire="chat"):
        config = SimpleNamespace(
            api_key="test-only-key",
            api_base_url=url,
            model_name="test-model",
            language="en",
            wire_api=wire,
            temperature=0.7,
            max_tokens=16000,
            llm_timeout_seconds=3,
            llm_max_retries=0,
            llm_call_log=False,
        )
        client = module.LLMClient(config)
        clients.append(client)
        return client

    yield create, module.ModelResponseError
    for client in clients:
        client.close()


def test_responses_preserves_roles_and_requested_output_limit(model_client):
    create, _ = model_client
    messages = [
        {"role": "system", "content": "Keep the story facts."},
        {"role": "user", "content": "Continue."},
    ]
    original = deepcopy(messages)
    with provider_server(lambda *args: (200, response())) as (url, requests):
        assert create(url, "responses").chat(messages, temperature=0, max_tokens=12000)
    body = requests[0]["body"]
    assert body["input"][-2:] == original
    assert body["max_output_tokens"] == 12000 and body["temperature"] == 0
    assert "reasoning" not in body and body["store"] is False
    assert messages == original


def test_responses_tools_replay_reasoning_and_call_ids(model_client):
    create, _ = model_client
    output = [
        {
            "type": "reasoning",
            "id": "rs_test",
            "summary": [],
            "encrypted_content": "opaque-test-state",
        },
        {
            "type": "function_call",
            "id": "fc_test",
            "call_id": "call_test",
            "name": "draft_chapter",
            "arguments": "{}",
            "status": "completed",
        },
    ]
    with provider_server(
        lambda path, body, number: (
            200,
            response(output=output) if number == 1 else response(),
        )
    ) as (url, requests):
        client = create(url, "responses")
        history = [{"role": "user", "content": "Write chapter one."}]
        turn = client.chat_with_tools(history, TOOLS)
        assert turn["tool_calls"] == [
            {"id": "call_test", "name": "draft_chapter", "args": {}}
        ]
        history += [
            {"role": "assistant", "_response_items": turn["response_items"]},
            {"role": "tool", "tool_call_id": "call_test", "content": "Draft saved."},
        ]
        client.chat_with_tools(history, TOOLS)
    assert all(item["path"] == "/v1/responses" for item in requests)
    assert requests[0]["body"]["tools"][0]["name"] == "draft_chapter"
    assert requests[0]["body"]["tools"][0]["strict"] is False
    assert requests[0]["body"]["parallel_tool_calls"] is False
    assert any(
        item.get("encrypted_content") == "opaque-test-state"
        for item in requests[1]["body"]["input"]
    )
    assert requests[1]["body"]["input"][-1] == {
        "type": "function_call_output",
        "call_id": "call_test",
        "output": "Draft saved.",
    }


@pytest.mark.parametrize("status", [401, 429, 503])
def test_operational_failures_are_not_tool_fallbacks(model_client, status):
    create, _ = model_client
    with provider_server(
        lambda *args: (
            status,
            {"error": {"message": "Provider unavailable", "type": "provider_error"}},
        )
    ) as (url, requests):
        with pytest.raises(APIStatusError) as error:
            create(url).chat_with_tools([{"role": "user", "content": "Write."}], TOOLS)
        assert error.value.status_code == status
    assert len(requests) == 1


def test_only_explicit_tool_rejection_uses_valid_text_history(model_client):
    create, _ = model_client

    def reply(path, body, number):
        if number == 1:
            return 400, {
                "error": {
                    "message": "tools are not supported",
                    "type": "invalid_request_error",
                    "param": "tools",
                    "code": "unsupported_parameter",
                }
            }
        return 200, completion('{"tool":"draft_chapter","args":{}}')

    with provider_server(reply) as (url, requests):
        client = create(url)
        history = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "old_call",
                        "type": "function",
                        "function": {"name": "draft_chapter", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "old_call", "content": "draft"},
        ]
        first = client.chat_with_tools(history, TOOLS)
        second = client.chat_with_tools(history, TOOLS)
    assert len(requests) == 3
    assert all(
        "tool_calls" not in item and item["role"] != "tool"
        for item in requests[1]["body"]["messages"]
    )
    assert first["tool_calls"][0]["id"] != second["tool_calls"][0]["id"]


@pytest.mark.parametrize("arguments", ["{broken", "[]", "null"])
def test_malformed_tool_arguments_are_reported(model_client, arguments):
    create, error_type = model_client
    calls = [
        {
            "id": "call_test",
            "type": "function",
            "function": {"name": "draft_chapter", "arguments": arguments},
        }
    ]
    with provider_server(lambda *args: (200, completion("", calls))) as (url, requests):
        with pytest.raises(error_type):
            create(url).chat_with_tools([], TOOLS)
    assert len(requests) == 1


def test_rejected_temperature_is_omitted_on_retry(model_client):
    create, _ = model_client

    def reply(path, body, number):
        if "temperature" in body:
            return 400, {
                "error": {
                    "message": "temperature is not supported",
                    "type": "invalid_request_error",
                    "param": "temperature",
                    "code": "unsupported_parameter",
                }
            }
        return 200, completion()

    with provider_server(reply) as (url, requests):
        assert create(url).chat([{"role": "user", "content": "Write."}])
    assert len(requests) == 2 and "temperature" not in requests[-1]["body"]


def test_invalid_tool_schema_is_not_downgraded(model_client):
    create, _ = model_client
    error = {
        "error": {
            "message": "Unsupported schema in tools",
            "type": "invalid_request_error",
            "param": "tools[0]",
            "code": "invalid_function_parameters",
        }
    }
    with provider_server(lambda *args: (400, error)) as (url, requests):
        with pytest.raises(APIStatusError):
            create(url).chat_with_tools([], TOOLS)
    assert len(requests) == 1
