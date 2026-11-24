# PROGRESS — estado da execução

> Mantido pelo Claude Code ao fim de cada etapa (ver protocolo no `CLAUDE.md`).
> Status: `pendente` · `em andamento` · `concluída` · `bloqueada (motivo)`

## Dados do usuário (para folha de rosto — preencher)
- Integrantes (nome completo — DRE):
  - 
- Repositório remoto (GitHub Classroom/GitLab): 
- Data da apresentação: 

## Etapas
| Etapa | Descrição | Status |
|---|---|---|
| E00 | Ambiente e esqueleto | concluída |
| E01 | Gerente de Arquivos | pendente |
| E02 | Gerente de Buffer Pool (LRU/MRU/FIFO/Clock) | pendente |
| E03 | Registros, slotted page, catálogo | pendente |
| E04 | Heap + interface FileOrganization | pendente |
| E05 | B+ parte 1 (busca, inserção, split) | pendente |
| E06 | B+ parte 2 (remoção, NOT UNIQUE, bulk load) | pendente |
| E07 | Hash estático externo | pendente |
| E08 | Índices secundários + métodos de acesso | pendente |
| E09 | Gerador da base + carga + SQLite | pendente |
| E10 | Seleção (A1–A6, hash) | pendente |
| E11 | Ordenação externa + BNL + INL | pendente |
| E12 | Sort-merge join + partition-hash join | pendente |
| E13 | Modelo de custo (estimado × medido) | pendente |
| E14 | Orquestrador + matriz de experimentos | pendente |
| E15 | Code review adversarial (checklist 7.1) | pendente |
| E16 | Estresse: bruto × refatorado | pendente |
| E17 | Execução completa + gráficos | pendente |
| E18 | Relatório técnico | pendente |
| E19 | Relatório de IA + POST_MORTEM.md | pendente |
| E20 | Slides + checklist final | pendente |

## Notas de handoff
<!-- Formato: ### Exx — AAAA-MM-DD  (≤ 8 linhas: feito, decisões, pendências, próximo passo se WIP) -->

### E00 — 2026-11-24
- Feito: .gitignore, venv + requirements.txt (versões fixadas), árvore src/{common,storage,access,executor,bench}, tests/, config/base.yaml (decisões fixadas + perfis), pytest.ini (marker stress, pythonpath=.).
- `src/common/config.py`: `load_config(perfil, overrides)` → `Config` frozen (Mappings read-only), valida soma das áreas, políticas e block_size. `erros.py`, `tipos.py` (RID, PageId).
- `tests/test_arquitetura.py`: AST, regra de camadas + proíbe `src.storage.file_manager` fora de storage.
- Docs: INTERFACES, DECISOES (D01–D23), code_review (1 defeito no analisador), README. Hook de prompts confirmado (prompts.md recebeu esta sessão).
- Decisão: PDFs de material/ continuam versionados (já estavam no commit init) — usuário pode pedir para remover.
- 20 testes verdes. Pendência: preencher dados do usuário (nomes/DRE) no topo deste arquivo.
