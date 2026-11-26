# Code review — M5J (Sort-merge join + partition-hash join)

> Revisão técnica realizada sobre os arquivos integrados à `main`.
> Escopo: implementação, gerenciamento de memória, arquivos temporários, tratamento de valores nulos, duplicatas e testes.
> Os achados abaixo são de auto-revisão, não de revisão cruzada por outro integrante.

## 1. Arquivos analisados

- `src/executor/join_hash.py`
- `src/executor/join_smj.py`
- `tests/test_join_smj_hash.py`

## 2. Achados — Sort-Merge Join

### [Auto-revisão] SMJ-01 — Dependência indevida de módulo de testes

**Arquivo:** `src/executor/join_smj.py`

Foi identificada a importação:

```python
from tests.conftest import ctx
```

O módulo de produção não deve depender de fixtures ou arquivos da suíte de testes. Essa importação é desnecessária para a implementação e pode causar problemas quando o executor for utilizado fora do ambiente de testes.

**Recomendação:** remover a importação e manter as dependências de produção restritas aos módulos de `src`.

**Prioridade:** alta.

### [Auto-revisão] SMJ-02 — Documentação não corresponde integralmente à implementação

**Arquivo:** `src/executor/join_smj.py`

A documentação inicial menciona duas otimizações:

- Pular a ordenação quando a relação já possui ordem disponível por `find_ordered`.
- Utilizar fallback BNL para grupos maiores que a memória disponível.

Na implementação examinada, as duas relações são sempre ordenadas com `external_sort`, e os grupos de chaves iguais são armazenados em arquivos temporários.

**Recomendação:** implementar as otimizações prometidas ou atualizar a documentação para descrever o comportamento real.

**Prioridade:** média.

### [Auto-revisão] SMJ-03 — Possível vazamento de temporário durante coleta de grupos

**Arquivo:** `src/executor/join_smj.py`

Na função `_merge`, o grupo de R é criado antes do grupo de S. O bloco `try/finally` responsável pela exclusão dos dois grupos começa somente depois da criação de ambos.

Se a coleta do grupo de S falhar, o temporário de R poderá não ser excluído.

**Recomendação:** ampliar a proteção com `try/finally` para cobrir também a criação e coleta dos dois grupos.

**Teste recomendado:** simular uma falha durante a coleta do grupo de S e verificar se o temporário de R foi excluído.

**Prioridade:** média.

## 3. Achados — Partition-Hash Join

### [Auto-revisão] HASH-01 — Limite de partições na chamada inicial

**Arquivo:** `src/executor/join_hash.py`

Na função `_hash`, a quantidade inicial de partições é definida a partir de `nh` quando esse argumento é fornecido:

```python
quantidade = nh or min(
    mb.M - 1,
    ...
)
```

Diferentemente do cálculo recursivo, essa expressão não limita explicitamente `nh` a `M - 1`.

Assim, uma chamada com valor elevado de `nh` pode criar mais arquivos temporários do que o orçamento de memória sugere.

**Recomendação:** aplicar o mesmo limite utilizado no particionamento recursivo.

**Teste recomendado:** utilizar `M=3` e um `nh` muito elevado, verificando a quantidade de arquivos de partição criados.

**Prioridade:** alta.

### [Auto-revisão] HASH-02 — Falha parcial na criação de partições

**Arquivo:** `src/executor/join_hash.py`

A função `_criar_particoes` cria os arquivos temporários em sequência. Se a criação de um arquivo falhar no meio do processo, os arquivos já criados podem permanecer sem limpeza, pois a proteção de `_particionar` começa depois da chamada a `_criar_particoes`.

**Recomendação:** proteger também a etapa de criação e excluir os arquivos já criados em caso de falha.

**Teste recomendado:** simular uma falha na criação de uma partição intermediária e verificar a exclusão dos arquivos anteriores.

**Prioridade:** média.

## 4. Aspectos positivos identificados

### Sort-Merge Join

- Ordenação externa das relações antes da intercalação.
- Tratamento de chaves nulas.
- Preservação de combinações envolvendo chaves duplicadas.
- Armazenamento dos grupos em arquivos temporários, evitando manter grupos inteiros na memória.
- Exclusão dos arquivos temporários ao finalizar o processamento.
- Uso de `try/finally` para proteger a limpeza durante o processamento dos grupos.

### Partition-Hash Join

- Particionamento das duas relações com a mesma função de distribuição.
- Construção da tabela hash sobre a menor partição.
- Tratamento de chaves nulas.
- Tratamento de colisões por meio de listas de registros.
- Particionamento recursivo.
- Fallback para nested-loop em situações de skew.
- Controle de reservas de memória por `MemoryBudget`.
- Limpeza de partições temporárias em blocos `finally`.

## 5. Testes e validação

Resultados registrados durante o desenvolvimento:

| Validação | Resultado |
|---|---:|
| Testes específicos do M5J | 15 passed |
| Suíte completa | 449 passed |
| Testes esperadamente falhos | 70 xfailed |

