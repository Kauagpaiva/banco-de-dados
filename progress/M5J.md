# M5J — Sort-merge join + partition-hash join

- **Dono:** P2 (ver `PROGRESS.md`) · **Fase:** 1 · **Branch:** `mod/M5J-join`
- Escopo, arquivos e dependências: `docs/MODULOS.md` › `### M5J`

## Etapas

| Etapa | Descrição | Status |
|---|---|---|
| E12 | SMJ + hash join | concluída |

## Pedidos de mudança de contrato

Nenhum.

## Notas de handoff

### E12 — 2026-11-26
- Implementados Sort-Merge Join e Partition-Hash Join.
- Tratamento de chaves nulas e duplicadas no SMJ.
- Limite de partições e limpeza de temporários no Hash Join.
- Testes específicos: 15 aprovados.
- Suíte completa: 449 passed, 70 xfailed.
- Validação realizada com fakes; integração com armazenamento real depende das etapas anteriores.
- Próximo passo: revisão final, documentação e PR.