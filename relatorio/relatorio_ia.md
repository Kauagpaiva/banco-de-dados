# Relatório de IA — Bancada de Teste de SBD

**Avaliação 2 — Indexação e Processamento de Consultas · CDB 2026.2 · UFRJ**

## Folha de rosto

| Papel | Nome completo | DRE |
|---|---|---|
| P1 (líder) | Kauã Gomes de Paiva da Costa | 122070496 |
| P2 | Emanuel Cardoso | 122033151 |
| P3 | Davi Richards Nascimento | 119022078 |
| P4 | Rodrigo Melo Dias | 119048189 |
| P5 | Ramon Silva Ramirez | 111205591 |

Repositório: <https://github.com/Kauagpaiva/banco-de-dados>

> **Estado deste relatório (28/11/2026).** Redigido no módulo M14 com o que existe em `main`. Seções que dependem de
> módulos ainda não concluídos (M8, M10, M11 integrado, M12, M13, RC/E15) estão marcadas **[PENDENTE]**; nada nelas foi
> inventado. Cada autor deve conferir a seção do seu módulo. Para o PDF, converter este arquivo mantendo a folha de rosto.

---

## 0. Como a IA foi usada

- **Ferramentas (conforme os logs):** Claude Code (Davi, Kauã e Rodrigo) e ChatGPT (Emanuel, no M5J). A ferramenta usada no M2 e por Ramon
  (M5) **não consta nos logs** — a confirmar. Cada integrante usou a **sua** IA num **módulo** próprio, em branch própria (`mod/Mx-<nome>`), integrando por PR/merge em `main`.
- **Protocolo comum (`CLAUDE.md`):** ler só a seção da etapa → implementar código **e** testes → **commit `ia-raw(Exx)` + tag
  `raw-Exx` antes de rodar os testes** (preserva o código bruto da IA) → corrigir até passar, registrando cada defeito em
  `ia_log/code_review/Mx.md` → suíte completa → decisões em `docs/decisoes/Mx.md` → handoff em `progress/Mx.md`.
- **Regras de arquitetura como critério de avaliação, verificadas por teste** (`tests/test_arquitetura.py`, 47 testes): 4 camadas
  (`bench → executor → access → storage`), imports só da camada imediatamente inferior.
- **Ressalva de método:** a tag `raw-Exx` só é "bruta" se o commit for feito antes de rodar os testes. Isso falhou em ao menos um
  caso (seção 1.3), e nos módulos M0/M1/M5J a evidência é parcial. O relatório diz onde.

---

## 1. (a) Log de prompts e código bruto

### 1.1 Logs de prompts (`ia_log/prompts/`)

| Arquivo | Autor / módulo | Origem do registro | Observação |
|---|---|---|---|
| `kaua-gomes.md` | P1 — M0, M1, M6 (e coordenação) | hook automático (literal) | Contém o prompt que originou a divisão em módulos paralelos (24/11). Acentos corrompidos (UTF-8 lido como Latin-1) — conteúdo preservado. |
| `M2.md` | P2 — M2 (E03/E04) | reconstruído (prompts em texto, não literais) | Sem marcação de data de cada prompt. |
| `emanuel.md` | P2 — M5J (E12) | reconstruído (ChatGPT) | Resume objetivos dos prompts, **não** os textos. |
| `rodrigo-melo-dias.md` | P4 — M4, M7, M9 | hook automático (literal) | Só comandos curtos (`/modulo Mx`): a IA recebeu a especificação do `CLAUDE.md`/`docs/`, não prompts longos. |
| `davi-richards.md` | P3 — M3, M14 | reconstruído da conversa (literal) | Criado no M14; não havia hook ativo. |
| `desconhecido.md` | não identificado | hook automático | 1 prompt (`/modulo M4`, 26/11) sem autor; atribuição pendente. |

**Lacunas conhecidas (declaradas):** não há log de prompts do **P5 (Ramon)** (M5, M10, M15); os logs de M2 e do Emanuel
são reconstruções, não transcrições. Isso deve ser completado pelos autores antes da entrega.

### 1.2 Como obter o código bruto gerado pela IA

```
git tag -l 'raw-*'                                   # raw-E00b raw-E01 raw-E02 raw-E03 raw-E04 raw-E05 raw-E06
                                                     # raw-E07 raw-E09 raw-E10 raw-E11 raw-E13 raw-E14
git show raw-E11:src/executor/sort.py                # arquivo como a IA o gerou (etapa E11)
git diff raw-E11 HEAD -- src/executor/sort.py        # o que mudou desde então
```

