# Plano de Execução — Bancada de Teste (Avaliação 2)

> Para o Claude Code: leia **apenas** a seção da etapa atual (indicada em `PROGRESS.md`) e,
> quando a etapa pedir, a seção "Decisões fixadas". Siga o protocolo do `CLAUDE.md`.
> Cada etapa foi dimensionada para **uma sessão**. Critério de pronto = todos os itens de
> "Aceite" verdadeiros + suíte completa verde.

---

## Decisões fixadas (valem para todas as etapas)

Valores-base. Ficam em `config/base.yaml`; código lê de lá. Justificativas em `docs/decisoes/M0-base.md` (+ `docs/decisoes/Mx.md` por módulo).

| Item | Valor-base | Observação |
|---|---|---|
| Tamanho do bloco | 4096 B | variação opcional 2048/8192 |
| Alocação | extents de 8 blocos | alternativa preterida: contígua / encadeada |
| Disco | 1 arquivo do SO por estrutura em `data/<perfil>/` | bloco 0 = cabeçalho do arquivo |
| Blocos livres | lista encadeada (ponteiro no cabeçalho) | |
| Modelo de seek | **um único braço de disco global**: acesso a (fid,b) é sequencial se o último acesso físico foi (fid,b−1); senão é seek | serve para tS do livro |
| RID | `(bloco, slot)` | |
| Página | *slotted page* (Silberschatz Fig. 13.6), blocagem *unspanned* | |
| Registro | null bitmap + parte fixa + pares (offset,len) p/ variáveis + área variável (Fig. 13.5) | multivalorados como campo variável serializado |
| Buffer total | 256 páginas (1 página = 1 bloco) | |
| Áreas do buffer (fixas) | catalogo 8 · indice 64 · dados 120 · trabalho **M = 64** | "tabela pequena" = cabe em M |
| Políticas | LRU, MRU, FIFO, Clock — por área | base: LRU |
| Pinning | contador de pins; página pinada nunca é expulsa | |
| Toss-immediate | opcional por chamada (`toss=True`) | |
| Forced output | `flush()` explícito, contado à parte | |
| Prioridade | área `indice` separada já retém índice/raiz | |
| Prefetch | opcional (`prefetch=k`), desligado na base | |
| Hash | estático, nB = ⌈nr / (fr·0,8)⌉, bucket = 1 bloco, overflow encadeado, FNV-1a 64 | |
| B+ | nó = 1 bloco, fan-out calculado do bloco; NOT UNIQUE via chave composta (chave, uniquificador) | bulk loading na carga |
| Índice secundário NOT UNIQUE | B+ **sem repetição de chave nas folhas**: folha guarda (chave → ponteiro p/ bloco(s) de lista de RIDs) | exigência do enunciado |
| Linguagem | Python 3.11 + pytest + hypothesis + pyyaml + pandas + matplotlib | SQLite (stdlib) como referência |

### Estrutura do repositório
```
CLAUDE.md  PROGRESS.md  POST_MORTEM.md  README.md  requirements.txt  pytest.ini
config/        base.yaml, perfis (teste/medio/completo), experimentos/*.yaml
src/common/    config.py, erros.py, tipos.py
src/storage/   file_manager.py, buffer_manager.py, replacement.py, stats.py
src/access/    record.py, page.py, catalog.py, organization.py (ABC), heap.py,
               bplus.py, hashfile.py, secondary.py, access_methods.py
src/executor/  memory.py, scan.py, selection.py, sort.py, join_bnl.py, join_inl.py,
               join_smj.py, join_hash.py
src/bench/     datagen.py, loader.py, cost_model.py, runner.py, plots.py, sqlite_ref.py
tests/         test_<modulo>.py, test_arquitetura.py, stress/
tools/         log_prompt.py
ia_log/        prompts/<autor>.md, code_review/<Mx>.md, stress_raw_vs_fix.md
docs/          PLANO_EXECUCAO.md, MODULOS.md, GIT_FLUXO.md, INTERFACES.md, decisoes/<Mx>.md, REFERENCIA_LIVRO.md
progress/      <Mx>.md (status por módulo)
results/       *.csv, plots/
relatorio/     relatorio_tecnico.md, relatorio_ia.md, slides.md (+ PDFs)
data/          (gitignored)
```

### Perfis de volume (calibrados na E09 para a matriz completa rodar em < ~40 min)
| Tabela | teste | medio | completo (alvo) |
|---|---|---|---|
| Curso | 10 | 30 | 50 |
| Disciplina | 100 | 500 | 2 000 |
| Turma | 300 | 2 000 | 8 000 |
| Aluno | 1 000 | 5 000 | 20 000 |
| Detalhes_do_Aluno | 1 000 | 5 000 | 20 000 |
| Inscricao_Aluno_Turma | 5 000 | 25 000 | 100 000 |

