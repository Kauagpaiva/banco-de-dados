# POST_MORTEM — IA na Bancada de Teste de SBD

**Avaliação 2 — Indexação e Processamento de Consultas · CDB 2026.2 · UFRJ**
Grupo: Kauã Gomes de Paiva da Costa (122070496) · Emanuel Cardoso (122033151) · Davi Richards Nascimento (119022078) ·
Rodrigo Melo Dias (119048189) · Ramon Silva Ramirez (111205591)

> **Estado (28/11/2026):** rascunho do módulo M14 com o que está em `main`. Cada autor deve conferir o trecho do seu módulo.
> O que depende de módulos não concluídos (M8, M10, M12, M13, RC/E15) está marcado **[PENDENTE]** — nada foi inventado.
> Relatório completo (logs, consolidação, bateria de testes): [`relatorio/relatorio_ia.md`](relatorio/relatorio_ia.md).
> Código bruto de qualquer etapa: `git show raw-Exx:<arquivo>` · diferenças: `git diff raw-Exx HEAD -- <arquivo>`.

## Resumo crítico

Cinco pessoas, cinco IAs, um módulo cada, integração por `main`. Dos **24 achados** registrados em `ia_log/code_review/`,
**15 foram em código de produção** e **9 em testes** (os testes gerados pela IA também estavam errados). O que a IA errou **não** foi
o que o enunciado (§7.1) mais temia — nenhuma leitura fora do Buffer Pool, nenhum `pin` sem `unpin`, B+ com as invariantes íntegras,
hash com a cadeia de overflow correta —, em boa parte porque essas regras estavam **escritas no prompt de contexto** (`CLAUDE.md`) e
porque havia testes e uma fixture (`assert_no_pins()`) que as impõem. (Ressalva: a regra explícita "memória ≤ M páginas" **foi** violada em 3 lugares;
regra escrita não basta quando a violação nasce dentro de uma abstração.) Os erros da IA concentraram-se em quatro famílias:

1. **Custos de E/S escondidos pela abstração** — o merge externo pinava páginas demais e fazia a página de saída ir e voltar ao disco
   (+66 % de transferências no caso medido). O código era *correto* (a saída ordenava) e *lento*.
2. **Memória sem querer** — um `list(...)` sobre o arquivo inteiro dentro de `reorganize()`, num projeto cujo critério é não passar de M páginas.
3. **Metodologia de medição** — "cold start" que não era frio (estado físico do braço do disco e *free list*), e uma manutenção cujas gravações
   não entravam na conta (dirty sem *flush* dentro da medição). Números plausíveis, porém errados.
4. **Calibração numérica** — arredondamento que fazia limiares de seletividade perderem uma tupla na fronteira.

Em paralelo, o próprio uso da IA teve falhas de **processo**, relatadas na seção 4: tag "bruta" criada tarde, **falso positivo** de
revisão que quase virou defeito no relatório, interpretação restritiva de um pedido, e logs de prompt incompletos.

---

## 1. Code Review crítico: prompts-chave e fragmentos brutos

### 1.1 Prompts-chave

