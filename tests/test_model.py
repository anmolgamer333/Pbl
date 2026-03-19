import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model import npv_from_events


def test_npv_single_event_year_zero():
    events = pd.DataFrame(
        [
            {"Alternative": "A1", "Year": 0, "Description": "Initial", "Cost": 1000.0},
        ]
    )
    assert npv_from_events(events, 0.04) == 1000.0


def test_npv_with_salvage_discounting():
    events = pd.DataFrame(
        [
            {"Alternative": "A1", "Year": 0, "Description": "Initial", "Cost": 1000.0},
            {"Alternative": "A1", "Year": 20, "Description": "Salvage", "Cost": -200.0},
        ]
    )
    expected = 1000.0 - (200.0 / ((1.0 + 0.04) ** 20))
    assert npv_from_events(events, 0.04) == expected
