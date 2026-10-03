import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def app():
    """Lambda real + DynamoDB simulado (moto) + harness falso, aislado por prueba."""
    import local

    mod, mock = local.build_app()
    yield mod
    mock.stop()
