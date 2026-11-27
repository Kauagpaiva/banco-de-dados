"""Gerador determinístico da base universitária (M7 / E09; enunciado §6.4).

Gera registros `dict` conforme `ESQUEMAS` (semente `cfg.seed`, volumes `cfg.volumes`,
parâmetros em `config/modulos/M7.yaml`, chave `datagen`).

Propriedades garantidas (testadas em `tests/test_datagen.py`):
- **Determinismo:** mesma semente + mesmo perfil → mesma sequência de registros. Cada tabela
  tem seu próprio `random.Random(f"{seed}/{tabela}")`, logo gerar uma tabela não altera outra.
- **Fluxo (streaming):** nada é materializado; as chaves saem de permutações afins
  `i -> (a·i + b) mod n` (gcd(a, n) = 1), que embaralham a ordem de inserção sem listas.
- **FKs válidas:** chaves estrangeiras são escolhidas no domínio da tabela referenciada, que é
  uma função fechada do volume (`DRE = base_dre + i`, `numero = base_numero_turma + t`...).
  `CPF` de Aluno é função bijetora do índice, por isso Detalhes_do_Aluno o reproduz sem ler Aluno.
- **CR calibrado:** o CR do aluno de posto r é o quantil (r + ½)/n de uma normal truncada
  (Silberschatz §16.3 usa seletividade = fração de tuplas; aqui ela é **exata**):
  `CR > x1` seleciona round(frac_x1·n) tuplas e `CR < x50` seleciona round(frac_x50·n).
- **Equijoin NOT UNIQUE:** `Turma.professor` e `Aluno.prof_orientador` vêm do mesmo conjunto
  de P = ceil(nr(Turma) / turmas_por_professor) professores; cada professor tem ⌊nT/P⌋ ou
  ⌈nT/P⌉ turmas, e o tamanho da junção ≈ nr(Aluno não nulo) · nT / P.
- **Inscrição sem pares repetidos:** a j-ésima inscrição liga o aluno a = j mod nA à turma
  (off(a) + m·passo) mod nT, m = j div nA < nT, com gcd(passo, nT) = 1.
"""
from __future__ import annotations

import datetime as dt
import math
import random
from functools import lru_cache
from statistics import NormalDist
from typing import Any, Callable, Iterator, Mapping

from src.common.erros import ConfigError
from src.executor.fachada import ESQUEMAS

# --------------------------------------------------------------------------- vocabulário
NOMES = ("Ana", "Bruno", "Carla", "Daniel", "Eduarda", "Felipe", "Gabriela", "Hugo", "Isabela",
         "Joao", "Karina", "Lucas", "Mariana", "Nicolas", "Olivia", "Pedro", "Rafaela", "Samuel",
         "Tatiana", "Vitor", "Yasmin", "Rodrigo", "Beatriz", "Caio", "Larissa", "Mateus")
SOBRENOMES = ("Silva", "Santos", "Oliveira", "Souza", "Lima", "Pereira", "Costa", "Ferreira",
              "Almeida", "Ribeiro", "Carvalho", "Gomes", "Martins", "Araujo", "Barbosa", "Rocha",
              "Dias", "Melo", "Cardoso", "Teixeira", "Moreira", "Mendes", "Nunes", "Freitas")
RUAS = ("Rua das Flores", "Av. Brasil", "Rua do Catete", "Av. Atlantica", "Rua Voluntarios",
        "Estrada do Galeao", "Rua Uruguai", "Av. Presidente Vargas", "Rua Haddock Lobo")
BAIRROS = ("Tijuca", "Botafogo", "Ilha do Governador", "Meier", "Copacabana", "Centro",
           "Barra", "Grajau", "Bonsucesso", "Niteroi")
ESCOLAS = ("Escola Politecnica", "Instituto de Matematica", "Instituto de Fisica",
           "Instituto de Quimica", "Escola de Quimica", "Instituto de Computacao",
           "Faculdade de Letras", "Instituto de Economia")
AREAS = ("Computacao", "Matematica", "Fisica", "Engenharia", "Estatistica", "Quimica",
         "Letras", "Economia", "Biologia", "Geografia")
TEMAS = ("Fundamentos", "Topicos", "Laboratorio", "Introducao", "Metodos", "Teoria",
         "Projeto", "Analise")
CIDADES = ("Rio de Janeiro", "Niteroi", "Sao Paulo", "Belo Horizonte", "Salvador", "Recife",
           "Petropolis", "Campos", "Vitoria", "Curitiba")
DIAS = ("SEG", "TER", "QUA", "QUI", "SEX")
BLOCOS = ("A", "B", "C", "D", "E", "F", "G", "H")
DOMINIOS = ("ufrj.br", "dcc.ufrj.br", "gmail.com", "poli.ufrj.br")


