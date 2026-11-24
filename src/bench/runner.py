"""Orquestrador da matriz de experimentos — STUB do M0; implementação: M9 (E14).

CLI: `python -m src.bench.runner --perfil teste --exp config/experimentos/sel_igualdade.yaml`.
Cold start (drop_all + reset_stats) por ponto; repetições até CV < 5% (mín 3, máx 7);
1 linha CSV por repetição em `results/<exp>.csv` (colunas em `COLUNAS`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

COLUNAS = (
    "exp", "operacao", "algoritmo", "caminho", "org_r", "idx_r", "org_s", "idx_s", "tam_r",
    "tam_s", "seletividade", "politica", "M", "block_size", "rep", "leituras", "gravacoes", "seq",
    "seeks", "requests", "hits", "misses", "hit_rate", "dirty_evictions", "forced_writes",
    "est_transf", "est_seeks", "dif_rel", "tuplas_saida", "tempo_s", "ok_sqlite",
)


def executar_experimento(caminho_exp: Path | str, perfil: str = "teste",
                         saida: Optional[Path | str] = None) -> Path:
    """Roda todos os pontos do YAML e devolve o caminho do CSV gerado."""
    raise NotImplementedError("M9/E14")


def main(argv: Optional[Sequence[str]] = None) -> int:
    raise NotImplementedError("M9/E14")


if __name__ == "__main__":
    raise SystemExit(main())
