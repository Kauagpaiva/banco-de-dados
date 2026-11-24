# INTERFACES — API pública congelada (fonte: `src/*/contracts.py`, E00b)

> **Fonte única de verdade = os arquivos `contracts.py`.** Este documento é o resumo.
> Mudança de assinatura só via "Pedido de mudança de contrato" (`progress/Mx.md`) + PR do M0.
> Testes de contrato em `tests/contratos/` valem para fake **e** real.

## Convenções gerais
- Camadas: `bench → executor → access → storage` (+ `common`). O bench chega à Camada 3 por
  `src.executor.contracts` (tipos re-exportados) e `src.executor.fachada` (fábricas re-exportadas).
- Registro = `dict` campo → valor: `int` · `float` · `datetime.date` · `str` · `list[str]` · `None` (se `Campo.nulo`).
- Injeção: estruturas da Camada 3 recebem `bm` e, opcionalmente, `page_impl` (classe SlottedPage) e
  `codec`; `None` → real (`contracts.padroes`). Construtor não toca o disco; `open()` cria ou abre.
- Iteradores mantêm no máximo 1 página pinada e a soltam **antes** do `yield`/em `finally`.
- Blocos de dados começam em 1 (bloco 0 = cabeçalho).

## src/common
### config.py
- `load_config(perfil="teste", overrides=None, caminho=None) -> Config` — lê `config/base.yaml`,
  faz merge de `config/modulos/*.yaml` (**só chaves novas**; redefinir chave existente → `ConfigError`),
  aplica overrides (`"buffer.policy": "MRU"` ou dict aninhado), valida.
- `Config` (frozen): `perfil, block_size, extent_blocks, data_dir, seek_model, buffer_total, buffer_areas,
  buffer_policy, buffer_policies, toss_immediate, prefetch, hash_fill_factor, hash_funcao, bplus_bulk_load,
  volumes, seed, raw`; `.M`, `.perfil_dir`, `.policy_for(area)`. `POLITICAS_VALIDAS`.
### erros.py
- `BancadaError` > `ConfigError`, `StorageError` > `BufferFullError`, `RecordError` > `CorruptedPageError`,
  `MemoryBudgetError`, `OperacaoNaoSuportada`, `ChaveDuplicadaError`.
### tipos.py
- `RID(bloco, slot)`, `PageId(fid, bno)`.
- `Predicado(campo, op, valor)` (`op ∈ OPS = '=','<','<=','>','>='`), `.validar()`, `.avaliar(rec)` (nulo → False).
- `CondJuncao(campo_r, campo_s)`.
- `CHAVES_BUFFER` (requests, hits, misses, hit_rate, dirty_evictions, forced_writes) ·
  `CHAVES_IO` (reads, writes, seq_reads, rand_reads, seq_writes, rand_writes) ·
  `CHAVES_DERIVADAS` (transferencias = reads+writes, seeks = rand_reads+rand_writes) · `CHAVES_STATS` = as três.
- `Metricas` (TypedDict: CHAVES_STATS + `tuplas_saida`, `escrita_saida`), `metricas_vazias()`, `diferenca_metricas(depois, antes)`.
- `CAMINHOS_SELECAO = A1_linear, A1_chave, A2..A6, HASH_PRIM, HASH_SEC` · `TIPOS_ORG` · `CHAVES_OCUPACAO` (dados, overflow, indice, total, registros).

## src/storage (M1) — `contracts.py`
- `Frame(fid, bno, data: bytearray, area, pin_count, dirty, ref_bit, extra)`, `.mark_dirty()`. `AREAS`.
- `FileManagerAPI` — real `FileManager(cfg, base_dir=None)`: `create(nome, tipo_org, meta)->fid`, `open`, `exists`,
  `close`, `delete`, `read_block`/`write_block` (**só o BufferManager**), `allocate_block`, `free_block`,
  `num_blocks` (exclui livres e cabeçalho), `header(fid)->{tipo_org, num_alocados, livre, extent, meta}`,
  `set_header(fid, **meta)`, `io_stats(fid=None)`, `reset_io_stats()`. Seek: braço global (D05); cabeçalho conta I/O.
