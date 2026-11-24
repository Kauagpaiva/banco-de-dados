"""Testes de contrato (M0): os mesmos testes valem para o fake e para a implementação real.
A variante `real` vira xfail enquanto a implementação for stub (NotImplementedError)."""
import pytest


def construir(tipo: str, real, fake):
    """tipo='fake' → fake(); tipo='real' → real(), ou xfail se ainda for stub."""
    if tipo == "fake":
        return fake()
    try:
        return real()
    except NotImplementedError:
        pytest.xfail("implementação real ainda é stub (NotImplementedError)")
