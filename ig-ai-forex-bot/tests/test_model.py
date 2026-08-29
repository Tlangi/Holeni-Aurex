import numpy as np
import pandas as pd

from forexbot.model import add_features


def test_unavailable_future_rows_are_removed_from_training_data():
    rows = 100
    close = pd.Series(1.05 + np.sin(np.arange(rows) / 5) * .01 + np.arange(rows) * .0001)
    frame = pd.DataFrame({"close": close, "high": close + .001, "low": close - .001,
                          "tick_volume": np.arange(rows) + 100})
    labelled = add_features(frame, horizon=4, labelled=True)
    assert labelled.index.max() <= rows - 5