| Prompt (fonte) | O que a IA fez | Avaliação crítica |
|---|---|---|
| *"Tem como separar o projeto em modulos que possam ser desenvolvidos simultaneamente? somos um grupo de 5 pessoas … cada um pudesse utilizar sua propria IA …"* (P1, 24/11, `ia_log/prompts/kaua-gomes.md`) | Gerou `docs/MODULOS.md`, contratos congelados (`contracts.py`), fakes (`tests/fakes/`) e o protocolo `/modulo Mx` do `CLAUDE.md`. | **Foi a decisão que mais valeu.** Contratos + fakes permitiram trabalhar em paralelo e testar cada módulo contra fake **e** real. Custo: contratos mal pensados viram pedidos de mudança (houve [E00b] contexto sem injeção). |
| Regras no `CLAUDE.md` ("Nenhum acesso a blocos fora do BufferManager", "Todo `pin` tem `unpin`", "memória de trabalho limitada a M páginas") + `/modulo Mx` | A IA cumpriu as regras de §7.1 que estavam explícitas. | Regras sobre **acesso a blocos, pin/unpin e overflow** explícitas no prompt → 0 achados. Mas a regra de **memória ≤ M** também era explícita e foi violada em 3 lugares (A, B, M5J `nh`), e o que *não* estava escrito (custo de I/O, estado físico da medição, calibração) concentra os defeitos. Contexto ajuda, não garante. |
| *"Analise a implementação existente de `src/access/record.py` e implemente o RecordCodec conforme os contratos … Respeite … bitmap de nulos, campos de tamanho fixo, campos variáveis com offset e tamanho …"* (M2, reconstruído, `ia_log/prompts/M2.md`) | Codec e slotted page. | Prompt específico sobre **offsets validados** — categoria §7.1 sem achados; o único achado do M2 foi de **arquitetura** (camadas), não de offsets. |
| *"faca o M3 do arquivo progress.md"* (P3, `ia_log/prompts/davi-richards.md`) | A IA fez **só a E05** (B+ parte 1). | **Falha de interpretação da IA** (seguiu "1 etapa por sessão" sem perguntar). Deixou 2 testes de contrato vermelhos na `main` e custou uma rodada extra. Corrigido por *"faca tudo do m3 entao"*. |
| *"commita direto na main, sem o pr"* (P3) | Merge *fast-forward* e push. | Autorizado explicitamente; a IA avisou do risco (CI vermelho). Mostra o custo de pular o PR: o M11 só descobriu o problema pelo CI. |

### 1.2 Fragmentos brutos devolvidos pela IA (antes de qualquer correção manual)

**A — M5 · `external_sort`, merge N-vias (`raw-E11`, `src/executor/sort.py`)**
```python
paginas = len(grupo) * bb
mb.reservar_paginas(paginas)        # buffers de entrada contados como páginas PINADAS
mb.reservar_paginas_io(bb)
```
*Defeito:* com a área `trabalho` = M sobra **1 frame** para ler os runs *e* para o *append* da saída; cada recarga de cursor expulsa a página
de saída (dirty → gravação) e o próximo *append* a relê. Saída correta, E/S ~66 % acima do livro. *Detectado por:* teste de custo
`test_transferencias_proximas_do_livro` (exigia ±15 % da fórmula do Silberschatz 15.4.2). *Evidência:* seção 3.1.

**B — M4 · `HashFile.reorganize()` (`raw-E07`, `src/access/hashfile.py:400`)**
```python
for bno, _ in list(self._blocos_fisicos()):      # materializa os bytes de TODOS os registros
```
*Defeito:* `_blocos_fisicos()` devolve os registros; o `list(...)` carrega a tabela inteira **só para obter números de bloco** — violação direta do
critério "não usar estruturas da linguagem maiores que a área de buffer". Os testes passavam. *Detectado por:* **revisão** do código bruto.

**C — M9 · runner, repetições (`raw-E14`, `src/bench/runner.py`)**
```python
for rep in range(1, self.rmax + 1):
    ctx.drop_all(); ctx.reset_stats()                 # "cold start"
    verificar = rep == 1 and self.comparar
...
with Medidor(ctx) as med:
    ...
    for _, rec in alvos: backend.insere(am, rec)      # manutenção: sem flush dentro da medição
```
*Defeitos:* (1) `drop_all()+reset_stats()` não zeram o **estado físico** (posição do braço, *free list* do rascunho): a 1ª repetição saía com contagens diferentes das demais —
A1_chave: **0 seeks** na rep 1 × **1** nas outras; BNL: **6 leituras** × **10**; SMJ: 15 × 16; INL: 6 × 7; (2) a manutenção media **0 gravações**
porque as páginas dirty só eram gravadas fora do `Medidor`. *Detectados por:* `test_contagens_deterministicas_e_cold_start` e leitura de `results/smoke.csv`.

