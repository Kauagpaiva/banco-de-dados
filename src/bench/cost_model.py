"""Modelo de custo analítico (M6/E13) — Silberschatz 15.2–15.5 (REFERENCIA_LIVRO §6–7).

Cada função devolve `{'transferencias': x, 'seeks': y}` (Custo) a partir das estatísticas do
catálogo (`InfoTabela`: nr, br, fr, V; `InfoIndice`: altura hi, tipo, unique, clustering,
primario, params['cadeia_media']) e de M/bb. Transferências e seeks são reportados separados
(não somamos tempo tT/tS).

Fontes de divergência esperadas entre estimado e medido (o medido é o que o BufferManager conta):
- **Buffer quente**: o modelo assume buffer frio; páginas já residentes (raiz/nós internos da B+,
  blocos do catálogo, interna do BNL que cabe no buffer) não geram transferência.
- **Raiz/nós internos da B+ em memória**: o livro sugere hi efetivo = 1 nesses casos; aqui usamos
  a altura do catálogo (pior caso).
- **Overflow de hash**: usamos a cadeia *média* (`params['cadeia_media']`); buckets com skew custam mais.
- **Blocos parcialmente cheios**: br real ≥ nr/fr; partições/runs com último bloco incompleto
  (o termo 4·nh do hash join) e páginas de folha a ~2/3 na B+.
- **Cabeçalho do arquivo** (bloco 0) e acessos ao catálogo contam I/O no medido e não aqui.
- **Seeks**: o medido usa o braço global do disco simulado (D05); leituras consecutivas de
  arquivos diferentes intercaladas geram seeks que o livro (1 seek por run/bloco) não prevê
  exatamente.
"""
from __future__ import annotations

import math
from typing import Optional, TypedDict

from src.executor.contracts import InfoIndice, InfoTabela


class Custo(TypedDict):
    transferencias: float
    seeks: float


def _custo(transferencias: float, seeks: float) -> Custo:
    return {"transferencias": transferencias, "seeks": seeks}


def _soma(*custos: Custo) -> Custo:
    return _custo(sum(c["transferencias"] for c in custos), sum(c["seeks"] for c in custos))


def _passos_merge(b: int, M: int, bb: int) -> int:
    """⌈log_{⌊M/bb⌋−1}(b/M)⌉ calculado com inteiros (15.4): nº de passos de merge.

    ⌈log_k(b/M)⌉ == ⌈log_k(⌈b/M⌉)⌉ porque k^p é inteiro; o laço evita erro de ponto flutuante."""
    k = M // bb - 1
    if k < 2:
        raise ValueError(f"⌊M/bb⌋−1 = {k} < 2: memória insuficiente para o merge (M={M}, bb={bb})")
    runs = math.ceil(b / M)
    passos = 0
    while runs > 1:
        runs = math.ceil(runs / k)
        passos += 1
    return passos


def _validar_M(M: int, minimo: int) -> None:
    if M < minimo:
        raise ValueError(f"M={M} < {minimo}")


# ============================================================================ seleção
def custo_selecao(caminho: str, tabela: InfoTabela, *, indice: Optional[InfoIndice] = None,
                  sc: float = 1.0) -> Custo:
    """Custo de seleção (Silberschatz 15.3.1, Fig. 15.3). `sc` = nº de tuplas que satisfazem.

    - A1_linear: br transf, 1 seek.  A1_chave (média): br/2 transf, 1 seek.
    - A2 (clustering, igualdade em chave): (hi+1)·(tT+tS); se o índice é a própria organização B+
      (`primario`), o registro está na folha ⇒ hi·(tT+tS) (nota do livro).
    - A3/A5 (clustering, não-chave / comparação): hi·(tT+tS) + tS + b·tT, b = ⌈sc/fr⌉.
    - A4/A6 (secundário): chave única ⇒ (hi+1)·(tT+tS); senão (hi+n)·(tT+tS), n = sc.
    - HASH_PRIM: 1 bucket + cadeia média de overflow (registros no próprio bucket).
    - HASH_SEC: bucket + cadeia + 1 acesso por registro apontado (n = sc).
    """
    br = tabela.br
    if caminho == "A1_linear":
        return _custo(br, 1 if br else 0)
    if caminho == "A1_chave":
        return _custo(br / 2, 1 if br else 0)

    if indice is None:
        raise ValueError(f"caminho {caminho} exige `indice`")
    hi = indice.altura
    n = max(sc, 0)

    if caminho == "A2":
        acessos = hi if indice.primario else hi + 1
        return _custo(acessos, acessos)
    if caminho in ("A3", "A5"):
        fr = tabela.fr if tabela.fr > 0 else 1.0
        b = math.ceil(n / fr) if n else 0
        return _custo(hi + b, hi + 1)
    if caminho in ("A4", "A6"):
        acessos = hi + 1 if (caminho == "A4" and indice.unique) else hi + n
        return _custo(acessos, acessos)
    if caminho in ("HASH_PRIM", "HASH_SEC"):
        cadeia = float(indice.params.get("cadeia_media", tabela.params.get("cadeia_media", 0.0)))
        acessos = 1 + cadeia
        if caminho == "HASH_SEC":
            acessos += 1 if indice.unique else n
        return _custo(acessos, acessos)
    raise ValueError(f"caminho de seleção desconhecido: {caminho!r}")


