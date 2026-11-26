"""Sort-merge join — STUB do M0; implementação: M5J (E12).

Silberschatz 15.5.4; REFERENCIA_LIVRO §7. Ordena com `external_sort` (pula se a organização
já fornece ordem via `find_ordered`); merge tratando grupos de duplicatas; grupo maior que M →
fallback BNL para o grupo.
"""
from __future__ import annotations

from typing import Any, Iterator, Optional

from src.executor.contracts import (
    CondJuncao,
    Relacao,
    Resultado,
    StorageContext,
    combinar,
    esquema_juncao,
)
from src.executor.memory import MemoryBudget
from src.executor.scan import saida_juncao
from src.executor.sort import external_sort
from src.executor.join_bnl import relacao, validar_cond
from tests.conftest import ctx


def sort_merge_join(
    ctx: StorageContext,
    r: Relacao,
    s: Relacao,
    cond: CondJuncao,
    *,
    M: Optional[int] = None,
    materializar: bool = False,
) -> Resultado:
    r, s = relacao(r), relacao(s)
    cond = CondJuncao(*cond)
    validar_cond(r, s, cond)

    mb = MemoryBudget(ctx, M)

    if mb.M < 3:
        raise ValueError(f"Sort-merge join exige M >= 3; M={mb.M}")

    corpo = _sort_merge(ctx, mb, r, s, cond)

    return saida_juncao(
        ctx, corpo, esquema_juncao(r.esquema, s.esquema), materializar
    )

def _sort_merge(ctx, mb, r, s, cond):
    """Ordena as relações e inicia a intercalação."""
    nome_r = r.esquema.nome
    nome_s = s.esquema.nome

    temp_r = None
    temp_s = None

    try:
        temp_r, _ = external_sort(
            ctx, _RelacaoSemNulos(r, cond.campo_r),
            r.esquema, cond.campo_r, M=mb.M
    )
        temp_s, _ = external_sort(
            ctx, _RelacaoSemNulos(s, cond.campo_s),
            s.esquema, cond.campo_s, M=mb.M
    )

        yield from _merge(
            ctx, mb, temp_r, temp_s, cond, nome_r, nome_s
        )

    finally:
        if temp_r is not None:
            temp_r.delete()
        if temp_s is not None:
            temp_s.delete()


def _registros(rel):
    """Percorre os registros de uma relação em ordem."""
    for bloco in rel.scan_blocos(False):
        yield from bloco

class _RelacaoSemNulos:
    def __init__(self, rel, campo):
        self._rel = rel
        self.esquema = rel.esquema
        self.campo = campo

    def scan_blocos(self, *args):
        for bloco in self._rel.scan_blocos(*args):
            filtrado = [
                rec for rec in bloco
                if rec[self.campo] is not None
            ]

            if filtrado:
                yield filtrado

def _proximo(it):
    try:
        return next(it)
    except StopIteration:
        return None

def _coletar_grupo(ctx, it, primeiro, campo, esquema, sufixo):
    """Armazena em arquivo temporário registros com a mesma chave."""
    chave = primeiro[campo]
    grupo = ctx.temp_file(esquema, sufixo)

    try:
        grupo.append(primeiro)

        while True:
            rec = _proximo(it)

            if rec is None:
                break

            if rec[campo] != chave:
                break

            grupo.append(rec)

        grupo.close()
        return grupo, rec

    except BaseException:
        grupo.delete()
        raise

def _merge(ctx, mb, temp_r, temp_s, cond, nome_r, nome_s):
    """Intercala as relações ordenadas e combina as chaves iguais."""
    it_r = iter(_registros(temp_r))
    it_s = iter(_registros(temp_s))

    atual_r = _proximo(it_r)
    atual_s = _proximo(it_s)

    while atual_r is not None and atual_s is not None:
        chave_r = atual_r[cond.campo_r]
        chave_s = atual_s[cond.campo_s]

        # NULL não participa de igualdade.
        if chave_r is None:
            atual_r = _proximo(it_r)
            continue

        if chave_s is None:
            atual_s = _proximo(it_s)
            continue

        if chave_r < chave_s:
            atual_r = _proximo(it_r)

        elif chave_r > chave_s:
            atual_s = _proximo(it_s)

        else:
            grupo_r, atual_r = _coletar_grupo(
                ctx, it_r, atual_r, cond.campo_r,
                temp_r.esquema, "smj_r"
            )
            grupo_s, atual_s = _coletar_grupo(
                ctx, it_s, atual_s, cond.campo_s,
                temp_s.esquema, "smj_s"
            )

            try:
                for bloco_r in grupo_r.scan_blocos(False):
                    for rec_r in bloco_r:
                        for bloco_s in grupo_s.scan_blocos(False):
                            for rec_s in bloco_s:
                                yield combinar(
                                    nome_r, rec_r, nome_s, rec_s
                                )
            finally:
                grupo_r.delete()
                grupo_s.delete()