---

## E00 — Ambiente e esqueleto
**Objetivo:** repositório pronto para as próximas etapas.
**Fazer:**
1. `git init` (se ainda não houver), `.gitignore` (`.venv/ data/ __pycache__/ *.pyc .pytest_cache/`; **não** ignorar `material/` — pergunte ao usuário se quer versionar os PDFs; padrão: ignorar `material/*.pdf`).
2. `python -m venv .venv`; `requirements.txt` (pytest, hypothesis, pyyaml, pandas, matplotlib); instalar.
3. Criar a árvore de diretórios acima com `__init__.py`; `pytest.ini` (`testpaths = tests`, marker `stress`, `addopts = -m "not stress"`).
4. `config/base.yaml` com todos os valores da tabela "Decisões fixadas" + perfis; `src/common/config.py` (`load_config(perfil="teste", overrides: dict|None) -> Config` dataclass imutável).
5. `tests/test_arquitetura.py`: percorre `src/` com `ast`, falha se uma camada importar outra que não a imediatamente inferior (common é livre).
6. *(feito na E00; hoje em `docs/decisoes/M0-base.md` e `ia_log/code_review/M0.md`)* `docs/INTERFACES.md`, `docs/DECISOES.md` (com as decisões fixadas já justificadas, 1–2 linhas cada, citando alternativa preterida), `ia_log/code_review.md` (cabeçalho), `README.md` (como rodar).
7. Verificar o hook de prompts: `tools/log_prompt.py` já existe; confirmar que `ia_log/prompts/<autor>.md` recebeu o prompt desta sessão.
**Aceite:** `.venv/Scripts/python -m pytest -q` verde; `load_config()` retorna block_size 4096; commit `feat(E00)`.
*(E00 é infraestrutura: pode pular o passo ia-raw.)*

---

## E00b — Contratos, stubs e fakes (módulo M0 — destrava o trabalho em paralelo)
**Objetivo:** congelar a API de todas as camadas para que M1–M7 possam ser desenvolvidos ao
mesmo tempo, cada um testando contra fakes das camadas que ainda não existem.
Leia `docs/MODULOS.md` (seções "Ideia central" e "Regras") e as interfaces das etapas E01–E14 deste plano.

**Fazer:**
1. **Tipos compartilhados** em `src/common/tipos.py`: `Predicado(campo, op, valor)` com
   `op ∈ {'=','<','<=','>','>='}`, `CondJuncao(campo_r, campo_s)`, `Metricas` (dict tipado com as
   chaves de `BufferManager.stats()` + `tuplas_saida`), `CAMINHOS_SELECAO` (A1_linear, A1_chave,
   A2…A6, HASH_PRIM, HASH_SEC).
2. **Contratos (ABC/Protocol + dataclasses), sem implementação:**
   - `src/storage/contracts.py`: `Frame`, `FileManagerAPI`, `BufferManagerAPI` (exatamente a interface de E01/E02), `CHAVES_STATS`.
   - `src/access/contracts.py`: `Campo`, `Esquema`, `RecordCodecAPI`, `SlottedPageAPI`, `CatalogAPI`
     (inclui `InfoTabela` com nr, br, fr, tam_registro, V(A), altura de índices — o formato que o
     `cost_model` consome), `FileOrganization` (interface da E04), `SecondaryIndex`
     (`insert(chave, ref)`, `delete(chave, ref)`, `search_eq(chave) -> Iterator[ref]`,
     `search_range(lo, hi, incl_lo, incl_hi) -> Iterator[ref]`, `altura()`, `num_blocks()`),
     `TempFile` (`append(rec)`, `blocks() -> Iterator[bno]`, `records_in_block(bno)`, `scan()`,
     `num_blocks()`, `close()`, `delete()`), `StorageContext` (dá ao executor o que ele precisa sem
     importar `storage`: `buffer_stats()`, `reset_stats()`, `drop_all()`, `work_capacity() -> M`,
     `pin_work_page()/unpin_work_page()`, `temp_file(esquema) -> TempFile`, `catalog`).
   - `src/access/esquemas.py`: os 6 esquemas da base universitária (E09) como `Esquema` — compartilhado por M2, M7, M8.
   - `src/executor/contracts.py`: assinaturas de `select`, `external_sort`, `block_nested_loop`,
     `indexed_nested_loop`, `sort_merge_join`, `hash_join` (todas retornam `(iterador, Metricas)`), e `MemoryBudget`.
3. **Stubs** de todos os arquivos de implementação listados em `docs/MODULOS.md` (classes/funções com a
   assinatura do contrato, docstring citando a seção do livro, corpo `raise NotImplementedError`).
