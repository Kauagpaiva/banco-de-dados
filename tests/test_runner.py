"""Testes do orquestrador (M9/E14).

Enquanto o loader/registry do M8 não estão em `main`, o runner recebe um `Backend` de teste que
monta os métodos de acesso diretamente com as estruturas reais da Camada 3 (Heap, B+, Hash,
HashIndex). Volumes reduzidos por override para a matriz mínima rodar em segundos.
"""
from __future__ import annotations

import csv
import textwrap
from pathlib import Path

import pytest

from src.access.bplus import BPlusTree
from src.access.contracts import AccessMethod
from src.access.esquemas import ESQUEMAS
from src.access.hash_index import HashIndex
from src.access.hashfile import HashFile
from src.access.heap import HeapFile
from src.bench import datagen, runner
from src.common.config import load_config
from src.common.erros import ConfigError

VOLUMES = {"Curso": 4, "Disciplina": 12, "Turma": 20, "Aluno": 80,
           "Detalhes_do_Aluno": 80, "Inscricao_Aluno_Turma": 160}
OVERRIDES = {f"perfis.teste.{k}": v for k, v in VOLUMES.items()}


# ----------------------------------------------------------------------------- backend de teste
def _carregar(ctx, nome, espec, registros=None):
    esq = ESQUEMAS[nome]
    regs = list(registros if registros is not None else datagen.gerar_tabela(ctx.cfg, nome))
    arq = f"{nome}__{runner.rotulo_metodo(espec)}".replace("(", "_").replace(")", "_") \
        .replace(",", "_").replace("+", "_")
    if espec.org == "heap":
        t = HeapFile(ctx.bm, arq, esq)
    elif espec.org == "bplus":
        t = BPlusTree(ctx.bm, arq, esq, espec.campo, unique=espec.unique)
    else:
        t = HashFile(ctx.bm, arq, esq, espec.campo, unique=espec.unique, nr_estimado=len(regs))
    t.open()
    if espec.org == "bplus":
        t.bulk_load(sorted(regs, key=lambda r: r[espec.campo]))
    else:
        for r in regs:
            t.insert(r)
    indices = {}
    for ei in espec.indices:
        assert ei.tipo == "hash" and ei.unique, "backend de teste: só HashIndex UNIQUE"
        idx = HashIndex(ctx.bm, f"{arq}__{ei.campo}", esq.campo(ei.campo), nr_estimado=len(regs))
        idx.open()
        indices[ei.campo] = idx
    for rid, rec in t.scan():
        for campo, idx in indices.items():
            idx.insert(rec[campo], rid)
    return AccessMethod(t, indices, espec.nome)


def _inserir(am, rec):
    rid = am.tabela.insert(rec)
    for campo, idx in am.indices.items():
        idx.insert(rec[campo], rid)
    return rid


def _remover(am, rid):
    rec = am.tabela.read(rid)
    for campo, idx in am.indices.items():
        idx.delete(rec[campo], rid)
    am.tabela.delete(rid)


BACKEND = runner.Backend(carregar=_carregar, inserir=_inserir, remover=_remover)

MINI = """
nome: mini
politica: LRU
M: 6
repeticoes: {min: 3, max: 4, cv: 0.05}
overrides: %s
metodos:
  heap: {org: heap}
  bplus_DRE: {org: bplus, campo: DRE}
  hash_DRE: {org: hash, campo: DRE}
  heap_hashCPF: {org: heap, indices: [{campo: CPF, tipo: hash, unique: true}]}
  Curso_bplus: {org: bplus, campo: codigo}
pontos:
  - operacao: selecao
    tabela: Aluno
    predicado: {campo: DRE, op: "=", valor: $dre_meio}
    alternativas:
      - {metodo: heap, caminho: A1_chave}
      - {metodo: bplus_DRE, caminho: A2}
      - {metodo: hash_DRE, caminho: HASH_PRIM}
  - operacao: selecao
    tabela: Aluno
    metodo: heap_hashCPF
    caminho: HASH_SEC
    predicado: {campo: CPF, op: "=", valor: $cpf_meio}
  - operacao: selecao
    tabela: Aluno
    alternativas:
      - {metodo: heap, caminho: A1_linear, predicado: {campo: CR, op: ">", valor: $cr_x1}}
      - {metodo: bplus_DRE, caminho: A5, predicado: {campo: DRE, op: ">", valor: "$dre_frac:0.5"}}
  - operacao: juncao
    caso: a
    r: {tabela: Curso, campo: codigo, metodo: heap}
    s: {tabela: Aluno, campo: cod_curso, metodo: heap}
    alternativas:
      - {algoritmo: bnl, politica: MRU}
      - {algoritmo: smj}
      - {algoritmo: hash}
  - operacao: juncao
    caso: b
    algoritmo: inl
    r: {tabela: Aluno, campo: cod_curso, metodo: heap}
    s: {tabela: Curso, campo: codigo, metodo: Curso_bplus}
  - operacao: manutencao
    tabela: Aluno
    variar: {metodo: [heap, bplus_DRE, heap_hashCPF]}
""" % (OVERRIDES,)


