"""Gerador mínimo de registros válidos para testes (M0).

NÃO é o gerador da base (`src/bench/datagen.py`, M7): só produz registros que respeitam o
esquema (tipos, tamanhos, nulos). Campos da chave primária são únicos e sequenciais.
"""
from __future__ import annotations

import datetime as dt
import random
from typing import Iterator

from src.access.contracts import Campo, Esquema

_LETRAS = "abcdefghijklmnopqrstuvwxyzáéíóúç"


def _str(rng: random.Random, n: int) -> str:
    alvo = rng.randint(0, n)
    s = ""
    for _ in range(alvo):
        ch = rng.choice(_LETRAS)
        if len((s + ch).encode("utf-8")) > n:
            break
        s += ch
    return s


def valor(rng: random.Random, c: Campo, i: int | None = None):
    """Valor aleatório válido para o campo; `i` fixa um valor único (chave)."""
    b = c.base
    if i is not None:
        if b == "int":
            return i
        if b in ("char", "varchar"):
            return str(i).zfill(min(c.n, 11))[-c.n:]
        if b == "float":
            return float(i)
        if b == "date":
            return dt.date(1970, 1, 1) + dt.timedelta(days=i)
    if c.nulo and rng.random() < 0.1:
        return None
    if b == "int":
        return rng.randint(0, 10_000)
    if b == "float":
        return round(rng.uniform(0, 10), 2)
    if b == "date":
        return dt.date(1990, 1, 1) + dt.timedelta(days=rng.randint(0, 12_000))
    if b == "char":
        return "".join(rng.choice("0123456789") for _ in range(c.n))
    if b == "varchar":
        return _str(rng, c.n)
    return [_str(rng, c.n) for _ in range(rng.randint(0, c.max_itens))]


def registros_fake(esquema: Esquema, n: int, seed: int = 0) -> Iterator[dict]:
    """n registros válidos; a 1ª coluna da chave recebe 1..n (única)."""
    rng = random.Random(seed)
    chave = esquema.chave[0] if esquema.chave else None
    for i in range(1, n + 1):
        yield {c.nome: valor(rng, c, i if c.nome == chave else None) for c in esquema.campos}
