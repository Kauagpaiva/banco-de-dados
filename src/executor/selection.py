"""Seleção (Camada 2) — M5, E10.

Silberschatz 15.2 / Fig. 15.3 (A1–A6) e 15.3; REFERENCIA_LIVRO §6. O caminho é escolhido pelo
chamador (sem otimizador) e validado contra o método de acesso:

| caminho    | exige                                                     | operação usada                     |
|------------|-----------------------------------------------------------|------------------------------------|
| A1_linear  | qualquer organização, qualquer op                         | `tabela.scan()` + filtro           |
| A1_chave   | op '=' em campo chave (UNIQUE)                            | `scan()` até o 1º casamento        |
| A2         | org. B+ no campo, UNIQUE, op '='                          | `find_ordered(v, v)` (1 registro)  |
| A3         | org. B+ no campo, op '='                                  | `find_ordered(v, v)`               |
| A4         | índice secundário no campo, op '='                        | `search_eq` + busca de cada ref    |
| A5         | org. B+ no campo, op de comparação                        | `find_ordered(lo, hi)`             |
| A6         | índice secundário no campo, op de comparação              | `search_range` + busca de cada ref |
| HASH_PRIM  | org. hash no campo, op '='                                | `find`/`find_next` + `read`        |
| HASH_SEC   | índice secundário (hash) no campo, op '='                 | `search_eq` + busca de cada ref    |

Combinação inválida → `ValueError` (na chamada, antes de qualquer I/O).
Ref de índice: RID (`tabela.read`) ou, se `refs_por_chave` (14.4.2), valor do campo da
organização primária ordenada (`tabela.find_ordered(ref, ref)`).
Todo registro devolvido passa por `predicado.avaliar` (nulos nunca satisfazem).
"""
from __future__ import annotations

from typing import Any, Iterator

from src.executor.contracts import (
    CAMINHOS_SELECAO, AccessMethod, Predicado, Resultado, SecondaryIndex, StorageContext,
)
from src.executor.scan import operacao_medida

_COMPARACOES = ("<", "<=", ">", ">=")


def select(ctx: StorageContext, am: AccessMethod, predicado: Predicado, caminho: str) -> Resultado:
    """σ_{campo op valor}(tabela) pelo caminho `caminho` ∈ CAMINHOS_SELECAO (Silberschatz 15.2).

    Devolve `(iterador, metricas)`; métricas preenchidas quando o iterador se esgota ou é
    fechado. Caminho incompatível com o método de acesso → ValueError."""
    corpo = _planejar(am, predicado, caminho)
    return operacao_medida(ctx, corpo)


# =========================================================================== validação
def _planejar(am: AccessMethod, pred: Predicado, caminho: str) -> Iterator[dict]:
    if caminho not in CAMINHOS_SELECAO:
        raise ValueError(f"caminho desconhecido: {caminho!r} (válidos: {CAMINHOS_SELECAO})")
    pred = Predicado(*pred).validar()
    tabela = am.tabela
    try:
        am.esquema.campo(pred.campo)
    except KeyError:
        raise ValueError(f"{am.esquema.nome}: campo inexistente {pred.campo!r}") from None

    igualdade = pred.op == "="
    org_no_campo = getattr(tabela, "campo", None) == pred.campo
    tipo_org = getattr(tabela, "tipo_org", None)

    def exigir(cond: bool, motivo: str) -> None:
        if not cond:
            raise ValueError(f"caminho {caminho} inválido para {am.esquema.nome}.{pred.campo} "
                             f"{pred.op}: {motivo}")

    if caminho == "A1_linear":
        return _linear(tabela, pred)
    if caminho == "A1_chave":
        exigir(igualdade, "A1_chave exige igualdade")
        exigir(_eh_chave(am, pred.campo), "campo não é chave (UNIQUE)")
        return _linear(tabela, pred, parar_no_primeiro=True)
    if caminho in ("A2", "A3", "A5"):
        exigir(tipo_org == "bplus" and org_no_campo,
               "exige organização primária B+ ordenada nesse campo")
        if caminho == "A2":
            exigir(igualdade, "A2 exige igualdade")
            exigir(bool(getattr(tabela, "unique", False)), "A2 exige campo UNIQUE (use A3)")
            return _primario_ordenado(tabela, pred, parar_no_primeiro=True)
        if caminho == "A3":
            exigir(igualdade, "A3 exige igualdade")
            return _primario_ordenado(tabela, pred)
        exigir(pred.op in _COMPARACOES, "A5 exige comparação (<, <=, >, >=)")
        return _primario_ordenado(tabela, pred)
    if caminho == "HASH_PRIM":
        exigir(tipo_org == "hash" and org_no_campo, "exige organização primária hash nesse campo")
        exigir(igualdade, "hash só atende igualdade")
        return _hash_primario(tabela, pred, unique=bool(getattr(tabela, "unique", False)))

    # A4, A6, HASH_SEC: índice secundário
    idx = am.indice(pred.campo)
    exigir(idx is not None, "não há índice secundário nesse campo")
    if idx.refs_por_chave:
        exigir(tipo_org == "bplus" and getattr(tabela, "campo", None) is not None,
               "índice com refs_por_chave exige organização B+ (14.4.2)")
    if caminho == "A6":
        exigir(pred.op in _COMPARACOES, "A6 exige comparação (<, <=, >, >=)")
    else:
        exigir(igualdade, f"{caminho} exige igualdade")
    return _secundario(tabela, idx, pred, parar_no_primeiro=igualdade and idx.unique)


