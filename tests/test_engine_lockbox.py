import pandas as pd

from jayu.engine import _partition_research_data
from jayu.settings import Settings


def test_research_partition_excludes_final_lockbox_and_gap():
    frame = pd.DataFrame({"Close": range(1000)})
    settings = Settings()

    development, split = _partition_research_data(frame, settings)

    assert split is not None
    assert len(development) == split.development_rows
    assert development.index.max() < split.lockbox_start
    assert split.development_end + split.purge_rows + split.embargo_rows == split.lockbox_start


def test_research_partition_can_be_disabled():
    frame = pd.DataFrame({"Close": range(1000)})
    settings = Settings.model_validate(
        {
            **Settings().model_dump(),
            "research": {
                **Settings().research.model_dump(),
                "final_lockbox_enabled": False,
            },
        }
    )

    development, split = _partition_research_data(frame, settings)

    assert split is None
    assert development is frame