def _ler_csv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def resultado(tmp_path_factory):
    d = tmp_path_factory.mktemp("runner")
    exp = d / "mini.yaml"
    exp.write_text(MINI, encoding="utf-8")
    saida = runner.executar_experimento(exp, "teste", d / "out" / "mini.csv",
                                        backend=BACKEND, pasta_dados=d / "dados")
    return saida, _ler_csv(saida)


# ----------------------------------------------------------------------------- matriz mínima
def test_csv_tem_todas_as_colunas(resultado):
    saida, linhas = resultado
    with open(saida, encoding="utf-8") as f:
        assert tuple(f.readline().strip().split(",")) == runner.COLUNAS
    assert linhas and all(set(l) == set(runner.COLUNAS) for l in linhas)


def test_ok_sqlite_em_todos_os_pontos(resultado):
    _, linhas = resultado
    ruins = [(l["operacao"], l["algoritmo"], l["caminho"], l["org_r"]) for l in linhas
             if l["ok_sqlite"] != "True"]
    assert not ruins


def test_pontos_e_repeticoes(resultado):
    _, linhas = resultado
    pontos = {}
    for l in linhas:
        k = (l["operacao"], l["algoritmo"], l["caminho"], l["org_r"], l["idx_r"], l["org_s"])
        pontos.setdefault(k, []).append(int(l["rep"]))
    assert len(pontos) == 3 + 1 + 2 + 3 + 1 + 3
    for k, reps in pontos.items():
        if k[0] == "manutencao":
            assert reps == [1]
        else:
            assert reps[:3] == [1, 2, 3] and len(reps) <= 4


def test_contagens_deterministicas_e_cold_start(resultado):
    _, linhas = resultado
    por_ponto = {}
    for l in linhas:
        if l["operacao"] != "manutencao":
            k = (l["algoritmo"], l["caminho"], l["org_r"], l["idx_r"], l["org_s"])
            por_ponto.setdefault(k, set()).add((l["leituras"], l["requests"], l["tuplas_saida"]))
    assert all(len(v) == 1 for v in por_ponto.values()), por_ponto
    assert all(int(l["leituras"]) > 0 for l in linhas if l["operacao"] != "manutencao")


def test_estimado_e_seletividade(resultado):
    _, linhas = resultado
    for l in linhas:
        if l["operacao"] == "manutencao":
            assert l["est_transf"] == "" and float(l["seletividade"]) == pytest.approx(0.05)
            continue
        assert float(l["est_transf"]) > 0 and l["dif_rel"] != ""
    sel = {l["caminho"]: l for l in linhas if l["operacao"] == "selecao" and l["rep"] == "1"}
    assert int(sel["A2"]["tuplas_saida"]) == 1 and int(sel["HASH_SEC"]["tuplas_saida"]) == 1
    assert float(sel["A1_linear"]["seletividade"]) == pytest.approx(0.01, abs=0.0126)
    assert float(sel["A5"]["seletividade"]) == pytest.approx(0.5)
    # BNL com MRU, demais LRU; M do ponto
    bnl = next(l for l in linhas if l["algoritmo"] == "bnl")
    assert bnl["politica"] == "MRU" and bnl["M"] == "6" and bnl["caminho"] == "caso_a"


