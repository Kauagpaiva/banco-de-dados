"""Orquestrador da matriz de experimentos — M9 (E14).

CLI: `python -m src.bench.runner --perfil teste --exp config/experimentos/sel_igualdade.yaml`
(`--exp todos` roda todos os `config/experimentos/*.yaml`; os que começam com `_` são padrões).

Para cada **ponto** da matriz (enunciado §5–6; Silberschatz 15.2–15.5 para as operações e
15.3.1/15.5 para as fórmulas de custo):
1. obtém a **base** (tabelas × métodos de acesso) — carregada uma vez por chave de cache
   (hash de perfil + overrides + tabelas/métodos) em `data/<perfil>/bench/<hash>/` e reaproveitada
   pelos pontos seguintes que pedem a mesma base; ocupação (`ocupacao()`) registrada após a carga;
2. aplica a política de substituição do ponto em todas as áreas do buffer;
3. a cada repetição: `drop_all()` + `reset_stats()` (cold start), executa, consome a saída;
   repete até CV(tempo) e CV(transferências) < `cv` (mín. 3, máx. 7 — `_base.yaml`);
   antes delas, 1 execução de aquecimento não gravada (D-M9-5: iguala o estado físico que o
   cold start não zera — braço do disco e free list do rascunho);
4. só no aquecimento compara a saída com o SQLite (contagem + checksum das chaves primárias);
5. grava 1 linha por repetição em `results/<exp>.csv` (colunas `COLUNAS`) com o custo estimado
   (`cost_model`) calculado com os parâmetros reais da base (br, nr, altura, cadeia de overflow…).

Manutenção (`operacao: manutencao`): ocupação antes → remove `frac` dos registros e reinsere os
mesmos → ocupação depois (arquivo `results/<exp>_ocupacao.csv`); a base fica isolada (é alterada)
e o conteúdo final é igual ao do SQLite, que valida a operação.

Formato dos YAMLs: comentado no cabeçalho de `config/experimentos/sel_igualdade.yaml` e em
`docs/decisoes/M9.md`. Dependências de carga (loader/registry do M8) são injetáveis via `Backend`.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import itertools
import json
import shutil
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence

import yaml

from src.bench import cost_model, datagen, loader, sqlite_ref
from src.common.config import POLITICAS_VALIDAS, Config, load_config
from src.common.erros import ConfigError
from src.executor import fachada, join_bnl, join_hash, join_inl, join_smj, selection
from src.executor.contracts import (
    CAMINHOS_SELECAO, AccessMethod, CondJuncao, InfoIndice, InfoTabela, Predicado,
)
from src.executor.fachada import ESQUEMAS, EspecIndice, EspecMetodo, criar_contexto
from src.executor.scan import Medidor

COLUNAS = (
    "exp", "operacao", "algoritmo", "caminho", "org_r", "idx_r", "org_s", "idx_s", "tam_r",
    "tam_s", "seletividade", "politica", "M", "block_size", "rep", "leituras", "gravacoes", "seq",
    "seeks", "requests", "hits", "misses", "hit_rate", "dirty_evictions", "forced_writes",
    "est_transf", "est_seeks", "dif_rel", "tuplas_saida", "tempo_s", "ok_sqlite",
)
COLUNAS_OCUPACAO = ("exp", "tabela", "metodo", "estrutura", "momento", "dados", "overflow",
                    "indice", "total", "registros")

RAIZ = Path(__file__).resolve().parents[2]
DIR_EXP = RAIZ / "config" / "experimentos"
DIR_RESULTADOS = RAIZ / "results"
OPERACOES = ("selecao", "juncao", "manutencao")
ALGORITMOS = ("bnl", "smj", "hash", "inl")
_MASCARA = (1 << 64) - 1


# =========================================================================== backend de carga
@dataclass(frozen=True)
class Backend:
    """Funções de carga/manutenção. `None` → implementação real (loader/registry do M8),
    resolvida na hora da chamada. Os testes injetam um loader próprio enquanto o M8 não chega."""
    carregar: Optional[Callable[..., AccessMethod]] = None
    inserir: Optional[Callable[[AccessMethod, Mapping], Any]] = None
    remover: Optional[Callable[[AccessMethod, Any], None]] = None

    def carga(self, ctx, nome: str, espec: EspecMetodo) -> AccessMethod:
        return (self.carregar or loader.carregar)(ctx, nome, espec)

    def insere(self, am: AccessMethod, rec: Mapping) -> Any:
        return (self.inserir or fachada.inserir)(am, rec)

    def remove(self, am: AccessMethod, rid: Any) -> None:
        (self.remover or fachada.remover)(am, rid)


# =========================================================================== leitura dos YAMLs
def _ler_yaml(caminho: Path) -> dict:
    with open(caminho, encoding="utf-8") as f:
        dados = yaml.safe_load(f) or {}
    if not isinstance(dados, Mapping):
        raise ConfigError(f"{caminho.name}: esperado um mapeamento YAML")
    return dict(dados)


def _mesclar(base: Mapping, extra: Mapping) -> dict:
    """Merge profundo (novo dict); `extra` vence."""
    out = copy.deepcopy(dict(base))
    for k, v in extra.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = _mesclar(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def carregar_experimento(caminho: Path | str, perfil: str = "teste") -> dict:
    """YAML do experimento mesclado sobre `_base.yaml` e sobre `por_perfil[perfil]`."""
    caminho = Path(caminho)
    base_arq = caminho.parent / "_base.yaml"
    if not base_arq.exists():
        base_arq = DIR_EXP / "_base.yaml"
    dados = _mesclar(_ler_yaml(base_arq) if base_arq.exists() else {}, _ler_yaml(caminho))
    por_perfil = dados.pop("por_perfil", None) or {}
    dados = _mesclar(dados, por_perfil.get(perfil, {}) or {})
    dados.setdefault("nome", caminho.stem)
    dados.setdefault("overrides", {})
    rep = dados.get("repeticoes") or {}
    try:
        rmin, rmax, cv = int(rep["min"]), int(rep["max"]), float(rep["cv"])
    except (KeyError, TypeError, ValueError):
        raise ConfigError(f"{caminho.name}: 'repeticoes' precisa de min, max e cv") from None
    if not 1 <= rmin <= rmax or cv <= 0:
        raise ConfigError(f"{caminho.name}: repeticoes inválidas ({rmin}, {rmax}, {cv})")
    if not isinstance(dados.get("pontos"), list) or not dados["pontos"]:
        raise ConfigError(f"{caminho.name}: lista 'pontos' ausente ou vazia")
    return dados


def _atribuir(d: dict, caminho: str, valor: Any) -> None:
    partes = caminho.split(".")
    for p in partes[:-1]:
        d = d.setdefault(p, {})
    d[partes[-1]] = copy.deepcopy(valor)


def _espec(x: Any, metodos: Mapping) -> EspecMetodo:
    """Nome de `metodos:` ou dict {org, campo, unique, indices, nome} → EspecMetodo."""
    if isinstance(x, str):
        if x not in metodos:
            raise ConfigError(f"método de acesso desconhecido: {x!r} (definidos: {sorted(metodos)})")
        d = dict(metodos[x])
        d.setdefault("nome", x)
    elif isinstance(x, Mapping):
        d = dict(x)
    else:
        raise ConfigError(f"método de acesso inválido: {x!r}")
    org = d.get("org")
    if org not in ("heap", "bplus", "hash"):
        raise ConfigError(f"org inválida: {org!r}")
    campo = d.get("campo")
    if org != "heap" and not campo:
        raise ConfigError(f"org {org} exige 'campo'")
    indices = []
    for i in d.get("indices") or ():
        if i.get("tipo") not in ("hash", "bplus") or not i.get("campo"):
            raise ConfigError(f"índice inválido: {i!r}")
        indices.append(EspecIndice(i["campo"], i["tipo"], bool(i.get("unique", False)),
                                   bool(i.get("clustering", False))))
    espec = EspecMetodo(org, campo, bool(d.get("unique", True)), tuple(indices), "")
    return EspecMetodo(espec.org, espec.campo, espec.unique, espec.indices,
                       str(d.get("nome") or rotulo_metodo(espec)))


def rotulo_org(espec: EspecMetodo) -> str:
    if espec.org == "heap":
        return "heap"
    return f"{espec.org}({espec.campo}{'' if espec.unique else ',NU'})"


def rotulo_idx(espec: EspecMetodo) -> str:
    if not espec.indices:
        return "-"
    return "+".join(f"{i.tipo}({i.campo}{'' if i.unique else ',NU'}{',cl' if i.clustering else ''})"
                    for i in espec.indices)


def rotulo_metodo(espec: EspecMetodo) -> str:
    idx = rotulo_idx(espec)
    return rotulo_org(espec) + ("" if idx == "-" else "+" + idx)


def _tabela(nome: Any) -> str:
    if nome not in ESQUEMAS:
        raise ConfigError(f"tabela desconhecida: {nome!r}")
    return nome


def _campo(tabela: str, campo: Any) -> str:
    if campo not in ESQUEMAS[tabela].nomes():
        raise ConfigError(f"{tabela}: campo inexistente {campo!r}")
    return campo


def _politica(pol: Any) -> Any:
    if isinstance(pol, str):
        pol = pol.upper()
        if pol not in POLITICAS_VALIDAS:
            raise ConfigError(f"política inválida: {pol}")
        return pol
    if isinstance(pol, Mapping):
        return {a: _politica(p) for a, p in pol.items()}
    raise ConfigError(f"política inválida: {pol!r}")


def _normalizar(p: dict, exp: Mapping, metodos: Mapping) -> dict:
    op = p.get("operacao")
    if op not in OPERACOES:
        raise ConfigError(f"operacao inválida: {op!r} (válidas: {OPERACOES})")
    q: dict[str, Any] = {
        "operacao": op,
        "politica": _politica(p.get("politica", exp.get("politica", "LRU"))),
        "M": p.get("M", exp.get("M")),
        "overrides": _mesclar(exp.get("overrides") or {}, p.get("overrides") or {}),
        "isolar": bool(p.get("isolar", False)),
    }
    if q["M"] is not None:
        q["M"] = int(q["M"])
    if op == "selecao":
        t = _tabela(p.get("tabela"))
        pr = p.get("predicado") or {}
        pred = Predicado(_campo(t, pr.get("campo")), pr.get("op"), pr.get("valor")).validar()
        caminho = p.get("caminho")
        if caminho not in CAMINHOS_SELECAO:
            raise ConfigError(f"caminho inválido: {caminho!r}")
        q.update(tabela=t, metodo=_espec(p.get("metodo"), metodos), predicado=pred,
                 caminho=caminho, algoritmo=p.get("algoritmo", caminho))
    elif op == "juncao":
        lados = {}
        for lado in ("r", "s"):
            d = p.get(lado) or {}
            t = _tabela(d.get("tabela"))
            lados[lado] = {"tabela": t, "metodo": _espec(d.get("metodo"), metodos),
                           "campo": _campo(t, d.get("campo"))}
        alg = p.get("algoritmo")
        if alg not in ALGORITMOS:
            raise ConfigError(f"algoritmo inválido: {alg!r} (válidos: {ALGORITMOS})")
        externa = p.get("externa", "auto")
        if externa not in ("auto", "r", "s"):
            raise ConfigError(f"externa inválida: {externa!r}")
        caso = p.get("caso")
        q.update(r=lados["r"], s=lados["s"], algoritmo=alg, externa=externa,
                 caminho=f"caso_{caso}" if caso else str(p.get("caminho", "")))
    else:
        t = _tabela(p.get("tabela"))
        frac = float(p.get("frac", (exp.get("manutencao") or {}).get("frac", 0.05)))
        if not 0 < frac < 1:
            raise ConfigError(f"frac de manutenção inválida: {frac}")
        q.update(tabela=t, metodo=_espec(p.get("metodo"), metodos), frac=frac,
                 algoritmo="remove+reinsere", caminho="", isolar=True)
    return q


def _grupos_alternativas(alt: Any) -> list[list[dict]]:
    if alt is None:
        return []
    grupos = list(alt.values()) if isinstance(alt, Mapping) else [alt]
    for g in grupos:
        if not isinstance(g, list) or not g or not all(isinstance(x, Mapping) for x in g):
            raise ConfigError("alternativas: esperada lista não vazia de mapeamentos "
                              "(ou um mapeamento de grupos)")
    return grupos


def expandir_pontos(exp: Mapping) -> list[dict]:
    """Expande cada item de `pontos` no produto cartesiano de:
    - `variar`: {chave pontuada (ex.: `r.metodo`): [valores]};
    - `alternativas`: lista de mapeamentos parciais mesclados no ponto (ex.: os casos a–e),
      ou {grupo: [mapeamentos]} para combinar vários grupos.
    Cada ponto é normalizado e validado (ConfigError se inválido)."""
    metodos = exp.get("metodos") or {}
    pontos = []
    for item in exp["pontos"]:
        item = dict(item)
        variar = item.pop("variar", None) or {}
        grupos = _grupos_alternativas(item.pop("alternativas", None))
        chaves = list(variar)
        for k in chaves:
            if not isinstance(variar[k], list) or not variar[k]:
                raise ConfigError(f"variar.{k}: esperada lista não vazia")
        for alts in itertools.product(*grupos):
            base = copy.deepcopy(item)
            for a in alts:
                base = _mesclar(base, a)
            for combo in itertools.product(*(variar[k] for k in chaves)):
                q = copy.deepcopy(base)
                for k, v in zip(chaves, combo):
                    _atribuir(q, k, v)
                pontos.append(_normalizar(q, exp, metodos))
    return pontos


def resolver_valor(v: Any, cfg: Config) -> Any:
    """Valores simbólicos do predicado: `$cr_x1` (CR > x1 ≈ 1%), `$cr_x50` (CR < x50 ≈ 50%),
    `$dre_meio`, `$cpf_meio` (aluno do meio da tabela), `$dre_frac:f` (DRE > v seleciona a
    fração f); qualquer outro valor passa direto."""
    if not (isinstance(v, str) and v.startswith("$")):
        return v
    nome = v[1:]
    n = int(cfg.volumes.get("Aluno", 0))
    if nome in ("cr_x1", "cr_x50"):
        return datagen.limiares_cr(cfg)[nome[3:]]
    if nome == "dre_meio":
        return datagen.dre(cfg, n // 2)
    if nome == "cpf_meio":
        return datagen.cpf(cfg, n // 2)
    if nome.startswith("dre_frac:"):
        # DRE(i) = base + i + 1 ⇒ "DRE > dre(n−1−k)" seleciona exatamente k = round(f·n) alunos
        k = round(float(nome.split(":", 1)[1]) * n)
        if not 0 < k < n:
            raise ConfigError(f"{v}: fração fora de (0, 1) para n={n}")
        return datagen.dre(cfg, n - 1 - k)
    raise ConfigError(f"valor simbólico desconhecido: {v!r}")


# =========================================================================== bases (cache)
def _hash(obj: Any, n: int = 12) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:n]


def _tabelas_do_ponto(p: Mapping) -> list[tuple[str, EspecMetodo]]:
    if p["operacao"] == "juncao":
        pares = [(p["r"]["tabela"], p["r"]["metodo"]), (p["s"]["tabela"], p["s"]["metodo"])]
    else:
        pares = [(p["tabela"], p["metodo"])]
    return list(dict.fromkeys(pares))


def _chave_base(perfil: str, p: Mapping, indice_ponto: int) -> str:
    over = {k: v for k, v in p["overrides"].items()}
    return _hash({"perfil": perfil, "overrides": over,
                  "tabelas": [(t, repr(e)) for t, e in _tabelas_do_ponto(p)],
                  "isolar": indice_ponto if p["isolar"] else None})


class _Base:
    """Contexto de armazenamento com as tabelas de um ponto carregadas."""

    def __init__(self, cfg: Config, pasta: Path, backend: Backend,
                 tabelas: Sequence[tuple[str, EspecMetodo]]):
        if pasta.exists():
            shutil.rmtree(pasta)          # sem reaproveitamento entre execuções (D-M9-3)
        pasta.mkdir(parents=True)
        self.cfg = cfg
        self.ctx = criar_contexto(cfg, pasta)
        self.ams: dict[tuple[str, EspecMetodo], AccessMethod] = {}
        try:
            for nome, espec in tabelas:
                self.ams[(nome, espec)] = backend.carga(self.ctx, nome, espec)
            self.ctx.bm.flush_all()       # carga persistida: a medição parte do disco
        except BaseException:
            self.fechar()
            raise

    def fechar(self) -> None:
        self.ctx.close()


def ocupacoes(nome: str, am: AccessMethod) -> list[dict]:
    """Ocupação (blocos) da organização primária e de cada índice secundário."""
    linhas = [{"tabela": nome, "estrutura": "organizacao", **am.tabela.ocupacao()}]
    for campo, idx in am.indices.items():
        n = idx.num_blocks()
        linhas.append({"tabela": nome, "estrutura": f"indice({campo})", "dados": 0,
                       "overflow": 0, "indice": n, "total": n, "registros": ""})
    return linhas


# =========================================================================== estatísticas
def info_tabela(ctx, nome: str, am: AccessMethod) -> InfoTabela:
    """InfoTabela com os parâmetros reais da base (Silberschatz 16.3.1) para o cost_model.
    Faz I/O (cabeçalhos, estatísticas do hash): chamar antes do cold start."""
    t = am.tabela
    org = t.tipo_org
    campo = getattr(t, "campo", None) if org != "heap" else None
    nr, br = t.num_registros(), t.num_blocks()
    V: dict = {}
    params: dict = {}
    try:
        cat = ctx.catalog.tabela(nome)
        V, params = dict(cat.V), dict(cat.params)
    except (KeyError, NotImplementedError):
        pass
    indices: list[InfoIndice] = []
    if org == "bplus":
        indices.append(InfoIndice(f"{nome}.{campo}", nome, campo, "bplus", bool(t.unique),
                                  clustering=True, primario=True, altura=t.altura(),
                                  num_blocks=br, fanout=t.fanout()))
    elif org == "hash":
        cadeia = float(t.estatisticas()["cadeia_media"])
        params["cadeia_media"] = cadeia
        indices.append(InfoIndice(f"{nome}.{campo}", nome, campo, "hash", bool(t.unique),
                                  primario=True, altura=1, num_blocks=br,
                                  params={"cadeia_media": cadeia}))
    for c, idx in am.indices.items():
        eh_hash = hasattr(idx, "estatisticas")
        p = {"cadeia_media": float(idx.estatisticas()["cadeia_media"])} if eh_hash else {}
        indices.append(InfoIndice(f"{nome}.{c}", nome, c, "hash" if eh_hash else "bplus",
                                  bool(idx.unique), clustering=bool(getattr(idx, "clustering", False)),
                                  altura=idx.altura(), num_blocks=idx.num_blocks(), params=p))
    return InfoTabela(nome, am.esquema, org, campo, params, nr, br, nr / br if br else 0.0,
                      V=V, indices=indices)


def _indice(info: InfoTabela, campo: str, primario: bool) -> Optional[InfoIndice]:
    return next((i for i in info.indices if i.campo == campo and i.primario == primario), None)


_CAMINHO_PRIMARIO = {"A2": True, "A3": True, "A5": True, "HASH_PRIM": True,
                     "A4": False, "A6": False, "HASH_SEC": False}


def _ordenado(info: InfoTabela, campo: str) -> bool:
    return info.org == "bplus" and info.campo_org == campo


def cv(valores: Sequence[float]) -> float:
    """Coeficiente de variação populacional (0 se < 2 valores ou média 0)."""
    if len(valores) < 2:
        return 0.0
    media = statistics.fmean(valores)
    return statistics.pstdev(valores) / media if media else 0.0


# =========================================================================== verificação SQLite
def _norm(v: Any) -> Any:
    return sqlite_ref.para_sqlite(v)


def _checksum(chaves: Iterator[tuple]) -> tuple[int, int]:
    n = soma = 0
    for k in chaves:
        n += 1
        soma = (soma + hash(tuple(_norm(x) for x in k))) & _MASCARA
    return n, soma


def _referencia(caminho_sqlite: Path, sql: str, params: Sequence = ()) -> tuple[int, int]:
    return _checksum(iter(sqlite_ref.consultar(caminho_sqlite, sql, params)))


def _consumir(it: Iterator[dict], chave: Callable[[dict], tuple], verificar: bool
              ) -> tuple[int, int]:
    """Esgota o iterador (preenche as métricas); checksum das chaves se `verificar`."""
    n = soma = 0
    try:
        for t in it:
            n += 1
            if verificar:
                soma = (soma + hash(tuple(_norm(x) for x in chave(t)))) & _MASCARA
    finally:
        fechar = getattr(it, "close", None)
        if fechar:
            fechar()
    return n, soma


def _pk(tabela: str) -> tuple[str, ...]:
    return tuple(ESQUEMAS[tabela].chave)


def _col(alias: str, campos: Sequence[str]) -> str:
    return ", ".join(f'{alias}."{c}"' for c in campos)


# =========================================================================== operações
@dataclass
class _Plano:
    """O que executar e como verificar/estimar um ponto."""
    rodar: Callable[[], tuple[Iterator[dict], dict]]
    chave: Callable[[dict], tuple]
    sql: str
    params: tuple
    estimar: Callable[[dict], Optional[dict]]
    desc: dict


def _plano_selecao(ctx, cfg: Config, p: Mapping, am: AccessMethod) -> _Plano:
    t = p["tabela"]
    pred = Predicado(p["predicado"].campo, p["predicado"].op,
                     resolver_valor(p["predicado"].valor, cfg)).validar()
    caminho = p["caminho"]
    info = info_tabela(ctx, t, am)
    pk = _pk(t)
    idx = None if caminho.startswith("A1") else _indice(info, pred.campo, _CAMINHO_PRIMARIO[caminho])

    def estimar(met: dict) -> dict:
        return cost_model.custo_selecao(caminho, info, indice=idx, sc=met["tuplas_saida"])

    return _Plano(
        rodar=lambda: selection.select(ctx, am, pred, caminho),
        chave=lambda rec: tuple(rec[k] for k in pk),
        sql=f'SELECT {_col("t", pk)} FROM "{t}" AS t WHERE t."{pred.campo}" {pred.op} ?',
        params=(_norm(pred.valor),),
        estimar=estimar,
        desc={"org_r": rotulo_org(p["metodo"]), "idx_r": rotulo_idx(p["metodo"]),
              "org_s": "", "idx_s": "", "tam_r": info.nr, "tam_s": ""},
    )


def _plano_juncao(ctx, p: Mapping, am_r: AccessMethod, am_s: AccessMethod, M: int) -> _Plano:
    R, S = p["r"]["tabela"], p["s"]["tabela"]
    cr, cs = p["r"]["campo"], p["s"]["campo"]
    cond = CondJuncao(cr, cs)
    ir, is_ = info_tabela(ctx, R, am_r), info_tabela(ctx, S, am_s)
    alg = p["algoritmo"]
    if alg == "bnl":
        externa = p["externa"]
        rodar = lambda: join_bnl.block_nested_loop(ctx, am_r, am_s, cond, M=M, externa=externa)
        r_externa = externa == "r" or (externa == "auto" and ir.br <= is_.br)
        est = lambda met: (cost_model.custo_bnl(ir, is_, M) if r_externa
                           else cost_model.custo_bnl(is_, ir, M))
    elif alg == "smj":
        rodar = lambda: join_smj.sort_merge_join(ctx, am_r, am_s, cond, M=M)
        est = lambda met: cost_model.custo_smj(ir, is_, M, ordenado_r=_ordenado(ir, cr),
                                               ordenado_s=_ordenado(is_, cs))
    elif alg == "hash":
        rodar = lambda: join_hash.hash_join(ctx, am_r, am_s, cond, M=M)
        est = lambda met: cost_model.custo_hash_join(ir, is_, M)
    else:  # inl: s precisa de organização primária ou índice no campo
        caminho = selection.caminho_igualdade(am_s, cs)
        idx = _indice(is_, cs, _CAMINHO_PRIMARIO[caminho])
        rodar = lambda: join_inl.indexed_nested_loop(ctx, am_r, am_s, cond, M=M)

        def est(met: dict) -> dict:
            sc = met["tuplas_saida"] / ir.nr if ir.nr else 0.0
            c = cost_model.custo_selecao(caminho, is_, indice=idx, sc=sc)
            return cost_model.custo_inl(ir, is_, idx, c)
    pk_r, pk_s = _pk(R), _pk(S)
    return _Plano(
        rodar=rodar,
        chave=lambda t: (tuple(t[f"{R}.{k}"] for k in pk_r) + tuple(t[f"{S}.{k}"] for k in pk_s)),
        sql=(f'SELECT {_col("r", pk_r)}, {_col("s", pk_s)} FROM "{R}" AS r JOIN "{S}" AS s '
             f'ON r."{cr}" = s."{cs}"'),
        params=(),
        estimar=est,
        desc={"org_r": rotulo_org(p["r"]["metodo"]), "idx_r": rotulo_idx(p["r"]["metodo"]),
              "org_s": rotulo_org(p["s"]["metodo"]), "idx_s": rotulo_idx(p["s"]["metodo"]),
              "tam_r": ir.nr, "tam_s": is_.nr},
    )


def _localizar(org, rec: Mapping) -> Any:
    """RID atual de `rec` pela estrutura da organização (RIDs de B+/hash mudam em split)."""
    it = org.find_all(org.campo, "=", rec[org.campo])
    try:
        for rid, r in it:
            if r == rec:
                return rid
    finally:
        it.close()
    raise LookupError(f"registro não encontrado para remoção: {dict(rec)}")


def manutencao(ctx, am: AccessMethod, backend: Backend, frac: float) -> tuple[dict, int]:
    """Remove ≈ `frac` dos registros (1 a cada ⌈1/frac⌉ na ordem física) e reinsere os mesmos.
    A escolha das vítimas (scan) não é medida; remoções + inserções são. Devolve (métricas, n)."""
    passo = max(1, round(1 / frac))
    alvos = [(rid, rec) for i, (rid, rec) in enumerate(am.tabela.scan()) if i % passo == 0]
    heap = am.tabela.tipo_org == "heap"     # heap: RID estável (slotted page, slots fixos)
    ctx.drop_all()
    ctx.reset_stats()
    with Medidor(ctx) as med:
        for rid, rec in alvos:
            backend.remove(am, rid if heap else _localizar(am.tabela, rec))
        for _, rec in alvos:
            backend.insere(am, rec)
    met = med.metricas
    met["tuplas_saida"] = len(alvos)
    return met, len(alvos)


# =========================================================================== execução
def _rotulo_politica(pol: Any) -> str:
    if isinstance(pol, str):
        return pol
    return ",".join(f"{a}={v}" for a, v in sorted(pol.items()))


def _aplicar_politica(ctx, cfg: Config, pol: Any) -> None:
    for area in cfg.buffer_areas:
        nome = pol if isinstance(pol, str) else pol.get(area, cfg.policy_for(area))
        ctx.set_policy(area, nome)


def _linha(exp: str, p: Mapping, desc: Mapping, met: Mapping, est: Optional[Mapping],
           rep: int, M: int, cfg: Config, tempo: float, ok: Any, selet: Any) -> dict:
    requests = met.get("requests", 0)
    if est is not None:
        comp = cost_model.comparar(met, est)
        est_t, est_s, dif = est["transferencias"], est["seeks"], comp["dif_rel_transf"]
    else:
        est_t = est_s = dif = ""
    return {
        "exp": exp, "operacao": p["operacao"], "algoritmo": p["algoritmo"],
        "caminho": p["caminho"], **{k: desc[k] for k in
                                    ("org_r", "idx_r", "org_s", "idx_s", "tam_r", "tam_s")},
        "seletividade": selet, "politica": _rotulo_politica(p["politica"]), "M": M,
        "block_size": cfg.block_size, "rep": rep,
        "leituras": met.get("reads", 0), "gravacoes": met.get("writes", 0),
        "seq": met.get("seq_reads", 0) + met.get("seq_writes", 0), "seeks": met.get("seeks", 0),
        "requests": requests, "hits": met.get("hits", 0), "misses": met.get("misses", 0),
        "hit_rate": round(met.get("hits", 0) / requests, 6) if requests else 0.0,
        "dirty_evictions": met.get("dirty_evictions", 0),
        "forced_writes": met.get("forced_writes", 0),
        "est_transf": _arred(est_t), "est_seeks": _arred(est_s), "dif_rel": _arred(dif),
        "tuplas_saida": met.get("tuplas_saida", 0), "tempo_s": round(tempo, 6), "ok_sqlite": ok,
    }


def _arred(x: Any) -> Any:
    return round(x, 6) if isinstance(x, float) else x


class _Execucao:
    def __init__(self, exp: Mapping, perfil: str, pasta_dados: Path, backend: Backend):
        self.exp = exp
        self.perfil = perfil
        self.pasta = pasta_dados
        self.backend = backend
        rep = exp["repeticoes"]
        self.rmin, self.rmax, self.cv = int(rep["min"]), int(rep["max"]), float(rep["cv"])
        self.comparar = bool(exp.get("comparar_sqlite", True))
        self._cfgs: dict[str, Config] = {}
        self._sqlite: dict[str, Path] = {}
        self.linhas: list[dict] = []
        self.ocup: list[dict] = []

    def cfg(self, overrides: Mapping) -> Config:
        k = _hash(overrides)
        if k not in self._cfgs:
            self._cfgs[k] = load_config(self.perfil, overrides=dict(overrides))
        return self._cfgs[k]

    def sqlite(self, cfg: Config) -> Path:
        """Banco de referência por identidade dos dados (volumes, seed, gerador)."""
        k = _hash({"volumes": dict(cfg.volumes), "seed": cfg.seed,
                   "datagen": cfg.raw.get("datagen")})
        if k not in self._sqlite:
            destino = self.pasta / "ref" / k / "ref.sqlite"
            if not destino.exists():
                sqlite_ref.exportar(cfg, destino)
            self._sqlite[k] = destino
        return self._sqlite[k]

    def _ocupacao(self, base: _Base, momento: str) -> None:
        for (nome, espec), am in base.ams.items():
            for o in ocupacoes(nome, am):
                self.ocup.append({"exp": self.exp["nome"], "metodo": espec.nome,
                                  "momento": momento, **o})

    def rodar(self) -> None:
        pontos = expandir_pontos(self.exp)
        chaves = [_chave_base(self.perfil, p, i) for i, p in enumerate(pontos)]
        ultimo = {k: i for i, k in enumerate(chaves)}
        bases: dict[str, _Base] = {}
        try:
            for i, (p, k) in enumerate(zip(pontos, chaves)):
                cfg = self.cfg(p["overrides"])
                if k not in bases:
                    bases[k] = _Base(cfg, self.pasta / "bench" / k, self.backend,
                                     _tabelas_do_ponto(p))
                    self._ocupacao(bases[k], "carga")
                self._ponto(p, cfg, bases[k])
                if ultimo[k] == i:
                    bases.pop(k).fechar()
        finally:
            for b in bases.values():
                b.fechar()

    def _ponto(self, p: Mapping, cfg: Config, base: _Base) -> None:
        ctx = base.ctx
        _aplicar_politica(ctx, cfg, p["politica"])
        M = p["M"] if p["M"] is not None else ctx.work_capacity()
        if p["operacao"] == "manutencao":
            self._manutencao(p, cfg, base, M)
            return
        if p["operacao"] == "selecao":
            am = base.ams[(p["tabela"], p["metodo"])]
            plano = _plano_selecao(ctx, cfg, p, am)
        else:
            plano = _plano_juncao(ctx, p, base.ams[(p["r"]["tabela"], p["r"]["metodo"])],
                                  base.ams[(p["s"]["tabela"], p["s"]["metodo"])], M)
        ok: Any = ""
        tempos: list[float] = []
        transf: list[float] = []
        # rep 0 = aquecimento (não gravado; faz a verificação SQLite): deixa o estado físico
        # que o cold start não zera — posição do braço (D05) e free list do rascunho — igual
        # ao de toda repetição medida, para que as contagens sejam idênticas entre reps.
        for rep in range(0, self.rmax + 1):
            ctx.drop_all()
            ctx.reset_stats()
            verificar = rep == 0 and self.comparar
            t0 = time.perf_counter()
            it, met = plano.rodar()
            n, soma = _consumir(it, plano.chave, verificar)
            dt = time.perf_counter() - t0
            ctx.bm.assert_no_pins()
            if verificar:
                ok = (n, soma) == _referencia(self.sqlite(cfg), plano.sql, plano.params)
            if rep == 0:
                continue
            met = dict(met)
            met.setdefault("tuplas_saida", n)
            selet = (round(n / plano.desc["tam_r"], 6)
                     if p["operacao"] == "selecao" and plano.desc["tam_r"] else "")
            self.linhas.append(_linha(self.exp["nome"], p, plano.desc, met, plano.estimar(met),
                                      rep, M, cfg, dt, ok, selet))
            tempos.append(dt)
            transf.append(float(met.get("transferencias", 0)))
            if rep >= self.rmin and cv(tempos) < self.cv and cv(transf) < self.cv:
                break

    def _manutencao(self, p: Mapping, cfg: Config, base: _Base, M: int) -> None:
        ctx = base.ctx
        nome = p["tabela"]
        am = base.ams[(nome, p["metodo"])]
        self._ocupacao(base, "antes_manutencao")
        t0 = time.perf_counter()
        met, n = manutencao(ctx, am, self.backend, p["frac"])
        dt = time.perf_counter() - t0
        ctx.bm.assert_no_pins()
        ctx.bm.flush_all()
        self._ocupacao(base, "depois_manutencao")
        ok: Any = ""
        if self.comparar:
            pk = _pk(nome)
            obtido = _checksum(tuple(rec[k] for k in pk) for _, rec in am.tabela.scan())
            ok = obtido == _referencia(self.sqlite(cfg), f'SELECT {_col("t", pk)} FROM "{nome}" AS t')
        desc = {"org_r": rotulo_org(p["metodo"]), "idx_r": rotulo_idx(p["metodo"]),
                "org_s": "", "idx_s": "", "tam_r": am.tabela.num_registros(), "tam_s": ""}
        self.linhas.append(_linha(self.exp["nome"], p, desc, met, None, 1, M, cfg, dt, ok,
                                  p["frac"]))


def _gravar(caminho: Path, colunas: Sequence[str], linhas: Sequence[Mapping]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(colunas))
        w.writeheader()
        w.writerows(linhas)


def executar_experimento(caminho_exp: Path | str, perfil: str = "teste",
                         saida: Optional[Path | str] = None, *,
                         backend: Optional[Backend] = None,
                         pasta_dados: Optional[Path | str] = None) -> Path:
    """Roda todos os pontos do YAML e devolve o caminho do CSV gerado.

    `saida` = caminho do CSV (padrão `results/<exp>.csv`); a ocupação vai para
    `<saida sem .csv>_ocupacao.csv`. `pasta_dados` = onde ficam bases e SQLite
    (padrão `data/<perfil>/`). `backend` = funções de carga (padrão: loader do M8)."""
    exp = carregar_experimento(caminho_exp, perfil)
    if pasta_dados is None:
        pasta_dados = load_config(perfil, overrides=dict(exp["overrides"])).perfil_dir
    saida = Path(saida) if saida is not None else DIR_RESULTADOS / f"{exp['nome']}.csv"
    ex = _Execucao(exp, perfil, Path(pasta_dados), backend or Backend())
    ex.rodar()
    _gravar(saida, COLUNAS, ex.linhas)
    if ex.ocup:
        _gravar(saida.with_name(saida.stem + "_ocupacao.csv"), COLUNAS_OCUPACAO, ex.ocup)
    return saida


def listar_experimentos(pasta: Path = DIR_EXP) -> list[Path]:
    return sorted(p for p in pasta.glob("*.yaml") if not p.name.startswith("_"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.bench.runner",
                                 description="Roda experimentos da bancada (E14).")
    ap.add_argument("--perfil", default="teste", help="teste | medio | completo")
    ap.add_argument("--exp", nargs="+", required=True,
                    help="YAML(s) de config/experimentos/ ou 'todos'")
    ap.add_argument("--saida", default=None, help="CSV de saída (só com um único --exp)")
    args = ap.parse_args(argv)
    exps = listar_experimentos() if args.exp == ["todos"] else [Path(e) for e in args.exp]
    if args.saida and len(exps) != 1:
        ap.error("--saida exige exatamente um --exp")
    for e in exps:
        t0 = time.perf_counter()
        csv_ = executar_experimento(e, args.perfil, args.saida)
        print(f"{e.name}: {csv_} ({time.perf_counter() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
