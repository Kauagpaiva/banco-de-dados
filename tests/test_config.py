import dataclasses

import pytest

from src.common.config import load_config
from src.common.erros import ConfigError


def test_base():
    cfg = load_config()
    assert cfg.block_size == 4096
    assert cfg.extent_blocks == 8
    assert cfg.buffer_total == 256
    assert dict(cfg.buffer_areas) == {"catalogo": 8, "indice": 64, "dados": 120, "trabalho": 64}
    assert cfg.M == 64
    assert cfg.buffer_policy == "LRU"
    assert cfg.volumes["Inscricao_Aluno_Turma"] == 5000
    assert cfg.perfil_dir.name == "teste"


def test_imutavel():
    cfg = load_config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.block_size = 1
    with pytest.raises(TypeError):
        cfg.buffer_areas["trabalho"] = 1


def test_overrides_pontuado_e_aninhado():
    cfg = load_config("medio", {"buffer.policy": "mru", "disco": {"block_size": 8192}})
    assert cfg.buffer_policy == "MRU" and cfg.block_size == 8192
    assert cfg.volumes["Aluno"] == 5000
    # overrides não vazam para a próxima carga
    assert load_config().block_size == 4096


def test_politica_por_area():
    cfg = load_config(overrides={"buffer.policies": {"dados": "MRU"}})
    assert cfg.policy_for("dados") == "MRU" and cfg.policy_for("indice") == "LRU"


@pytest.mark.parametrize("ov", [
    {"buffer.areas.trabalho": 10},          # soma != total
    {"buffer.policy": "RANDOM"},
    {"disco.block_size": 3000},
    {"buffer.policies": {"inexistente": "LRU"}},
])
def test_invalidos(ov):
    with pytest.raises(ConfigError):
        load_config(overrides=ov)


def test_perfil_invalido():
    with pytest.raises(ConfigError):
        load_config("gigante")