4. **Fakes** em `tests/fakes/` (simples, corretos, **contam I/O pelo mesmo contrato**):
   `FakeFileManager` (blocos em dict) + `FakeBufferManager` (LRU simples, pin/unpin/dirty, stats),
   `FakeCodec` (JSON com limite de tamanho), `FakeSlottedPage` (lista serializada no bytearray com
   checagem de capacidade), `FakeCatalog`, `FakeTable` (FileOrganization heap sobre o buffer),
   `FakeIndex` (SecondaryIndex em dict, contando 1 acesso de página por busca), `FakeTempFile`,
   `FakeStorageContext`.
5. **`tests/conftest.py`:** fixtures `cfg`, `bm`, `ctx`, `codec`, `page_impl`, `tabela(nome, n)` —
   cada uma tenta instanciar a implementação real e cai no fake se ela lançar `NotImplementedError`;
   fixture autouse que chama `assert_no_pins()` no teardown; opção `--so-fakes` para forçar fakes.
6. **Testes de contrato** em `tests/contratos/`: testes parametrizados pela implementação
   (fake e real) para buffer, codec, slotted page, FileOrganization, SecondaryIndex, TempFile.
   O real é marcado `xfail(strict=False)` enquanto for stub.
7. `src/common/config.py`: também carrega e faz merge de `config/modulos/*.yaml`.
8. `docs/INTERFACES.md` reescrito a partir dos contratos (fonte única de verdade).
9. CI: conferir que `.github/workflows/testes.yml` passa.
**Aceite:** suíte verde (stubs como xfail); `tests/test_arquitetura.py` verde; todos os fakes passam
nos testes de contrato; merge em `main` **antes** de qualquer módulo da Fase 1 começar.

---

## E01 — Gerente de Arquivos (Camada 4a)
**Livro:** 12.3, 12.6, 13.2 (REFERENCIA_LIVRO §1).
**Arquivos:** `src/storage/file_manager.py`, `src/storage/stats.py`, `tests/test_file_manager.py`.
**Interface:**
```python
class FileManager:
    def __init__(self, cfg, base_dir)
    def create(self, nome: str, tipo_org: str, meta: dict) -> int   # fid
    def open(self, nome) -> int ; def close(self, fid) ; def delete(self, nome)
    def read_block(self, fid, bno) -> bytearray        # SÓ o BufferManager chama
    def write_block(self, fid, bno, data: bytes)
    def allocate_block(self, fid) -> int                # usa lista livre, senão novo extent
    def free_block(self, fid, bno)
    def num_blocks(self, fid) -> int                    # blocos em uso (exclui livres e cabeçalho)
    def header(self, fid) -> dict ; def set_header(self, fid, **campos)
    stats: IOStats   # por arquivo e global: reads, writes, seq_reads, rand_reads, seq_writes, rand_writes
```
**Detalhes:** cabeçalho no bloco 0 serializado com `struct` (magic, versão, tipo_org, nº blocos alocados, cabeça da lista livre, tamanho de extent, + `meta` em JSON curto limitado ao bloco). Acesso ao cabeçalho **também conta** como I/O. Seek conforme "Modelo de seek".
**Testes:** escrever/ler N blocos; dado maior que bloco → erro; reuso de bloco liberado; alocação em extents (alocar 9 blocos → arquivo com 2 extents); contagem seq vs aleatório numa sequência conhecida (0,1,2,7,8,3 → 3 seeks contando o primeiro); persistência após reabrir.
**Aceite:** testes verdes; nenhum cache interno de blocos no FileManager.

---

## E02 — Gerente de Buffer Pool (Camada 4b)
**Livro:** 13.5, 19.5 (REFERENCIA_LIVRO §2).
**Arquivos:** `src/storage/buffer_manager.py`, `src/storage/replacement.py`, `tests/test_buffer_manager.py`, `tests/test_replacement.py`.
**Interface:**
```python
class Frame: fid, bno, data: bytearray, pin_count, dirty, ref_bit ; def mark_dirty()
class BufferManager:
    def __init__(self, cfg, fm: FileManager)            # áreas e políticas do cfg
    @contextmanager
    def page(self, fid, bno, area="dados", dirty=False, toss=False) -> Frame
    def pin(self, fid, bno, area="dados") -> Frame ; def unpin(self, frame, dirty=False, toss=False)
    def new_page(self, fid, area="dados") -> Frame       # allocate_block + pin (sem ler do disco)
    def free_page(self, fid, bno)
    def flush(self, fid, bno)        # forced output (conta forced_writes)
    def flush_all(self) ; def drop_all(self)   # drop_all = flush + esvaziar (cold start)
    def set_policy(self, area, nome) ; def area_capacity(self, area) -> int
    def stats(self) -> dict   # por área e global: requests, hits, misses, hit_rate,
                              # dirty_evictions, forced_writes, + IOStats do FileManager
    def reset_stats(self) ; def assert_no_pins(self)
    # repassa ao FileManager: create/open/close/delete/num_blocks/header/set_header
```
**Políticas** (`replacement.py`, interface comum `Policy.on_load/on_access/on_unpin/victim(frames)`): LRU, MRU, FIFO, Clock. Vítima só entre frames com `pin_count == 0`; se nenhuma → `BufferFullError`.
**Testes:** para cada política, sequência de referência clássica com nº de faltas calculado à mão (documente o cálculo no teste); dirty → expulsão grava; página não dirty → expulsão não grava; toss-immediate coloca a página como próxima vítima; pin impede expulsão; `assert_no_pins` falha se houver pin pendente; hits+misses == requests.
**Aceite:** testes verdes; `grep -rn "read_block\|write_block" src/ | grep -v storage/` vazio.

