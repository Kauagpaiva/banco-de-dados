"""Fachada do executor para a Camada 1 (`src/bench`) — M0.

O bench só pode importar o executor (regra de camadas), mas precisa criar o armazenamento,
conhecer os esquemas e montar métodos de acesso. Este módulo apenas **re-exporta** essas
peças da Camada 3, sem lógica própria; os operadores ficam em `src.executor.<modulo>`.
"""
from src.access.access_methods import (  # noqa: F401
    REGISTRY, EspecIndice, EspecMetodo, inserir, montar, remover,
)
from src.access.context import criar_contexto  # noqa: F401
from src.access.esquemas import ESQUEMAS, FKS  # noqa: F401
