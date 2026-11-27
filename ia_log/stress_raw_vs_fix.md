@'
# Comparação de estresse — código bruto × refatorado

## Metodologia

A comparação histórica foi executada usando `tests/stress/test_join_stress.py`,
com amostra reduzida de 500 registros por relação, para viabilizar a execução
nos worktrees das versões anteriores.

Os resultados abaixo não representam a execução integral dos testes de estresse.

| Versão | Resultado | Exceções | Transferências | Tempo (s) |
|---|---|---|---:|---:|
| refatorado (HEAD) | PASSOU | Nenhuma identificada | N/D | 11.76 |
| raw-E02 | FALHOU | NotImplementedError | N/D | 3.51 |
| raw-E05 | PASSOU | Nenhuma identificada | N/D | 10.65 |
| raw-E06 | PASSOU | Nenhuma identificada | N/D | 10.36 |
| raw-E07 | PASSOU | Nenhuma identificada | N/D | 10.75 |
| raw-E11 | FALHOU | NotImplementedError | N/D | 3.83 |
| raw-E12 | AUSENTE | Tag não encontrada | N/D | 0.00 |

## Validação da versão atual

Na versão atual, foram aprovados:

- B+ Tree: 200.000 inserções aleatórias.
- Hash Join: memória mínima e chaves concentradas.
- Sort-Merge Join: memória mínima e chaves concentradas.
- Hash Join: 100% de chaves duplicadas.
- Sort-Merge Join: 100% de chaves duplicadas.

Os quatro testes de join também foram executados com 20.000 registros por relação e aprovados.

## Limitações e observações

- A comparação histórica utilizou amostra reduzida de 500 registros por relação.
- `N/D` indica que a execução não expôs a métrica de transferências.
- A tag `raw-E12` não foi encontrada.
- As falhas de E02 e E11 apresentaram `NotImplementedError`.
- O teste de estresse do HashIndex não foi concluído: a implementação disponível na branch atual ainda apresenta `NotImplementedError`.
- O cenário de registros de tamanho máximo e o hash degenerado ainda precisam de validação.
'@ | Set-Content ia_log\stress_raw_vs_fix.md -Encoding utf8