def _eh_chave(am: AccessMethod, campo: str) -> bool:
    """Campo é chave candidata: PK de um campo, campo de org. UNIQUE ou índice UNIQUE."""
    t = am.tabela
    if tuple(am.esquema.chave) == (campo,):
        return True
    if getattr(t, "campo", None) == campo and getattr(t, "unique", False):
        return True
    idx = am.indice(campo)
    return idx is not None and bool(idx.unique)


def _faixa(pred: Predicado) -> tuple[Any, Any, bool, bool]:
    """(lo, hi, incl_lo, incl_hi) do predicado (None = sem limite)."""
    v, op = pred.valor, pred.op
    if op == "=":
        return v, v, True, True
    if op == "<":
        return None, v, True, False
    if op == "<=":
        return None, v, True, True
    if op == ">":
        return v, None, False, True
    return v, None, True, True          # '>='


# =========================================================================== corpos
def _linear(tabela, pred: Predicado, parar_no_primeiro: bool = False) -> Iterator[dict]:
    """A1 (15.2): varredura física de todos os blocos; com chave, para no 1º casamento."""
    it = tabela.scan()
    try:
        for _, rec in it:
            if pred.avaliar(rec):
                yield rec
                if parar_no_primeiro:
                    return
    finally:
        _fechar(it)


def _primario_ordenado(tabela, pred: Predicado, parar_no_primeiro: bool = False
                       ) -> Iterator[dict]:
    """A2/A3/A5 (15.2): índice clustering = organização B+ no campo; a faixa é lida em ordem
    pelas folhas encadeadas (`find_ordered`). Para `<`/`<=` começa do início do arquivo."""
    lo, hi, incl_lo, incl_hi = _faixa(pred)
    it = tabela.find_ordered(pred.campo, lo, hi, incl_lo, incl_hi)
    try:
        for _, rec in it:
            if pred.avaliar(rec):
                yield rec
                if parar_no_primeiro:
                    return
    finally:
        _fechar(it)


def _hash_primario(tabela, pred: Predicado, unique: bool) -> Iterator[dict]:
    """Hash estático primário (14.5): bucket (com cadeia de overflow) via `find`/`find_next`."""
    try:
        rid = tabela.find(pred.campo, pred.valor)
        while rid is not None:
            rec = tabela.read(rid)
            if pred.avaliar(rec):
                yield rec
                if unique:
                    return
            rid = tabela.find_next()
    finally:
        tabela.reset()


def _secundario(tabela, idx: SecondaryIndex, pred: Predicado, parar_no_primeiro: bool
                ) -> Iterator[dict]:
    """A4/A6/HASH_SEC (15.2): refs do índice secundário; cada ref custa um acesso ao arquivo
    (RID → `read`; chave primária → `find_ordered(k, k)` na B+ primária)."""
    if pred.op == "=":
        refs = idx.search_eq(pred.valor)
    else:
        lo, hi, incl_lo, incl_hi = _faixa(pred)
        refs = idx.search_range(lo, hi, incl_lo, incl_hi)
    try:
        for ref in refs:
            for rec in _buscar_ref(tabela, idx, ref):
                if pred.avaliar(rec):
                    yield rec
                    if parar_no_primeiro:
                        return
    finally:
        _fechar(refs)


def _buscar_ref(tabela, idx: SecondaryIndex, ref: Any) -> Iterator[dict]:
    if not idx.refs_por_chave:
        yield tabela.read(ref)
        return
    it = tabela.find_ordered(tabela.campo, ref, ref, True, True)
    try:
        for _, rec in it:
            yield rec
    finally:
        _fechar(it)


def _fechar(it: Any) -> None:
    fechar = getattr(it, "close", None)
    if callable(fechar):
        fechar()


# =========================================================================== uso pelo INL (E11)
def caminho_igualdade(am: AccessMethod, campo: str) -> str:
    """Melhor caminho estrutural para `campo = v` em `am` (usado pelo indexed nested-loop,
    15.5.3): organização primária no campo (A2/A3 ou HASH_PRIM) > índice secundário
    (A4/HASH_SEC). Sem estrutura no campo → ValueError (o INL exige índice)."""
    t = am.tabela
    if getattr(t, "campo", None) == campo:
        tipo = getattr(t, "tipo_org", None)
        if tipo == "bplus":
            return "A2" if getattr(t, "unique", False) else "A3"
        if tipo == "hash":
            return "HASH_PRIM"
    if am.indice(campo) is not None:
        return "A4"
    raise ValueError(f"{am.esquema.nome}: não há índice nem organização primária em {campo!r}")


def buscar_igualdade(am: AccessMethod, campo: str, valor: Any, caminho: str) -> Iterator[dict]:
    """Corpo (sem medição) de σ_{campo = valor} pelo `caminho` de `caminho_igualdade`.
    Valor nulo → nenhum registro (nulos não casam)."""
    if valor is None:
        return iter(())
    return _planejar(am, Predicado(campo, "=", valor), caminho)
