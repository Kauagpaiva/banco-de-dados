"""Fixtures comuns (M0). Cada fixture tenta a implementação **real**; se ela ainda for stub
(`NotImplementedError`), usa o **fake** de `tests/fakes/`. `pytest --so-fakes` força os fakes.

Fixtures: cfg · bm · ctx · codec (fábrica: codec(esquema)) · page_impl · tabela(nome, n).
Autouse: ao fim de cada teste, `assert_no_pins()` em todo buffer criado pelas fixtures.
"""
from __future__ import annotations

from typing import Callable

import pytest

from src.access.esquemas import ESQUEMAS
from src.common.config import load_config
from tests.fakes import (
    FakeBufferManager, FakeCodec, FakeFileManager, FakeSlottedPage, FakeStorageContext, FakeTable,
    registros_fake,
)


def pytest_addoption(parser):
    parser.addoption("--so-fakes", action="store_true", default=False,
                     help="usa só os fakes de tests/fakes, mesmo se a implementação real existir")


# ----------------------------------------------------------------------------- helpers
def real_ou_fake(real: Callable, fake: Callable, so_fakes: bool = False):
    """Devolve `real()`; se for stub (NotImplementedError) ou `so_fakes`, devolve `fake()`."""
    if not so_fakes:
        try:
            return real()
        except NotImplementedError:
            pass
    return fake()


def page_impl_real():
    """Classe SlottedPage real, ou NotImplementedError se ainda for stub."""
    from src.access.page import SlottedPage
    SlottedPage.format(bytearray(512))
    return SlottedPage


def bm_real(cfg, base_dir):
    from src.storage.buffer_manager import BufferManager
    from src.storage.file_manager import FileManager
    return BufferManager(cfg, FileManager(cfg, base_dir))


def bm_fake(cfg):
    return FakeBufferManager(cfg, FakeFileManager(cfg))


@pytest.fixture
def so_fakes(request) -> bool:
    return request.config.getoption("--so-fakes")


# ----------------------------------------------------------------------------- no pins
@pytest.fixture(autouse=True)
def _buffers_sem_pins():
    """Lista de buffers criados no teste; no teardown todos devem estar sem pins (E04)."""
    criados: list = []
    yield criados
    for b in criados:
        b.assert_no_pins()


# ----------------------------------------------------------------------------- fixtures
@pytest.fixture
def cfg():
    return load_config("teste")


@pytest.fixture
def bm(cfg, tmp_path, so_fakes, _buffers_sem_pins):
    b = real_ou_fake(lambda: bm_real(cfg, tmp_path), lambda: bm_fake(cfg), so_fakes)
    _buffers_sem_pins.append(b)
    return b


@pytest.fixture
def page_impl(so_fakes):
    return real_ou_fake(page_impl_real, lambda: FakeSlottedPage, so_fakes)


@pytest.fixture
def codec(so_fakes):
    """Fábrica `codec(esquema)` → RecordCodec real ou FakeCodec."""
    def fabrica(esquema):
        def real():
            from src.access.record import RecordCodec
            return RecordCodec(esquema)
        return real_ou_fake(real, lambda: FakeCodec(esquema), so_fakes)
    return fabrica


@pytest.fixture
def ctx(cfg, bm, tmp_path, so_fakes, page_impl, codec, _buffers_sem_pins):
    def real():
        from src.access.context import criar_contexto
        return criar_contexto(cfg, tmp_path / "ctx")
    c = real_ou_fake(real, lambda: FakeStorageContext(cfg, bm, page_impl=page_impl,
                                                      codec_factory=codec), so_fakes)
    _buffers_sem_pins.append(c.bm)
    yield c
    c.close()


@pytest.fixture
def tabela(ctx, page_impl, codec, so_fakes):
    """Fábrica `tabela(nome, n, registros=None)` → Heap aberto e carregado (HeapFile real ou
    FakeTable) com o esquema `ESQUEMAS[nome]` e n registros de `registros_fake`."""
    cont = {"n": 0}

    def fabrica(nome: str, n: int = 0, registros=None, seed: int = 0):
        esquema = ESQUEMAS[nome]
        cont["n"] += 1
        arq = f"{nome}_heap_{cont['n']}"

        def real():
            from src.access.heap import HeapFile
            t = HeapFile(ctx.bm, arq, esquema, page_impl=page_impl, codec=codec(esquema))
            t.open()
            return t
        def fake():
            t = FakeTable(ctx.bm, arq, esquema, page_impl=page_impl, codec=codec(esquema))
            t.open()
            return t
        t = real_ou_fake(real, fake, so_fakes)
        for r in (registros if registros is not None else registros_fake(esquema, n, seed)):
            t.insert(r)
        return t
    return fabrica