# ============================================================================ ordenação
def custo_sort(b: int, M: int, bb: int = 1) -> Custo:
    """Ordenação externa sort-merge de b blocos (Silberschatz 15.4.2), sem gravar o resultado final.

    Transferências: b·(2⌈log_{⌊M/bb⌋−1}(b/M)⌉ + 1); seeks: 2⌈b/M⌉ + ⌈b/bb⌉·(2⌈log…⌉ − 1).
    Se b ≤ M (um único run, ordenação em memória): b transferências e 1 seek.
    """
    _validar_M(M, 2)
    if b <= 0:
        return _custo(0, 0)
    p = _passos_merge(b, M, bb)
    if p == 0:
        return _custo(b, 1)
    return _custo(b * (2 * p + 1), 2 * math.ceil(b / M) + math.ceil(b / bb) * (2 * p - 1))


# ============================================================================ junções
def custo_bnl(r: InfoTabela, s: InfoTabela, M: int) -> Custo:
    """Block nested-loop com r externa (Silberschatz 15.5.2).

    ⌈br/(M−2)⌉·bs + br transferências; 2·⌈br/(M−2)⌉ seeks (M−2 blocos para a externa,
    1 para a interna, 1 de saída). Melhor caso — interna inteira cabe (bs ≤ M−2): br+bs, 2 seeks.
    """
    _validar_M(M, 3)
    br, bs = r.br, s.br
    if bs <= M - 2:
        return _custo(br + bs, 2)
    blocos_ext = math.ceil(br / (M - 2))
    return _custo(blocos_ext * bs + br, 2 * blocos_ext)


def custo_inl(r: InfoTabela, s: InfoTabela, indice_s: InfoIndice, c: Optional[Custo] = None) -> Custo:
    """Indexed nested-loop: br·(tT+tS) + nr·c (Silberschatz 15.5.3).

    `c` = custo de uma seleção por igualdade em s usando `indice_s`; se omitido, é derivado do
    índice: B+ primário/clustering ⇒ A2 (único) ou A3; B+ secundário ⇒ A4; hash ⇒ HASH_PRIM/HASH_SEC.
    Para chave não única, cada busca devolve sc = ns / V(s, campo) tuplas.
    """
    if c is None:
        sc = 1.0
        if not indice_s.unique:
            v = s.V.get(indice_s.campo) or 0
            sc = s.nr / v if v > 0 else float(s.nr)
        if indice_s.tipo == "hash":
            caminho = "HASH_PRIM" if indice_s.primario else "HASH_SEC"
        elif indice_s.primario or indice_s.clustering:
            caminho = "A2" if indice_s.unique else "A3"
        else:
            caminho = "A4"
        c = custo_selecao(caminho, s, indice=indice_s, sc=sc)
    return _custo(r.br + r.nr * c["transferencias"], r.br + r.nr * c["seeks"])


def _custo_ordenar_e_gravar(b: int, M: int, bb: int) -> Custo:
    """Ordenar b blocos e gravar o resultado ordenado (b transferências, ⌈b/bb⌉ seeks)."""
    return _soma(custo_sort(b, M, bb), _custo(b, math.ceil(b / bb)))