# --------------------------------------------------------------------------- parâmetros
def _params(cfg) -> Mapping[str, Any]:
    try:
        return cfg.raw["datagen"]
    except KeyError as e:  # pragma: no cover - config/modulos/M7.yaml ausente
        raise ConfigError("chave 'datagen' ausente (config/modulos/M7.yaml)") from e


def _volume(cfg, nome: str) -> int:
    n = int(cfg.volumes.get(nome, 0))
    if n < 0:
        raise ConfigError(f"volume negativo para {nome}: {n}")
    return n


def n_professores(cfg) -> int:
    """P = ceil(nr(Turma) / turmas_por_professor), mínimo 1."""
    tpp = int(_params(cfg)["turmas_por_professor"])
    if tpp < 1:
        raise ConfigError("datagen.turmas_por_professor deve ser >= 1")
    return max(1, math.ceil(_volume(cfg, "Turma") / tpp))


def nome_professor(k: int) -> str:
    """Nome único (≤ 40 bytes) do professor de índice k."""
    return (f"Prof {NOMES[k % len(NOMES)]} "
            f"{SOBRENOMES[(k // len(NOMES)) % len(SOBRENOMES)]} {k:05d}")


# --------------------------------------------------------------------------- permutações
def _coprimo(n: int, rng: random.Random) -> int:
    """Multiplicador a ∈ [1, n) com gcd(a, n) = 1 (n = 1 → 1)."""
    if n <= 2:
        return 1
    a = rng.randrange(max(2, n // 3), n)
    while math.gcd(a, n) != 1:
        a = a + 1 if a + 1 < n else 1
    return a


class _Permutacao:
    """Bijeção afim i -> (a·i + b) mod n sobre [0, n) — embaralha sem materializar."""

    def __init__(self, n: int, rng: random.Random):
        self.n = n
        self.a = _coprimo(n, rng)
        self.b = rng.randrange(n) if n > 0 else 0

    def __call__(self, i: int) -> int:
        return (self.a * i + self.b) % self.n


def _rng(cfg, rotulo: str) -> random.Random:
    # semente string: determinística (sha512), independente de PYTHONHASHSEED
    return random.Random(f"{cfg.seed}/{rotulo}")


# --------------------------------------------------------------------------- domínios das chaves
def dre(cfg, i: int) -> int:
    """DRE do aluno de índice i ∈ [0, nr(Aluno))."""
    return int(_params(cfg)["base_dre"]) + i + 1


def codigo_curso(cfg, i: int) -> int:
    return int(_params(cfg)["base_codigo_curso"]) + i


def codigo_disciplina(cfg, i: int) -> int:
    return int(_params(cfg)["base_codigo_disciplina"]) + i


def numero_turma(cfg, i: int) -> int:
    return int(_params(cfg)["base_numero_turma"]) + i


def _digitos_cpf(base9: str) -> str:
    """Acrescenta os 2 dígitos verificadores do CPF (módulo 11)."""
    d = [int(c) for c in base9]
    for peso_ini in (10, 11):
        s = sum(x * p for x, p in zip(d, range(peso_ini, 1, -1)))
        r = (s * 10) % 11
        d.append(0 if r == 10 else r)
    return "".join(map(str, d))


def cpf(cfg, i: int) -> str:
    """CPF (11 dígitos, válido) do aluno de índice i — bijeção sobre os 9 primeiros dígitos."""
    return _digitos_cpf(f"{_perm_cpf(cfg.seed)(i):09d}")


@lru_cache(maxsize=8)
def _perm_cpf(seed: int) -> "_Permutacao":
    return _Permutacao(10 ** 9, random.Random(f"{seed}/cpf"))


# --------------------------------------------------------------------------- CR
def _cr_de_posto(cfg, r: int, n: int) -> float:
    """CR do aluno de posto r ∈ [0, n): quantil (r+½)/n da normal truncada, 4 casas."""
    p = _params(cfg)["cr"]
    nd = NormalDist(float(p["media"]), float(p["desvio"]))
    lo, hi = nd.cdf(float(p["min"])), nd.cdf(float(p["max"]))
    u = lo + (r + 0.5) / n * (hi - lo)
    return round(min(max(nd.inv_cdf(u), float(p["min"])), float(p["max"])), 4)


def limiares_cr(cfg) -> dict[str, float]:
    """{'x1': ..., 'x50': ...} tais que CR > x1 ≈ 1% e CR < x50 ≈ 50% das tuplas de Aluno.

    Como o CR é função monótona do posto, os limiares são pontos médios entre postos vizinhos:
    `CR > x1` pega exatamente os k1 = round(frac_x1·n) maiores e `CR < x50` os k50 menores
    (salvo empate após o arredondamento a 4 casas, que é verificado no teste).
    """
    n = _volume(cfg, "Aluno")
    p = _params(cfg)["cr"]
    if n < 2:
        return {"x1": float(p["max"]), "x50": float(p["min"])}
    k1 = min(max(round(float(p["frac_x1"]) * n), 1), n - 1)
    k50 = min(max(round(float(p["frac_x50"]) * n), 1), n - 1)
    x1 = (_cr_de_posto(cfg, n - k1 - 1, n) + _cr_de_posto(cfg, n - k1, n)) / 2
    x50 = (_cr_de_posto(cfg, k50 - 1, n) + _cr_de_posto(cfg, k50, n)) / 2
    return {"x1": round(x1, 5), "x50": round(x50, 5)}


# --------------------------------------------------------------------------- auxiliares de valor
def _nome(rng: random.Random) -> str:
    return (f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)} "
            f"{rng.choice(SOBRENOMES)}")


