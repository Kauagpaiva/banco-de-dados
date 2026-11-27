
from src.access.catalog import Catalog
from src.access.esquemas import ESQUEMAS


def test_catalogo_registra_tabela_e_reabre(bm):
    catalogo = Catalog(bm, nome="teste_catalogo")

    esquema = ESQUEMAS["Aluno"]

    catalogo.registrar_tabela(
        esquema=esquema,
        org="heap",
    )

    assert "Aluno" in catalogo.tabelas()
    assert catalogo.tabela("Aluno").org == "heap"

    bm.close(catalogo._fid)

    catalogo_reaberto = Catalog(bm, nome="teste_catalogo")

    assert "Aluno" in catalogo_reaberto.tabelas()
    assert catalogo_reaberto.tabela("Aluno").esquema.nome == "Aluno"


def test_catalogo_registra_indice_e_atualiza_estatisticas(bm):
    catalogo = Catalog(bm, nome="teste_catalogo_indice")

    esquema = ESQUEMAS["Aluno"]
    catalogo.registrar_tabela(esquema, org="heap")

    catalogo.registrar_indice(
        tabela="Aluno",
        nome="idx_cpf",
        campo="CPF",
        tipo="bplus",
        unique=True,
        primario=True,
    )

    catalogo.atualizar_indice(
        tabela="Aluno",
        campo="CPF",
        altura=2,
        num_blocks=5,
        fanout=10,
    )

    catalogo.atualizar_estatisticas(
        nome="Aluno",
        nr=100,
        br=10,
        V={"CPF": 100},
        fr=0.8,
        tam_registro=120.0,
    )

    tabela = catalogo.tabela("Aluno")
    indice = tabela.indice("CPF")

    assert indice is not None
    assert indice.altura == 2
    assert indice.num_blocks == 5
    assert indice.fanout == 10

    assert tabela.nr == 100
    assert tabela.br == 10
    assert tabela.V["CPF"] == 100
    assert tabela.fr == 0.8
    assert tabela.tam_registro == 120.0


def test_catalogo_guarda_valores(bm):
    catalogo = Catalog(bm, nome="teste_catalogo_valores")

    catalogo.definir("versao", 1)
    catalogo.definir("configuracao", {"idioma": "pt-BR"})

    assert catalogo.obter("versao") == 1
    assert catalogo.obter("configuracao") == {"idioma": "pt-BR"}
    assert catalogo.obter("inexistente", "padrão") == "padrão"


def test_catalogo_remove_tabela(bm):
    catalogo = Catalog(bm, nome="teste_catalogo_remocao")

    catalogo.registrar_tabela(ESQUEMAS["Aluno"], org="heap")
    catalogo.remover_tabela("Aluno")

    assert "Aluno" not in catalogo.tabelas()
