import pytest

from backend.config import Settings
from backend.service import AcquisitionService
from .fakes import FakeFactory


@pytest.fixture
def settings(tmp_path):
    return Settings(database=str(tmp_path / "microp.sqlite3"), command_timeout=0.2,
                    reset_delay=0, read_timeout=0.005, stale_after=0.05,
                    pin_file=str(tmp_path / 'pin.json'), model_file=str(tmp_path / 'model.json'))


@pytest.fixture
def factory():
    return FakeFactory()


@pytest.fixture
def service(settings, factory):
    instance = AcquisitionService(settings, factory)
    try:
        yield instance
    finally:
        instance.close()