**D — M7 · limiares de seletividade do CR (`raw-E09`, `src/bench/datagen.py:162,180`)**
```python
return round(min(max(nd.inv_cdf(u), float(p["min"])), float(p["max"])), 4)
...
{"x1": round(x1, 5), "x50": round(x50, 5)}
```
*Defeito:* casas fixas; com n = 50 003 os postos vizinhos empatam após `round(·, 4)` e `CR < x50` **perde a tupla da fronteira** (idem n = 224 923).
Os perfis atuais passavam *por sorte*. *Detectado por:* revisão + sondagem de volumes maiores.

**E — M3 · B+ primária (`raw-E06`, `src/access/bplus.py`)** — defeitos menores, honestamente pequenos:
```python
except AssertionError as e:            # _localizar: RID para bloco inexistente
    raise KeyError(...) from e         # StorageError (bloco fora do arquivo) vazava sem conversão
```
e, só em revisão (nenhum teste cobria `fill < 0,5`): `cap = max(2, min(self._n, ceil(fill * self._n)))` no `bulk_load` — com `fill` baixo
um nó interno nasce com menos de ⌈n/2⌉ filhos, **violando a ocupação mínima** (o item §7.1 sobre B+). Nota: a `raw-E06` já contém a 1ª correção
(ver seção 4); a `raw-E05` é o código 100 % bruto (15 testes verdes na 1ª execução).

**F — M2 · `context.py` (sem fragmento recuperável)**: o log registra que a 1ª versão importava `FileManager`/`BufferManager` direto na camada `access`
(quebrava `test_imports_respeitam_camadas`). O código **não está** em nenhuma tag (`raw-E03/E04` ainda tinham `context.py` como stub): evidência de processo perdida.

---

## 2. Justificativa de refatoração

| # | Alteração | Por quê (requisito atendido) | Alternativa preterida |
|---|---|---|---|
| A | Merge do `sort.py`: os N·bb buffers de entrada passam a contar como páginas de **E/S** (`reservar_paginas_io(len(grupo)*bb + bb)`), não como rascunho pinado. | **Desempenho/correção do custo:** 1359 → 798 transferências (M=3), livro 816. Os buffers de entrada *são* os frames onde `records_in_block` lê os runs; pinar rascunhos deixa 1 frame para leitura + saída (*thrash*). | Aumentar a área `trabalho` (esconde o defeito e muda o experimento) |
| B | `reorganize()` percorre bucket a bucket via `_cadeia`, com 1 página pinada e só o nº de bloco corrente em memória. | **Memória ≤ M páginas** (critério do enunciado §7.1); `reorganize` deixa de ser O(tabela) em RAM. | Manter `list(...)` e documentar (viola o critério) |
| C | Repetição 0 de **aquecimento** (não gravada) antes das medidas; `ctx.bm.flush_all()` **dentro** do `Medidor` na manutenção. | **Correção dos números:** todas as repetições partem do mesmo estado físico (CV passa a refletir só o relógio) e as gravações das remoções/inserções entram no custo. | Zerar o estado físico no FileManager (altera o contrato D05 do M1) |
| D | Casas decimais adaptativas `casas = max(casas_min, ⌈log10 n⌉)`; limiares com `casas+1`; erro de configuração se a faixa não comportar; teste de regressão n = 50 003 e 224 923. | **Correção da seletividade** nos volumes que o M9 pode recalibrar. | Casas fixas maiores (só adia o problema) |
| E | `StorageError` → `KeyError` em `_localizar`; piso `_min_filhos` no `cap` do bulk load; `reorganize` limpa `.reorg` sobrado. | **Correção/robustez** da B+; mantém `check_invariants()` verdadeira para qualquer `fill`. | — |
| F | `src/storage/factory.py` instancia FileManager/BufferManager; `context.py` usa `criar_armazenamento`. | **Arquitetura em 4 camadas** (teste `test_arquitetura.py`). | Relaxar o teste (inaceitável: é critério de avaliação) |

