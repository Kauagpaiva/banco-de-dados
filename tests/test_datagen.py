"""E09 (M7): gerador determinístico da base + referência SQLite.

Aceite: seletividades reais dentro de ±0,3 p.p. de 1% e 50%; contagens iguais no SQLite;
FKs válidas. Também: registros válidos pelo esquema, chaves únicas, determinismo, cardinalidade
controlada de `professor` (equijoin NOT UNIQUE Aluno.prof_orientador = Turma.professor).
"""
from __future__ import annotations

import datetime as dt
import json
import math
from collections import Counter

import pytest

from src.bench import datagen, sqlite_ref
from src.common.config import load_config
from src.common.erros import ConfigError
from src.executor.fachada import ESQUEMAS, FKS
from tests.fakes.access import validar_registro

TABELAS = list(ESQUEMAS)


@pytest.fixture(scope="module")
def cfg_teste():
    return load_config("teste")


@pytest.fixture(scope="module")
def base(cfg_teste):
    return {nome: list(datagen.gerar_tabela(cfg_teste, nome)) for nome in TABELAS}


@pytest.fixture(scope="module")
def ref(cfg_teste, tmp_path_factory):
    return sqlite_ref.exportar(cfg_teste, tmp_path_factory.mktemp("sqlite") / "ref.sqlite")


def _chave(esq, r):
    return tuple(r[k] for k in esq.chave)


# --------------------------------------------------------------------------- gerador
@pytest.mark.parametrize("nome", TABELAS)
def test_volume_e_registros_validos(cfg_teste, base, nome):
    regs = base[nome]
    assert len(regs) == cfg_teste.volumes[nome]
    for r in regs:
        validar_registro(ESQUEMAS[nome], r)


@pytest.mark.parametrize("nome", TABELAS)
def test_chave_unica(base, nome):
    esq = ESQUEMAS[nome]
    chaves = [_chave(esq, r) for r in base[nome]]
    assert len(set(chaves)) == len(chaves)


def test_cpf_unico_e_valido(base):
    cpfs = [r["CPF"] for r in base["Aluno"]]
    assert len(set(cpfs)) == len(cpfs)
    for c in cpfs[:200]:
        assert len(c) == 11 and c.isdigit()
        d = [int(x) for x in c]
        for pos in (9, 10):
            s = sum(x * p for x, p in zip(d[:pos], range(pos + 1, 1, -1)))
            assert d[pos] == (0 if (s * 10) % 11 == 10 else (s * 10) % 11)


@pytest.mark.parametrize("fk", sorted(FKS))
def test_fks_validas(base, fk):
    (tab, campo), (ref, campo_ref) = fk, FKS[fk]
    alvo = {r[campo_ref] for r in base[ref]}
    assert all(r[campo] in alvo for r in base[tab])


def test_detalhes_1_para_1(base):
    assert {r["CPF"] for r in base["Detalhes_do_Aluno"]} <= {r["CPF"] for r in base["Aluno"]}
    assert len({r["CPF"] for r in base["Detalhes_do_Aluno"]}) == len(base["Detalhes_do_Aluno"])


@pytest.mark.parametrize("nome", TABELAS)
def test_deterministico(cfg_teste, base, nome):
    assert list(datagen.gerar_tabela(cfg_teste, nome)) == base[nome]


def test_semente_diferente_muda_a_base(base):
    outra = load_config("teste", {"seed": 7})
    assert list(datagen.gerar_tabela(outra, "Aluno")) != base["Aluno"]


def test_ordem_de_insercao_embaralhada(base):
    dres = [r["DRE"] for r in base["Aluno"]]
    assert dres != sorted(dres) and dres != sorted(dres, reverse=True)


def test_tabela_desconhecida(cfg_teste):
    with pytest.raises(KeyError):
        datagen.gerar_tabela(cfg_teste, "Professor")


def test_detalhes_maior_que_aluno_e_erro():
    cfg = load_config("teste", {"perfis": {"teste": {"Detalhes_do_Aluno": 5000}}})
    with pytest.raises(ConfigError):
        list(datagen.gerar_tabela(cfg, "Detalhes_do_Aluno"))


# --------------------------------------------------------------------------- CR
def _seletividades(cfg):
    lim = datagen.limiares_cr(cfg)
    crs = [r["CR"] for r in datagen.gerar_tabela(cfg, "Aluno")]
    n = len(crs)
    return lim, sum(c > lim["x1"] for c in crs) / n, sum(c < lim["x50"] for c in crs) / n, crs