---

## E03 — Registros, páginas e catálogo (Camada 3 — base)
**Livro:** 13.2, 13.3, 13.4 (REFERENCIA_LIVRO §3).
**Arquivos:** `src/access/record.py`, `page.py`, `catalog.py`, `tests/test_record.py`, `test_page.py`, `test_catalog.py`.
**Interface:**
```python
@dataclass class Campo: nome, tipo ('int','float','date','char(n)','varchar(n)','list[varchar(n)]'), nulo: bool
@dataclass class Esquema: nome, campos: list[Campo], chave: list[str]
class RecordCodec: def __init__(self, esquema) ; encode(dict)->bytes ; decode(bytes)->dict ; max_size
class SlottedPage:   # opera sobre frame.data (bytearray do bloco), sem copiar o bloco
    @staticmethod format(buf) ; insert(buf, rec: bytes)->slot|None ; get(buf, slot)->bytes|None
    delete(buf, slot) ; update(buf, slot, rec)->bool ; compact(buf) ; free_space(buf) ; slots(buf)->iter
class Catalog:   # persistido num arquivo próprio via BufferManager (área 'catalogo')
    registrar_tabela(esquema, org, params) ; registrar_indice(...) ; tabela(nome)->InfoTabela
    atualizar_estatisticas(nome, nr, br, V: dict[campo,int], fr)   # usados pelo cost_model
```
**Detalhes:** null bitmap; datas como int (dias); compactação preserva números de slot (RIDs estáveis); toda leitura de offset/len valida `0 <= off <= off+len <= block_size`.
**Testes:** round-trip com `hypothesis` (nulos, strings vazias, tamanhos máximos, listas vazias); página cheia retorna None; delete+compact mantém RIDs; offset corrompido → `CorruptedPageError` (não lê fora do bloco).
**Aceite:** testes verdes.

---

## E04 — Arquivo Heap + interface comum de organização
**Livro:** 13.3.1.
**Arquivos:** `src/access/organization.py` (ABC), `heap.py`, `tests/test_heap.py`.
**Interface (ABC `FileOrganization`)** — registro a registro e conjunto a conjunto, conforme enunciado §3:
```python
open() ; reset() ; close()
find(campo, valor) -> RID|None ; find_next() -> RID|None      # cursor
read(rid) -> dict ; insert(rec) -> RID ; delete(rid) ; update(rid, rec) -> RID
scan(toss=False) -> Iterator[(RID, dict)]                    # varredura física bloco a bloco
find_all(campo, op, valor) -> Iterator[(RID, dict)]
find_ordered(campo, lo, hi) -> Iterator[(RID, dict)]          # quando a organização permite
reorganize() ; num_blocks() -> int ; ocupacao() -> dict       # blocos de dados/overflow/índice
```
**Heap:** *free-space map* simples (lista de blocos com espaço no cabeçalho, ou 1 byte/bloco num bloco de mapa) — escolher, justificar em DECISOES; compactação de bloco quando espaço fragmentado > 25% (parâmetro).
**Testes:** inserir N, scan devolve N; delete + reinserção reaproveita espaço; find linear; `assert_no_pins` após cada operação (fixture global em `tests/conftest.py` que chama `buffer.assert_no_pins()` no teardown — **criar aqui e reutilizar sempre**).
**Aceite:** testes verdes.

---

## E05 — Árvore B+ como organização primária (parte 1: busca/inserção)
**Livro:** 14.3, 14.4.1 (REFERENCIA_LIVRO §4).
**Arquivos:** `src/access/bplus.py`, `tests/test_bplus.py`.
**Fazer:** nós em blocos (área `indice` para internos, `dados` para folhas — folhas guardam os registros, pois é organização primária); layout do nó documentado no docstring; fan-out `n` calculado do bloco e do tamanho da chave; busca; busca por faixa seguindo ponteiro de próxima folha; inserção com split de folha e de nó interno **propagando até a raiz** (nova raiz quando necessário); raiz no cabeçalho do arquivo; `altura()`; `check_invariants()` (ordenação, ocupação mínima exceto raiz, todas as folhas mesma profundidade, encadeamento completo e ordenado, contagem de registros).
**Testes:** 10 000 inserções aleatórias com `check_invariants` a cada 500; busca de todas as chaves; faixa vs `sorted()` (oráculo só no teste); altura ≤ ⌈log_{⌈n/2⌉}(N)⌉ + 1.
**Aceite:** testes verdes; busca binária dentro do nó opera sobre as entradas do bloco já pinado (não sobre o arquivo).