- `PolicyAPI` (`replacement.py`): `on_load/on_access/on_unpin(frame, toss)/on_evict/victim(frames)`; `criar_politica(nome)`.
- `BufferManagerAPI` — real `BufferManager(cfg, fm)`: `pin(fid,bno,area)`, `unpin(frame, dirty, toss)`,
  `new_page(fid, area)` (não conta request), `free_page`, **`page(...)`** e **`fresh_page(fid, area)`** (context managers
  prontos no contrato), `flush` (forced_writes), `flush_all`, `drop_all` (cold start), `set_policy`, `area_capacity`,
  `stats()` (CHAVES_STATS + `por_area`), `reset_stats()` (zera buffer **e** FM), `assert_no_pins()`,
  repasse: `create/open/exists/close/delete/num_blocks/header/set_header`. Atributos `cfg`, `block_size`.

## src/access — `contracts.py`, `esquemas.py`
- `Campo(nome, tipo, nulo=False, max_itens=4)` (`int|float|date|char(n)|varchar(n)|list[varchar(n)]`; `.base .n .variavel`);
  `Esquema(nome, campos, chave)` (`.nomes() .campo(n)`); `esquema_juncao(r, s)`.
- `esquemas.py`: `ALUNO, CURSO, DISCIPLINA, TURMA, INSCRICAO, DETALHES`, `ESQUEMAS[nome]`, `FKS`.
- `RecordCodecAPI` — `RecordCodec(esquema)` (M2): `encode(dict)->bytes`, `decode`, `max_size`; inválido → `RecordError`.
- `SlottedPageAPI` — `SlottedPage` (M2), **estáticos** sobre `frame.data`: `format(buf, reserva=0)`, `insert->slot|None`,
  `get->bytes|None`, `delete`, `update->bool`, `compact` (slots estáveis), `free_space`, `slots`, `count`,
  `reserva(buf)->(off, n)`, `capacidade_max(block_size, reserva)`. Offset fora do bloco → `CorruptedPageError`.
- `InfoTabela(nome, esquema, org, campo_org, params, nr, br, fr, tam_registro, V, indices)`, `.indice(campo)`;
  `InfoIndice(nome, tabela, campo, tipo, unique, clustering, primario, altura, num_blocks, fanout, params)`.
- `CatalogAPI` — `Catalog(bm, nome="catalogo")` (M2): `registrar_tabela`, `registrar_indice`, `tabela`, `tabelas`,
  `remover_tabela`, `atualizar_estatisticas(nome, nr, br, V, fr, tam_registro)`, `atualizar_indice`, `definir/obter`.
- `Relacao` (Protocol): `esquema`, `num_blocks()`, `num_registros()`, `scan_blocos(toss) -> Iterator[list[dict]]`.
- `FileOrganization` (`tipo_org`, `campo`, `unique`): `open/close/reset`, `find(campo, v)->RID|None`, `find_next`,
  `read`, `insert` (UNIQUE repetida → `ChaveDuplicadaError`), `delete`, `update->RID`, `scan(toss)->(RID, dict)`,
  `scan_blocos`, `find_all(campo, op, v)`, `find_ordered(campo, lo, hi, incl_lo, incl_hi)` (sem ordem → `OperacaoNaoSuportada`),
  `reorganize`, `num_blocks`, `num_registros`, `ocupacao()`.
  - `HeapFile(bm, nome, esquema, *, page_impl, codec, fragmentacao_max=0.25)` (M2)
  - `BPlusTree(bm, nome, esquema, campo, *, unique=True, page_impl, codec)` + `altura() fanout() check_invariants() bulk_load(regs, fill=0.8)` (M3). RIDs instáveis em split.
  - `HashFile(bm, nome, esquema, campo, *, unique=True, n_buckets, nr_estimado, page_impl, codec)` + `estatisticas()`; `fnv1a64(bytes)` (M4)
- `SecondaryIndex` (`campo, unique, clustering, refs_por_chave`): `open/close`, `insert(chave, ref)`, `delete(chave, ref)` (KeyError se ausente),
  `search_eq`, `search_range(lo, hi, incl_lo, incl_hi)`, `altura`, `num_blocks`.
  - `HashIndex(bm, nome, campo: Campo, *, nr_estimado, n_buckets, page_impl)` — UNIQUE (M4)
  - `BPlusIndex(bm, nome, campo: Campo, *, unique=False, clustering=False, refs_por_chave=False, page_impl)` (M8)
- `TempFile` — `ArquivoTemporario(bm, nome, esquema, *, page_impl, codec)` (M2), área 'trabalho': `append`, `blocks`,
  `records_in_block(bno)->list`, `scan(toss)->dict`, `scan_blocos`, `num_blocks`, `num_registros`, `close`, `delete`.
