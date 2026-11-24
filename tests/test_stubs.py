"""E00b: todo módulo de src/ é importável, toda classe de implementação cobre o contrato
(não sobra método abstrato) e os operadores do executor existem com o nome do contrato."""
import importlib
import inspect
from pathlib import Path

import pytest

from src.access import contracts as ac
from src.executor.contracts import OPERADORES, MemoryBudgetAPI
from src.storage import contracts as sc

SRC = Path(__file__).resolve().parents[1] / "src"
MODULOS = sorted(".".join(p.relative_to(SRC.parent).with_suffix("").parts)
                 for p in SRC.rglob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("mod", MODULOS)
def test_importavel(mod):
    importlib.import_module(mod)


IMPLEMENTACOES = [
    ("src.storage.file_manager", "FileManager", sc.FileManagerAPI),
    ("src.storage.buffer_manager", "BufferManager", sc.BufferManagerAPI),
    ("src.storage.replacement", "LRU", sc.PolicyAPI),
    ("src.access.record", "RecordCodec", ac.RecordCodecAPI),
    ("src.access.page", "SlottedPage", ac.SlottedPageAPI),
    ("src.access.catalog", "Catalog", ac.CatalogAPI),
    ("src.access.heap", "HeapFile", ac.FileOrganization),
    ("src.access.bplus", "BPlusTree", ac.FileOrganization),
    ("src.access.hashfile", "HashFile", ac.FileOrganization),
    ("src.access.hash_index", "HashIndex", ac.SecondaryIndex),
    ("src.access.secondary_bplus", "BPlusIndex", ac.SecondaryIndex),
    ("src.access.tempfile", "ArquivoTemporario", ac.TempFile),
    ("src.access.context", "ContextoArmazenamento", ac.StorageContext),
    ("src.executor.memory", "MemoryBudget", MemoryBudgetAPI),
]


@pytest.mark.parametrize("mod,nome,base", IMPLEMENTACOES, ids=lambda x: getattr(x, "__name__", x))
def test_implementa_contrato(mod, nome, base):
    cls = getattr(importlib.import_module(mod), nome)
    assert issubclass(cls, base)
    assert not inspect.isabstract(cls), f"{nome}: faltam {sorted(cls.__abstractmethods__)}"


@pytest.mark.parametrize("op", sorted(OPERADORES))
def test_operadores_existem(op):
    mod, nome = OPERADORES[op]
    fn = getattr(importlib.import_module(mod), nome)
    params = list(inspect.signature(fn).parameters)
    assert params[0] == "ctx"
    if op != "select" and op != "external_sort":
        assert params[1:4] == ["r", "s", "cond"]
        assert "M" in params and "materializar" in params


def test_fakes_cobrem_contratos():
    from tests import fakes
    for cls, base in [(fakes.FakeFileManager, sc.FileManagerAPI),
                      (fakes.FakeBufferManager, sc.BufferManagerAPI),
                      (fakes.FakeCodec, ac.RecordCodecAPI), (fakes.FakeSlottedPage, ac.SlottedPageAPI),
                      (fakes.FakeCatalog, ac.CatalogAPI), (fakes.FakeTable, ac.FileOrganization),
                      (fakes.FakeIndex, ac.SecondaryIndex), (fakes.FakeTempFile, ac.TempFile),
                      (fakes.FakeStorageContext, ac.StorageContext)]:
        assert issubclass(cls, base) and not inspect.isabstract(cls), cls.__name__