def test_ocupacao_antes_depois(resultado):
    saida, _ = resultado
    ocup = _ler_csv(saida.with_name("mini_ocupacao.csv"))
    momentos = {(o["metodo"], o["estrutura"], o["momento"]) for o in ocup}
    for m in ("heap", "bplus_DRE", "heap_hashCPF"):
        for mom in ("carga", "antes_manutencao", "depois_manutencao"):
            assert (m, "organizacao", mom) in momentos
    assert ("heap_hashCPF", "indice(CPF)", "depois_manutencao") in momentos
    regs = {o["momento"]: o["registros"] for o in ocup
            if o["metodo"] == "heap" and o["estrutura"] == "organizacao"
            and o["tabela"] == "Aluno"}
    assert regs["antes_manutencao"] == regs["depois_manutencao"] == str(VOLUMES["Aluno"])


# ----------------------------------------------------------------------------- YAMLs do projeto
@pytest.mark.parametrize("perfil", ["teste", "medio", "completo"])
@pytest.mark.parametrize("arq", runner.listar_experimentos(), ids=lambda p: p.stem)
def test_yamls_do_projeto_validos(arq, perfil):
    exp = runner.carregar_experimento(arq, perfil)
    pontos = runner.expandir_pontos(exp)
    assert pontos
    for p in pontos:
        cfg = load_config(perfil, overrides=p["overrides"])       # overrides válidos
        if p["M"] is not None:
            assert 3 <= p["M"] <= cfg.M
        if p["operacao"] == "selecao":
            runner.resolver_valor(p["predicado"].valor, cfg)


def test_matriz_do_join_natural():
    exp = runner.carregar_experimento(runner.DIR_EXP / "join_natural.yaml", "teste")
    pontos = runner.expandir_pontos(exp)
    trios = [p for p in pontos if p["algoritmo"] != "inl"]
    assert len(trios) == 5 * 3 * 3
    assert {p["caminho"] for p in trios} == {f"caso_{c}" for c in "abcde"}
    assert {p["algoritmo"] for p in trios} == {"bnl", "smj", "hash"}
    assert all(p["politica"] == ("MRU" if p["algoritmo"] == "bnl" else "LRU") for p in trios)
    assert len([p for p in pontos if p["algoritmo"] == "inl"]) == 4 * 3


def test_existem_os_experimentos_pedidos():
    nomes = {p.stem for p in runner.listar_experimentos()}
    assert {"sel_igualdade", "sel_faixa", "join_natural", "join_unique", "join_nonunique",
            "politicas_buffer", "manutencao"} <= nomes


# ----------------------------------------------------------------------------- unidades
def test_cv():
    assert runner.cv([]) == 0 and runner.cv([5.0]) == 0 and runner.cv([0.0, 0.0]) == 0
    assert runner.cv([1.0, 1.0, 1.0]) == 0
    assert runner.cv([1.0, 3.0]) == pytest.approx(0.5)


def test_expansao_variar_e_alternativas():
    exp = {"politica": "LRU", "overrides": {}, "metodos": {"h": {"org": "heap"}},
           "pontos": [{"operacao": "selecao", "tabela": "Aluno", "metodo": "h",
                       "predicado": {"campo": "CR", "op": ">", "valor": 1.0},
                       "alternativas": {"g1": [{"caminho": "A1_linear"}, {"caminho": "A1_linear",
                                                                         "politica": "MRU"}],
                                        "g2": [{"M": 4}, {"M": 5}]},
                       "variar": {"predicado.valor": [1.0, 2.0, 3.0]}}]}
    pontos = runner.expandir_pontos(exp)
    assert len(pontos) == 2 * 2 * 3
    assert {p["politica"] for p in pontos} == {"LRU", "MRU"}
    assert {p["predicado"].valor for p in pontos} == {1.0, 2.0, 3.0}