Refatorações **por decisão de projeto**, não por defeito (ver `docs/decisoes/M3.md`): B+ com nó próprio e ocupação por **bytes** (registros variáveis),
remoção por fusão/redistribuição propagando até a raiz, NOT UNIQUE por `(valor, uniquificador)`, `bulk_load` com piso de ocupação e `reorganize` em streaming por arquivo temporário.

---

## 3. Evidência de testes: refatorado supera o ingênuo

### 3.1 Bruto × refatorado, medido (reproduzível)

`ia_log/evidencia/medir_sort.py` (saída em `ia_log/evidencia/medir_sort_resultado.txt`), b = 68 blocos, buffer frio, área `trabalho` = M:

| Caso | **Bruto** (`raw-E11`) | **Refatorado** (HEAD) | Livro (15.4.2) | Bruto vs livro | Refatorado vs livro |
|---|---:|---:|---:|---:|---:|
| M = 3 | 1359 | **798** | 816 | **+66 %** | −2 % |
| M = 5 | 646 | **418** | 408 | **+58 %** | +2 % |

O refatorado fica a 2 % do livro e **reduz as transferências em 41 % (M=3) e 35 % (M=5)** sobre o código ingênuo. (No log da etapa, com o
BufferManager real, os valores foram 1449 → 800; aqui usa-se o `FakeBufferManager` LRU para o script rodar nas duas árvores.)

Outros pares com contagem registrada (valores do log da E14): cold start do runner — A1_chave 0 × 1 seeks, BNL 6 × 10 leituras, SMJ 15 × 16, INL 6 × 7 entre a 1ª repetição e as demais **antes** da correção; idênticas **depois**
(`test_contagens_deterministicas_e_cold_start`); manutenção: `gravacoes = 0` → contagem real após `flush_all()` dentro da medição.

### 3.2 Testes de estresse da versão atual (E16, `pytest -m stress`)

Execução própria em 28/11/2026 (`python -m pytest -m stress tests/stress`, `main` com M2 real integrado), **parcial**:

| Teste | Cenário | Resultado |
|---|---|---|
| `test_bplus_200_mil_insercoes_aleatorias` | B+ com 200 000 inserções aleatórias | **passou** |
| `test_hash_index_20_mil_insercoes_buscas_e_remocoes` | HashIndex, 20 000 inserções/buscas/remoções | **passou** |
| `test_join_com_memoria_minima_e_chaves_concentradas[hash]` | Hash join, M = 3, chaves concentradas, 20 000 registros | **não terminou**: ~5 100 s de CPU (≈ 1h25) e ainda rodando quando encerrei a espera |
| `…[sort-merge]` | idem, sort-merge | não executou (depois do anterior) |
| `test_join_com_100_porcento_de_chaves_duplicadas[hash]`, `[sort-merge]` | 100 % de chaves duplicadas | não executaram |

O M11 (`progress/M11.md`) registra os 6 como aprovados e a B+ com 200 mil inserções e 20 mil remoções. **Não reproduzi** a aprovação dos 4 joins: com o `RecordCodec`/`SlottedPage`
reais integrados, o cenário de 20 000 registros com M = 3 não terminou em tempo razoável nesta máquina. Pode ser lentidão real do join com o codec real (a mesma causa do teste lento do hash,
seção 3.3 do relatório) ou diferença de ambiente; **precisa ser reexecutado e medido pelo M11**. Até lá, a evidência de estresse **confirmada** é: B+ (200 000) e HashIndex (20 000).

### 3.3 Limites da evidência (o que ainda **não** está provado)

- O comparativo do M11 (`ia_log/stress_raw_vs_fix.md`) **não** mostra o refatorado superando o bruto: roda sobre **500 registros** por relação, as tags
  `raw-E02` e `raw-E11` falham com `NotImplementedError` (eram stubs de outros módulos, não código ingênuo), as transferências estão `N/D`, `raw-E12` não existe e
  o arquivo contém sobra de um comando PowerShell (`@'` … `| Set-Content`). Serve como diário, não como evidência. A evidência **de verdade** é a 3.1; o M11 precisa refazê-la com a métrica de transferências.
