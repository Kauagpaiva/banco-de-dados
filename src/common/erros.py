"""Exceções comuns a todas as camadas."""


class BancadaError(Exception):
    """Raiz das exceções da bancada."""


class ConfigError(BancadaError):
    """Configuração inválida."""


class StorageError(BancadaError):
    """Erro na camada de armazenamento (arquivos/buffer)."""


class BufferFullError(StorageError):
    """Nenhum quadro livre/expulsável na área do buffer (todos pinados)."""


class RecordError(BancadaError):
    """Registro/página malformado (offset fora do bloco, tamanho inválido...)."""


class MemoryBudgetError(BancadaError):
    """Operador do executor tentou exceder as M páginas de trabalho."""


class CorruptedPageError(RecordError):
    """Offset/tamanho lido da página aponta para fora do bloco (página corrompida)."""


class OperacaoNaoSuportada(BancadaError):
    """A organização/índice não oferece a operação pedida (ex.: find_ordered em Heap)."""


class ChaveDuplicadaError(BancadaError):
    """Inserção de chave repetida em estrutura UNIQUE."""
