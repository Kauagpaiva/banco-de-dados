"""Compara a suíte de estresse atual com versões brutas do projeto."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAGS = ["raw-E02", "raw-E05", "raw-E06", "raw-E07", "raw-E11", "raw-E12"]
TESTS = ROOT / "tests" / "stress"
REPORT = ROOT / "ia_log" / "stress_raw_vs_fix.md"


def executar(comando, cwd):
    inicio = time.perf_counter()
    processo = subprocess.run(
        comando,
        cwd=cwd,
        text=True,
        capture_output=True,
        errors="replace",
    )
    duracao = time.perf_counter() - inicio
    saida = processo.stdout + "\n" + processo.stderr

    excecoes = sorted(set(re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)\b",
        saida,
    )))

    transferencias = re.findall(
        r"(?:transfer[eê]ncias|transfers)\s*[:=]\s*(\d+)",
        saida,
        re.IGNORECASE,
    )

    return {
        "ok": processo.returncode == 0,
        "tempo": duracao,
        "excecoes": ", ".join(excecoes) if excecoes else "Nenhuma identificada",
        "transferencias": transferencias[-1] if transferencias else "N/D",
        "saida": saida,
    }


def testar(nome, diretorio):
    resultado = executar(
        [
            sys.executable, "-m", "pytest",
            "tests/stress/test_join_stress.py", "-m", "stress", "-q", "-s",
        ],
        diretorio,
    )

    status = "PASSOU" if resultado["ok"] else "FALHOU"

    return {
        "versao": nome,
        "status": status,
        **resultado,
    }


def main():
    resultados = []

    # Versão refatorada atual.
    resultados.append(testar("refatorado (HEAD)", ROOT))

    with tempfile.TemporaryDirectory(prefix="m11_stress_") as temporario:
        base = Path(temporario)

        for tag in TAGS:
            existe = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/tags/{tag}"],
                cwd=ROOT,
                capture_output=True,
            )

            if existe.returncode != 0:
                resultados.append({
                    "versao": tag,
                    "status": "AUSENTE",
                    "tempo": 0,
                    "excecoes": "Tag não encontrada",
                    "transferencias": "N/D",
                    "saida": "",
                })
                continue

            worktree = base / tag

            adicao = subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree), tag],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            if adicao.returncode != 0:
                resultados.append({
                    "versao": tag,
                    "status": "ERRO WORKTREE",
                    "tempo": 0,
                    "excecoes": adicao.stderr.strip(),
                    "transferencias": "N/D",
                    "saida": adicao.stderr,
                })
                continue

            try:
                destino = worktree / "tests" / "stress"
                destino.mkdir(parents=True, exist_ok=True)

                shutil.copytree(
                    ROOT / "tests" / "fakes",
                    worktree / "tests" / "fakes",
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )

                shutil.copy2(
                    ROOT / "tests" / "conftest.py",
                    worktree / "tests" / "conftest.py",
                )

                shutil.copytree(
                    TESTS,
                    destino,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )

                resultados.append(testar(tag, worktree))
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )

    REPORT.parent.mkdir(parents=True, exist_ok=True)

    linhas = [
        "# Comparação de estresse — código bruto × refatorado",
        "",
        "Execução automática da suíte `tests/stress`.",
        "",
        "| Versão | Resultado | Exceções | Transferências | Tempo (s) |",
        "|---|---|---|---:|---:|",
    ]

    for r in resultados:
        linhas.append(
            f"| {r['versao']} | {r['status']} | "
            f"{r['excecoes']} | {r['transferencias']} | "
            f"{r['tempo']:.2f} |"
        )

    linhas.extend([
        "",
        "## Observações",
        "",
        "- `N/D` significa que a suíte não expôs a métrica de transferências.",
        "- Tags ausentes foram registradas sem execução.",
        "- Falhas devem ser analisadas considerando diferenças de interface entre versões.",
        "",
    ])

    REPORT.write_text("\n".join(linhas), encoding="utf-8")

    print(f"Relatório gerado: {REPORT}")
    print("\nResumo:")
    for r in resultados:
        print(f"{r['versao']}: {r['status']} ({r['tempo']:.2f}s)")


if __name__ == "__main__":
    main()