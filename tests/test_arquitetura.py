"""Verifica as regras de camadas por análise estática de imports (ast).

Ordem: bench -> executor -> access -> storage. Cada camada importa apenas ela mesma,
a imediatamente inferior e `src.common`. `src.common` não importa nenhuma camada.
Além disso, fora de `src/storage` ninguém importa `src.storage.file_manager`
(acesso a blocos só via BufferManager).
"""
import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
CAMADAS = ["bench", "executor", "access", "storage"]
PERMITIDAS = {
    c: {c, "common", *([CAMADAS[i + 1]] if i + 1 < len(CAMADAS) else [])}
    for i, c in enumerate(CAMADAS)
}
PERMITIDAS["common"] = {"common"}


def _modulos_importados(arquivo: Path) -> list[tuple[int, str]]:
    """Devolve (linha, módulo absoluto) para cada import de src.* no arquivo."""
    pacote = arquivo.relative_to(SRC.parent).with_suffix("").parts[:-1]
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    achados = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            achados += [(no.lineno, a.name) for a in no.names]
        elif isinstance(no, ast.ImportFrom):
            if no.level:  # import relativo -> resolve para absoluto
                base = pacote[: len(pacote) - (no.level - 1)]
                mod = ".".join([*base, *([no.module] if no.module else [])])
                if no.module:
                    achados.append((no.lineno, mod))
                achados += [(no.lineno, f"{mod}.{a.name}") for a in no.names]
            elif no.module:
                achados.append((no.lineno, no.module))
                achados += [(no.lineno, f"{no.module}.{a.name}") for a in no.names]
    return [(l, m) for l, m in achados if m == "src" or m.startswith("src.")]


def _arquivos():
    return sorted(SRC.rglob("*.py"))


def test_existem_todas_as_camadas():
    for c in [*CAMADAS, "common"]:
        assert (SRC / c / "__init__.py").exists(), f"falta src/{c}/__init__.py"


@pytest.mark.parametrize("arquivo", _arquivos(), ids=lambda p: str(p.relative_to(SRC)))
def test_imports_respeitam_camadas(arquivo):
    rel = arquivo.relative_to(SRC).parts
    if len(rel) == 1:
        return  # src/__init__.py
    camada = rel[0]
    violacoes = []
    for linha, mod in _modulos_importados(arquivo):
        partes = mod.split(".")
        if len(partes) < 2:
            violacoes.append(f"{linha}: import genérico de 'src'")
            continue
        alvo = partes[1]
        if alvo not in PERMITIDAS.get(camada, set()):
            violacoes.append(f"{linha}: {camada} importa {mod}")
        if camada != "storage" and mod.startswith("src.storage.file_manager"):
            violacoes.append(f"{linha}: FileManager usado fora de src/storage")
    assert not violacoes, f"{arquivo.relative_to(SRC)}:\n" + "\n".join(violacoes)


def test_detector_pega_violacao(tmp_path, monkeypatch):
    """Sanidade: o analisador detecta import proibido (bench -> storage) e relativo."""
    falso = tmp_path / "src"
    (falso / "bench").mkdir(parents=True)
    f = falso / "bench" / "x.py"
    f.write_text("from src.storage import buffer_manager\nfrom ..access import heap\n",
                 encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "SRC", falso)
    mods = [m for _, m in _modulos_importados(f)]
    assert "src.storage" in mods and "src.access.heap" in mods
