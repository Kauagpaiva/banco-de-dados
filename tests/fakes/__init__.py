"""Fakes do M0: implementações simples e corretas dos contratos, usadas enquanto a
implementação real não está em `main`. Ver `tests/conftest.py` (troca automática)."""
from tests.fakes.access import (  # noqa: F401
    FakeCatalog, FakeCodec, FakeIndex, FakeSlottedPage, FakeStorageContext, FakeTable,
    FakeTempFile, validar_registro,
)
from tests.fakes.gerador import registros_fake  # noqa: F401
from tests.fakes.storage import FakeBufferManager, FakeFileManager  # noqa: F401
