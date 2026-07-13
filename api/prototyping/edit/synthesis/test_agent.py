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
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:
        mock_query = MagicMock()

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

        result = run_synthesis_loop("dummy.mp4", "make a cool video", query_clips_fn=mock_query)

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
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:

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
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:

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
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:

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
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:

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
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:

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
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:

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


def _lyrics_timing(mode="aligned", lines=None):
    if lines is None:
        lines = [
            {
                "line_idx": 0,
                "start_sec": 0.42,
                "end_sec": 2.95,
                "text": "I got a feeling in my soul",
                "words": [
                    {"word": "I", "start_sec": 0.42, "end_sec": 0.55, "confidence": 0.9},
                    {"word": "got", "start_sec": 0.63, "end_sec": 0.8, "confidence": 0.9},
                    {"word": "a", "start_sec": 0.88, "end_sec": 0.95, "confidence": 0.9},
                    {"word": "feeling", "start_sec": 1.1, "end_sec": 1.6, "confidence": 0.9},
                ],
            },
            {
                "line_idx": 1,
                "start_sec": 3.1,
                "end_sec": 5.7,
                "text": "Burning brighter than a wildfire",
                "words": [
                    {"word": "Burning", "start_sec": 3.1, "end_sec": 3.5, "confidence": 0.9},
                    {"word": "wildfire", "start_sec": 4.38, "end_sec": 5.1, "confidence": 0.9},
                ],
            },
        ]
    return {
        "schema_version": 1,
        "source": {"duration_sec": 25.0},
        "mode": mode,
        "language": "en",
        "text_source": "synced_lrc" if mode == "aligned" else "none",
        "model": "large-v3",
        "quality": {"word_count": sum(len(l["words"]) for l in lines)},
        "lines": lines,
    }


def _run_with_lyrics(mock_openai, lyrics):
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
    run_synthesis_loop("dummy.mp4", "make a cool video", lyrics=lyrics)
    return mock_client.responses.create.call_args_list[0].kwargs["input"]


def test_lyrics_context_injected_with_word_detail():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:
        first_input = _run_with_lyrics(mock_openai, _lyrics_timing())

        assert "Lyrics timing" in first_input
        # Line rows carry the window and text; word rows carry per-word times.
        assert '[0.42-2.95] "I got a feeling in my soul"' in first_input
        assert "wildfire(4.38)" in first_input
        # The three uses: literal imagery, emotional arc, anchors.
        assert "Literal imagery" in first_input
        assert "Emotional arc" in first_input
        assert "Anchors" in first_input


def test_lyrics_context_collapses_to_lines_above_word_cap():
    lines = [
        {
            "line_idx": i,
            "start_sec": float(i),
            "end_sec": float(i) + 0.9,
            "text": f"line number {i}",
            "words": [
                {"word": f"w{i}_{j}", "start_sec": float(i), "end_sec": float(i) + 0.1,
                 "confidence": 0.9}
                for j in range(10)
            ],
        }
        for i in range(40)  # 400 words > LYRICS_WORD_DETAIL_MAX
    ]
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:
        first_input = _run_with_lyrics(mock_openai, _lyrics_timing(lines=lines))

        assert "Lyrics timing" in first_input
        assert '"line number 3"' in first_input
        # Per-word rows are dropped in line-only mode.
        assert "w3_0(" not in first_input


def test_lyrics_context_transcribed_mode_carries_caveat():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:
        first_input = _run_with_lyrics(mock_openai, _lyrics_timing(mode="transcribed"))

        assert "recognition errors" in first_input


def test_lyrics_context_absent_when_missing_or_empty():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:
        first_input = _run_with_lyrics(mock_openai, None)
        assert "Lyrics timing" not in first_input

    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:
        first_input = _run_with_lyrics(mock_openai, _lyrics_timing(lines=[]))
        assert "Lyrics timing" not in first_input


def test_overlay_skill_catalog_injected_into_user_prompt():
    with patch("api.prototyping.edit.synthesis.agent.OpenAI") as mock_openai:

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
