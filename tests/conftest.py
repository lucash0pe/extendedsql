from pathlib import Path

import pandas as pd
import pytest

from esql.accessor import _enforce_allowed_dtypes

REPO_ROOT = Path(__file__).resolve().parent.parent
SALES_CSV = REPO_ROOT / "public" / "data" / "sales.csv"


@pytest.fixture
def sales_test_data() -> pd.DataFrame:
    return _enforce_allowed_dtypes(pd.read_csv(SALES_CSV))
