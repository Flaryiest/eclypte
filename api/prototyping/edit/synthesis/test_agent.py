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

        result = run_synthesis_loop("dummy.mp4", "make a cool video")

        assert len(result["shots"]) == 1
        assert result["shots"][0]["source_timestamp"] == 5.0
        assert result["overlays"] == []
        mock_query.assert_called_with("test", "dummy.mp4", 2)
        assert mock_create.call_count == 2

        # First call carries the system prompt via `instructions`; subsequent calls use previous_response_id.
        first_kwargs = mock_create.call_args_list[0].kwargs
        assert "instructions" in first_kwargs
        assert first_kwargs["model"] == "gpt-5.5"
        assert first_kwargs["reasoning"] == {"effort": "high"}
        assert first_kwargs["text"] == {"verbosity": "low"}

        second_kwargs = mock_create.call_args_list[1].kwargs
        assert second_kwargs.get("previous_response_id") == "resp_1"
        # Second input should include the function_call_output plus the reminder message
        second_input = second_kwargs["input"]
        assert any(i.get("type") == "function_call_output" and i.get("call_id") == "call_1" for i in second_input)
        assert any(i.get("type") == "message" and "Reminder" in i.get("content", "") for i in second_input)


def test_source_duration_added_to_user_prompt():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai, \
         patch("api.prototyping.edit.synthesis.agent.query_clips"):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        finish = _fake_response(
            [_function_call(
                "finish_edit",
                '{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 5.0}]}',
                "call_1",
            )],
            response_id="resp_1",
        )
        mock_create = MagicMock(side_effect=[finish])
        mock_client.responses.create = mock_create

        run_synthesis_loop("dummy.mp4", "make a cool video", source_duration_sec=137.0)

        # The source extent + full-span mandate must reach the model so it knows
        # where the end of the film is, regardless of the active system prompt.
        first_input = mock_create.call_args_list[0].kwargs["input"]
        assert "137" in first_input
        assert "full content" in first_input.lower()


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

        result = run_synthesis_loop(
            "source.mp4",
            "make it sharp",
            system_prompt="ACTIVE PROMPT",
            query_clips_fn=query_fn,
        )

        assert result["shots"][0]["source_timestamp"] == 6.0
        query_fn.assert_called_with("opening strike", "source.mp4", 3)
        assert mock_client.responses.create.call_args_list[0].kwargs["instructions"] == "ACTIVE PROMPT"


def test_finish_edit_returns_overlays():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai, \
         patch("api.prototyping.edit.synthesis.agent.query_clips"):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        finish = _fake_response(
            [_function_call(
                "finish_edit",
                '{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 5.0}], '
                '"overlays": [{"skill_id": "text.hook", "text": "no way", '
                '"start_time": 0.0, "end_time": 1.5}]}',
                "call_1",
            )],
            response_id="resp_1",
        )
        mock_client.responses.create = MagicMock(side_effect=[finish])

        result = run_synthesis_loop("dummy.mp4", "make a cool video")

        assert result["overlays"] == [
            {"skill_id": "text.hook", "text": "no way", "start_time": 0.0, "end_time": 1.5}
        ]


def test_pacing_targets_injected_into_user_prompt():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai, \
         patch("api.prototyping.edit.synthesis.agent.query_clips"):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        finish = _fake_response(
            [_function_call(
                "finish_edit",
                '{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 5.0}]}',
                "call_1",
            )],
            response_id="resp_1",
        )
        mock_client.responses.create = MagicMock(side_effect=[finish])

        song = {
            "source": {"duration_sec": 60.0},
            "tempo_bpm": 120.0,
            "segments": [
                {"start_sec": 0.0, "end_sec": 30.0, "label": "chorus"},
                {"start_sec": 30.0, "end_sec": 60.0, "label": "verse"},
            ],
        }
        run_synthesis_loop("dummy.mp4", "make a cool video", song=song)

        first_input = mock_client.responses.create.call_args_list[0].kwargs["input"]
        # Section-aware pacing targets (chorus band at 120bpm is 1.0-2.0s)
        assert "Pacing targets" in first_input
        assert "1.0-2.0s" in first_input
        # ...and the note that query_clips results carry motion/impact metadata.
        assert "impact_near" in first_input


def test_pacing_targets_honor_style_profile_overrides():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai, \
         patch("api.prototyping.edit.synthesis.agent.query_clips"):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        finish = _fake_response(
            [_function_call(
                "finish_edit",
                '{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 5.0}]}',
                "call_1",
            )],
            response_id="resp_1",
        )
        mock_client.responses.create = MagicMock(side_effect=[finish])

        song = {
            "source": {"duration_sec": 60.0},
            "tempo_bpm": 120.0,
            "segments": [{"start_sec": 0.0, "end_sec": 60.0, "label": "chorus"}],
        }
        run_synthesis_loop(
            "dummy.mp4", "make a cool video", song=song,
            style_profile={"pacing_bands_beats": {"chorus": (1.0, 2.0)}},
        )

        first_input = mock_client.responses.create.call_args_list[0].kwargs["input"]
        # override band (0.5-1.0s at 120bpm) replaces the default 1.0-2.0s
        assert "0.5-1.0s" in first_input


def test_pacing_targets_skipped_without_segments():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai, \
         patch("api.prototyping.edit.synthesis.agent.query_clips"):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        finish = _fake_response(
            [_function_call(
                "finish_edit",
                '{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 5.0}]}',
                "call_1",
            )],
            response_id="resp_1",
        )
        mock_client.responses.create = MagicMock(side_effect=[finish])

        run_synthesis_loop("dummy.mp4", "make a cool video", song={"source": {"duration_sec": 60.0}})

        first_input = mock_client.responses.create.call_args_list[0].kwargs["input"]
        assert "Pacing targets" not in first_input


def test_finish_edit_returns_grade():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai, \
         patch("api.prototyping.edit.synthesis.agent.query_clips"):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        finish = _fake_response(
            [_function_call(
                "finish_edit",
                '{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 5.0}], '
                '"grade": "grade.cinematic"}',
                "call_1",
            )],
            response_id="resp_1",
        )
        mock_client.responses.create = MagicMock(side_effect=[finish])

        result = run_synthesis_loop("dummy.mp4", "make a cool video")

        assert result["grade"] == "grade.cinematic"


def test_grade_enum_exposed_in_finish_edit_tool():
    from api.prototyping.edit.synthesis.agent import TOOLS

    finish = next(t for t in TOOLS if t["name"] == "finish_edit")
    grade_prop = finish["parameters"]["properties"]["grade"]
    assert "grade.cinematic" in grade_prop["enum"]
    assert "grade.vibrant" in grade_prop["enum"]
    # only grade-kind skills belong in this enum
    assert "text.hook" not in grade_prop["enum"]


def test_overlay_skill_catalog_injected_into_user_prompt():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai, \
         patch("api.prototyping.edit.synthesis.agent.query_clips"):

        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        finish = _fake_response(
            [_function_call(
                "finish_edit",
                '{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 5.0}]}',
                "call_1",
            )],
            response_id="resp_1",
        )
        mock_client.responses.create = MagicMock(side_effect=[finish])

        run_synthesis_loop("dummy.mp4", "make a cool video")

        first_input = mock_client.responses.create.call_args_list[0].kwargs["input"]
        assert "text.hook" in first_input
        assert "mask.vignette" in first_input
