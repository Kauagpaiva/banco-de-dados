"""Contrato do RecordCodec (Silberschatz 13.2.2): round-trip, nulos, limites."""
import datetime as dt

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.access.contracts import Campo, Esquema
from src.access.esquemas import ESQUEMAS
from src.common.erros import RecordError
from tests.contratos import construir
from tests.fakes import FakeCodec, registros_fake

PEQ = Esquema("Peq", (
    Campo("id", "int"),
    Campo("x", "float", nulo=True),
    Campo("d", "date"),
    Campo("c", "char(4)"),
    Campo("v", "varchar(10)", nulo=True),
    Campo("l", "list[varchar(5)]", max_itens=3),
), chave=("id",))


def _real(esquema):
    from src.access.record import RecordCodec
    return RecordCodec(esquema)


@pytest.fixture(params=["fake", "real"])
def mk(request):
    """Fábrica de codec para a implementação do parâmetro."""
    construir(request.param, lambda: _real(PEQ), lambda: FakeCodec(PEQ))  # xfail cedo se stub
    return (lambda e: _real(e)) if request.param == "real" else FakeCodec


@pytest.mark.parametrize("nome", sorted(ESQUEMAS))
def test_round_trip_esquemas(mk, nome):
    c = mk(ESQUEMAS[nome])
    for r in registros_fake(ESQUEMAS[nome], 50, seed=1):
        b = c.encode(r)
        assert len(b) <= c.max_size
        assert c.decode(b) == r


def _rec(**kw):
    base = {"id": 1, "x": 1.5, "d": dt.date(2000, 1, 2), "c": "abcd", "v": "", "l": []}
    base.update(kw)
    return base


def test_nulos_e_vazios(mk):
    c = mk(PEQ)
    for r in [_rec(x=None, v=None), _rec(v="", l=[]), _rec(l=["", "ab", "çã"])]:
        assert c.decode(c.encode(r)) == r


def test_tamanhos_maximos(mk):
    c = mk(PEQ)
    r = _rec(c="çç", v="é" * 5, l=["abcde"] * 3)     # 4 e 10 bytes UTF-8 exatos
    assert c.decode(c.encode(r)) == r


@pytest.mark.parametrize("ruim", [
    {"x": 1.0},                                        # faltam campos
    _rec(id=None),                                     # nulo em NOT NULL
    _rec(v="x" * 11),                                  # varchar estourado
    _rec(c="abcde"),                                   # char estourado
    _rec(l=["a", "b", "c", "d"]),                      # itens demais
    _rec(l=["abcdef"]),                                # item estourado
    _rec(id="1"),                                      # tipo errado
    {**_rec(), "extra": 1},                            # campo desconhecido
])
def test_invalidos(mk, ruim):
    with pytest.raises(RecordError):
        mk(PEQ).encode(ruim)


_txt = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=0x24F), max_size=10)


@settings(max_examples=60, deadline=None)
@given(
    x=st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False)),
    v=st.one_of(st.none(), _txt.filter(lambda s: len(s.encode()) <= 10)),
    l=st.lists(_txt.filter(lambda s: len(s.encode()) <= 5), max_size=3),
    i=st.integers(-2**31, 2**31 - 1),
    d=st.dates(dt.date(1900, 1, 1), dt.date(2100, 1, 1)),
)
def test_round_trip_hypothesis(x, v, l, i, d):
    for c in _codecs_disponiveis():
        r = _rec(id=i, x=x, v=v, l=l, d=d)
        assert c.decode(c.encode(r)) == r


def _codecs_disponiveis():
    cs = [FakeCodec(PEQ)]
    try:
        cs.append(_real(PEQ))
    except NotImplementedError:
        pass
    return cs