def _endereco(rng: random.Random) -> str:
    return f"{rng.choice(RUAS)}, {rng.randint(1, 3999)} - {rng.choice(BAIRROS)}"


def _telefone(rng: random.Random) -> str:
    return f"(21) 9{rng.randint(0, 9999):04d}-{rng.randint(0, 9999):04d}"


def _data(rng: random.Random, ini: dt.date, fim: dt.date) -> dt.date:
    return ini + dt.timedelta(days=rng.randrange((fim - ini).days + 1))


# --------------------------------------------------------------------------- tabelas
def _curso(cfg, rng: random.Random) -> Iterator[dict]:
    n = _volume(cfg, "Curso")
    P = n_professores(cfg)
    perm = _Permutacao(n, rng)
    for j in range(n):
        i = perm(j)
        cod = codigo_curso(cfg, i)
        area = AREAS[i % len(AREAS)]
        yield {
            "codigo": cod,
            "nome": f"Bacharelado em {area} {cod}",
            "escola": ESCOLAS[i % len(ESCOLAS)],
            "carga_horaria": rng.choice((2400, 3000, 3200, 3600, 4000)),
            "prof_coordenador": nome_professor(rng.randrange(P)),
            "email": f"secretaria{cod}@ufrj.br",
            "endereco_secretaria": f"CT Bloco {rng.choice(BLOCOS)}, sala {rng.randint(100, 299)}",
            "telefones": [_telefone(rng) for _ in range(rng.randint(1, 3))],
        }


def _disciplina(cfg, rng: random.Random) -> Iterator[dict]:
    n, nc = _volume(cfg, "Disciplina"), _volume(cfg, "Curso")
    if n and not nc:
        raise ConfigError("Disciplina exige Curso > 0 (FK cod_curso)")
    perm = _Permutacao(n, rng)
    for j in range(n):
        i = perm(j)
        cod = codigo_disciplina(cfg, i)
        npre = rng.randint(0, min(4, i))
        pre = sorted({str(codigo_disciplina(cfg, rng.randrange(i))) for _ in range(npre)})
        yield {
            "codigo": cod,
            "cod_curso": codigo_curso(cfg, rng.randrange(nc)),
            "nome": f"{rng.choice(TEMAS)} de {rng.choice(AREAS)} {cod}",
            "ementa": (f"Disciplina {cod}: {rng.choice(TEMAS).lower()} de "
                       f"{rng.choice(AREAS).lower()}, com aulas teoricas e exercicios."),
            "carga_horaria": rng.choice((30, 45, 60, 90)),
            "pre_requisitos": pre,
        }


def _turma(cfg, rng: random.Random) -> Iterator[dict]:
    p = _params(cfg)
    n, nd = _volume(cfg, "Turma"), _volume(cfg, "Disciplina")
    if n and not nd:
        raise ConfigError("Turma exige Disciplina > 0 (FK cod_disciplina)")
    P = n_professores(cfg)
    perm = _Permutacao(n, rng)
    ano_min, ano_max = int(p["ano_min"]), int(p["ano_max"])
    for j in range(n):
        t = perm(j)
        h = rng.choice((8, 10, 13, 15, 18))
        yield {
            "numero": numero_turma(cfg, t),
            "cod_disciplina": codigo_disciplina(cfg, rng.randrange(nd)),
            "semestre": rng.randint(1, 2),
            "ano": rng.randint(ano_min, ano_max),
            "horario": f"{rng.choice(DIAS)} {h:02d}:00-{h + 2:02d}:00",
            "sala": f"{rng.choice(BLOCOS)}-{rng.randint(100, 330)}",
            # t mod P: cada professor com ⌊nT/P⌋ ou ⌈nT/P⌉ turmas (cardinalidade controlada)
            "professor": nome_professor(t % P),
        }


