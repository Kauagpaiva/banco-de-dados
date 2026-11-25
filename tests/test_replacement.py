"""E02 — Políticas de substituição (Silberschatz 13.5.2): LRU, MRU, FIFO, Clock.

As políticas são testadas isoladamente por um simulador que segue o mesmo protocolo do
BufferManager: miss → victim/on_evict/on_load; hit → on_access; depois unpin → on_unpin.
"""
import pytest

from src.common.erros import StorageError
from src.storage.contracts import Frame
from src.storage.replacement import FIFO, LRU, MRU, Clock, criar_politica

# Sequência clássica de referência (Silberschatz, Operating System Concepts, cap. 9/10)
REF = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]


def simular(nome, refs, cap, toss=()):
    """Executa `refs` num pool de `cap` quadros; devolve (faltas, residentes finais).
    Páginas em `toss` são liberadas com toss-immediate."""
    pol = criar_politica(nome)
    quadros: dict[int, Frame] = {}
    faltas = 0
    for p in refs:
        fr = quadros.get(p)
        if fr is None:
            faltas += 1
            if len(quadros) == cap:
                v = pol.victim(list(quadros.values()))
                pol.on_evict(v)
                del quadros[v.bno]
            fr = Frame(0, p, bytearray(1))
            quadros[p] = fr
            pol.on_load(fr)
        else:
            pol.on_access(fr)
        fr.pin_count += 1
        fr.pin_count -= 1
        pol.on_unpin(fr, toss=p in toss)
    return faltas, set(quadros)


def test_fifo_sequencia_classica():
    # 3 quadros, REF: resultado clássico do livro = 15 faltas
    # 7m 0m 1m | 2m(-7) 0h 3m(-0) 0m(-1) 4m(-2) 2m(-3) 3m(-0) 0m(-4) 3h 2h
    # 1m(-2) 2m(-3) 0h 1h 7m(-0) 0m(-1) 1m(-2)  -> 15
    assert simular("FIFO", REF, 3)[0] == 15


def test_lru_sequencia_classica():
    # 3 quadros, REF: resultado clássico do livro = 12 faltas
    # 7m 0m 1m 2m(-7) 0h 3m(-1) 0h 4m(-2) 2m(-3) 3m(-0) 0m(-4) 3h 2h
    # 1m(-0) 2h 0m(-3) 1h 7m(-2) 0h 1h  -> 12
    assert simular("LRU", REF, 3)[0] == 12


def test_mru_sequencia_classica():
    # 3 quadros; MRU expulsa o usado por último:
    # 7m 0m 1m | 2m(-1) 0h 3m(-0) 0m(-3) 4m(-0) 2h 3m(-2) 0m(-3) 3m(-0) 2m(-3)
    # 1m(-2) 2m(-1) 0m(-2) 1m(-0) 7h 0m(-7) 1h  -> 16 faltas
    faltas, finais = simular("MRU", REF, 3)
    assert faltas == 16 and finais == {4, 1, 0}


def test_clock_sequencia_classica():
    # 3 quadros, bit=1 na carga e no acesso; página nova ocupa a posição da vítima.
    # anel [7,0,1]; 2: zera 7,0,1, expulsa 7 -> [2,0,1] mão=1 ; 0h ; 3: zera 0, expulsa 1 -> [2,0,3] mão=0
    # 0h ; 4: zera 2,0,3, expulsa 2 -> [4,0,3] mão=1 ; 2: expulsa 0 (bit 0) -> [4,2,3] mão=2 ; 3h
    # 0: zera 3,4,2, expulsa 3 -> [4,2,0] mão=0 ; 3: expulsa 4 -> [3,2,0] mão=1 ; 2h
    # 1: zera 2,0,3, expulsa 2 -> [3,1,0] mão=2 ; 2: expulsa 0 -> [3,1,2] mão=0
    # 0: expulsa 3 -> [0,1,2] mão=1 ; 1h ; 7: zera 1,2,0, expulsa 1 -> [0,7,2] mão=2 ; 0h
    # 1: expulsa 2 -> [0,7,1]  -> 14 faltas
    faltas, finais = simular("CLOCK", REF, 3)
    assert faltas == 14 and finais == {0, 7, 1}


def test_fifo_anomalia_de_belady():
    # 1,2,3,4,1,2,5,1,2,3,4,5: FIFO com 3 quadros = 9 faltas; com 4 quadros = 10 faltas
    seq = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
    assert simular("FIFO", seq, 3)[0] == 9
    assert simular("FIFO", seq, 4)[0] == 10


def test_varredura_ciclica_mru_vence_lru():
    # 3 quadros, 3 voltas em 4 páginas (caso do loop interno do nested-loop, 13.5.2):
    # LRU: toda referência é falta (12). MRU: volta 1 = 4 faltas (4 expulsa 3);
    # volta 2: 1h 2h 3m(-2) 4h ; volta 3: 1h 2m(-1) 3h 4h -> 6 faltas
    seq = [1, 2, 3, 4] * 3
    assert simular("LRU", seq, 3)[0] == 12
    assert simular("MRU", seq, 3)[0] == 6


@pytest.mark.parametrize("nome", ["LRU", "MRU", "FIFO", "CLOCK"])
def test_toss_immediate_vira_proxima_vitima(nome):
    # 3 quadros: 1,2,3 (3 tossed) e depois 4 -> a vítima deve ser 3 em qualquer política
    _, finais = simular(nome, [1, 2, 3, 4], 3, toss={3})
    assert finais == {1, 2, 4}


@pytest.mark.parametrize("nome", ["LRU", "MRU", "FIFO", "CLOCK"])
def test_novo_acesso_cancela_toss(nome):
    pol = criar_politica(nome)
    frs = [Frame(0, b, bytearray(1)) for b in (1, 2)]
    for f in frs:
        pol.on_load(f)
    pol.on_unpin(frs[0], toss=True)
    pol.on_access(frs[0])
    pol.on_unpin(frs[0], toss=False)
    assert "toss" not in frs[0].extra


@pytest.mark.parametrize("nome", ["LRU", "MRU", "FIFO", "CLOCK"])
def test_vitima_ignora_pinadas(nome):
    pol = criar_politica(nome)
    frs = [Frame(0, b, bytearray(1)) for b in (1, 2, 3)]
    for f in frs:
        pol.on_load(f)
    for f in frs:
        f.pin_count = 1
    assert pol.victim(frs) is None
    frs[1].pin_count = 0
    assert pol.victim(frs) is frs[1]


def test_clock_pula_pinada_e_da_segunda_chance():
    pol = Clock()
    a, b, c = (Frame(0, i, bytearray(1)) for i in (1, 2, 3))
    for f in (a, b, c):
        pol.on_load(f)
    a.pin_count = 1                     # pinada: pulada
    v = pol.victim([a, b, c])           # zera b e c na 1ª volta, escolhe b na 2ª
    assert v is b and not c.ref_bit


def test_fabrica():
    assert isinstance(criar_politica("lru"), LRU)
    assert isinstance(criar_politica("MRU"), MRU)
    assert isinstance(criar_politica("Fifo"), FIFO)
    assert isinstance(criar_politica("CLOCK"), Clock)
    with pytest.raises(StorageError):
        criar_politica("OPT")
