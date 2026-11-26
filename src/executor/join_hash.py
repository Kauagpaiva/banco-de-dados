"""Partition-hash join — M5J (E12).

Silberschatz 15.5.5: particionamento das duas relações e construção
da tabela hash em memória sobre a menor partição.
"""
from __future__ import annotations

import math
from typing import Any, Iterator, Optional

from src.executor.contracts import (
    CondJuncao, Relacao, Resultado, StorageContext, combinar, esquema_juncao,
)
from src.executor.memory import MemoryBudget
from src.executor.scan import saida_juncao
from src.executor.join_bnl import relacao, validar_cond, chave_hash


def hash_join(
    ctx: StorageContext,
    r: Relacao,
    s: Relacao,
    cond: CondJuncao,
    *,
    M: Optional[int] = None,
    materializar: bool = False,
    fudge: float = 1.2,
    nh: Optional[int] = None,
) -> Resultado:
    r, s = relacao(r), relacao(s)
    cond = CondJuncao(*cond)
    validar_cond(r, s, cond)

    mb = MemoryBudget(ctx, M)

    if mb.M < 3:
        raise ValueError(f"Hash join exige M >= 3; M={mb.M}")
    if fudge <= 0:
        raise ValueError("fudge deve ser positivo")
    if nh is not None and nh < 1:
        raise ValueError("nh deve ser positivo")

    corpo = _hash(ctx, mb, r, s, cond, fudge, nh)

    return saida_juncao(
        ctx, corpo, esquema_juncao(r.esquema, s.esquema), materializar
    )


def _hash_particao(valor: Any, nivel: int, nh: int) -> int:
    """Distribui chaves iguais sempre para a mesma partição."""
    chave = chave_hash(valor)
    return hash((nivel, chave)) % nh


def _tamanho_registro(rec: dict) -> int:
    """Estimativa conservadora do tamanho de um registro."""
    return max(1, len(repr(rec).encode("utf-8")))


def _criar_particoes(ctx, esquema, nh, sufixo):
    arquivos = []

    for i in range(nh):
        arquivos.append(ctx.temp_file(esquema, f"hash_{sufixo}_{i}"))

    return arquivos


def _particionar(ctx, mb, rel, campo, nh, nivel, sufixo):
    """Lê uma relação e distribui seus registros em arquivos temporários."""
    particoes = _criar_particoes(ctx, rel.esquema, nh, sufixo)

    try:
        with mb:
            mb.reservar_paginas_io(2)

            for bloco in rel.scan_blocos(False):
                for rec in bloco:
                    valor = rec[campo]

                    # NULL não participa de igualdade em junções.
                    if valor is None:
                        continue

                    indice = _hash_particao(valor, nivel, nh)
                    particoes[indice].append(rec)

            for arquivo in particoes:
                arquivo.close()

        return particoes

    except BaseException:
        for arquivo in particoes:
            arquivo.delete()
        raise


def _particao_cabe(ctx, mb, rel):
    """Verifica se a relação cabe no espaço reservado para a tabela hash."""
    limite = max(1, (mb.M - 2) * ctx.bm.block_size)

    tamanho = 0

    for bloco in rel.scan_blocos(False):
        if bloco:
            tamanho += len(bloco) * max(
                _tamanho_registro(rec) for rec in bloco
            )
            if tamanho > limite:
                return False

    return True