- Os **4 testes de estresse de junção não foram reproduzidos** (seção 3.2); estresse com **registros de tamanho máximo** e **hash degenerado integrado ao RecordCodec real** o M11 registra como pendente.
- Não há comparação bruto × refatorado de **tempo** para os defeitos B, C e D (são de memória/metodologia/calibração, comprovados por teste de regressão, não por cronômetro).
- **[PENDENTE]** E15 (revisão cruzada adversarial, 8 itens de §7.1 com teste comprobatório) e as seções de M8, M10, M12, M13.

---

## 4. Análise crítica do uso de IA

**O que funcionou**
- **Contexto explícito ajuda muito, mas não basta.** As regras de acesso a blocos, pin/unpin e overflow, escritas no `CLAUDE.md`, não foram violadas; o que não estava escrito (custo de E/S, estado físico da medição, calibração) gerou a maioria dos defeitos — e a regra de memória, mesmo escrita, foi violada 3 vezes.
- **Testes por contrato (fake × real) e invariantes executáveis** acharam erros cedo e deram segurança para refatorar (`check_invariants()` da B+, `assert_no_pins()` em todo teste).
- **Tags `raw-Exx`** tornam a análise bruto × corrigido reproduzível por comando — foi isso que permitiu a tabela 3.1.

**O que a IA fez mal**
- Escreveu **testes errados** (9 de 24 achados): asserção vazia que sempre passava (M5), limiar sem considerar o fator de carga (M4), fixture que reutilizava RIDs que mudam em split (M0),
  expectativa copiada de uma errata do livro (M6). Um teste errado é pior que nenhum: dá confiança falsa.
- Subestimou **custo de E/S** (A) e **memória** (B): a abstração escondeu o problema; só um teste de *custo* ou a leitura crítica o revelou.
- Produziu números plausíveis e errados em **medição** (C) e **calibração** (D) — onde nenhum teste de correção funcional pega.
- **Revisão da própria IA também erra:** na M3, a auto-revisão acusou "variáveis não inicializadas" em `update`; ao reler, era **falso positivo** (o uso estava dentro do ramo onde são atribuídas).
  Foi registrado e **retratado** em `ia_log/code_review/M3.md`. Sem a releitura, teria virado um "defeito" falso no relatório.
- No M5J, a auto-revisão apontou `from tests.conftest import ctx` em código de produção (prioridade alta) e o limite de `nh`, e **ambos continuam em `main`** — revisar sem corrigir não fecha o ciclo.

**Falhas de processo (nossas e da IA)**
- A tag `raw-E06` (M3) foi criada **depois** de uma rodada de testes e já inclui uma correção; a `raw-E12` (M5J) não existe; `raw-E04` não preserva o `context.py` com o defeito de camada.
  O protocolo exigia o commit bruto **antes** de rodar; isso só vale se for cumprido.
- A IA interpretou "faça o M3" como "faça uma etapa" e deixou a `main` com testes de contrato vermelhos até a E06 — seguir o protocolo à risca sem perguntar foi pior que perguntar.
- Logs de prompt: um autor sem registro (P5), dois logs reconstruídos (M2, M5J) e um sem autor (`desconhecido.md`). O hook gravou só comandos curtos; o raciocínio ficou nos arquivos `docs/decisoes/`.

**O que faríamos diferente**
1. Pôr no `CLAUDE.md`, desde o início, **teste de custo** (`transferências ≈ fórmula ± 15 %`) para toda operação do executor e **regras de medição** (estado físico, flush dentro do `Medidor`).
2. Automatizar a tag `raw-Exx` (hook de pré-teste), em vez de depender da disciplina.
3. Um teste que falhe quando `src/` importar `tests/` (teria pego SMJ-01 no dia) e outro para "só `src/storage/` chama `read_block`/`write_block`".
4. Revisão cruzada (RC/E15) **antes** de integrar, com correção obrigatória — não só registro.
5. Medir bruto × refatorado desde a E02, com a métrica de transferências, e não só no fim.
