
"""Catálogo do sistema (Camada 3).

Silberschatz 13.4 (dicionário de dados) e 16.3.1 (estatísticas).
Persistido em páginas gerenciadas pelo BufferManager, na área 'catalogo'.
"""

from __future__ import annotations

import json
import math
import struct
from typing import Any, Mapping

from src.access.contracts import (
    CatalogAPI,
    Campo,
    Esquema,
    InfoIndice,
    InfoTabela,
)
from src.common.erros import CorruptedPageError
from src.storage.contracts import BufferManagerAPI


# Formato de cada página:
# magic (4 bytes), próximo bloco (4 bytes), tamanho do conteúdo (4 bytes).
_CABECALHO = struct.Struct("<4sII")
_MAGIC = b"CAT1"


class Catalog(CatalogAPI):
    """Catálogo persistente de tabelas, índices e propriedades do sistema."""

    def __init__(
        self,
        bm: BufferManagerAPI,
        nome: str = "catalogo",
    ):
        self._bm = bm
        self._nome = nome
        self._tabelas: dict[str, InfoTabela] = {}
        self._valores: dict[str, Any] = {}

        if bm.exists(nome):
            self._fid = bm.open(nome)
        else:
            self._fid = bm.create(
                nome,
                "catalogo",
                meta={"catalog_root": 0},
            )

        cabecalho = bm.header(self._fid)
        meta = cabecalho.get("meta", {})
        raiz = meta.get("catalog_root", 0)

        if raiz:
            self._carregar(raiz)

    # ---------------------------------------------------------
    # Persistência
    # ---------------------------------------------------------

    def _tamanho_bloco(self) -> int:
        """Obtém o tamanho de bloco configurado no BufferManager."""
        tamanho = getattr(self._bm, "block_size", None)

        if tamanho is None:
            cfg = getattr(self._bm, "cfg", None)
            tamanho = getattr(cfg, "block_size", None)

        if tamanho is None:
            raise RuntimeError(
                "Não foi possível obter o tamanho do bloco do BufferManager."
            )

        return int(tamanho)

    def _serializar(self) -> bytes:
        """Converte o estado do catálogo para JSON."""
        dados = {
            "tabelas": {
                nome: self._tabela_para_dict(tabela)
                for nome, tabela in self._tabelas.items()
            },
            "valores": self._valores,
        }

        return json.dumps(
            dados,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @staticmethod
    def _tabela_para_dict(tabela: InfoTabela) -> dict[str, Any]:
        esquema = tabela.esquema

        return {
            "nome": tabela.nome,
            "esquema": {
                "nome": esquema.nome,
                "campos": [
                    {
                        "nome": campo.nome,
                        "tipo": campo.tipo,
                        "nulo": campo.nulo,
                        "max_itens": campo.max_itens,
                    }
                    for campo in esquema.campos
                ],
                "chave": esquema.chave,
            },
            "org": tabela.org,
            "campo_org": tabela.campo_org,
            "params": tabela.params,
            "nr": tabela.nr,
            "br": tabela.br,
            "fr": tabela.fr,
            "tam_registro": tabela.tam_registro,
            "V": tabela.V,
            "indices": [
                {
                    "nome": indice.nome,
                    "tabela": indice.tabela,
                    "campo": indice.campo,
                    "tipo": indice.tipo,
                    "unique": indice.unique,
                    "clustering": indice.clustering,
                    "primario": indice.primario,
                    "altura": indice.altura,
                    "num_blocks": indice.num_blocks,
                    "fanout": indice.fanout,
                    "params": indice.params,
                }
                for indice in tabela.indices
            ],
        }

    @staticmethod
    def _dict_para_tabela(dados: dict[str, Any]) -> InfoTabela:
        dados_esquema = dados["esquema"]

        campos = [
            Campo(
                nome=campo["nome"],
                tipo=campo["tipo"],
                nulo=campo.get("nulo", False),
                max_itens=campo.get("max_itens", 4),
            )
            for campo in dados_esquema["campos"]
        ]

        esquema = Esquema(
            nome=dados_esquema["nome"],
            campos=campos,
            chave=dados_esquema["chave"],
        )

        indices = [
            InfoIndice(**indice)
            for indice in dados.get("indices", [])
        ]

        return InfoTabela(
            nome=dados["nome"],
            esquema=esquema,
            org=dados["org"],
            campo_org=dados.get("campo_org"),
            params=dados.get("params", {}),
            nr=dados.get("nr", 0),
            br=dados.get("br", 0),
            fr=dados.get("fr", 0.0),
            tam_registro=dados.get("tam_registro", 0.0),
            V=dados.get("V", {}),
            indices=indices,
        )

    def _ler_cadeia(self, raiz: int) -> tuple[bytes, list[int]]:
        """Lê as páginas encadeadas e recupera o conteúdo serializado."""
        partes: list[bytes] = []
        blocos: list[int] = []
        visitados: set[int] = set()
        atual = raiz

        while atual:
            if atual in visitados:
                raise CorruptedPageError(
                    "Ciclo encontrado na cadeia de páginas do catálogo."
                )

            visitados.add(atual)
            blocos.append(atual)

            with self._bm.page(
                self._fid,
                atual,
                area="catalogo",
            ) as frame:
                dados = frame.data

                if len(dados) < _CABECALHO.size:
                    raise CorruptedPageError(
                        "Página do catálogo menor que o cabeçalho."
                    )

                magic, proximo, tamanho = _CABECALHO.unpack_from(dados)

                if magic != _MAGIC:
                    raise CorruptedPageError(
                        "Identificador inválido em página do catálogo."
                    )

                capacidade = len(dados) - _CABECALHO.size

                if tamanho > capacidade:
                    raise CorruptedPageError(
                        "Conteúdo excede o limite da página do catálogo."
                    )

                inicio = _CABECALHO.size
                partes.append(bytes(dados[inicio : inicio + tamanho]))

            atual = proximo

        return b"".join(partes), blocos

    def _carregar(self, raiz: int) -> None:
        """Reconstrói o estado do catálogo a partir das páginas."""
        conteudo, _ = self._ler_cadeia(raiz)

        try:
            dados = json.loads(conteudo.decode("utf-8"))

            self._tabelas = {
                nome: self._dict_para_tabela(tabela)
                for nome, tabela in dados.get("tabelas", {}).items()
            }
            self._valores = dados.get("valores", {})

        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as erro:
            raise CorruptedPageError(
                "Não foi possível interpretar os dados do catálogo."
            ) from erro

    def _persistir(self) -> None:
        """Grava o estado atual em páginas encadeadas."""
        conteudo = self._serializar()
        tamanho_bloco = self._tamanho_bloco()
        capacidade = tamanho_bloco - _CABECALHO.size

        if capacidade <= 0:
            raise RuntimeError("Tamanho de bloco insuficiente para o catálogo.")

        quantidade = max(1, math.ceil(len(conteudo) / capacidade))

        cabecalho = self._bm.header(self._fid)
        raiz_antiga = cabecalho.get("meta", {}).get("catalog_root", 0)

        if raiz_antiga:
            _, blocos_antigos = self._ler_cadeia(raiz_antiga)
        else:
            blocos_antigos = []

        blocos = blocos_antigos[:quantidade]

        # Aloca páginas adicionais quando o conteúdo cresce.
        while len(blocos) < quantidade:
            with self._bm.fresh_page(
                self._fid,
                area="catalogo",
            ) as frame:
                blocos.append(frame.bno)

        # Escreve o conteúdo e os ponteiros da cadeia.
        for i, bloco in enumerate(blocos):
            inicio = i * capacidade
            parte = conteudo[inicio : inicio + capacidade]
            proximo = blocos[i + 1] if i + 1 < len(blocos) else 0

            pagina = bytearray(tamanho_bloco)
            _CABECALHO.pack_into(
                pagina,
                0,
                _MAGIC,
                proximo,
                len(parte),
            )
            pagina[
                _CABECALHO.size : _CABECALHO.size + len(parte)
            ] = parte

            with self._bm.page(
                self._fid,
                bloco,
                area="catalogo",
                dirty=True,
            ) as frame:
                frame.data[:] = pagina

        # Atualiza a raiz no cabeçalho do arquivo.
        self._bm.set_header(
            self._fid,
            catalog_root=blocos[0],
        )

        # Libera páginas que deixaram de ser necessárias.
        for bloco in blocos_antigos[quantidade:]:
            self._bm.free_page(self._fid, bloco)

    # ---------------------------------------------------------
    # Operações do contrato CatalogAPI
    # ---------------------------------------------------------

    def registrar_tabela(
        self,
        esquema: Esquema,
        org: str,
        params: Mapping | None = None,
        campo_org: str | None = None,
    ) -> InfoTabela:
        tabela = InfoTabela(
            nome=esquema.nome,
            esquema=esquema,
            org=org,
            campo_org=campo_org,
            params=dict(params or {}),
        )

        self._tabelas[esquema.nome] = tabela
        self._persistir()
        return tabela

    def registrar_indice(
        self,
        tabela: str,
        nome: str,
        campo: str,
        tipo: str,
        unique: bool,
        clustering: bool = False,
        primario: bool = False,
        params: Mapping | None = None,
    ) -> InfoIndice:
        info_tabela = self.tabela(tabela)

        indice = InfoIndice(
            nome=nome,
            tabela=tabela,
            campo=campo,
            tipo=tipo,
            unique=unique,
            clustering=clustering,
            primario=primario,
            params=dict(params or {}),
        )

        info_tabela.indices = [
            existente
            for existente in info_tabela.indices
            if existente.campo != campo
        ]
        info_tabela.indices.append(indice)

        self._persistir()
        return indice

    def tabela(self, nome: str) -> InfoTabela:
        return self._tabelas[nome]

    def tabelas(self) -> list[str]:
        return sorted(self._tabelas)

    def remover_tabela(self, nome: str) -> None:
        del self._tabelas[nome]
        self._persistir()

    def atualizar_estatisticas(
        self,
        nome: str,
        nr: int,
        br: int,
        V: Mapping[str, int],
        fr: float,
        tam_registro: float | None = None,
    ) -> None:
        tabela = self.tabela(nome)

        tabela.nr = nr
        tabela.br = br
        tabela.V = dict(V)
        tabela.fr = fr

        if tam_registro is not None:
            tabela.tam_registro = tam_registro

        self._persistir()

    def atualizar_indice(
        self,
        tabela: str,
        campo: str,
        altura: int,
        num_blocks: int,
        fanout: int = 0,
    ) -> None:
        indice = self.tabela(tabela).indice(campo)

        if indice is None:
            raise KeyError(f"{tabela}: sem índice em {campo}")

        indice.altura = altura
        indice.num_blocks = num_blocks
        indice.fanout = fanout

        self._persistir()

    def definir(self, chave: str, valor: Any) -> None:
        # A cópia via JSON também verifica se o valor é serializável.
        valor_copiado = json.loads(json.dumps(valor))
        self._valores[chave] = valor_copiado
        self._persistir()

    def obter(self, chave: str, padrao: Any = None) -> Any:
        return self._valores.get(chave, padrao)