## E06 — Árvore B+ (parte 2: remoção, NOT UNIQUE, bulk loading)
**Fazer:** remoção com redistribuição e fusão respeitando ocupação mínima e propagando até a raiz (encolher altura); modo NOT UNIQUE (chave composta com uniquificador; `find_all(campo,'=',v)` devolve todos); `bulk_load(registros_ordenados, fill=0.8)` bottom-up (seção 14.4, ver REFERENCIA_LIVRO §4); `reorganize()` = reconstruir por bulk load.
**Testes:** property-based com `hypothesis` (sequência aleatória de insert/delete vs dict oráculo, `check_invariants` após cada op); remover tudo → árvore vazia válida; bulk load de 20 000 → invariantes + altura mínima; NOT UNIQUE com 1 000 duplicatas da mesma chave.
**Aceite:** testes verdes.

---

## E07 — Hash estático externo (UNIQUE e NOT UNIQUE)
**Livro:** 14.5 (REFERENCIA_LIVRO §5).
**Arquivos:** `src/access/hashfile.py`, `hash_index.py`, `tests/test_hashfile.py`, `test_hash_index.py`.
**Inclui (movido da E08 no modo paralelo):** `HashIndex` secundário UNIQUE (chave → RID), que
implementa `SecondaryIndex` de `src/access/contracts.py`, reaproveitando buckets/overflow do hashfile.
**Fazer:** nB buckets primários contíguos (blocos 1..nB) definidos na criação; bucket = slotted page + ponteiro de overflow no fim; overflow encadeado; função FNV-1a 64 (alternativas comparadas no teste de dispersão: `hash()` do Python NÃO — não é determinístico entre execuções); `find`, `find_next` (percorre cadeia), `insert`, `delete` (procura na cadeia toda; libera bloco de overflow vazio), `estatisticas()` → buckets, overflow, cadeia máx/média, fator de carga, coeficiente de variação da ocupação (skew).
**Testes:** função degenerada (tudo no bucket 0) → busca e remoção corretas em cadeia longa; dispersão de CPF/DRE gerados (qui-quadrado simples ou CV < limiar); NOT UNIQUE com duplicatas; `scan` vê tudo.
**Aceite:** testes verdes.

---

## E08 — Índices secundários e métodos de acesso
**Livro:** 14.2, 14.4.2 (REFERENCIA_LIVRO §4–5).
**Arquivos:** `src/access/secondary.py`, `access_methods.py`, `tests/test_secondary.py`.
**Fazer:**
- `HashIndex` secundário UNIQUE (chave → RID) — para Heap. **Já entregue pelo M4 (E07)**; aqui só é registrado no registry.
- Arquivo do índice B+ secundário: `src/access/secondary_bplus.py` (módulo M8).
- `BPlusIndex` secundário NOT UNIQUE **sem repetição de chave nas folhas**: entrada de folha = (chave, ponteiro para cadeia de blocos de RIDs) — para Heap, B+ e Hash.
- Índice secundário *clustering* (para B+ e Hash, campo NOT UNIQUE): definir no DECISOES como interpretar (sugestão: B+ secundário cujas listas de RIDs estão ordenadas pelo endereço físico, de modo que o acesso aos dados é em ordem de bloco).
- Para organização B+ (registros se movem em split): índice secundário guarda **chave primária**, não RID (14.4.2) — documentar o custo extra.
- Manutenção: insert/delete na tabela atualizam todos os índices dela.
- `access_methods.py`: `AccessMethod` = (organização, índice opcional). Registry que monta exatamente as combinações da tabela 4.2 do enunciado:
  Heap {sem índice, Hash UNIQUE secundário, B+ NOT UNIQUE secundário} · B+ {primário UNIQUE/NOT UNIQUE, secundário clustering NOT UNIQUE} · Hash {primário UNIQUE, primário NOT UNIQUE, secundário clustering B+ NOT UNIQUE}.
**Testes:** cada combinação: inserir, buscar por igualdade e faixa, remover, conferir consistência índice×dados; `ocupacao()` inclui blocos dos índices.
**Aceite:** testes verdes; `docs/INTERFACES.md` lista o registry.

---

