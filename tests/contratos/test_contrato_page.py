"""Contrato da SlottedPage (Silberschatz 13.2.2, Fig. 13.6): slots estáveis, capacidade, reserva."""
import pytest

from tests.conftest import page_impl_real
from tests.contratos import construir
from tests.fakes import FakeSlottedPage

BS = 4096


@pytest.fixture(params=["fake", "real"])
def P(request):
    return construir(request.param, page_impl_real, lambda: FakeSlottedPage)


def _pagina(P, reserva=0):
    buf = bytearray(BS)
    P.format(buf, reserva)
    return buf


def test_vazia(P):
    buf = _pagina(P)
    assert P.count(buf) == 0 and list(P.slots(buf)) == []
    assert P.get(buf, 0) is None
    assert P.free_space(buf) >= P.capacidade_max(BS) > BS // 2


def test_insere_ate_encher(P):
    buf = _pagina(P)
    recs = {}
    i = 0
    livre = P.free_space(buf)
    while True:
        r = f"registro-{i:05d}".encode() * 3
        s = P.insert(buf, r)
        if s is None:
            break
        assert s not in recs
        recs[s] = r
        assert P.free_space(buf) < livre
        livre = P.free_space(buf)
        i += 1
    assert len(recs) > 10 and P.count(buf) == len(recs)
    assert list(P.slots(buf)) == sorted(recs)
    for s, r in recs.items():
        assert P.get(buf, s) == r


def test_delete_compact_preservam_slots(P):
    buf = _pagina(P)
    slots = [P.insert(buf, bytes([i]) * 100) for i in range(20)]
    for s in slots[::2]:
        P.delete(buf, s)
    P.compact(buf)
    assert P.count(buf) == 10
    for i, s in enumerate(slots):
        assert P.get(buf, s) == (None if i % 2 == 0 else bytes([i]) * 100)
    assert list(P.slots(buf)) == slots[1::2]


def test_update(P):
    buf = _pagina(P)
    a = P.insert(buf, b"a" * 10)
    b = P.insert(buf, b"b" * 10)
    assert P.update(buf, a, b"A" * 50) is True
    assert P.get(buf, a) == b"A" * 50 and P.get(buf, b) == b"b" * 10
    assert P.update(buf, b, b"x" * BS) is False      # não cabe: página inalterada
    assert P.get(buf, b) == b"b" * 10


def test_capacidade_max_exata(P):
    for reserva in (0, 16):
        cap = P.capacidade_max(BS, reserva)
        buf = _pagina(P, reserva)
        assert P.insert(buf, b"z" * cap) is not None
        buf = _pagina(P, reserva)
        assert P.insert(buf, b"z" * (cap + 1)) is None


def test_area_reservada_intocada(P):
    buf = _pagina(P, reserva=16)
    off, n = P.reserva(buf)
    assert (off, n) == (BS - 16, 16)
    buf[off:off + n] = b"\xab" * 16
    slots = [P.insert(buf, b"q" * 200) for _ in range(30)]
    slots = [s for s in slots if s is not None]
    for s in slots[:5]:
        P.delete(buf, s)
    P.compact(buf)
    assert buf[off:off + n] == b"\xab" * 16
    assert P.reserva(buf) == (off, n)
