from unittest.mock import MagicMock, patch

from api.prototyping.edit.synthesis.agent import run_synthesis_loop


def _fake_response(output_items, response_id="resp_1"):
    r = MagicMock()
    r.id = response_id
    r.output = output_items
    r.output_text = ""
    return r


def _function_call(name, arguments, call_id):
    item = MagicMock()
    item.type = "function_call"
    item.name = name
    item.arguments = arguments
    item.call_id = call_id
    return item


def test_run_synthesis_loop():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai, \
         patch("api.prototyping.edit.synthesis.agent.query_clips") as mock_query:

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        first = _fake_response(
            [_function_call("query_clips", '{"query": "test", "top_k": 2}', "call_1")],
            response_id="resp_1",
        )
        second = _fake_response(
            [_function_call(
                "finish_edit",
                '{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 5.0}]}',
                "call_2",
            )],
            response_id="resp_2",
        )

        mock_create = MagicMock(side_effect=[first, second])
        mock_client.responses.create = mock_create

        mock_query.return_value = [{"timestamp": 5.0, "score": 0.9}]

        timeline = run_synthesis_loop("dummy.mp4", "make a cool video")

        assert len(timeline) == 1
        assert timeline[0]["source_timestamp"] == 5.0
        mock_query.assert_called_with("test", "dummy.mp4", 2)
        assert mock_create.call_count == 2

        # First call carries the system prompt via `instructions`; subsequent calls use previous_response_id.
        first_kwargs = mock_create.call_args_list[0].kwargs
        assert "instructions" in first_kwargs
        assert first_kwargs["model"] == "gpt-5.4"
        assert first_kwargs["reasoning"] == {"effort": "high"}
        assert first_kwargs["text"] == {"verbosity": "low"}

        second_kwargs = mock_create.call_args_list[1].kwargs
        assert second_kwargs.get("previous_response_id") == "resp_1"
        # Second input should include the function_call_output plus the reminder message
        second_input = second_kwargs["input"]
        assert any(i.get("type") == "function_call_output" and i.get("call_id") == "call_1" for i in second_input)
        assert any(i.get("type") == "message" and "Reminder" in i.get("content", "") for i in second_input)


def test_run_synthesis_loop_accepts_injected_prompt_and_query_function():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        first = _fake_response(
            [_function_call("query_clips", '{"query": "opening strike", "top_k": 3}', "call_1")],
            response_id="resp_1",
        )
        second = _fake_response(
            [_function_call(
                "finish_edit",
                '{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 6.0}]}',
                "call_2",
            )],
            response_id="resp_2",
        )
        mock_client.responses.create = MagicMock(side_effect=[first, second])
        query_fn = MagicMock(return_value=[{"timestamp": 6.0, "score": 0.95}])

        timeline = run_synthesis_loop(
            "source.mp4",
            "make it sharp",
            system_prompt="ACTIVE PROMPT",
            query_clips_fn=query_fn,
        )

        assert timeline[0]["source_timestamp"] == 6.0
        query_fn.assert_called_with("opening strike", "source.mp4", 3)
        assert mock_client.responses.create.call_args_list[0].kwargs["instructions"] == "ACTIVE PROMPT"
