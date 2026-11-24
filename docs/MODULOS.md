# Módulos para desenvolvimento em paralelo (grupo de 5)

> Para o Claude Code: leia **apenas** a seção do seu módulo (Grep por `^### M5` etc.) e a seção
> "Regras do trabalho em paralelo". As especificações técnicas de cada etapa continuam em
> `docs/PLANO_EXECUCAO.md` (seções `## Exx`).

## Ideia central: contrato primeiro, depois todos em paralelo

O que impede 5 pessoas de trabalhar ao mesmo tempo é a dependência entre camadas: a B+ precisa
do Buffer Manager, as junções precisam das tabelas, etc. A solução:

1. **Fase 0 (1 pessoa, 1 sessão):** o módulo **M0** escreve os **contratos** (assinaturas
   congeladas de todas as classes/funções, como *stubs* que lançam `NotImplementedError`) e
   **fakes** simples em `tests/fakes/` (Buffer Manager em memória, tabela fake, codec fake…).
   Merge em `main`.
2. **Fase 1 (todos em paralelo):** cada módulo implementa os seus stubs e testa contra os
   **fakes** das camadas que ainda não existem. A fixture `bm` do `tests/conftest.py` usa a
   implementação real quando ela já existe em `main` e o fake caso contrário — a integração
   acontece sozinha à medida que os merges chegam.
3. **Fase 2 (integração):** índices secundários B+, carga, runner, testes de integração e
   code review cruzado, já sobre as implementações reais.
4. **Fase 3:** experimentos, gráficos, relatórios e slides, divididos por pessoa.

```
Fase 0      M0 Contratos + fakes ──────────────┐ (merge em main antes de todos começarem)
            ┌──────────┬──────────┬────────────┼───────────┬───────────┐
Fase 1      M1 Storage  M2 Registro  M3 B+       M4 Hash     M5 Seleção  M5J Junções
            (FM+BM)     +Heap        primária    +HashIndex  +Sort+NL    SMJ+Hash join
            └→ M6 Custo └→(M5J)                  └→ M7 Datagen+SQLite
            ─────────────────── merges em main (ordem sugerida: M1, M2, M3, M4, M5, M5J, M6, M7)
Fase 2      M8 Índices B+ sec. + registry + loader │ M9 Runner + experimentos │ M10 Integração vs SQLite
            M11 Estresse bruto×refatorado          │ RC Code review cruzado (todos)
Fase 3      M12 Execução+gráficos │ M13 Rel. técnico │ M14 Rel. IA + POST_MORTEM │ M15 Slides
```

## Distribuição (nomes e DREs em `PROGRESS.md`)

| Pessoa | Fase 0 | Fase 1 | Fase 2 | Fase 3 |
|---|---|---|---|---|
| **P1** Kauã (líder/integrador) | **M0** | M1 Storage → M6 Modelo de custo | Integra merges; RC revisa M2 | M13 Relatório técnico (cap. arquitetura/decisões) |
| **P2** Emanuel | — | M2 Registros+Heap → M5J Junções | M11 Estresse; RC revisa M3 | M13 Relatório técnico (resultados/conclusão) |
| **P3** Davi | — | M3 Árvore B+ | M8 Índices secundários + loader; RC revisa M4 | M14 Relatório de IA + POST_MORTEM |
| **P4** Rodrigo | — | M4 Hash → M7 Datagen | M9 Runner + experimentos; RC revisa M5/M5J | M12 Execução completa + gráficos |
| **P5** Ramon | — | M5 Seleção + Sort + NL | M10 Integração; RC revisa M1 | M15 Slides + checklist final |

Carga equilibrada: M1 e M4 são menores, por isso P1 e P4 emendam um segundo módulo da Fase 1.
M5J começa com os fakes, mas só fecha depois que M5 (sort) estiver em `main`.

## Regras do trabalho em paralelo (todas as IAs devem seguir)

1. **Propriedade de arquivos.** Cada módulo só cria/edita os arquivos listados como seus.
   Precisa mudar arquivo de outro módulo ou um contrato? **Pare**, registre um
   "Pedido de mudança de contrato" no `progress/Mx.md` e avise o usuário para abrir uma issue
   para o dono (M0 = líder). Nunca altere assinatura de contrato por conta própria.