## E09 — Gerador da base, carga e referência SQLite (Camada 1 — dados)
**Arquivos:** `src/bench/datagen.py`, `loader.py`, `sqlite_ref.py`, `tests/test_datagen.py`.
**Modo paralelo:** M7 faz gerador + SQLite (registros como `dict`, esquemas de `src/access/esquemas.py`);
o **loader** (criar tabela × AccessMethod e carregar) fica com o M8. A calibração dos volumes é feita pelo M9.
**Esquema** (enunciado §6.4; documentar esquema físico em DECISOES):
Aluno(CPF, **DRE**, nome, data_nasc, sexo, endereco, emails list, cod_curso FK, CR, prof_orientador) ·
Curso(**codigo**, nome, escola, carga_horaria, prof_coordenador, email, endereco_secretaria, telefones list) ·
Disciplina(**codigo**, cod_curso FK, nome, ementa, carga_horaria, pre_requisitos list) ·
Turma(**numero**, cod_disciplina FK, semestre, ano, horario, sala, professor) ·
Inscricao_Aluno_Turma(**DRE, numero_turma**, frequencia, media_final) ·
Detalhes_do_Aluno(CPF UNIQUE, campos extras).
**Fazer:** gerador determinístico (semente no config) por perfil; CR com distribuição tal que `CR > x1` dá ≈1% e `CR < x50` dá ≈50% (calcular e gravar os limiares no catálogo); `professor` com cardinalidade controlada (equijoin NOT UNIQUE Aluno.prof_orientador = Turma.professor); loader que cria qualquer (tabela × AccessMethod) e usa bulk load para B+; exporta a mesma base para SQLite em `data/<perfil>/ref.sqlite`.
**Calibração:** medir tempo de carga e de um BNL grande⋈grande no perfil `medio`; extrapolar e ajustar os volumes do perfil `completo` em `config/base.yaml` para a matriz completa (E14) caber em ~40 min. Registrar em DECISOES.
**Aceite:** seletividades reais dentro de ±0,3 p.p. de 1% e 50%; contagens iguais no SQLite; FKs válidas.

---

## E10 — Seleção (Camada 2)
**Livro:** 15.2, 15.3 (REFERENCIA_LIVRO §6).
**Arquivos:** `src/executor/memory.py`, `scan.py`, `selection.py`, `tests/test_selection.py`.
**Fazer:**
- `MemoryBudget(buffer, M)`: controla páginas da área `trabalho` e o nº de tuplas mantidas em memória (`reservar(n_tuplas, tam)` lança erro se exceder M páginas). Usado por todas as primitivas da Camada 2.
- `select(tabela, AccessMethod, predicado, caminho)` onde `caminho ∈ {A1_linear, A1_chave, A2, A3, A4, A5, A6, HASH_PRIM, HASH_SEC}` é **escolhido explicitamente** pelo chamador (sem otimizador). Retorna `(iterador, metricas)`.
- Predicados: igualdade UNIQUE; faixa `<,<=,>,>=` NOT UNIQUE; (opcional) faixa UNIQUE.
**Testes:** para cada combinação válida (campo sem índice / da organização primária / com índice secundário) × seletividade {1%, 50%}: resultado == SQLite (multiconjunto); `assert_no_pins`.
**Aceite:** testes verdes no perfil `teste`.

---

## E11 — Ordenação externa, Block Nested-Loop e Indexed Nested-Loop
**Livro:** 15.4, 15.5.1–15.5.3 (REFERENCIA_LIVRO §7).
**Arquivos:** `src/executor/sort.py`, `join_bnl.py`, `join_inl.py`, `tests/test_sort.py`, `tests/test_join_nl.py`.
**Fazer:**
- `external_sort(entrada, chave, M, bb=1)`: runs de M páginas em arquivos temporários (via BufferManager, área `trabalho`), merge (M−1)-way, retorna arquivo ordenado + métricas. Temporários apagados ao final.
- `block_nested_loop(r, s, cond, M, externa='r'|'s'|'auto')`: M−2 blocos para a externa, 1 para a interna, 1 de saída; `auto` escolhe a menor como externa; opção `toss` na interna e política MRU recomendada (testar ambas).
- `indexed_nested_loop(r, s_com_indice, cond)`.
- Saída da junção: iterador (não materializa) ou arquivo temporário (`materializar=True`) — métricas de escrita do resultado separadas.
**Testes:** com M=3 (mínimo) e M=64 o resultado == SQLite; MemoryBudget nunca excedido; nº de transferências da interna no BNL == ⌈br/(M−2)⌉·bs (± leituras de cabeçalho) com buffer frio e área `dados` pequena.
**Aceite:** testes verdes.

---

