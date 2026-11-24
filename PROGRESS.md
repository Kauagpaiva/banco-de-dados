# PROGRESS — quadro geral

> O status detalhado de cada módulo fica em `progress/Mx.md` (cada módulo edita só o seu,
> para não gerar conflito de merge). Este quadro é atualizado pelo líder ao integrar.
> Divisão e regras: `docs/MODULOS.md` · Fluxo de Git: `docs/GIT_FLUXO.md`.

## Integrantes (nome completo — DRE)
| Papel | Nome completo | DRE | Usuário GitHub |
|---|---|---|---|
| P1 (líder) | Kauã Gomes de Paiva da Costa | 122070496 | Kauagpaiva |
| P2 | Emanuel Cardoso | 122033151 | |
| P3 | Davi Richards Nascimento | 119022078 | |
| P4 | Rodrigo Melo Dias | 119048189 | |
| P5 | Ramon Silva Ramirez | 111205591 | |

> Papéis P2–P5 podem ser trocados entre os integrantes; basta ajustar esta tabela.

- Repositório: https://github.com/Kauagpaiva/banco-de-dados
- Data da apresentação:

## Módulos
| Módulo | Descrição | Fase | Dono | Status |
|---|---|---|---|---|
| M0 | Contratos, fakes e infraestrutura | 0 | P1 | `progress/M0.md` |
| M1 | Gerente de Arquivos + Buffer Pool | 1 | P1 | `progress/M1.md` |
| M2 | Registros, slotted page, catálogo, Heap, TempFile | 1 | P2 | `progress/M2.md` |
| M3 | Árvore B+ primária | 1 | P3 | `progress/M3.md` |
| M4 | Hash estático + HashIndex secundário | 1 | P4 | `progress/M4.md` |
| M5 | Seleção, ordenação externa, BNL, INL | 1 | P5 | `progress/M5.md` |
| M5J | Sort-merge join + partition-hash join | 1 | P2 | `progress/M5J.md` |
| M6 | Modelo de custo | 1 | P1 | `progress/M6.md` |
| M7 | Gerador da base + SQLite | 1 | P4 | `progress/M7.md` |
| M8 | Índices B+ secundários, registry, loader | 2 | P3 | `progress/M8.md` |
| M9 | Orquestrador + experimentos | 2 | P4 | `progress/M9.md` |
| M10 | Integração vs SQLite + estimado × medido | 2 | P5 | `progress/M10.md` |
| M11 | Estresse bruto × refatorado | 2 | P2 | `progress/M11.md` |
| RC | Code review cruzado | 2 | todos | `progress/RC.md` |
| M12 | Execução completa + gráficos | 3 | P4 | `progress/M12.md` |
| M13 | Relatório técnico | 3 | P1+P2 | `progress/M13.md` |
| M14 | Relatório de IA + POST_MORTEM | 3 | P3 | `progress/M14.md` |
| M15 | Slides + checklist final | 3 | P5 | `progress/M15.md` |

## Marcos de integração
- [ ] Fase 0: M0 em `main` (libera a Fase 1)
- [ ] M1 + M2 em `main` (testes passam a usar buffer/página reais)
- [ ] Fase 1 completa em `main` (libera a Fase 2)
- [ ] Fase 2 completa (libera os experimentos)
- [ ] Entrega: relatórios, POST_MORTEM.md, slides