2. **Arquivos compartilhados são por módulo** (evita conflito de merge):
   - progresso: `progress/Mx.md` · decisões: `docs/decisoes/Mx.md` · code review: `ia_log/code_review/Mx.md`
   - prompts: `ia_log/prompts/<autor>.md` (o hook grava automaticamente pelo `git config user.name`)
   - `docs/INTERFACES.md`, `config/base.yaml`, `tests/conftest.py`, `tests/fakes/*`, `src/*/contracts.py`
     pertencem ao **M0**: mudanças só via PR revisado pelo líder.
   - Chaves novas de configuração: em `config/modulos/Mx.yaml` (o `load_config` faz merge de todos).
3. **Branch por módulo:** `mod/M3-bplus`. Antes de começar cada sessão: `git pull --rebase origin main`
   (ou merge). PR para `main` ao fim de cada etapa (PRs pequenos integram melhor que um PR gigante).
4. **CI** (`.github/workflows/testes.yml`) roda a suíte em todo PR. Só faz merge com CI verde.
5. **Tags de código bruto** continuam `raw-Exx` (as etapas têm números únicos; não há colisão).
   Envie as tags: `git push origin --tags`.
6. **Testes contra fakes** devem continuar passando quando o real chegar. Se um teste só passa
   com o fake, o defeito é do seu módulo ou do contrato — registre no code review.

---

## Módulos

### M0 — Contratos, fakes e infraestrutura (Fase 0 · P1)
- **Etapas:** E00 (concluída) + **E00b** (`PLANO_EXECUCAO.md`).
- **Arquivos:** `src/common/*`, `src/storage/contracts.py`, `src/access/contracts.py`,
  `src/access/esquemas.py`, `src/executor/contracts.py`, stubs de **todos** os módulos
  (`src/**/*.py` listados abaixo, só com assinaturas + docstring + `raise NotImplementedError`),
  `tests/conftest.py`, `tests/fakes/*`, `config/base.yaml`, `docs/INTERFACES.md`, `.github/`.
- **Pronto quando:** `pytest` verde; cada stub importável; fakes passam nos testes de contrato
  `tests/contratos/*` (os mesmos testes que depois validarão a implementação real).

### M1 — Gerente de Arquivos + Buffer Pool (Fase 1 · P1)
- **Etapas:** E01, E02.
- **Arquivos:** `src/storage/file_manager.py`, `buffer_manager.py`, `replacement.py`, `stats.py`;
  `tests/test_file_manager.py`, `test_buffer_manager.py`, `test_replacement.py`.
- **Depende de:** M0. **Destrava:** troca automática do `FakeBufferManager` pelo real em todos os testes.
- **Pronto quando:** testes de E01/E02 + `tests/contratos/test_contrato_buffer.py` verdes com a implementação real.

### M2 — Registros, slotted page, catálogo, Heap e arquivo temporário (Fase 1 · P2)
- **Etapas:** E03, E04 + `TempFile`/`StorageContext` (definidos em `src/access/contracts.py`).
- **Arquivos:** `src/access/record.py`, `page.py`, `catalog.py`, `heap.py`, `tempfile.py`, `context.py`;
  testes correspondentes.
- **Depende de:** M0 (usa `FakeBufferManager` até M1 entrar).
- **Destrava:** M3/M4 trocam `FakeCodec`/`FakeSlottedPage` pelos reais; M5/M5J trocam `FakeTable`/`FakeTempFile`.
- **Prioridade interna:** entregar `record.py` + `page.py` primeiro (PR curto), pois M3 e M4 usam.

### M3 — Árvore B+ como organização primária (Fase 1 · P3)
- **Etapas:** E05, E06.
- **Arquivos:** `src/access/bplus.py`, `tests/test_bplus.py`.
- **Depende de:** M0 (fakes de buffer e codec). Usa `SlottedPage`/`RecordCodec` reais quando M2 entrar.

### M4 — Hash estático externo + índice hash secundário (Fase 1 · P4)
- **Etapas:** E07 (inclui `HashIndex` secundário UNIQUE, movido da E08).
- **Arquivos:** `src/access/hashfile.py`, `hash_index.py`, `tests/test_hashfile.py`, `test_hash_index.py`.
- **Depende de:** M0.

### M5 — Seleção, ordenação externa, Block NL e Indexed NL (Fase 1 · P5)
- **Etapas:** E10, E11.
- **Arquivos:** `src/executor/memory.py`, `scan.py`, `selection.py`, `sort.py`, `join_bnl.py`, `join_inl.py`;
  testes correspondentes.
