"""Testes do hash estático externo (M4/E07) — Silberschatz 14.5.

Rodam sobre o BufferManager real (M1) e a SlottedPage/codec reais quando existirem
(senão os fakes do M0, via fixtures `page_impl`/`codec`).
"""
import random

import pytest

from src.access.esquemas import ALUNO, TURMA
from src.access.hashfile import FUNCOES_HASH, HashFile, chave_bytes, fnv1a64
from src.common.config import load_config
from src.common.erros import ChaveDuplicadaError, ConfigError, OperacaoNaoSuportada
from src.common.tipos import RID
from tests.conftest import bm_fake, bm_real, real_ou_fake
from tests.fakes import registros_fake

N = 300


@pytest.fixture
def novo_bm(tmp_path, so_fakes, _buffers_sem_pins):
    """Fábrica de buffer com overrides de configuração (ex.: função de hash)."""
    cont = {"n": 0}

    def fabrica(**overrides):
        cont["n"] += 1
        cfg = load_config("teste", overrides=overrides or None)
        b = real_ou_fake(lambda: bm_real(cfg, tmp_path / f"bm{cont['n']}"),
                         lambda: bm_fake(cfg), so_fakes)
        _buffers_sem_pins.append(b)
        return b
    return fabrica


def _hf(bm, page_impl, codec, *, campo="numero", unique=True, esquema=TURMA, **kw):
    if "n_buckets" not in kw:
        kw.setdefault("nr_estimado", N)
    h = HashFile(bm, f"h_{campo}", esquema, campo, unique=unique, page_impl=page_impl,
                 codec=codec(esquema), **kw)
    h.open()
    return h


def _todos(h):
    return sorted((r for _, r in h.scan()), key=lambda r: r["numero"])


# ----------------------------------------------------------------------------- função de hash
def test_fnv1a64_vetores_conhecidos():
    assert fnv1a64(b"") == 0xCBF29CE484222325
    assert fnv1a64(b"a") == 0xAF63DC4C8601EC8C
    assert fnv1a64(b"foobar") == 0x85944171F73967E8
    assert fnv1a64(bytearray(b"foobar")) == fnv1a64(b"foobar")


def test_chave_bytes_deterministica_e_tipada():
    assert chave_bytes(12) == chave_bytes(12) != chave_bytes("12")
    assert chave_bytes(None) != chave_bytes("")
    with pytest.raises(TypeError):
        chave_bytes(object())


def test_funcao_desconhecida(novo_bm, page_impl, codec):
    bm = novo_bm(**{"hash.funcao": "md5"})
    with pytest.raises(ConfigError):
        HashFile(bm, "x", TURMA, "numero", nr_estimado=10, page_impl=page_impl, codec=codec(TURMA))


def test_exige_dimensionamento(bm, page_impl, codec):
    with pytest.raises(ValueError):
        HashFile(bm, "x", TURMA, "numero", page_impl=page_impl, codec=codec(TURMA))


# ----------------------------------------------------------------------------- estrutura
def test_buckets_contiguos_e_dimensionamento(bm, page_impl, codec):
    h = _hf(bm, page_impl, codec)
    nb = h.n_buckets
    fr = h._fr_estimado()
    import math
    assert nb == math.ceil(N / (fr * bm.cfg.hash_fill_factor))
    oc = h.ocupacao()
    assert oc == {"dados": nb, "overflow": 0, "indice": 0, "total": nb, "registros": 0}
    assert [b for b, _ in h._blocos_fisicos()] == list(range(1, nb + 1))


def test_busca_igualdade_custa_um_bloco_sem_overflow(bm, page_impl, codec):
    h = _hf(bm, page_impl, codec)
    recs = list(registros_fake(TURMA, N, seed=1))
    for r in recs:
        h.insert(r)
    assert h.estatisticas()["overflow"] == 0
    bm.reset_stats()
    rid = h.find("numero", recs[77]["numero"])
    assert h.read(rid) == recs[77]
    assert h.find_next() is None
    assert bm.stats()["requests"] == 2              # bucket (find) + bucket (read)


