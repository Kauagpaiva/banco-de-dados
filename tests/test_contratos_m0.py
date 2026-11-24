"""E00b: tipos compartilhados, esquemas, merge de config/modulos e fixtures do conftest."""
import textwrap

import pytest

from src.access.contracts import Campo, Esquema, esquema_juncao
from src.access.esquemas import ESQUEMAS, FKS
from src.common.config import load_config
from src.common.erros import ConfigError
from src.common.tipos import (
    CAMINHOS_SELECAO, CondJuncao, Predicado, diferenca_metricas, metricas_vazias,
)
from src.executor.contracts import combinar
from tests.fakes import FakeCatalog, FakeTable, registros_fake, validar_registro


# ------------------------------------------------------------------ tipos
def test_predicado():
    r = {"CR": 7.5, "x": None}
    assert Predicado("CR", ">", 7).avaliar(r)
    assert not Predicado("CR", "<=", 7).avaliar(r)
    assert not Predicado("x", "=", None).avaliar(r)     # nulo nunca satisfaz
    with pytest.raises(ValueError):
        Predicado("CR", "!=", 1).validar()


def test_metricas_e_caminhos():
    a = {**metricas_vazias(), "requests": 10, "hits": 4, "reads": 6}
    b = {**metricas_vazias(), "requests": 30, "hits": 24, "reads": 6}
    d = diferenca_metricas(b, a)
    assert d["requests"] == 20 and d["hits"] == 20 and d["hit_rate"] == 1.0 and d["reads"] == 0
    assert len(CAMINHOS_SELECAO) == 9 and "HASH_SEC" in CAMINHOS_SELECAO


def test_combinar_e_esquema_juncao():
    c = CondJuncao("cod_curso", "codigo")
    assert c.campo_r == "cod_curso"
    out = combinar("Aluno", {"DRE": 1, "nome": "a"}, "Curso", {"codigo": 2, "nome": "b"})
    assert out == {"Aluno.DRE": 1, "Aluno.nome": "a", "Curso.codigo": 2, "Curso.nome": "b"}
    e = esquema_juncao(ESQUEMAS["Aluno"], ESQUEMAS["Curso"])
    assert e.nomes()[0] == "Aluno.CPF" and len(e.campos) == 18


# ------------------------------------------------------------------ esquemas
def test_esquemas():
    assert set(ESQUEMAS) == set(load_config().volumes)
    for (t, c), (rt, rc) in FKS.items():
        assert ESQUEMAS[t].campo(c).tipo == ESQUEMAS[rt].campo(rc).tipo
    assert ESQUEMAS["Inscricao_Aluno_Turma"].chave == ("DRE", "numero_turma")
    for e in ESQUEMAS.values():
        for r in registros_fake(e, 20):
            validar_registro(e, r)


def test_campo_e_esquema_invalidos():
    with pytest.raises(ValueError):
        Campo("x", "text")
    with pytest.raises(ValueError):
        Esquema("E", (Campo("a", "int"),), chave=("b",))
    c = Campo("l", "list[varchar(7)]")
    assert (c.base, c.n, c.variavel) == ("list", 7, True)


# ------------------------------------------------------------------ config/modulos
def _base(tmp_path, extra=None):
    from src.common.config import CONFIG_PADRAO
    (tmp_path / "base.yaml").write_text(CONFIG_PADRAO.read_text(encoding="utf-8"), encoding="utf-8")
    if extra is not None:
        (tmp_path / "modulos").mkdir()
        (tmp_path / "modulos" / "M9.yaml").write_text(textwrap.dedent(extra), encoding="utf-8")
    return tmp_path / "base.yaml"


def test_modulos_acrescentam_chaves(tmp_path):
    cfg = load_config(caminho=_base(tmp_path, """
        runner:
          cv_max: 0.05
        hash:
          funcao_alternativa: djb2
    """))
    assert cfg.raw["runner"]["cv_max"] == 0.05
    assert cfg.raw["hash"]["funcao_alternativa"] == "djb2" and cfg.hash_funcao == "fnv1a64"


def test_modulo_nao_redefine_chave(tmp_path):
    with pytest.raises(ConfigError):
        load_config(caminho=_base(tmp_path, "buffer:\n  policy: MRU\n"))


# ------------------------------------------------------------------ fixtures
def test_fixtures_basicas(cfg, bm, ctx, page_impl, codec):
    assert bm.block_size == cfg.block_size
    assert ctx.work_capacity() == cfg.M
    e = ESQUEMAS["Curso"]
    r = next(registros_fake(e, 1))
    assert codec(e).decode(codec(e).encode(r)) == r
    buf = bytearray(cfg.block_size)
    page_impl.format(buf)
    assert page_impl.count(buf) == 0


def test_fixture_tabela(tabela):
    t = tabela("Aluno", 200)
    assert t.num_registros() == 200 and t.num_blocks() > 1
    assert sum(1 for _ in t.scan()) == 200


def test_fixture_detecta_pin_pendente(cfg):
    """O autouse `_buffers_sem_pins` usa assert_no_pins: confere que ele acusa pin pendente."""
    from tests.conftest import bm_fake
    b = bm_fake(cfg)
    fid = b.create("x", "heap")
    fr = b.new_page(fid)
    with pytest.raises(AssertionError):
        b.assert_no_pins()
    b.unpin(fr)


def test_iterador_nao_segura_pin(bm):
    t = FakeTable(bm, "h", ESQUEMAS["Turma"])
    t.open()
    for r in registros_fake(ESQUEMAS["Turma"], 100):
        t.insert(r)
    it = t.scan()
    next(it)
    bm.assert_no_pins()           # entre yields nenhuma página fica pinada
    it.close()


def test_fake_catalogo():
    c = FakeCatalog()
    c.registrar_tabela(ESQUEMAS["Aluno"], "heap")
    c.registrar_indice("Aluno", "idx_cpf", "CPF", "hash", unique=True)
    c.atualizar_estatisticas("Aluno", nr=100, br=10, V={"CPF": 100}, fr=10.0)
    c.atualizar_indice("Aluno", "CPF", altura=1, num_blocks=3)
    c.definir("limiares_cr", {"x1": 9.5})
    t = c.tabela("Aluno")
    assert (t.nr, t.br, t.V["CPF"], t.indice("CPF").num_blocks) == (100, 10, 100, 3)
    assert c.obter("limiares_cr")["x1"] == 9.5 and c.obter("nada", 0) == 0