## E12 — Sort-Merge Join e Partition-Hash Join
**Livro:** 15.5.4, 15.5.5 (REFERENCIA_LIVRO §7).
**Arquivos:** `src/executor/join_smj.py`, `join_hash.py`, `tests/test_join_smj_hash.py`.
**Fazer:**
- Sort-merge: ordena entradas não ordenadas com `external_sort` (pula se a organização já fornece ordem: B+ na chave de junção via `find_ordered`); merge tratando grupos de chaves duplicadas; se um grupo Ss não couber em M, fallback de BNL para o grupo (documentar).
- Partition-hash: nh = ⌈bs/M⌉ (ajustado com fudge 1,2 — justificar); build input = menor; particionamento recursivo quando uma partição > M−2; função de hash de partição **diferente** da do build em memória; tabela hash em memória limitada por MemoryBudget.
**Testes:** os 3 tamanhos (menor⋈menor, menor⋈maior, maior⋈maior) × NATURAL JOIN PK–FK, equijoin UNIQUE (CPF) e NOT UNIQUE (professor) == SQLite; M=3 e M=64; skew forçado (90% da FK num valor) não quebra.
**Aceite:** testes verdes.

---

## E13 — Modelo de custo e validação estimado × medido
**Livro:** 15.2–15.5 (REFERENCIA_LIVRO §6–7, fórmulas já conferidas).
**Arquivos:** `src/bench/cost_model.py`, `tests/test_cost_model.py`.
**Fazer:** uma função por algoritmo retornando `{'transferencias': x, 'seeks': y}` a partir do catálogo real (br, bs, nr, ns, hi, n, b, M, bb, nh, cadeia média de overflow). Função `comparar(medido, estimado) -> dict` com diferença absoluta e relativa.
**Testes:** reproduzir os números de exemplo do livro (BNL student⋈takes = 40 100 transferências/200 seeks; hash join = 1 500 / 336; sort-merge M=3 = 9 100 transferências) — ver REFERENCIA_LIVRO; em casos pequenos com buffer frio e área `dados` de 1–3 páginas, medido == estimado (±cabeçalhos). Documentar no docstring as fontes de divergência esperadas (buffer quente, raiz da B+ em memória, overflow, blocos parcialmente cheios).
**Aceite:** testes verdes.

---

## E14 — Orquestrador e matriz de experimentos
**Arquivos:** `src/bench/runner.py`, `config/experimentos/*.yaml`, `tests/test_runner.py`.
**Fazer:**
- CLI: `.venv/Scripts/python -m src.bench.runner --perfil teste --exp config/experimentos/sel_igualdade.yaml`.
- Para cada ponto: carrega/reaproveita base (cache por hash da config em `data/`), registra `ocupacao()` antes/depois das cargas de manutenção (inserção de 5% + remoção de 5%), `drop_all()` + `reset_stats()` (cold start), executa, repete até CV < 5% (mín. 3, máx. 7 — contagens de blocos são determinísticas; o critério importa para o tempo de relógio), compara com SQLite (só no 1º rep), grava 1 linha CSV em `results/<exp>.csv`.
- Colunas: exp, operacao, algoritmo, caminho, org_r, idx_r, org_s, idx_s, tam_r, tam_s, seletividade, politica, M, block_size, rep, leituras, gravacoes, seq, seeks, requests, hits, misses, hit_rate, dirty_evictions, forced_writes, est_transf, est_seeks, dif_rel, tuplas_saida, tempo_s, ok_sqlite.
- Arquivos de experimento (variar **um fator por vez** em torno da base):
  `sel_igualdade.yaml`, `sel_faixa.yaml`, `join_natural.yaml` (casos a–e × 3 tamanhos × 3 algoritmos [+INL quando houver índice]), `join_unique.yaml`, `join_nonunique.yaml`, `politicas_buffer.yaml` (LRU/MRU/FIFO/Clock nos casos mais sensíveis: BNL e scan repetido), `manutencao.yaml` (ocupação antes/depois), opcional `block_size.yaml`.
  Para cada experimento, a política usada deve ser a mais apropriada (enunciado §6.2) — o `politicas_buffer.yaml` é o que justifica a escolha.
**Testes:** runner no perfil `teste` com uma matriz mínima gera CSV com todas as colunas e `ok_sqlite` verdadeiro.
**Aceite:** testes verdes; `results/` com CSV de smoke test.

---

