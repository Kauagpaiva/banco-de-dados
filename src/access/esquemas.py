"""Os 6 esquemas da base universitária (enunciado §6.4, E09) — contrato M0, compartilhado por M2, M7, M8.

Convenções de valor (ver `src.access.contracts`): códigos/DRE/números são `int` (ordenáveis e
baratos para hash/B+); CPF é `char(11)` só com dígitos; datas são `datetime.date`;
listas são `list[str]` com no máximo `max_itens` itens.
FKs: Aluno.cod_curso -> Curso.codigo; Disciplina.cod_curso -> Curso.codigo;
Turma.cod_disciplina -> Disciplina.codigo; Inscricao.DRE -> Aluno.DRE;
Inscricao.numero_turma -> Turma.numero; Detalhes_do_Aluno.CPF -> Aluno.CPF (1:1, UNIQUE).
Equijoin NOT UNIQUE: Aluno.prof_orientador = Turma.professor (cardinalidade controlada no gerador).
"""
from __future__ import annotations

from src.access.contracts import Campo, Esquema

ALUNO = Esquema("Aluno", (
    Campo("CPF", "char(11)"),
    Campo("DRE", "int"),
    Campo("nome", "varchar(60)"),
    Campo("data_nasc", "date"),
    Campo("sexo", "char(1)"),
    Campo("endereco", "varchar(100)"),
    Campo("emails", "list[varchar(40)]", max_itens=3),
    Campo("cod_curso", "int"),
    Campo("CR", "float"),
    Campo("prof_orientador", "varchar(40)", nulo=True),
), chave=("DRE",))

CURSO = Esquema("Curso", (
    Campo("codigo", "int"),
    Campo("nome", "varchar(60)"),
    Campo("escola", "varchar(40)"),
    Campo("carga_horaria", "int"),
    Campo("prof_coordenador", "varchar(40)"),
    Campo("email", "varchar(40)"),
    Campo("endereco_secretaria", "varchar(100)"),
    Campo("telefones", "list[varchar(15)]", max_itens=3),
), chave=("codigo",))

DISCIPLINA = Esquema("Disciplina", (
    Campo("codigo", "int"),
    Campo("cod_curso", "int"),
    Campo("nome", "varchar(60)"),
    Campo("ementa", "varchar(200)"),
    Campo("carga_horaria", "int"),
    Campo("pre_requisitos", "list[varchar(10)]", max_itens=4),
), chave=("codigo",))

TURMA = Esquema("Turma", (
    Campo("numero", "int"),
    Campo("cod_disciplina", "int"),
    Campo("semestre", "int"),
    Campo("ano", "int"),
    Campo("horario", "varchar(20)"),
    Campo("sala", "varchar(10)"),
    Campo("professor", "varchar(40)"),
), chave=("numero",))

INSCRICAO = Esquema("Inscricao_Aluno_Turma", (
    Campo("DRE", "int"),
    Campo("numero_turma", "int"),
    Campo("frequencia", "float"),
    Campo("media_final", "float", nulo=True),
), chave=("DRE", "numero_turma"))

DETALHES = Esquema("Detalhes_do_Aluno", (
    Campo("CPF", "char(11)"),
    Campo("nome_mae", "varchar(60)"),
    Campo("nome_pai", "varchar(60)", nulo=True),
    Campo("telefone", "varchar(15)"),
    Campo("naturalidade", "varchar(40)"),
    Campo("renda_familiar", "float"),
    Campo("observacoes", "varchar(200)", nulo=True),
), chave=("CPF",))

#: nome -> Esquema (mesmos nomes das chaves de `cfg.volumes`).
ESQUEMAS: dict[str, Esquema] = {e.nome: e for e in
                                (CURSO, DISCIPLINA, TURMA, ALUNO, DETALHES, INSCRICAO)}

#: FKs: (tabela, campo) -> (tabela referenciada, campo).
FKS: dict[tuple[str, str], tuple[str, str]] = {
    ("Aluno", "cod_curso"): ("Curso", "codigo"),
    ("Disciplina", "cod_curso"): ("Curso", "codigo"),
    ("Turma", "cod_disciplina"): ("Disciplina", "codigo"),
    ("Inscricao_Aluno_Turma", "DRE"): ("Aluno", "DRE"),
    ("Inscricao_Aluno_Turma", "numero_turma"): ("Turma", "numero"),
    ("Detalhes_do_Aluno", "CPF"): ("Aluno", "CPF"),
}