@pytest.mark.parametrize("perfil", ["teste", "medio", "completo"])
def test_seletividade_cr(perfil):
    """Aceite E09: CR > x1 ≈ 1% e CR < x50 ≈ 50% dentro de ±0,3 p.p."""
    lim, s1, s50, crs = _seletividades(load_config(perfil))
    assert abs(s1 - 0.01) <= 0.003, (lim, s1)
    assert abs(s50 - 0.50) <= 0.003, (lim, s50)
    assert all(0.0 <= c <= 10.0 for c in crs)
    assert lim["x50"] < lim["x1"]


def test_cr_e_distribuicao_nao_degenerada(base):
    crs = [r["CR"] for r in base["Aluno"]]
    assert len(set(crs)) > 0.9 * len(crs)
    media = sum(crs) / len(crs)
    assert 6.0 < media < 7.0


# --------------------------------------------------------------------------- professor
def test_professor_cardinalidade_controlada(cfg_teste, base):
    P = datagen.n_professores(cfg_teste)
    nt = cfg_teste.volumes["Turma"]
    por_prof = Counter(r["professor"] for r in base["Turma"])
    assert len(por_prof) == P
    assert set(por_prof.values()) <= {nt // P, math.ceil(nt / P)}
    orient = [r["prof_orientador"] for r in base["Aluno"]]
    assert {o for o in orient if o is not None} <= set(por_prof)
    frac_nulo = sum(o is None for o in orient) / len(orient)
    assert abs(frac_nulo - cfg_teste.raw["datagen"]["frac_sem_orientador"]) < 0.04
    # junção NOT UNIQUE: cada aluno com orientador casa com várias turmas
    tam = sum(por_prof[o] for o in orient if o is not None)
    assert tam > len(orient)


# --------------------------------------------------------------------------- SQLite
@pytest.mark.parametrize("nome", TABELAS)
def test_sqlite_contagens_iguais(cfg_teste, ref, nome):
    (n,), = sqlite_ref.consultar(ref, f'SELECT COUNT(*) FROM "{nome}"')
    assert n == cfg_teste.volumes[nome]


def test_sqlite_fks_validas(ref):
    assert sqlite_ref.consultar(ref, "PRAGMA foreign_key_check") == []
    (n,), = sqlite_ref.consultar(ref, """SELECT COUNT(*) FROM Inscricao_Aluno_Turma i
        LEFT JOIN Aluno a ON a.DRE = i.DRE WHERE a.DRE IS NULL""")
    assert n == 0


def test_sqlite_meta_e_seletividade(cfg_teste, ref, base):
    meta = dict(sqlite_ref.consultar(ref, "SELECT chave, valor FROM _meta"))
    lim = datagen.limiares_cr(cfg_teste)
    assert float(meta["x1"]) == lim["x1"] and float(meta["x50"]) == lim["x50"]
    assert int(meta["seed"]) == cfg_teste.seed
    (n1,), = sqlite_ref.consultar(ref, "SELECT COUNT(*) FROM Aluno WHERE CR > ?", (lim["x1"],))
    assert n1 == sum(r["CR"] > lim["x1"] for r in base["Aluno"])


def test_sqlite_juncao_professor_igual_python(ref, base):
    (n,), = sqlite_ref.consultar(ref, """SELECT COUNT(*) FROM Aluno a
        JOIN Turma t ON a.prof_orientador = t.professor""")
    por_prof = Counter(r["professor"] for r in base["Turma"])
    assert n == sum(por_prof[r["prof_orientador"]] for r in base["Aluno"]
                    if r["prof_orientador"] is not None)


def test_sqlite_valores_preservados(ref, base):
    r = base["Aluno"][0]
    linha, = sqlite_ref.consultar(ref, "SELECT * FROM Aluno WHERE DRE = ?", (r["DRE"],))
    d = dict(zip(ESQUEMAS["Aluno"].nomes(), linha))
    assert json.loads(d["emails"]) == r["emails"]
    assert dt.date.fromisoformat(d["data_nasc"]) == r["data_nasc"]
    assert d["CR"] == r["CR"] and d["CPF"] == r["CPF"]


def test_exportar_caminho_padrao_e_sobrescreve(tmp_path):
    cfg = load_config("teste", {"disco.data_dir": str(tmp_path)})
    p1 = sqlite_ref.exportar(cfg)
    assert p1 == tmp_path / "teste" / "ref.sqlite"
    p2 = sqlite_ref.exportar(cfg)  # reexportar não falha nem duplica
    (n,), = sqlite_ref.consultar(p2, "SELECT COUNT(*) FROM Curso")
    assert n == cfg.volumes["Curso"]
    assert not (tmp_path / "teste" / "ref.sqlite.tmp").exists()


def test_consultar_banco_ausente(tmp_path):
    with pytest.raises(FileNotFoundError):
        sqlite_ref.consultar(tmp_path / "nao_existe.sqlite", "SELECT 1")


def test_consultar_somente_leitura(ref):
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        sqlite_ref.consultar(ref, "DELETE FROM Curso")
