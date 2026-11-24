"""Gerador determinístico da base universitária — STUB do M0; implementação: M7 (E09).

Gera registros `dict` conforme `ESQUEMAS` (semente `cfg.seed`, volumes `cfg.volumes`),
com FKs válidas, CR calibrado (CR > x1 ≈ 1%, CR < x50 ≈ 50%) e `professor` com cardinalidade
controlada (equijoin NOT UNIQUE Aluno.prof_orientador = Turma.professor).
"""
from __future__ import annotations

from typing import Iterator


def gerar_tabela(cfg, nome: str) -> Iterator[dict]:
    """Registros da tabela `nome` no perfil de `cfg` (mesma saída para a mesma semente)."""
    raise NotImplementedError("M7/E09")


def limiares_cr(cfg) -> dict[str, float]:
    """{'x1': ..., 'x50': ...} tais que CR > x1 ≈ 1% e CR < x50 ≈ 50% das tuplas de Aluno."""
    raise NotImplementedError("M7/E09")
