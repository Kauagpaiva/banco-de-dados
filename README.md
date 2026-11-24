# Bancada de Teste de SBD — Avaliação 2 (CDB 2026.2 / UFRJ)

Bancada em Python que mede **blocos transferidos entre disco simulado e buffer pool** para
comparar configurações do Gerente de Armazenamento (organização primária, índices, política de
buffer, algoritmos de seleção e junção).

## Arquitetura (4 camadas)
`src/bench` → `src/executor` → `src/access` → `src/storage` (+ `src/common`, livre).
Cada camada importa só a imediatamente inferior; verificado por `tests/test_arquitetura.py`.

## Como rodar (Windows)
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -q              # suíte rápida
.venv/Scripts/python -m pytest -q -m stress    # testes de estresse
```
Linux/macOS: troque `.venv/Scripts/python` por `.venv/bin/python`.

## Configuração
`config/base.yaml` (bloco, buffer e áreas, políticas, hash, B+, perfis de volume).
No código: `from src.common.config import load_config; cfg = load_config("teste", {"buffer.policy": "MRU"})`.

## Pastas
- `config/` parâmetros e experimentos · `src/` código · `tests/` testes
- `data/` bases geradas (fora do git) · `results/` CSVs e gráficos
- `docs/` plano, interfaces, decisões, referência do livro · `ia_log/` prompts e code review
- `relatorio/` relatórios e slides