@pytest.mark.parametrize("ruim", [
    {"operacao": "projecao"},
    {"operacao": "selecao", "tabela": "Nada", "metodo": "h", "caminho": "A1_linear",
     "predicado": {"campo": "CR", "op": ">", "valor": 1}},
    {"operacao": "selecao", "tabela": "Aluno", "metodo": "inexistente", "caminho": "A1_linear",
     "predicado": {"campo": "CR", "op": ">", "valor": 1}},
    {"operacao": "selecao", "tabela": "Aluno", "metodo": "h", "caminho": "A9",
     "predicado": {"campo": "CR", "op": ">", "valor": 1}},
    {"operacao": "juncao", "algoritmo": "nested", "r": {"tabela": "Curso", "campo": "codigo",
     "metodo": "h"}, "s": {"tabela": "Aluno", "campo": "cod_curso", "metodo": "h"}},
    {"operacao": "juncao", "algoritmo": "bnl", "r": {"tabela": "Curso", "campo": "xx",
     "metodo": "h"}, "s": {"tabela": "Aluno", "campo": "cod_curso", "metodo": "h"}},
    {"operacao": "manutencao", "tabela": "Aluno", "metodo": "h", "frac": 1.5},
    {"operacao": "selecao", "tabela": "Aluno", "metodo": {"org": "bplus"}, "caminho": "A5",
     "predicado": {"campo": "CR", "op": ">", "valor": 1}},
    {"operacao": "selecao", "tabela": "Aluno", "metodo": "h", "caminho": "A1_linear",
     "politica": "ARC", "predicado": {"campo": "CR", "op": ">", "valor": 1}},
])
def test_pontos_invalidos(ruim):
    exp = {"politica": "LRU", "overrides": {}, "metodos": {"h": {"org": "heap"}}, "pontos": [ruim]}
    with pytest.raises(ConfigError):
        runner.expandir_pontos(exp)


def test_valores_simbolicos():
    cfg = load_config("teste", overrides=OVERRIDES)
    n = VOLUMES["Aluno"]
    assert runner.resolver_valor("$dre_meio", cfg) == datagen.dre(cfg, n // 2)
    assert runner.resolver_valor("$cr_x1", cfg) == datagen.limiares_cr(cfg)["x1"]
    assert runner.resolver_valor(7, cfg) == 7
    with pytest.raises(ConfigError):
        runner.resolver_valor("$nada", cfg)
    with pytest.raises(ConfigError):
        runner.resolver_valor("$dre_frac:1.0", cfg)


def test_repeticoes_invalidas(tmp_path):
    arq = tmp_path / "x.yaml"
    arq.write_text(textwrap.dedent("""
        repeticoes: {min: 5, max: 3, cv: 0.05}
        pontos: [{operacao: selecao}]
    """), encoding="utf-8")
    with pytest.raises(ConfigError):
        runner.carregar_experimento(arq)


def test_cli_saida_exige_um_exp(capsys):
    with pytest.raises(SystemExit):
        runner.main(["--exp", "a.yaml", "b.yaml", "--saida", "x.csv"])


def test_cli_roda_experimento(tmp_path, monkeypatch):
    """CLI com o loader padrão substituído (monkeypatch) pelo de teste."""
    from src.bench import loader
    from src.executor import fachada
    monkeypatch.setattr(loader, "carregar", _carregar)
    monkeypatch.setattr(fachada, "inserir", _inserir)
    monkeypatch.setattr(fachada, "remover", _remover)
    monkeypatch.setattr(runner.Config, "perfil_dir", property(lambda self: tmp_path / "dados"),
                        raising=False)
    exp = tmp_path / "cli.yaml"
    exp.write_text(textwrap.dedent(f"""
        repeticoes: {{min: 3, max: 3, cv: 0.05}}
        overrides: {OVERRIDES}
        pontos:
          - {{operacao: selecao, tabela: Curso, metodo: {{org: heap}}, caminho: A1_linear,
              predicado: {{campo: codigo, op: ">=", valor: 0}}}}
    """), encoding="utf-8")
    saida = tmp_path / "cli.csv"
    assert runner.main(["--perfil", "teste", "--exp", str(exp), "--saida", str(saida)]) == 0
    linhas = _ler_csv(saida)
    assert len(linhas) == 3 and all(l["ok_sqlite"] == "True" for l in linhas)
    assert all(l["tuplas_saida"] == str(VOLUMES["Curso"]) for l in linhas)