- `StorageContext` — `criar_contexto(cfg, base_dir=None, *, bm=None, catalog=None)` (M2): `cfg`, `bm`, `catalog`,
  `buffer_stats`, `reset_stats`, `drop_all`, `set_policy`, `work_capacity()->M`, `pin_work_page()/unpin_work_page(fr)`,
  `temp_file(esquema, prefixo)`, `close()` (apaga temporários).
- `AccessMethod(tabela, indices: {campo: SecondaryIndex}, descricao)`, `.esquema`, `.indice(campo)`.
- `access_methods.py` (M8): `EspecIndice(campo, tipo, unique, clustering)`, `EspecMetodo(org, campo, unique, indices, nome)`,
  `REGISTRY`, `montar(ctx, esquema, espec, *, nr_estimado, nome_arquivo) -> AccessMethod`, `inserir(am, rec)`, `remover(am, rid)`.

## src/executor — `contracts.py`, `fachada.py`
- Todos os operadores: 1º argumento `ctx`; `M=None` → `ctx.work_capacity()`; devolvem `(iterador, Metricas)`,
  com as métricas preenchidas quando o iterador se esgota. Saída de junção: `combinar(nome_r, rec_r, nome_s, rec_s)`
  (chaves `"Tabela.campo"`), esquema `esquema_juncao`.
- `select(ctx, am, predicado, caminho)` (M5, `selection.py`)
- `external_sort(ctx, entrada, esquema, chave, *, M=None, bb=1) -> (TempFile, Metricas)` (M5, `sort.py`)
- `block_nested_loop(ctx, r, s, cond, *, M, materializar, externa='auto', toss=False)` (M5, `join_bnl.py`)
- `indexed_nested_loop(ctx, r, s: AccessMethod, cond, *, M, materializar)` (M5, `join_inl.py`)
- `sort_merge_join(ctx, r, s, cond, *, M, materializar)` (M5J, `join_smj.py`)
- `hash_join(ctx, r, s, cond, *, M, materializar, fudge=1.2, nh=None)` (M5J, `join_hash.py`)
- `MemoryBudgetAPI` — `MemoryBudget(ctx, M=None)` (M5): `M`, `paginas_em_uso`, `reservar_paginas/liberar_paginas`,
  `reservar_tuplas(n, tam)/liberar_tuplas`, `tuplas_por_pagina`, `liberar_tudo`; context manager. Exceder → `MemoryBudgetError`.
- `scan.py` (M5): `scan_registros(entrada, toss)`, `Medidor(ctx)` (`with` → `.metricas`).
- `fachada.py`: re-exporta `criar_contexto`, `ESQUEMAS`, `FKS`, `REGISTRY`, `EspecMetodo`, `EspecIndice`, `montar`, `inserir`, `remover`.

## src/bench
- `cost_model.py` (M6): `Custo{transferencias, seeks}`; `custo_selecao(caminho, tabela, *, indice, sc)`, `custo_sort(b, M, bb)`,
  `custo_bnl(r, s, M)`, `custo_inl(r, s, indice_s, c)`, `custo_smj(r, s, M, bb, *, ordenado_r, ordenado_s)`,
  `custo_hash_join(r, s, M, bb, nh)`, `comparar(medido, estimado)`.
- `datagen.py` (M7): `gerar_tabela(cfg, nome) -> Iterator[dict]`, `limiares_cr(cfg)`.
- `sqlite_ref.py` (M7): `exportar(cfg, caminho=None) -> Path`, `consultar(caminho, sql, params)`.
- `loader.py` (M8): `carregar(ctx, nome_tabela, espec, registros=None) -> AccessMethod`.
- `runner.py` (M9): `COLUNAS`, `executar_experimento(caminho_exp, perfil, saida) -> Path`, `main(argv)`.
- `plots.py` (M12): `gerar_graficos(csv, destino) -> list[Path]`.

## tests (M0)
- `tests/conftest.py`: `cfg`, `bm`, `ctx`, `codec` (fábrica), `page_impl`, `tabela(nome, n, registros=None, seed=0)`;
  real se existir, senão fake; `--so-fakes`; autouse `assert_no_pins()` no teardown.
- `tests/fakes/`: `FakeFileManager`, `FakeBufferManager` (LRU/MRU/FIFO; CLOCK≈LRU; cabeçalho não conta I/O),
  `FakeCodec`, `FakeSlottedPage`, `FakeCatalog`, `FakeTable` (heap), `FakeIndex`, `FakeTempFile`, `FakeStorageContext`,
  `registros_fake(esquema, n, seed)`, `validar_registro(esquema, rec)`.