| Tag | Etapa · módulo | Conteúdo bruto |
|---|---|---|
| `raw-E00b` | contratos/fakes · M0 | `contracts.py`, fakes, fixtures |
| `raw-E01`, `raw-E02` | M1 | FileManager; replacement + BufferManager |
| `raw-E03`, `raw-E04` | M2 | `raw-E03`: codec/page/catalog · `raw-E04`: + heap. **`tempfile` e `context` ainda eram stub nessas tags**: o código bruto do `context.py` (com o defeito de camada) não está preservado |
| `raw-E05`, `raw-E06` | M3 | B+ (busca/inserção; remoção/NOT UNIQUE/bulk load) |
| `raw-E07` | M4 | HashFile + HashIndex |
| `raw-E09` | M7 | gerador da base |
| `raw-E10`, `raw-E11` | M5 | seleção; ordenação externa + BNL/INL |
| `raw-E13` | M6 | modelo de custo |
| `raw-E14` | M9 | runner |
| *(ausente)* `raw-E12` | M5J | não foi criada (a tag consta no script de estresse e não existe) |

### 1.3 Ressalva sobre a `raw-E06` (M3)

A tag `raw-E06` foi criada **depois** de uma 1ª rodada de testes e já contém a única correção feita por teste
(`StorageError` → `KeyError` em `_localizar`). O código 100% bruto da E06 = `raw-E06` sem essa linha. Registrado em
`ia_log/code_review/M3.md`. A `raw-E05` é íntegra (código bruto, 15 testes verdes na 1ª execução).

---

## 2. (b) Code review do código da IA

Fonte: `ia_log/code_review/*.md` (um por módulo), todos consolidados abaixo. Cada achado foi detectado por **teste**,
por **revisão** do código gerado ou por **auto-revisão**; classificados como defeito de **código** (produção) ou de **teste**.

### 2.1 Por módulo e autor

| Módulo | Autor | Código | Teste | Observações |
|---|---|---:|---:|---|
| M0 — contratos/fakes | P1 | 1 | 2 | contexto sem injeção de BM; analisador de imports; teste reutilizava RIDs da B+ |
| M1 — FileManager/Buffer | P1 | 0 | 0 | 109 testes verdes sobre o código bruto; pontos a revisitar: `victim()` O(n), handles do SO abertos |
| M2 — registros/heap | P2 | 1 | 0 | `context.py` importava `storage` direto (violação de camada) |
| M3 — B+ primária | P3 | 3 | 2 | ver 2.3 (+1 falso positivo da própria revisão, retratado) |
| M4 — Hash | P4 | 1 | 1 | `reorganize()` materializava o arquivo em memória; limiar de dispersão do teste |
| M5 — seleção/ordenação/NL | P5 | 1 | 3 | merge externo com *thrash* da página de saída |
| M5J — SMJ/hash join | P2 | 5 | 0 | **auto-revisão**; 2 confirmados ainda abertos (2.4) |
| M6 — custo | P1 | 0 | 1 | erro de soma **no livro** (1 640 × 1 540) — o código estava certo |
| M7 — gerador | P4 | 1 | 0 | limiares de CR inexatos com empate no arredondamento |
| M9 — runner | P4 | 2 | 0 | cold start incompleto; manutenção sem gravações |
| M8, M10, M11, M12, M13, M15, RC | — | — | — | **[PENDENTE]** sem entradas (módulos não concluídos) |
| **Total** | | **15** | **9** | 24 achados |

### 2.2 Por categoria do enunciado (§7.1)

| Categoria (§7.1) | Achados no código | Onde |
|---|---:|---|
| Leitura de blocos fora do Buffer Pool | 0 | verificação estática (abaixo); sem teste dedicado ainda |
| Pin sem unpin / página alterada sem dirty | 1 | M9 — manutenção media 0 gravações (dirty/flush fora da medição) |
| Busca binária sobre registros | 0 | — |
| B+ sem ocupação mínima / encadeamento / propagação | 1 | M3 — `cap` do bulk load podia gerar nó interno abaixo do mínimo (achado em revisão, antes de rodar). As três invariantes **não** foram violadas pelo código bruto (`check_invariants()`); 1 achado de **teste** (RIDs reutilizados, M0) |
| Hash sem overflow na busca/remoção | 0 | `reorganize` ineficiente (M4) é de memória, não de correção |
| Junção/ordenação/reorganização com estruturas > área de buffer | 3 | M5 merge (E11), M4 `reorganize` (`list(...)` do arquivo todo), M5J `nh` > M−1 (aberto) |
| Offsets/tamanhos fora do bloco | 0 | validados nos codecs/páginas; sem achado |
| Eficiência / vazamento de temporários / arquitetura | 5 | M2 camada (`context` → `storage`), M3 `.reorg` sobrado, M5J: `tests` importado em produção (SMJ-01), vazamento em falha parcial (SMJ-03, HASH-02) |
| Outros (testabilidade, metodologia, calibração, documentação) | 5 | M0 contexto sem injeção, M3 `StorageError`, M5J doc ≠ código (SMJ-02), M7 limiares de CR, M9 cold start |
| **Total (código)** | **15** | |