- **Depende de:** M0 (`FakeTable`, `FakeIndex`, `FakeTempFile`, `StorageContext` fake).
- **Atenção:** a referência SQLite real é do M7; até lá use o oráculo em Python **só nos testes**.

### M5J — Sort-merge join e partition-hash join (Fase 1 · P2, após M2)
- **Etapas:** E12.
- **Arquivos:** `src/executor/join_smj.py`, `join_hash.py`, `tests/test_join_smj_hash.py`.
- **Depende de:** M0; `external_sort` do M5 (até ele entrar, testar o merge com entradas já ordenadas da `FakeTable`).

### M6 — Modelo de custo (Fase 1 · P1, após M1)
- **Etapas:** E13 (parte analítica: fórmulas + testes com os exemplos do livro).
  A comparação estimado × medido sobre o sistema real fica para M10.
- **Arquivos:** `src/bench/cost_model.py`, `tests/test_cost_model.py`.
- **Depende de:** apenas `docs/REFERENCIA_LIVRO.md` e do formato de estatísticas do catálogo (contrato).

### M7 — Gerador da base + referência SQLite (Fase 1 · P4, após M4)
- **Etapas:** E09, **exceto o loader** (vai para M8).
- **Arquivos:** `src/bench/datagen.py`, `sqlite_ref.py`, `tests/test_datagen.py`.
- **Depende de:** `src/access/esquemas.py` (M0). Gera registros como `dict` + exporta SQLite; não precisa de nenhuma organização.

### M8 — Índices secundários B+, registry de métodos de acesso, loader (Fase 2 · P3)
- **Etapas:** E08 (sem o HashIndex) + parte "loader" da E09.
- **Arquivos:** `src/access/secondary_bplus.py`, `access_methods.py`, `src/bench/loader.py`; testes.
- **Depende de:** M2, M3, M4 em `main`.

### M9 — Orquestrador e matriz de experimentos (Fase 2 · P4)
- **Etapas:** E14.
- **Arquivos:** `src/bench/runner.py`, `config/experimentos/*.yaml`, `tests/test_runner.py`.
- **Depende de:** M5, M5J, M6, M7, M8. Pode começar com `loader` fake e trocar depois.

### M10 — Testes de integração vs SQLite + estimado × medido (Fase 2 · P5)
- **Etapas:** parte de validação da E13 + aceite de E10–E12 sobre o sistema real.
- **Arquivos:** `tests/integracao/*.py`.
- **Depende de:** M1–M8.

### M11 — Estresse: código bruto × refatorado (Fase 2 · P2)
- **Etapas:** E16.
- **Arquivos:** `tests/stress/*.py`, `tools/stress_raw_vs_fix.py`, `ia_log/stress_raw_vs_fix.md`.

### RC — Code review cruzado (Fase 2 · todos)
- **Etapa:** E15, mas **cada pessoa revisa o módulo de outra** (tabela de distribuição acima).
- Registra achados em `ia_log/code_review/<modulo revisado>.md` com o prefixo `[RC por Px]`;
  a correção é feita pelo **dono** do módulo (é ele quem precisa saber explicar o defeito).

### M12–M15 — Fase 3
| Módulo | Etapa | Dono | Arquivos |
|---|---|---|---|
| M12 Execução completa + gráficos | E17 | P4 | `results/*`, `src/bench/plots.py` |
| M13 Relatório técnico | E18 | P1 + P2 | `relatorio/relatorio_tecnico.md` (P1: seções 1–4; P2: 5–6) |
| M14 Relatório de IA + POST_MORTEM | E19 | P3 (todos enviam a seção do seu módulo) | `relatorio/relatorio_ia.md`, `POST_MORTEM.md` |
| M15 Slides + checklist final | E20 | P5 | `relatorio/slides.md` |

## Ordem de merge recomendada na Fase 1
1. **M0** (antes de todos) → 2. **M2 parte record/page** (PR curto) → 3. **M1** → 4. M3, M4 →
5. M5 → 6. M5J → 7. M6, M7.
Depois de cada merge de M1 ou M2, todos fazem `git pull origin main` e rodam a suíte: é aqui que
os testes passam a rodar contra a implementação real. Falhas nesse momento são o material mais
valioso para o code review e o Post-Mortem.