def _hash_em_memoria(
    ctx,
    mb,
    r,
    s,
    cond,
    build_r,
):
    """Executa o hash join quando a menor relação cabe em memória."""
    build = r if build_r else s
    probe = s if build_r else r

    campo_build = cond.campo_r if build_r else cond.campo_s
    campo_probe = cond.campo_s if build_r else cond.campo_r

    nome_r = r.esquema.nome
    nome_s = s.esquema.nome

    tabela = {}
    reservas = []

    with mb:
        mb.reservar_paginas(mb.M - 2)
        mb.reservar_paginas_io(2)

        try:
            for bloco in build.scan_blocos(False):
                if not bloco:
                    continue

                tam = max(
                    _tamanho_registro(rec) for rec in bloco
                )

                mb.reservar_tuplas(len(bloco), tam)
                reservas.append((len(bloco), tam))

                for rec in bloco:
                    valor = rec[campo_build]

                    if valor is not None:
                        tabela.setdefault(
                            chave_hash(valor), []
                        ).append(rec)

            for bloco in probe.scan_blocos(False):
                for rec in bloco:
                    valor = rec[campo_probe]

                    if valor is None:
                        continue

                    encontrados = tabela.get(chave_hash(valor), ())

                    for outro in encontrados:
                        if build_r:
                            yield combinar(
                                nome_r, outro, nome_s, rec
                            )
                        else:
                            yield combinar(
                                nome_r, rec, nome_s, outro
                            )

        finally:
            for n, tam in reversed(reservas):
                mb.liberar_tuplas(n, tam)


def _processar_particoes(
    ctx,
    mb,
    r,
    s,
    cond,
    fudge,
    nh,
    nivel=0,
):
    """Processa pares de partições, subdividindo quando necessário."""
    br = r.num_blocks()
    bs = s.num_blocks()

    if br == 0 or bs == 0:
        return

    build_r = br <= bs
    build = r if build_r else s

    if _particao_cabe(ctx, mb, build):
        yield from _hash_em_memoria(
            ctx, mb, r, s, cond, build_r
        )
        return

    # Limite de recursão: evita particionamento infinito em caso de skew.
    if nivel >= 3:
        yield from _nested_loop_particao(
            ctx, mb, r, s, cond
        )
        return

    quantidade = min(nh, mb.M - 1) if nh is not None else min(
        mb.M - 1,
        max(
            2,
            math.ceil(
                max(br, bs) / max(1, mb.M - 2) * fudge
            ),
        ),
    )

    novas_r = []
    novas_s = []

    try:
        novas_r = _particionar(
            ctx, mb, r, cond.campo_r,
            quantidade, nivel + 1, f"r_{nivel}"
        )

        novas_s = _particionar(
            ctx, mb, s, cond.campo_s,
            quantidade, nivel + 1, f"s_{nivel}"
        )

        for i in range(quantidade):
            yield from _processar_particoes(
                ctx,
                mb,
                novas_r[i],
                novas_s[i],
                cond,
                fudge,
                None,
                nivel + 1,
            )

    finally:
        for arquivo in novas_r + novas_s:
            arquivo.delete()


def _nested_loop_particao(ctx, mb, r, s, cond):
    """Fallback para partições que não diminuem por causa de skew."""
    nome_r = r.esquema.nome
    nome_s = s.esquema.nome
    with mb:
        mb.reservar_paginas_io(2)

        for bloco_r in r.scan_blocos(False):
            for bloco_s in s.scan_blocos(False):
                for rec_r in bloco_r:
                    vr = rec_r[cond.campo_r]

                    if vr is None:
                        continue

                    for rec_s in bloco_s:
                        vs = rec_s[cond.campo_s]

                        if vs is not None and vr == vs:
                            yield combinar(
                                nome_r, rec_r, nome_s, rec_s
                            )


def _hash(ctx, mb, r, s, cond, fudge, nh):
    """Executa o particionamento inicial e processa as partições."""
    br = r.num_blocks()
    bs = s.num_blocks()

    if br == 0 or bs == 0:
        return

    quantidade = nh or min(
        mb.M - 1,
        max(
            2,
            math.ceil(
                max(br, bs) / max(1, mb.M - 2) * fudge
            ),
        ),
    )
    particoes_r = []
    particoes_s = []

    try:
        particoes_r = _particionar(
            ctx, mb, r, cond.campo_r,
            quantidade, 0, "r"
        )

        particoes_s = _particionar(
            ctx, mb, s, cond.campo_s,
            quantidade, 0, "s"
        )

        for i in range(quantidade):
            yield from _processar_particoes(
                ctx,
                mb,
                particoes_r[i],
                particoes_s[i],
                cond,
                fudge,
                None,
            )

    finally:
        for arquivo in particoes_r + particoes_s:
            arquivo.delete()