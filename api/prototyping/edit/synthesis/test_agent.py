import pytest
from unittest.mock import patch, MagicMock
from api.prototyping.edit.synthesis.agent import run_synthesis_loop

def test_run_synthesis_loop():
    with patch('api.prototyping.edit.synthesis.agent.OpenAI') as mock_openai:
        with patch('api.prototyping.edit.synthesis.agent.query_clips') as mock_query:
            
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            
            # First response calls query_clips
            msg1 = MagicMock()
            msg1.tool_calls = [
                MagicMock(
                    id="call_1",
                    function=MagicMock(name="query_clips", arguments='{"query": "test", "top_k": 2}')
                )
            ]
            msg1.tool_calls[0].function.name = "query_clips"
            
            mock_query.return_value = [{"timestamp": 5.0, "score": 0.9}]
            
            # Second response calls finish_edit
            msg2 = MagicMock()
            msg2.tool_calls = [
                MagicMock(
                    id="call_2",
                    function=MagicMock(name="finish_edit", arguments='{"timeline": [{"start_time": 0, "end_time": 2, "source_timestamp": 5.0}]}')
                )
            ]
            msg2.tool_calls[0].function.name = "finish_edit"
            
            # Set up the chat completions mock to return msg1 then msg2
            choice1 = MagicMock()
            choice1.message = msg1
            choice2 = MagicMock()
            choice2.message = msg2
            
            mock_create = MagicMock()
            mock_create.side_effect = [
                MagicMock(choices=[choice1]),
                MagicMock(choices=[choice2])
            ]
            mock_client.chat.completions.create = mock_create
            
            timeline = run_synthesis_loop("dummy.mp4", "make a cool video")
            
            assert len(timeline) == 1
            assert timeline[0]["source_timestamp"] == 5.0
            mock_query.assert_called_with("test", "dummy.mp4", 2)
            assert mock_create.call_count == 2