> **Este quadro NÃO substitui a E15 (RC — code review cruzado adversarial) [PENDENTE]**, que deve revisar `src/` inteiro
> item a item e, onde nada for achado, citar o teste que comprova. Verificação estática rápida feita no M14:
> `grep -rn "read_block\|write_block" src | grep -v "^src/storage/"` → **nenhuma ocorrência** (só `src/storage/` toca o disco);
> `pin`/`unpin` manuais fora de `src/storage/` só em `context.py` (`pin_work_page`/`unpin_work_page`); todo teste termina com
> `assert_no_pins()` (fixture autouse). Não há `list.pop(0)` em `src/` fora de um espelho da lista livre no FileManager (O(n), irrelevante).

### 2.3 M3 — B+ primária (detalhe, autor deste relatório)

| # | Achado | Como foi detectado | Gravidade |
|---|---|---|---|
| 1 | RID inválido (bloco inexistente) lançava `StorageError` em vez de `KeyError` | teste `test_delete_rid_invalido` | baixa |
| 2 | `cap` de grupo interno no bulk load podia ficar < ⌈n/2⌉ com `fill` < 0,5 (violaria a invariante) | revisão (nenhum teste cobre fill < 0,5) | média |
| 3 | `reorganize` não tratava arquivo `.reorg` sobrado de execução interrompida | revisão | baixa |
| FP | `update` com `cabe`/`abaixo` "não inicializadas" — **falso positivo**: o uso estava dentro do ramo onde são atribuídas | revisão (retratado ao reler) | — |
| T1 | Teste esperava detectar RID obsoleto (impossível: RID posicional por contrato) | execução | — (teste) |
| T2 | Teste contava mal duplicatas (`i=5` também gerava a chave 5) | execução | — (teste) |

As invariantes que o enunciado cita (ocupação mínima, folhas encadeadas, split propagado até a raiz) **não** foram violadas pelo
código bruto: `check_invariants()` rodou a cada 500 inserções/a cada operação (hypothesis) sem falhar. Um teste de mutação manual
(remover a propagação da fusão aos níveis internos) faz `test_remover_tudo_deixa_arvore_vazia_valida` falhar — o teste tem poder
de detecção.

### 2.4 Achados que continuam **abertos** em `main` (verificados em 28/11)

1. **M5J — `src/executor/join_smj.py:23`: `from tests.conftest import ctx`** em código de produção (auto-revisão SMJ-01,
   prioridade alta). Acopla o executor às fixtures do pytest (importa `pytest` e `tests.fakes` ao carregar o módulo); o parâmetro
   `ctx` da função sobrepõe o nome importado, então a linha é morta. Hoje funciona porque `pytest` está instalado e `tests/` está no caminho, mas
   a bancada passa a exigir a suíte de testes só para executar. Correção: apagar a linha (dono: P2).
2. **M5J — `src/executor/join_hash.py:292`: `nh or min(M−1, …)`** não limita `nh` informado a M−1 (HASH-01): um `nh` grande cria
   mais arquivos de partição do que o orçamento permite. (dono: P2).
3. As demais recomendações do M5J (SMJ-02 documentação, SMJ-03 e HASH-02 vazamento de temporário em falha parcial) constam como
   recomendações; **o estado de correção não foi reverificado**.

---

## 3. (c) Bateria de testes

### 3.1 Suíte

Estado em 28/11/2026, `main` após a integração do M2/M4/M7/M9 (`pytest -q`):

| Item | Resultado |
|---|---|
| Testes coletados | **684** (+ 6 de estresse, marcados `-m stress`) |
| Execução completa | **681 passed, 3 xfailed**, 6 deselected (estresse) |
| Tempo | 14 min 43 s sem cobertura (rodando junto de outra cópia da suíte; ver alerta) |
| Cobertura de linhas (`pytest --cov=src`) | **94 %** de `src/` (4 867 linhas, 277 não cobertas). Menores: `secondary_bplus.py` 65 % e `loader.py` 83 % (M8, ainda stub), `record.py` 84 %, `memory.py` 85 %, `page.py` 89 %, `join_smj.py` 89 %, `heap.py` 90 %; `bplus.py` 95 %. Execução com rastreamento: 52 min (681 passed, 3 xfailed) |

