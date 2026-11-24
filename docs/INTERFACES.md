# INTERFACES — API pública das camadas prontas

> Só assinaturas + 1 linha. Atualizado ao fim de cada etapa. Não abrir o código de outras
> camadas sem necessidade — consulte aqui.

## src/common
### config.py
- `load_config(perfil="teste", overrides: Mapping|None=None, caminho=None) -> Config` — lê `config/base.yaml`, aplica overrides (`"buffer.policy": "MRU"` ou dict aninhado), valida.
- `Config` (dataclass frozen): `perfil, block_size, extent_blocks, data_dir: Path, seek_model, buffer_total, buffer_areas: Mapping[str,int], buffer_policy, buffer_policies, toss_immediate, prefetch, hash_fill_factor, hash_funcao, bplus_bulk_load, volumes: Mapping[str,int], seed, raw` (YAML congelado).
- `Config.M -> int` — páginas da área `trabalho`; `Config.perfil_dir -> Path` — `data/<perfil>`; `Config.policy_for(area) -> str`.
- `POLITICAS_VALIDAS = ("LRU","MRU","FIFO","CLOCK")`.
### erros.py
- `BancadaError` > `ConfigError`, `StorageError` > `BufferFullError`, `RecordError`, `MemoryBudgetError`.
### tipos.py
- `RID(bloco, slot)`, `PageId(fid, bno)` — NamedTuples.

## src/storage
_(E01/E02)_

## src/access
_(E03–E08)_

## src/executor
_(E10–E12)_

## src/bench
_(E09, E13, E14)_