## E15 — Code review adversarial (checklist do enunciado §7.1)
**Fazer:** revisar `src/` inteiro procurando **cada** item, escrevendo um teste que o detectaria antes de concluir que não existe:
1. leitura de blocos fora do Buffer Manager · 2. pin sem unpin / página alterada sem dirty ·
3. busca binária sobre registros · 4. B+ sem ocupação mínima / sem encadeamento / sem propagação até a raiz ·
5. hash ignorando overflow na busca ou remoção · 6. junções com estruturas da linguagem > área de buffer ·
7. offsets/tamanhos fora do bloco · 8. eficiência: complexidade (ex.: `list.pop(0)`, cópias de bloco desnecessárias, O(n²) escondido), vazamento de arquivos temporários/handles.
Pode rodar `/code-review` do Claude Code como apoio. Para cada achado: entrada em `ia_log/code_review/<módulo revisado>.md` com prefixo `[RC por Px]`; a correção é do dono do módulo, commit `fix(E15)`. Se nada for encontrado num item, registrar **qual teste** comprova.
**Aceite:** cada `ia_log/code_review/Mx.md` revisado tem seção "Checklist 7.1" com os 8 itens resolvidos; suíte verde.

---

## E16 — Testes de estresse: código bruto × refatorado
**Arquivos:** `tests/stress/*.py` (marker `stress`), `tools/stress_raw_vs_fix.py`, `ia_log/stress_raw_vs_fix.md`.
**Fazer:** suíte de estresse: 200 000 insert/delete aleatórios em B+ e Hash com invariantes; buffer mínimo (M=3, áreas de 4 páginas); chaves 100% duplicadas; registros no tamanho máximo; hash degenerado; junções maior⋈maior com skew. Script que, para cada tag `raw-Exx` relevante (E02, E05–E07, E11, E12), cria um `git worktree` temporário, roda a mesma suíte e coleta: passou/falhou, exceções, nº de transferências, tempo. Gera tabela comparativa em `ia_log/stress_raw_vs_fix.md` (evidência 7.2.3.d).
**Aceite:** relatório gerado; worktrees temporários removidos.

---

## E17 — Execução completa e gráficos
**Fazer:** rodar todos os `config/experimentos/*.yaml` no perfil `completo` (em background; se demorar demais, `medio` + justificar). `src/bench/plots.py`: gráficos medido × estimado por experimento, hit rate por política, ocupação por organização, transferências por algoritmo de junção × tamanho × caso (a–e). Salvar em `results/plots/*.png`. Gerar `results/RESUMO.md` com tabelas-síntese (pandas → markdown).
**Aceite:** todos os CSVs com `ok_sqlite` verdadeiro; plots gerados; RESUMO.md criado.

---

## E18 — Relatório técnico
**Arquivo:** `relatorio/relatorio_tecnico.md` (+ PDF se `pandoc` estiver disponível; senão avisar o usuário).
**Seções:** folha de rosto (nomes completos + DRE — pegar em `PROGRESS.md` › "Integrantes"; se vazio, **perguntar**) · 1. Arquitetura (diagrama das 4 camadas) · 2. Decisões e justificativas (a partir de `docs/decisoes/*.md`, cada uma com alternativa preterida: bloco, blocagem, registro, cabeçalhos, campos de ordenação, funções de hash, ordem das árvores, buffer) · 3. Base de dados e esquema físico (tabelas, tamanhos de registro, fr, br, volumes) · 4. Metodologia · 5. Resultados (tabelas e gráficos medido × estimado, explicando diferenças) · 6. **Conclusão + lista de recomendações** (qual organização primária, quais índices, qual política de buffer e qual algoritmo para cada carga: seleção pontual, faixa 1%/50%, junções por tamanho e caso a–e).
**Aceite:** todas as afirmações numéricas vêm dos CSVs (citar arquivo).

## E19 — Relatório de IA e POST_MORTEM.md
**Arquivos:** `relatorio/relatorio_ia.md`, `POST_MORTEM.md` (raiz).
**Conteúdo:** a. log de prompts (`ia_log/prompts/*.md`, um por integrante) + como obter o código bruto (`git show raw-Exx`) · b. code review (consolidar `ia_log/code_review/*.md` por categoria e por módulo/autor, com contagem) · c. bateria de testes (lista, cobertura — `pytest --co -q | tail -1`) e estresse · d. POST_MORTEM: prompts-chave + fragmentos brutos (via `git diff raw-Exx feat-commit -- arquivo`, trechos curtos), justificativa de cada refatoração, evidência de `ia_log/stress_raw_vs_fix.md`.
**Aceite:** POST_MORTEM.md na raiz com as 4 subseções do enunciado §7.2.3.d.

## E20 — Slides e checklist final
**Fazer:** `relatorio/slides.md` (formato Marp, ~12 slides: problema, arquitetura, decisões-chave, 4–5 gráficos, recomendações, lições do code review). Checklist final de entrega em `PROGRESS.md`: repositório completo, README com reprodução (`gerar base → rodar experimentos → gerar gráficos`), PDFs, slides, POST_MORTEM.md. Lembrar o usuário: postagem no AVA (um integrante posta tudo; demais só folha de rosto).
**Aceite:** `pytest -q` verde; `README.md` reproduz tudo do zero; checklist completo.