Testes por arquivo (coleta): `test_stubs` 60 · `test_selection` 58 · `contratos/organizacao` 52 · `test_datagen` 51 · `test_runner` 50 · `test_arquitetura` 47 ·
`test_join_nl` 35 · `contratos/codec` 33 · `contratos/buffer` 32 · `test_file_manager` 31 · `test_bplus` 31 · `test_buffer_manager` 26 · `test_sort` 24 ·
`test_cost_model` 22 · `test_replacement` 20 · `test_hashfile` 16 · `test_join_smj_hash` 15 · `test_memory_scan` 14 · `test_contratos_m0` 12 ·
`contratos/page` 12 · `contratos/indice` 12 · `test_hash_index` 11 · `test_config` 9 · `contratos/tempfile` 7 · `test_catalog` 4.

> **Alerta de desempenho da própria bateria.** Antes da integração do M2/M4 a suíte inteira levava ~76 s; agora ~15 min.
> Medido: `tests/test_hash_index.py::test_cadeia_longa_funcao_degenerada` (M4, hash degenerado com cadeia longa de overflow) leva **35 s com fakes
> (`--so-fakes`)** e **mais de 100 s com o `RecordCodec`/`SlottedPage` reais** — e foi onde a execução com cobertura ficou parada por vários minutos (a suíte com rastreamento levou 52 min). Isso é um achado de
> eficiência (teste ou cadeia de overflow quadrática no codec real) a investigar pelo dono (P4); não foi corrigido no M14.


### 3.2 Estratégias de teste usadas para achar defeitos

- **Testes de contrato** (`tests/contratos/`): o mesmo teste roda no **fake** e na implementação **real** (Heap, B+, Hash,
  buffer, página, codec, tempfile, índice); a variante real fica `xfail` enquanto for stub.
- **Oráculos em Python só nos testes** (`sorted()`, dict, `FakeTable`) e **SQLite** como referência dos resultados da bancada
  (`src/bench/sqlite_ref.py`, comparação de contagem + checksum no runner).
- **Property-based (hypothesis)** na B+: sequências aleatórias de insert/delete/update contra um dict, `check_invariants()` após
  cada operação, com bloco de 512 B e chave larga (fan-out 8) para forçar árvores profundas.
- **Invariantes executáveis** (`check_invariants` da B+, `estatisticas` do hash), **teste de arquitetura** por análise de imports,
  `assert_no_pins()` em todo teste, e **fakes configuráveis** para isolar camadas.
- **Teste de mutação manual** (B+): quebrar de propósito uma regra e confirmar que algum teste falha.
- **Testes de metodologia** (M9): contagens determinísticas entre repetições (descobriu o cold start incompleto).

### 3.3 Testes de estresse (`pytest -m stress`, E16 — M11)

Execução própria de 28/11/2026, `pytest -m stress` (6 testes): **2 passaram** (B+ com 200 000 inserções aleatórias; HashIndex com 20 000 inserções/buscas/remoções)
e **4 não terminaram** (joins hash e sort-merge com M = 3 / 100 % duplicatas, 20 000 registros): ~5 100 s de CPU sem concluir o 3º teste. O M11 registra os 6 como aprovados em
`progress/M11.md`, mas isso **não foi reproduzido** aqui com o `RecordCodec`/`SlottedPage` reais já integrados. Ação: o dono do M11/M5J reexecuta, mede o tempo de cada teste e,
se for lentidão real, investiga junto com o teste lento do M4 (seção 3.1). Detalhes e tabela em `POST_MORTEM.md` §3.2.

---

## 4. (d) Análise crítica e Post-Mortem

O conteúdo exigido (§7.2.3.d) está em **`POST_MORTEM.md`**, na raiz: prompts-chave e fragmentos brutos, justificativa de
refatoração e evidência de testes de estresse, com código bruto × refatorado reproduzido por comando.

---

## 5. Pendências para fechar a entrega

| Item | Responsável | Situação |
|---|---|---|
| Log de prompts do P5 (Ramon) | P5 | ausente |
| Atribuir `desconhecido.md` | quem o gerou | pendente |
| Seção de cada módulo restante (M8, M10, M12, M13, M15) e checklist 7.1 (E15/RC) | donos | **[PENDENTE]** |
| Tag `raw-E12` (M5J) | P2 | não criada; relatar ou refazer |
| Corrigir `join_smj.py:23` e `join_hash.py:292` | P2 | abertos |
| Integrar M11 e refazer o comparativo de estresse com métricas de transferências | P2 | ver seção 3.3 |
| Converter para PDF com folha de rosto | M13/M15 | pendente |
