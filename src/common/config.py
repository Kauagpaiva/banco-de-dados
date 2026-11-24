"""Carregamento da configuração da bancada (config/base.yaml).

`load_config(perfil, overrides)` devolve um `Config` imutável. Overrides usam caminhos
pontuados ("buffer.policy": "MRU") ou dicionários aninhados ({"buffer": {"policy": "MRU"}}).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from src.common.erros import ConfigError

RAIZ = Path(__file__).resolve().parents[2]
CONFIG_PADRAO = RAIZ / "config" / "base.yaml"
POLITICAS_VALIDAS = ("LRU", "MRU", "FIFO", "CLOCK")


@dataclass(frozen=True)
class Config:
    perfil: str
    block_size: int
    extent_blocks: int
    data_dir: Path
    seek_model: str
    buffer_total: int
    buffer_areas: Mapping[str, int]
    buffer_policy: str
    buffer_policies: Mapping[str, str]
    toss_immediate: bool
    prefetch: int
    hash_fill_factor: float
    hash_funcao: str
    bplus_bulk_load: bool
    volumes: Mapping[str, int]
    seed: int
    raw: Mapping[str, Any] = field(repr=False, compare=False)

    @property
    def M(self) -> int:
        """Páginas da área de trabalho (memória de junção/ordenação)."""
        return self.buffer_areas["trabalho"]

    @property
    def perfil_dir(self) -> Path:
        return self.data_dir / self.perfil

    def policy_for(self, area: str) -> str:
        return self.buffer_policies.get(area, self.buffer_policy)


def _merge(base: dict, extra: Mapping) -> None:
    for k, v in extra.items():
        if isinstance(v, Mapping) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)


def _aplicar_overrides(dados: dict, overrides: Mapping[str, Any]) -> None:
    for chave, valor in overrides.items():
        if "." not in chave:
            _merge(dados, {chave: valor})
            continue
        partes = chave.split(".")
        alvo = dados
        for p in partes[:-1]:
            alvo = alvo.setdefault(p, {})
            if not isinstance(alvo, dict):
                raise ConfigError(f"override inválido: {chave}")
        _merge(alvo, {partes[-1]: valor})


def _congelar(d: Any) -> Any:
    if isinstance(d, dict):
        return MappingProxyType({k: _congelar(v) for k, v in d.items()})
    if isinstance(d, list):
        return tuple(_congelar(v) for v in d)
    return d


def _merge_modulo(base: dict, extra: Mapping, origem: str, prefixo: str = "") -> None:
    """Acrescenta chaves novas de um `config/modulos/Mx.yaml`; redefinir chave existente é erro."""
    for k, v in extra.items():
        caminho = f"{prefixo}{k}"
        if k not in base:
            base[k] = copy.deepcopy(v)
        elif isinstance(v, Mapping) and isinstance(base[k], dict):
            _merge_modulo(base[k], v, origem, caminho + ".")
        else:
            raise ConfigError(f"{origem} redefine a chave já existente {caminho!r}")


def _carregar_modulos(dados: dict, pasta: Path) -> None:
    if not pasta.is_dir():
        return
    for arq in sorted(pasta.glob("*.yaml")):
        with open(arq, encoding="utf-8") as f:
            extra = yaml.safe_load(f) or {}
        if not isinstance(extra, Mapping):
            raise ConfigError(f"{arq.name}: esperado um mapeamento YAML")
        _merge_modulo(dados, extra, arq.name)


def load_config(perfil: str = "teste", overrides: Mapping[str, Any] | None = None,
                caminho: Path | str | None = None) -> Config:
    """Lê o YAML base, faz merge de `config/modulos/*.yaml` (só chaves novas), aplica
    overrides e valida. Devolve Config imutável. Os módulos ficam em `<pasta do base>/modulos/`."""
    caminho = Path(caminho) if caminho else CONFIG_PADRAO
    with open(caminho, encoding="utf-8") as f:
        dados = yaml.safe_load(f) or {}
    _carregar_modulos(dados, caminho.parent / "modulos")
    if overrides:
        _aplicar_overrides(dados, overrides)

    perfis = dados.get("perfis", {})
    if perfil not in perfis:
        raise ConfigError(f"perfil desconhecido: {perfil!r} (válidos: {sorted(perfis)})")

    disco, buf = dados["disco"], dados["buffer"]
    areas = {k: int(v) for k, v in buf["areas"].items()}
    total = int(buf["total_pages"])
    if sum(areas.values()) != total:
        raise ConfigError(f"soma das áreas ({sum(areas.values())}) != total_pages ({total})")
    if "trabalho" not in areas or areas["trabalho"] < 3:
        raise ConfigError("área 'trabalho' precisa de pelo menos 3 páginas")
    bs = int(disco["block_size"])
    if bs < 512 or bs & (bs - 1):
        raise ConfigError(f"block_size deve ser potência de 2 >= 512: {bs}")
    politicas = {k: str(v).upper() for k, v in (buf.get("policies") or {}).items()}
    for p in [str(buf["policy"]).upper(), *politicas.values()]:
        if p not in POLITICAS_VALIDAS:
            raise ConfigError(f"política de substituição inválida: {p}")
    for a in politicas:
        if a not in areas:
            raise ConfigError(f"política para área inexistente: {a}")

    data_dir = Path(disco["data_dir"])
    if not data_dir.is_absolute():
        data_dir = RAIZ / data_dir

    return Config(
        perfil=perfil,
        block_size=bs,
        extent_blocks=int(disco["extent_blocks"]),
        data_dir=data_dir,
        seek_model=str(disco["seek_model"]),
        buffer_total=total,
        buffer_areas=MappingProxyType(areas),
        buffer_policy=str(buf["policy"]).upper(),
        buffer_policies=MappingProxyType(politicas),
        toss_immediate=bool(buf.get("toss_immediate", False)),
        prefetch=int(buf.get("prefetch", 0)),
        hash_fill_factor=float(dados["hash"]["fill_factor"]),
        hash_funcao=str(dados["hash"]["funcao"]),
        bplus_bulk_load=bool(dados["bplus"]["bulk_load"]),
        volumes=MappingProxyType({k: int(v) for k, v in perfis[perfil].items()}),
        seed=int(dados.get("seed", 0)),
        raw=_congelar(dados),
    )
