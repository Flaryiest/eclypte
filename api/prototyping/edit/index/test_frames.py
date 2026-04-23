import numpy as np
from unittest.mock import patch, MagicMock
from api.prototyping.edit.index.frames import extract_frames


def test_extract_frames():
    # Mock cv2.VideoCapture to simulate a 3-second video at 30 fps
    with patch('api.prototyping.edit.index.frames.cv2') as mock_cv2:
        mock_cap = MagicMock()
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.CAP_PROP_FPS = 5
        mock_cv2.CAP_PROP_POS_MSEC = 0
        
        mock_cap.get.side_effect = lambda prop: 30.0 if prop == 5 else 0.0
        
        dummy_frame = np.zeros((10, 10, 3), dtype=np.uint8)

        # Sequential decode keeps every 30th frame for 1 fps output from 30 fps input.
        mock_cap.read.side_effect = [(True, dummy_frame)] * 90 + [(False, None)]
        
        # Call function
        frames = extract_frames("dummy.mp4", fps=1)
        
        # We expect 3 frames extracted
        assert len(frames) == 3
        
        # Check timestamps
        assert frames[0][0] == 0.0
        assert frames[1][0] == 1.0
        assert frames[2][0] == 2.0
