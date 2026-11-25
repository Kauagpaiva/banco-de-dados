"""E01 — Gerente de Arquivos (Silberschatz 12.3, 12.6, 13.2)."""
import pytest

from src.common.config import load_config
from src.common.erros import StorageError
from src.common.tipos import CHAVES_IO
from src.storage.file_manager import FileManager


@pytest.fixture
def cfg():
    return load_config("teste")


@pytest.fixture
def fm(cfg, tmp_path):
    f = FileManager(cfg, tmp_path)
    yield f
    f.close_all()


def _bloco(fm, valor: int) -> bytes:
    return valor.to_bytes(4, "little") * (fm.block_size // 4)


def _novo_com(fm, nome, n):
    fid = fm.create(nome, "heap")
    bnos = [fm.allocate_block(fid) for _ in range(n)]
    for b in bnos:
        fm.write_block(fid, b, _bloco(fm, b))
    return fid, bnos


# ------------------------------------------------------------------ escrita/leitura
def test_escreve_e_le_n_blocos(fm):
    fid, bnos = _novo_com(fm, "t", 20)
    assert bnos == list(range(1, 21))             # dados começam no bloco 1
    for b in bnos:
        d = fm.read_block(fid, b)
        assert isinstance(d, bytearray) and len(d) == fm.block_size
        assert bytes(d) == _bloco(fm, b)
    assert fm.num_blocks(fid) == 20


def test_dado_menor_que_bloco_e_completado_com_zeros(fm):
    fid = fm.create("t", "heap")
    b = fm.allocate_block(fid)
    fm.write_block(fid, b, b"abc")
    d = fm.read_block(fid, b)
    assert d[:3] == b"abc" and not any(d[3:]) and len(d) == fm.block_size


def test_dado_maior_que_bloco_erro(fm):
    fid = fm.create("t", "heap")
    b = fm.allocate_block(fid)
    with pytest.raises(StorageError):
        fm.write_block(fid, b, bytes(fm.block_size + 1))


@pytest.mark.parametrize("bno", [0, -1, 2, 99])
def test_bloco_fora_do_alocado_erro(fm, bno):
    fid = fm.create("t", "heap")
    fm.allocate_block(fid)                        # só o bloco 1 em uso
    with pytest.raises(StorageError):
        fm.read_block(fid, bno)
    with pytest.raises(StorageError):
        fm.write_block(fid, bno, b"x")


def test_sem_cache_de_blocos(fm):
    """Duas leituras do mesmo bloco = 2 I/Os (o FileManager não guarda blocos)."""
    fid, b = _novo_com(fm, "t", 1)
    fm.reset_io_stats()
    fm.read_block(fid, b[0])
    fm.read_block(fid, b[0])
    assert fm.io_stats()["reads"] == 2


# ------------------------------------------------------------------ extents e lista livre
def test_alocacao_em_extents(fm, cfg, tmp_path):
    assert cfg.extent_blocks == 8
    fid = fm.create("t", "heap")
    for _ in range(9):
        fm.allocate_block(fid)
    h = fm.header(fid)
    assert h["extents"] == 2 and h["num_alocados"] == 16 and h["extent"] == 8
    assert fm.num_blocks(fid) == 9
    # arquivo do SO = cabeçalho + 2 extents
    assert (tmp_path / "t.dat").stat().st_size == (1 + 16) * fm.block_size


def test_extent_nao_cresce_antes_de_encher(fm):
    fid = fm.create("t", "heap")
    for i in range(8):
        fm.allocate_block(fid)
        assert fm.header(fid)["extents"] == 1, i


def test_reuso_de_bloco_liberado(fm):
    fid, b = _novo_com(fm, "t", 5)
    fm.free_block(fid, b[1])
    fm.free_block(fid, b[3])
    assert fm.num_blocks(fid) == 3
    assert fm.header(fid)["livre"] == b[3]        # cabeça da lista = último liberado
    with pytest.raises(StorageError):              # bloco livre não pode ser lido
        fm.read_block(fid, b[1])
    with pytest.raises(StorageError):              # nem liberado duas vezes
        fm.free_block(fid, b[1])
    assert fm.allocate_block(fid) == b[3]          # LIFO pela lista encadeada
    assert fm.allocate_block(fid) == b[1]
    assert fm.header(fid)["livre"] == 0
    assert fm.allocate_block(fid) == 6             # lista vazia → próximo bloco novo
    assert fm.num_blocks(fid) == 6


def test_lista_livre_custa_io(fm):
    """Liberar grava o ponteiro no bloco (1 escrita); reusar lê o próximo (1 leitura)."""
    fid, b = _novo_com(fm, "t", 3)
    fm.reset_io_stats()
    fm.free_block(fid, b[0])
    assert fm.io_stats()["writes"] == 1
    fm.allocate_block(fid)
    assert fm.io_stats()["reads"] == 1
    fm.reset_io_stats()
    fm.allocate_block(fid)                         # bloco novo: nenhum I/O
    assert fm.io_stats()["reads"] == fm.io_stats()["writes"] == 0


# ------------------------------------------------------------------ seek / estatísticas
def test_seq_vs_aleatorio_sequencia_conhecida(fm):
    """Acessos 0..: 1,2,3,8,9,4 (blocos de dados; o enunciado da E01 usa 0,1,2,7,8,3 com
    numeração a partir de 0) → seeks no 1º (1), em 8 (salto) e em 4 (volta) = 3 seeks."""
    fid, _ = _novo_com(fm, "t", 9)
    outro = fm.create("u", "heap")                # leva o braço para outro arquivo
    ub = fm.allocate_block(outro)
    fm.write_block(outro, ub, b"x")
    fm.reset_io_stats()
    for b in (1, 2, 3, 8, 9, 4):
        fm.read_block(fid, b)
    st = fm.io_stats()
    assert st["reads"] == 6
    assert st["rand_reads"] == 3 and st["seq_reads"] == 3
    assert fm.io_stats(fid) == st
    assert fm.io_stats(outro)["reads"] == 0


def test_braco_global_entre_arquivos(fm):
    """Intercalar dois arquivos quebra a sequencialidade (braço único)."""
    a, _ = _novo_com(fm, "a", 3)
    b, _ = _novo_com(fm, "b", 3)
    fm.reset_io_stats()
    for i in (1, 2, 3):
        fm.read_block(a, i)
        fm.read_block(b, i)
    st = fm.io_stats()
    assert st["reads"] == 6 and st["rand_reads"] == 6


def test_escritas_sequenciais(fm):
    fid = fm.create("t", "heap")
    bnos = [fm.allocate_block(fid) for _ in range(4)]
    fm.reset_io_stats()
    for b in bnos:
        fm.write_block(fid, b, b"y")
    st = fm.io_stats()
    assert st["writes"] == 4 and st["seq_writes"] == 3 and st["rand_writes"] == 1


def test_chaves_e_reset(fm):
    fid, _ = _novo_com(fm, "t", 2)
    assert set(fm.io_stats()) == set(CHAVES_IO)
    assert set(fm.io_stats(fid)) == set(CHAVES_IO)
    fm.reset_io_stats()
    assert all(v == 0 for v in fm.io_stats().values())
    assert all(v == 0 for v in fm.io_stats(fid).values())


# ------------------------------------------------------------------ cabeçalho e persistência
def test_cabecalho_e_meta(fm):
    fid = fm.create("t", "bplus", {"raiz": 1, "campo": "ID"})
    fm.set_header(fid, raiz=7, altura=2)
    h = fm.header(fid)
    assert h["tipo_org"] == "bplus"
    assert h["meta"] == {"raiz": 7, "campo": "ID", "altura": 2}
    h["meta"]["raiz"] = 99                         # header() devolve cópia
    assert fm.header(fid)["meta"]["raiz"] == 7


def test_meta_grande_demais_erro(fm):
    fid = fm.create("t", "heap")
    with pytest.raises(StorageError):
        fm.set_header(fid, lixo="x" * fm.block_size)
    assert "lixo" not in fm.header(fid)["meta"]    # não alterou
    with pytest.raises(StorageError):
        fm.create("u", "heap", {"lixo": "x" * fm.block_size})
    assert not fm.exists("u")


def test_cabecalho_conta_io_no_open_e_close(fm):
    fid, _ = _novo_com(fm, "t", 2)
    fm.reset_io_stats()
    fm.close(fid)                                  # cabeçalho alterado → 1 escrita
    assert fm.io_stats()["writes"] == 1
    fid = fm.open("t")                             # leitura do cabeçalho → 1 leitura
    assert fm.io_stats()["reads"] == 1
    fm.close(fid)                                  # nada mudou → sem escrita
    assert fm.io_stats()["writes"] == 1


def test_persistencia_apos_reabrir(cfg, tmp_path):
    fm1 = FileManager(cfg, tmp_path)
    fid, b = _novo_com(fm1, "t", 10)
    fm1.free_block(fid, b[4])
    fm1.free_block(fid, b[7])
    fm1.set_header(fid, raiz=3)
    fm1.close(fid)

    fm2 = FileManager(cfg, tmp_path)               # "outro processo"
    fid = fm2.open("t")
    h = fm2.header(fid)
    assert h["tipo_org"] == "heap" and h["meta"] == {"raiz": 3}
    assert h["num_alocados"] == 16 and fm2.num_blocks(fid) == 8
    for x in b:
        if x in (b[4], b[7]):
            continue
        assert bytes(fm2.read_block(fid, x)) == _bloco(fm2, x)
    assert fm2.allocate_block(fid) == b[7]         # lista livre sobreviveu
    assert fm2.allocate_block(fid) == b[4]
    fm2.close_all()


def test_create_open_exists_delete(fm):
    assert not fm.exists("t")
    with pytest.raises(StorageError):
        fm.open("t")
    fid = fm.create("t", "heap")
    assert fm.exists("t")
    assert fm.open("t") == fid                     # já aberto → mesmo fid
    with pytest.raises(StorageError):
        fm.create("t", "heap")
    fm.delete("t")                                 # fecha antes de apagar
    assert not fm.exists("t")
    with pytest.raises(StorageError):
        fm.read_block(fid, 1)
    with pytest.raises(StorageError):
        fm.delete("t")


def test_fid_fechado_erro(fm):
    fid = fm.create("t", "heap")
    fm.close(fid)
    fm.close(fid)                                  # idempotente
    with pytest.raises(StorageError):
        fm.allocate_block(fid)


@pytest.mark.parametrize("nome", ["", "../x", "a/b", "a\\b", ".oculto"])
def test_nome_invalido(fm, nome):
    with pytest.raises(StorageError):
        fm.create(nome, "heap")


def test_tipo_org_longo_erro(fm):
    with pytest.raises(StorageError):
        fm.create("t", "x" * 17)


def test_block_size_diferente_detectado(cfg, tmp_path):
    fm1 = FileManager(cfg, tmp_path)
    fid, _ = _novo_com(fm1, "t", 1)
    fm1.close_all()
    outro = load_config("teste", overrides={"disco.block_size": 2048})
    fm2 = FileManager(outro, tmp_path)
    with pytest.raises(StorageError):
        fm2.open("t")


def test_cabecalho_corrompido_detectado(cfg, tmp_path):
    fm1 = FileManager(cfg, tmp_path)
    fm1.close(fm1.create("t", "heap"))
    caminho = tmp_path / "t.dat"
    dados = bytearray(caminho.read_bytes())
    dados[0:4] = b"XXXX"
    caminho.write_bytes(bytes(dados))
    with pytest.raises(StorageError):
        FileManager(cfg, tmp_path).open("t")


def test_base_dir_padrao_e_perfil_dir(tmp_path):
    cfg = load_config("teste", overrides={"disco.data_dir": str(tmp_path / "d")})
    fm = FileManager(cfg)
    fm.close(fm.create("t", "heap"))
    assert (cfg.perfil_dir / "t.dat").exists()
