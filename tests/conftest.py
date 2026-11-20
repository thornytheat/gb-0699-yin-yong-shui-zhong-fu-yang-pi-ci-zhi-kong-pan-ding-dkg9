import os
import tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="water-lab-pytest-")
import pytest
from app.pipeline import run,sample_text
@pytest.fixture
def sample(): return sample_text()
@pytest.fixture
def result(sample): return run(sample)
