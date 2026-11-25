"""Varreduras auxiliares do executor (M5, E10).

Silberschatz 15.2 (A1: varredura linear). Adapta FileOrganization/TempFile/iteráveis em
iteradores de registros e mede a operação (Metricas = diferença de `ctx.buffer_stats()`).

- `scan_registros(entrada, toss)`: registros (sem RID) de qualquer `Entrada`.
- `Medidor(ctx)`: `with Medidor(ctx) as m: ...` → `m.metricas`.
- `IteradorMedido` / `operacao_medida(ctx, corpo, metricas)`: envolve o iterador preguiçoso de
  um operador; ao se esgotar **ou** ser fechado (`close()`), grava no dict `metricas` a
  diferença de stats desde a criação + `tuplas_saida`. É o mecanismo comum a todos os
  operadores do M5 (contrato de `src/executor/contracts.py`).
"""
from __future__ import annotations

from typing import Any, Iterable, Iterator, Optional

from src.executor.contracts import (
    Entrada, FileOrganization, Metricas, StorageContext, TempFile, metricas_vazias,
)
from src.common.tipos import diferenca_metricas


def _fechar(it: Any) -> None:
    """Fecha um iterador/gerador, se ele souber fechar (libera páginas em `finally`)."""
    fechar = getattr(it, "close", None)
    if callable(fechar):
        fechar()


def scan_registros(entrada: Entrada, toss: bool = False) -> Iterator[dict]:
    """Registros de FileOrganization (sem RID), TempFile, Relacao (`scan_blocos`) ou
    iterável de dicts. Preguiçoso; o iterador interno é fechado ao fim/fechamento."""
    if isinstance(entrada, FileOrganization):
        interno: Iterator = (rec for _, rec in entrada.scan(toss))
    elif isinstance(entrada, TempFile):
        interno = entrada.scan(toss)
    elif hasattr(entrada, "scan_blocos") and not isinstance(entrada, (list, tuple)):
        interno = (rec for bloco in entrada.scan_blocos(toss) for rec in bloco)
    elif isinstance(entrada, Iterable) and not isinstance(entrada, (str, bytes, dict)):
        interno = iter(entrada)
    else:
        raise TypeError(f"entrada não suportada: {type(entrada).__name__}")
    return _gerar(interno)


def _gerar(interno: Iterator) -> Iterator[dict]:
    try:
        for rec in interno:
            if not isinstance(rec, dict):
                raise TypeError(f"registro deve ser dict, veio {type(rec).__name__}")
            yield rec
    finally:
        _fechar(interno)


class Medidor:
    """`with Medidor(ctx) as m: ...` → `m.metricas` com a diferença de stats no período.

    Dentro do `with`, `metricas` devolve a diferença parcial até o momento."""

    def __init__(self, ctx: StorageContext):
        self._ctx = ctx
        self._antes: Optional[dict] = None
        self._final: Optional[Metricas] = None

    def __enter__(self) -> "Medidor":
        self._antes = dict(self._ctx.buffer_stats())
        self._final = None
        return self

    def __exit__(self, *exc) -> None:
        if self._antes is not None and self._final is None:
            self._final = self._diferenca()

    def _diferenca(self) -> Metricas:
        m = diferenca_metricas(self._ctx.buffer_stats(), self._antes or {})
        m["escrita_saida"] = 0
        return m

    @property
    def metricas(self) -> Metricas:
        if self._final is not None:
            return dict(self._final)  # type: ignore[return-value]
        if self._antes is None:
            m = metricas_vazias()
            m["escrita_saida"] = 0
            return m
        return self._diferenca()


class IteradorMedido(Iterator[dict]):
    """Iterador de saída de um operador: mede da criação até esgotar ou `close()`.

    Ao terminar, atualiza **no próprio dict** `metricas` (o mesmo devolvido ao chamador)
    as chaves de stats + `tuplas_saida`; `extras()` pode acrescentar chaves (ex.:
    `escrita_saida`) — é chamado depois da medição."""

    def __init__(self, ctx: StorageContext, corpo: Iterator[dict], metricas: Metricas,
                 extras=None):
        self._corpo = corpo
        self._metricas = metricas
        self._extras = extras
        self._n = 0
        self._fim = False
        self._med = Medidor(ctx).__enter__()

    def __iter__(self) -> "IteradorMedido":
        return self

    def __next__(self) -> dict:
        if self._fim:
            raise StopIteration
        try:
            rec = next(self._corpo)
        except StopIteration:
            self._encerrar()
            raise
        except BaseException:
            self._encerrar()
            raise
        self._n += 1
        return rec

    def close(self) -> None:
        self._encerrar()

    def _encerrar(self) -> None:
        if self._fim:
            return
        self._fim = True
        try:
            _fechar(self._corpo)          # solta páginas pendentes antes de medir
        finally:
            self._med.__exit__(None, None, None)
            self._metricas.update(self._med.metricas)
            self._metricas["tuplas_saida"] = self._n
            if self._extras is not None:
                self._metricas.update(self._extras())

    def __enter__(self) -> "IteradorMedido":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def operacao_medida(ctx: StorageContext, corpo: Iterator[dict],
                    metricas: Optional[Metricas] = None, extras=None
                    ) -> tuple[IteradorMedido, Metricas]:
    """Atalho: `(IteradorMedido(ctx, corpo, m), m)`; `m` começa zerado."""
    if metricas is None:
        metricas = metricas_vazias()
        metricas["escrita_saida"] = 0
    return IteradorMedido(ctx, corpo, metricas, extras), metricas


# =========================================================================== E11: saída
def forcar_gravacao(ctx: StorageContext, tmp: TempFile) -> int:
    """Forced output (Silberschatz 13.5.1) dos blocos de um TempFile já fechado: grava os
    que ainda estão dirty no buffer, para que a escrita do resultado apareça nas métricas da
    própria operação (e não numa evicção futura). Devolve o nº de blocos do arquivo."""
    fid = getattr(tmp, "fid", None)
    if fid is not None:
        for bno in tmp.blocks():
            ctx.bm.flush(fid, bno)
    return tmp.num_blocks()


def saida_juncao(ctx: StorageContext, corpo: Iterator[dict], esquema, materializar: bool
                 ) -> tuple[IteradorMedido, Metricas]:
    """Saída comum dos operadores de junção (contrato do executor).

    `materializar=False`: o iterador devolve as tuplas de `corpo` à medida que são produzidas.
    `materializar=True`: `corpo` é esgotado num TempFile (área 'trabalho'), os blocos são
    forçados a disco e o iterador lê do arquivo, que é apagado ao fim; `escrita_saida` = nº
    de blocos gravados do resultado (também somados em `writes`)."""
    if not materializar:
        return operacao_medida(ctx, corpo)
    estado = {"escrita_saida": 0}
    return operacao_medida(ctx, _materializado(ctx, corpo, esquema, estado),
                           extras=lambda: dict(estado))


def _materializado(ctx: StorageContext, corpo: Iterator[dict], esquema,
                   estado: dict) -> Iterator[dict]:
    tmp = None
    try:
        try:
            tmp = ctx.temp_file(esquema, "res")
            for rec in corpo:
                tmp.append(rec)
        finally:
            _fechar(corpo)            # solta as páginas do operador antes de ler o resultado
        tmp.close()
        estado["escrita_saida"] = forcar_gravacao(ctx, tmp)
        it = tmp.scan()
        try:
            yield from it
        finally:
            _fechar(it)
    finally:
        if tmp is not None:
            tmp.delete()
