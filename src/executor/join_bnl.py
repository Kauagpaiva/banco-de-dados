"""Block nested-loop join (Camada 2) — M5, E11.

Silberschatz 15.5.2 (REFERENCIA_LIVRO §7): M−2 blocos para a relação externa, 1 para a
interna, 1 de saída. Para cada grupo de M−2 blocos da externa, a interna é varrida inteira:
custo br + ⌈br/(M−2)⌉·bs transferências (externa = r). `externa='auto'` escolhe a menor
(em blocos) como externa. Na interna recomenda-se MRU e/ou toss-immediate (13.5.1): `toss`
é repassado ao `scan_blocos` da interna; a política é a da área da interna (`ctx.set_policy`).

Memória (MemoryBudget, D-M5-08): M−2 páginas pinadas para as tuplas da externa + 2 de E/S
(frame da interna e frame de saída). As tuplas do grupo externo ficam numa lista e num
dicionário valor → tuplas que só guarda **referências** a elas (D-M5-10): o I/O é o do BNL;
o dicionário evita a comparação O(|grupo|) por tupla interna.

Equijunção r.campo_r = s.campo_s; nulos nunca casam. Saída: `combinar(r, s)` na ordem
(r, s) mesmo quando s é a externa.
"""
from __future__ import annotations

from typing import Any, Iterator, Optional

from src.executor.contracts import (
    AccessMethod, CondJuncao, Relacao, Resultado, StorageContext, combinar, esquema_juncao,
)
from src.executor.memory import MemoryBudget
from src.executor.scan import _fechar, saida_juncao

EXTERNAS = ("r", "s", "auto")


def block_nested_loop(ctx: StorageContext, r: Relacao, s: Relacao, cond: CondJuncao, *,
                      M: Optional[int] = None, materializar: bool = False,
                      externa: str = "auto", toss: bool = False) -> Resultado:
    """r ⋈_{r.campo_r = s.campo_s} s por BNL (15.5.2). Ver docstring do módulo."""
    r, s = relacao(r), relacao(s)
    cond = CondJuncao(*cond)
    validar_cond(r, s, cond)
    if externa not in EXTERNAS:
        raise ValueError(f"externa inválida: {externa!r} (válidas: {EXTERNAS})")
    mb = MemoryBudget(ctx, M)
    if mb.M < 3:
        raise ValueError(f"BNL exige M ≥ 3 (M−2 externa + 1 interna + 1 saída); M={mb.M}")
    if externa == "auto":
        externa = "r" if r.num_blocks() <= s.num_blocks() else "s"
    corpo = _bnl(ctx, mb, r, s, cond, externa == "r", toss)
    return saida_juncao(ctx, corpo, esquema_juncao(r.esquema, s.esquema), materializar)


# =========================================================================== auxiliares
def relacao(x: Any) -> Relacao:
    """AccessMethod → sua organização primária; demais Relacao passam direto."""
    return x.tabela if isinstance(x, AccessMethod) else x


def validar_cond(r: Relacao, s: Relacao, cond: CondJuncao) -> None:
    if cond.campo_r not in r.esquema.nomes():
        raise ValueError(f"{r.esquema.nome}: campo de junção inexistente {cond.campo_r!r}")
    if cond.campo_s not in s.esquema.nomes():
        raise ValueError(f"{s.esquema.nome}: campo de junção inexistente {cond.campo_s!r}")


def chave_hash(v: Any) -> Any:
    """Valor de junção como chave de dict (listas viram tuplas)."""
    return tuple(v) if isinstance(v, list) else v


def _bnl(ctx: StorageContext, mb: MemoryBudget, r: Relacao, s: Relacao, cond: CondJuncao,
         r_externa: bool, toss: bool) -> Iterator[dict]:
    ext, inn = (r, s) if r_externa else (s, r)
    campo_ext, campo_inn = (cond.campo_r, cond.campo_s) if r_externa else (cond.campo_s, cond.campo_r)
    nome_r, nome_s = r.esquema.nome, s.esquema.nome
    bs = ctx.bm.block_size
    with mb:
        mb.reservar_paginas(mb.M - 2)
        mb.reservar_paginas_io(2)
        capacidade = mb.M - 2
        blocos_ext = ext.scan_blocos(False)
        try:
            while True:
                grupo: dict[Any, list[dict]] = {}
                reservas: list[tuple[int, int]] = []
                for bloco in blocos_ext:
                    if bloco:
                        tam = max(1, bs // len(bloco))
                        mb.reservar_tuplas(len(bloco), tam)
                        reservas.append((len(bloco), tam))
                        for rec in bloco:
                            v = rec[campo_ext]
                            if v is not None:
                                grupo.setdefault(chave_hash(v), []).append(rec)
                    else:
                        reservas.append((0, 1))
                    if len(reservas) == capacidade:
                        break
                if not reservas:
                    return
                # a interna é varrida mesmo se o grupo só tiver nulos: custo fiel a 15.5.2
                yield from _varrer_interna(inn, campo_inn, grupo, toss, r_externa,
                                           nome_r, nome_s)
                for n, tam in reservas:
                    if n:
                        mb.liberar_tuplas(n, tam)
                if len(reservas) < capacidade:
                    return
        finally:
            _fechar(blocos_ext)


def _varrer_interna(inn: Relacao, campo_inn: str, grupo: dict, toss: bool, r_externa: bool,
                    nome_r: str, nome_s: str) -> Iterator[dict]:
    blocos = inn.scan_blocos(toss)
    try:
        for bloco in blocos:
            for rec_i in bloco:
                v = rec_i[campo_inn]
                if v is None:
                    continue
                for rec_e in grupo.get(chave_hash(v), ()):
                    if r_externa:
                        yield combinar(nome_r, rec_e, nome_s, rec_i)
                    else:
                        yield combinar(nome_r, rec_i, nome_s, rec_e)
    finally:
        _fechar(blocos)