def test_scan_ve_tudo_incluindo_overflow(novo_bm, page_impl, codec):
    bm = novo_bm()
    h = _hf(bm, page_impl, codec, n_buckets=3)       # poucos buckets → overflow garantido
    recs = list(registros_fake(TURMA, N, seed=2))
    for r in recs:
        h.insert(r)
    est = h.estatisticas()
    assert est["overflow"] > 0 and est["buckets"] == 3
    assert _todos(h) == recs
    blocos = list(h.scan_blocos())
    assert len(blocos) == h.num_blocks() == 3 + est["overflow"]
    assert sum(len(b) for b in blocos) == N
    oc = h.ocupacao()
    assert oc["overflow"] == est["overflow"] and oc["total"] == oc["dados"] + oc["overflow"]


def test_unique_rejeita_duplicata(bm, page_impl, codec):
    h = _hf(bm, page_impl, codec)
    r = next(registros_fake(TURMA, 1))
    h.insert(r)
    with pytest.raises(ChaveDuplicadaError):
        h.insert(dict(r, sala="Z"))
    assert h.num_registros() == 1


def test_find_ordered_nao_suportado(bm, page_impl, codec):
    h = _hf(bm, page_impl, codec)
    with pytest.raises(OperacaoNaoSuportada):
        h.find_ordered("numero", 1, 2)