def _aluno(cfg, rng: random.Random) -> Iterator[dict]:
    p = _params(cfg)
    n, nc = _volume(cfg, "Aluno"), _volume(cfg, "Curso")
    if n and not nc:
        raise ConfigError("Aluno exige Curso > 0 (FK cod_curso)")
    P = n_professores(cfg)
    frac_nulo = float(p["frac_sem_orientador"])
    ordem = _Permutacao(n, rng)          # ordem de emissão
    posto = _Permutacao(n, rng)          # posto do CR de cada aluno
    nasc_ini, nasc_fim = dt.date(1990, 1, 1), dt.date(2008, 12, 31)
    for j in range(n):
        i = ordem(j)
        d = dre(cfg, i)
        primeiro = rng.choice(NOMES)
        nome = f"{primeiro} {rng.choice(SOBRENOMES)} {rng.choice(SOBRENOMES)}"
        emails = [f"{primeiro.lower()}.{d}@{DOMINIOS[k]}"
                  for k in range(rng.randint(1, 3))]
        yield {
            "CPF": cpf(cfg, i),
            "DRE": d,
            "nome": nome,
            "data_nasc": _data(rng, nasc_ini, nasc_fim),
            "sexo": rng.choice("FM"),
            "endereco": _endereco(rng),
            "emails": emails,
            "cod_curso": codigo_curso(cfg, rng.randrange(nc)),
            "CR": _cr_de_posto(cfg, posto(i), n),
            "prof_orientador": None if rng.random() < frac_nulo else nome_professor(rng.randrange(P)),
        }


def _detalhes(cfg, rng: random.Random) -> Iterator[dict]:
    p = _params(cfg)
    n, na = _volume(cfg, "Detalhes_do_Aluno"), _volume(cfg, "Aluno")
    if n > na:
        raise ConfigError(f"Detalhes_do_Aluno ({n}) > Aluno ({na}): CPF é 1:1 UNIQUE")
    perm = _Permutacao(na, rng)
    f_pai, f_obs = float(p["frac_sem_pai"]), float(p["frac_sem_obs"])
    for j in range(n):
        i = perm(j)
        yield {
            "CPF": cpf(cfg, i),
            "nome_mae": _nome(rng),
            "nome_pai": None if rng.random() < f_pai else _nome(rng),
            "telefone": _telefone(rng),
            "naturalidade": rng.choice(CIDADES),
            "renda_familiar": round(rng.lognormvariate(8.3, 0.7), 2),
            "observacoes": None if rng.random() < f_obs else
            f"Bolsista desde {rng.randint(2019, 2026)}; atendimento {rng.choice(('PAE', 'PNAES', 'nenhum'))}.",
        }


def _inscricao(cfg, rng: random.Random) -> Iterator[dict]:
    p = _params(cfg)
    n, na, nt = (_volume(cfg, "Inscricao_Aluno_Turma"), _volume(cfg, "Aluno"),
                 _volume(cfg, "Turma"))
    if n > na * nt:
        raise ConfigError(f"Inscricao ({n}) > Aluno·Turma ({na * nt}): pares (DRE, turma) repetiriam")
    frac_nula = float(p["frac_media_nula"])
    ordem = _Permutacao(n, rng)
    passo = _coprimo(nt, rng)
    off = _Permutacao(nt, rng)
    for j0 in range(n):
        j = ordem(j0)
        a, m = j % na, j // na                      # m < nt garantido por n <= na·nt
        t = (off(a % nt) + a // nt + m * passo) % nt
        freq = round(min(1.0, max(0.0, rng.gauss(0.85, 0.12))), 3)
        media = None if rng.random() < frac_nula else round(min(10.0, max(0.0, rng.gauss(6.5, 2.0))), 2)
        yield {
            "DRE": dre(cfg, a),
            "numero_turma": numero_turma(cfg, t),
            "frequencia": freq,
            "media_final": media,
        }


_GERADORES: dict[str, Callable[[Any, random.Random], Iterator[dict]]] = {
    "Curso": _curso,
    "Disciplina": _disciplina,
    "Turma": _turma,
    "Aluno": _aluno,
    "Detalhes_do_Aluno": _detalhes,
    "Inscricao_Aluno_Turma": _inscricao,
}


def gerar_tabela(cfg, nome: str) -> Iterator[dict]:
    """Registros da tabela `nome` no perfil de `cfg` (mesma saída para a mesma semente)."""
    if nome not in _GERADORES or nome not in ESQUEMAS:
        raise KeyError(f"tabela desconhecida: {nome!r} (válidas: {sorted(_GERADORES)})")
    return _GERADORES[nome](cfg, _rng(cfg, nome))
