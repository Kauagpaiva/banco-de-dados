"""Mede as transferências do `external_sort` (Silberschatz 15.4.2) no código bruto (`raw-E11`) e no atual.

Uso (a partir da raiz de cada árvore de trabalho; usa FakeBufferManager/FakeTable, área 'trabalho' = M):

    git worktree add ../wt_raw_e11 raw-E11
    (cd ../wt_raw_e11 && python ../banco-de-dados/ia_log/evidencia/medir_sort.py)   # código bruto
    python ia_log/evidencia/medir_sort.py                                            # código atual
    git worktree remove --force ../wt_raw_e11

Resultado de 28/11/2026 em `ia_log/evidencia/medir_sort_resultado.txt`.
"""
import sys, math
sys.path.insert(0, ".")
from src.common.config import load_config
from tests.conftest import bm_fake
from tests.fakes import FakeStorageContext, FakeTable
from src.access.esquemas import ALUNO
from src.executor.sort import external_sort
from tests.test_sort import _regs
for M in (3, 5):
    cfg = load_config(overrides={"buffer.areas.trabalho": M, "buffer.total_pages": 8 + 64 + 120 + M})
    bm = bm_fake(cfg)
    ctx = FakeStorageContext(cfg, bm=bm)
    t = FakeTable(bm, "aluno_custo", ALUNO); t.open()
    for r in _regs(): t.insert(r)
    b = t.num_blocks(); ctx.drop_all(); ctx.reset_stats()
    tmp, m = external_sort(ctx, t, ALUNO, "CR", M=M)
    passos = math.ceil(math.log(math.ceil(b / M), M - 1))
    esperado = b * (2 * passos + 1) + b
    print(f"M={M} b={b} medido={m['transferencias']} esperado(livro)={esperado}")
    tmp.delete(); ctx.close()
