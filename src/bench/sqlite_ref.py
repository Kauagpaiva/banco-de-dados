"""Referência SQLite (M7 / E09): oráculo de resultado para seleções e junções.

`exportar` grava a mesma base de `datagen` em `data/<perfil>/ref.sqlite` (configurável em
`sqlite_ref.arquivo`), com chaves primárias, UNIQUE em CPF e FKs declaradas e **verificadas**
(`PRAGMA foreign_keys = ON` durante a carga: FK inválida aborta a exportação).

Mapeamento de tipos (esquema lógico → SQLite): int → INTEGER · float → REAL ·
date → TEXT ISO-8601 (ordem lexicográfica = cronológica) · char/varchar → TEXT ·
list[varchar] → TEXT com JSON. A tabela `_meta(chave, valor)` guarda perfil, semente,
volumes e os limiares de CR (`x1`, `x50`) usados pelas seleções A2–A6.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from src.bench import datagen
from src.executor.fachada import ESQUEMAS, FKS

_TIPOS = {"int": "INTEGER", "float": "REAL", "date": "TEXT", "char": "TEXT",
          "varchar": "TEXT", "list": "TEXT"}
#: campos UNIQUE além da chave primária (alvo de FK precisa de UNIQUE no SQLite)
_UNIQUE_EXTRA = {("Aluno", "CPF")}


def _ddl(esquema) -> str:
    cols = []
    for c in esquema.campos:
        linha = f'"{c.nome}" {_TIPOS[c.base]}'
        if not c.nulo:
            linha += " NOT NULL"
        if (esquema.nome, c.nome) in _UNIQUE_EXTRA:
            linha += " UNIQUE"
        cols.append(linha)
    cols.append("PRIMARY KEY (" + ", ".join(f'"{k}"' for k in esquema.chave) + ")")
    for (tab, campo), (ref, campo_ref) in FKS.items():
        if tab == esquema.nome:
            cols.append(f'FOREIGN KEY ("{campo}") REFERENCES "{ref}"("{campo_ref}")')
    return f'CREATE TABLE "{esquema.nome}" (\n  ' + ",\n  ".join(cols) + "\n)"


def para_sqlite(v: Any) -> Any:
    """Converte um valor do registro para o tipo armazenado no SQLite."""
    if isinstance(v, list):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def _linhas(esquema, regs: Iterable[dict]) -> Iterator[tuple]:
    nomes = esquema.nomes()
    for r in regs:
        yield tuple(para_sqlite(r[n]) for n in nomes)


def _lotes(it: Iterator[tuple], n: int) -> Iterator[list[tuple]]:
    while lote := list(islice(it, n)):
        yield lote


def caminho_padrao(cfg) -> Path:
    return Path(cfg.perfil_dir) / str(cfg.raw["sqlite_ref"]["arquivo"])


def exportar(cfg, caminho: Path | str | None = None) -> Path:
    """Cria o banco SQLite com as 6 tabelas geradas por `datagen`; devolve o caminho.

    Escreve num arquivo temporário e renomeia no fim: um `ref.sqlite` existente só é
    substituído por uma exportação completa e consistente.
    """
    destino = Path(caminho) if caminho is not None else caminho_padrao(cfg)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    lote = int(cfg.raw["sqlite_ref"]["lote"])
    con = sqlite3.connect(tmp)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = OFF")
        con.execute("PRAGMA synchronous = OFF")
        with con:
            # ESQUEMAS está em ordem topológica das FKs (pais antes dos filhos)
            for nome, esq in ESQUEMAS.items():
                con.execute(_ddl(esq))
                ph = ", ".join("?" * len(esq.campos))
                sql = f'INSERT INTO "{nome}" VALUES ({ph})'
                for bloco in _lotes(_linhas(esq, datagen.gerar_tabela(cfg, nome)), lote):
                    con.executemany(sql, bloco)
            con.execute("CREATE TABLE _meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
            meta = {"perfil": cfg.perfil, "seed": cfg.seed,
                    "volumes": json.dumps(dict(cfg.volumes)),
                    "n_professores": datagen.n_professores(cfg),
                    **datagen.limiares_cr(cfg)}
            con.executemany("INSERT INTO _meta VALUES (?, ?)",
                            [(k, str(v)) for k, v in meta.items()])
            violacoes = con.execute("PRAGMA foreign_key_check").fetchall()
            if violacoes:
                raise sqlite3.IntegrityError(f"FKs inválidas: {violacoes[:5]}")
    finally:
        con.close()
    os.replace(tmp, destino)
    return destino


def consultar(caminho: Path | str, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
    """Executa `sql` (somente leitura) no banco de referência e devolve todas as linhas."""
    p = Path(caminho)
    if not p.exists():
        raise FileNotFoundError(f"banco de referência ausente: {p} (rode exportar)")
    con = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return con.execute(sql, tuple(params)).fetchall()
    finally:
        con.close()