# ----------------------------------------------------------------------------- pior caso
def test_funcao_degenerada_cadeia_longa(novo_bm, page_impl, codec):
    bm = novo_bm(**{"hash.funcao": "degenerada"})
    h = _hf(bm, page_impl, codec, n_buckets=8)
    recs = list(registros_fake(TURMA, N, seed=4))
    for r in recs:
        h.insert(r)
    est = h.estatisticas()
    assert est["cadeia_max"] == est["overflow"] >= 5      # tudo no bucket 0
    assert est["cv_ocupacao"] > 2
    # busca correta em qualquer posição da cadeia (inclusive no fim)
    for r in recs[::23] + [recs[-1]]:
        assert h.read(h.find("numero", r["numero"])) == r
    assert h.find("numero", -5) is None
    # remoção percorre a cadeia toda; blocos de overflow vazios são liberados
    for r in recs[: N // 2]:
        h.delete(h.find("numero", r["numero"]))
    assert h.find("numero", recs[0]["numero"]) is None
    assert _todos(h) == recs[N // 2:]
    assert h.num_blocks() == 8 + h.estatisticas()["overflow"]
    for r in recs[N // 2:]:
        h.delete(h.find("numero", r["numero"]))
    assert h.num_registros() == 0
    assert h.estatisticas()["overflow"] == 0 and h.num_blocks() == 8
    # blocos liberados são reaproveitados e a cadeia volta a funcionar
    for r in recs[:50]:
        h.insert(r)
    assert _todos(h) == recs[:50]


def test_delete_meio_da_cadeia_preserva_resto(novo_bm, page_impl, codec):
    bm = novo_bm(**{"hash.funcao": "degenerada"})
    h = _hf(bm, page_impl, codec, n_buckets=1)
    recs = list(registros_fake(TURMA, N, seed=5))
    rids = {r["numero"]: h.insert(r) for r in recs}
    # esvazia um bloco de overflow do meio
    blocos = sorted({rid.bloco for rid in rids.values()})
    meio = blocos[len(blocos) // 2]
    alvo = [n for n, rid in rids.items() if rid.bloco == meio]
    antes = h.estatisticas()["overflow"]
    for n in alvo:
        h.delete(h.find("numero", n))
    assert h.estatisticas()["overflow"] == antes - 1
    assert sorted(r["numero"] for _, r in h.scan()) == sorted(set(rids) - set(alvo))
    with pytest.raises(KeyError):
        h.read(RID(1, 10_000))


# ----------------------------------------------------------------------------- dispersão
def _dispersao(func, chaves, nb):
    cont = [0] * nb
    for k in chaves:
        cont[func(chave_bytes(k)) % nb] += 1
    media = len(chaves) / nb
    var = sum((c - media) ** 2 for c in cont) / nb
    qui2 = sum((c - media) ** 2 / media for c in cont)
    return var ** 0.5 / media, qui2


def test_dispersao_cpf_e_dre():
    rng = random.Random(42)
    nb = 101
    cpfs = [f"{rng.randrange(10**11):011d}" for _ in range(5000)]
    dres = [119_000_000 + rng.randrange(10**6) for _ in range(5000)]
    seq = list(range(1, 5001))                       # chaves sequenciais (pior caso comum)
    for chaves in (cpfs, dres, seq):
        cv, qui2 = _dispersao(fnv1a64, chaves, nb)
        # E[cv] ≈ sqrt(nb/n) ≈ 0.14 para hash uniforme; qui² com nb-1 g.l. ≈ 100 ± 14
        assert cv < 0.25, cv
        assert qui2 < 160, qui2
    # a soma dos bytes concentra as chaves: muito pior que FNV-1a
    cv_soma, _ = _dispersao(FUNCOES_HASH["soma"], cpfs, nb)
    assert cv_soma > 2 * _dispersao(fnv1a64, cpfs, nb)[0]


def test_dispersao_no_arquivo(bm, page_impl, codec):
    regs = list(registros_fake(ALUNO, 1000, seed=7))
    h = HashFile(bm, "aluno_cpf", ALUNO, "CPF", unique=False, nr_estimado=1000,
                 page_impl=page_impl, codec=codec(ALUNO))
    h.open()
    for r in regs:
        h.insert(r)
    est = h.estatisticas()
    assert set(est) == {"buckets", "overflow", "cadeia_max", "cadeia_media", "fator_carga",
                        "cv_ocupacao"}
    # hash uniforme ⇒ ocupação ~ Poisson(λ = nr/nB) ⇒ CV esperado ≈ 1/sqrt(λ)
    esperado = (est["buckets"] / len(regs)) ** 0.5
    assert est["cv_ocupacao"] < 1.3 * esperado, (est["cv_ocupacao"], esperado)
    assert 0 < est["fator_carga"] <= 1.0
    for r in regs[::97]:
        assert r in [h.read(rid) for rid, _ in h.find_all("CPF", "=", r["CPF"])]


# ----------------------------------------------------------------------------- NOT UNIQUE
def test_not_unique_com_duplicatas(novo_bm, page_impl, codec):
    bm = novo_bm()
    h = _hf(bm, page_impl, codec, campo="semestre", unique=False, n_buckets=4)
    recs = list(registros_fake(TURMA, N, seed=6))
    for r in recs:
        h.insert(r)
    for sem in sorted({r["semestre"] for r in recs}):
        esperado = sorted(r["numero"] for r in recs if r["semestre"] == sem)
        achados, rid = [], h.find("semestre", sem)
        while rid is not None:
            achados.append(h.read(rid)["numero"])
            rid = h.find_next()
        assert sorted(achados) == esperado
        assert sorted(r["numero"] for _, r in h.find_all("semestre", "=", sem)) == esperado
    # remove todas as duplicatas de um valor
    sem0 = recs[0]["semestre"]
    for rid, _ in list(h.find_all("semestre", "=", sem0)):
        h.delete(rid)
    assert h.find("semestre", sem0) is None
    assert h.num_registros() == sum(r["semestre"] != sem0 for r in recs)
    assert list(h.find_all("numero", ">", 10 ** 9)) == []


# ----------------------------------------------------------------------------- update/reabrir
def test_update(bm, page_impl, codec):
    h = _hf(bm, page_impl, codec)
    recs = list(registros_fake(TURMA, 50, seed=8))
    for r in recs:
        h.insert(r)
    rid = h.find("numero", 10)
    novo = h.update(rid, dict(recs[9], sala="S-1"))
    assert h.read(novo)["sala"] == "S-1"
    # muda a chave → vai para outro bucket
    rid = h.update(h.find("numero", 11), dict(recs[10], numero=999))
    assert h.read(rid)["numero"] == 999 and h.find("numero", 11) is None
    # chave nova repetida → erro e registro original preservado
    with pytest.raises(ChaveDuplicadaError):
        h.update(h.find("numero", 12), dict(recs[11], numero=13))
    assert h.read(h.find("numero", 12)) == recs[11]
    assert h.num_registros() == 50


def test_reabrir_com_overflow(novo_bm, page_impl, codec):
    bm = novo_bm()
    h = _hf(bm, page_impl, codec, n_buckets=2)
    recs = list(registros_fake(TURMA, N, seed=9))
    for r in recs:
        h.insert(r)
    est = h.estatisticas()
    h.close()
    h2 = HashFile(bm, "h_numero", TURMA, "numero", n_buckets=99, page_impl=page_impl,
                  codec=codec(TURMA))
    h2.open()                                        # nB vem do cabeçalho, não do construtor
    assert h2.n_buckets == 2 and h2.num_registros() == N
    assert h2.estatisticas() == est
    assert _todos(h2) == recs
    h2.reorganize()
    assert _todos(h2) == recs
    h2.close()
