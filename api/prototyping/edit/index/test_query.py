import pytest
from unittest.mock import patch, MagicMock
from api.prototyping.edit.index.query import query_clips

def test_query_clips():
    with patch('api.prototyping.edit.index.query.modal.Function.from_name') as mock_lookup:
        mock_func = MagicMock()
        mock_lookup.return_value = mock_func
        
        mock_func.remote.return_value = [
            {"timestamp": 12.0, "score": 0.95},
            {"timestamp": 15.0, "score": 0.85}
        ]
        
        results = query_clips("test query", "dummy.mp4", top_k=2)
        assert len(results) == 2
        mock_func.remote.assert_called_with("test query", "dummy.mp4", 2)