def custo_smj(r: InfoTabela, s: InfoTabela, M: int, bb: int = 1, *, ordenado_r: bool = False,
              ordenado_s: bool = False) -> Custo:
    """Sort-merge join (Silberschatz 15.5.4, pág. 711).

    Merge: br + bs transferências; ⌈br/bb⌉ + ⌈bs/bb⌉ seeks. Cada entrada não ordenada soma
    custo_sort + gravação do resultado ordenado (b transferências, ⌈b/bb⌉ seeks).
    Exemplo do livro (M=3): 9 100 transferências e 8 436 seeks — o texto diz 8 932, mas as suas
    próprias parcelas (6 668 + 1 268 + 500) somam 8 436 (ver docs/decisoes/M6.md).
    Assume que cada grupo de mesma chave de s cabe na memória.
    """
    _validar_M(M, 3)
    partes = [_custo(r.br + s.br, math.ceil(r.br / bb) + math.ceil(s.br / bb))]
    if not ordenado_r:
        partes.append(_custo_ordenar_e_gravar(r.br, M, bb))
    if not ordenado_s:
        partes.append(_custo_ordenar_e_gravar(s.br, M, bb))
    return _soma(*partes)


def detalhar_hash_join(r: InfoTabela, s: InfoTabela, M: int, bb: int = 1,
                       nh: Optional[int] = None) -> dict:
    """Como `custo_hash_join`, mas separa o termo de blocos parcialmente cheios.

    Devolve {'transferencias', 'seeks', 'parciais_transf', 'parciais_seeks', 'nh', 'modo'}
    com modo ∈ {'memoria', 'simples', 'recursivo'}. O livro ignora o termo 4·nh/2·nh nos exemplos
    (1 500 / 336 para takes ⋈ student, M=20, bb=3).
    """
    _validar_M(M, 3)
    br, bs = r.br, s.br
    if nh is None:
        nh = math.ceil(bs / M)
    if bs <= M - 2:
        return {"transferencias": br + bs, "seeks": 2, "parciais_transf": 0, "parciais_seeks": 0,
                "nh": 0, "modo": "memoria"}
    seeks_base = math.ceil(br / bb) + math.ceil(bs / bb)
    # Particionamento em uma passada: nh partições × bb buffers de saída + 1 de entrada ≤ M.
    if nh * bb < M:
        return {"transferencias": 3 * (br + bs) + 4 * nh, "seeks": 2 * seeks_base + 2 * nh,
                "parciais_transf": 4 * nh, "parciais_seeks": 2 * nh, "nh": nh, "modo": "simples"}
    p = _passos_merge(bs, M, bb)  # ⌈log_{⌊M/bb⌋−1}(bs/M)⌉ passadas de particionamento
    p = max(p, 1)
    return {"transferencias": 2 * (br + bs) * p + br + bs, "seeks": 2 * seeks_base * p,
            "parciais_transf": 0, "parciais_seeks": 0, "nh": nh, "modo": "recursivo"}


def custo_hash_join(r: InfoTabela, s: InfoTabela, M: int, bb: int = 1,
                    nh: Optional[int] = None) -> Custo:
    """Partition-hash join com s como build input (Silberschatz 15.5.5, págs. 716–717).

    - Build cabe na memória (bs ≤ M−2): br + bs transferências, 2 seeks.
    - Sem recursão (nh·bb < M): 3(br+bs) + 4·nh transferências; 2(⌈br/bb⌉+⌈bs/bb⌉) + 2·nh seeks.
    - Com recursão: 2(br+bs)·⌈log_{⌊M/bb⌋−1}(bs/M)⌉ + br + bs transferências;
      2(⌈br/bb⌉+⌈bs/bb⌉)·⌈log_{⌊M/bb⌋−1}(bs/M)⌉ seeks.
    `nh=None` ⇒ ⌈bs/M⌉ (sem fudge; passe o nh real do executor para comparar com o medido).
    """
    d = detalhar_hash_join(r, s, M, bb, nh)
    return _custo(d["transferencias"], d["seeks"])


# ============================================================================ comparação
def _dif(medido: float, estimado: float) -> tuple[float, float]:
    abs_ = medido - estimado
    if estimado:
        return abs_, abs_ / estimado
    return abs_, (0.0 if abs_ == 0 else math.inf)


def comparar(medido: dict, estimado: Custo) -> dict:
    """{'dif_abs_transf', 'dif_rel_transf', 'dif_abs_seeks', 'dif_rel_seeks'}.

    Diferença = medido − estimado; relativa = diferença / estimado (estimado 0 ⇒ 0 se iguais, senão inf).
    `medido` pode ser um `Metricas` (usa as chaves 'transferencias' e 'seeks')."""
    at, rt = _dif(float(medido["transferencias"]), float(estimado["transferencias"]))
    as_, rs = _dif(float(medido["seeks"]), float(estimado["seeks"]))
    return {"dif_abs_transf": at, "dif_rel_transf": rt, "dif_abs_seeks": as_, "dif_rel_seeks": rs}
