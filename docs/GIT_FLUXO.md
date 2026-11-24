# Fluxo de trabalho no GitHub (grupo de 5, cada um com sua IA)

Repositório: https://github.com/Kauagpaiva/banco-de-dados

## 1. Preparação (uma vez por pessoa)
1. O dono do repositório adiciona os 4 colegas como colaboradores
   (GitHub › Settings › Collaborators) — ou usa o GitHub Classroom da disciplina.
2. Recomendado: proteger a `main` (Settings › Branches › *Require a pull request* +
   *Require status checks: testes*). Assim nada entra em `main` sem PR e CI verde.
3. Cada integrante:
   ```powershell
   git clone https://github.com/Kauagpaiva/banco-de-dados.git
   ```
   ```powershell
   cd banco-de-dados; python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt
   ```
   ```powershell
   git config user.name "Seu Nome Completo"; git config user.email "seu-email@poli.ufrj.br"
   ```
   O `user.name` define o arquivo do seu log de prompts (`ia_log/prompts/<seu-nome>.md`).
4. Abrir o Claude Code **na pasta do repositório** (app, VS Code ou `claude` no terminal).
   O `CLAUDE.md`, o comando `/modulo` e o hook de prompts são carregados de lá.

## 2. Ciclo de trabalho de cada pessoa
```
/modulo M3            ← a IA faz 1 etapa, testa, commita, faz push e abre/pede o PR
(revisar o PR no GitHub, CI verde → merge)
/clear  (ou nova sessão)
/modulo M3            ← próxima etapa
```
- Uma etapa = um PR pequeno. Quanto menor o PR, mais fácil o merge.
- **Leia o código que a IA gerou antes de aprovar o PR**: a nota do trabalho vem da capacidade
  de explicar e corrigir os defeitos do código gerado.
- Quem aprova o PR de um módulo: preferencialmente o revisor indicado no code review cruzado
  (`docs/MODULOS.md`), ou o líder.

## 3. Evitando conflitos
| Situação | Regra |
|---|---|
| Arquivos de código | cada módulo só mexe nos seus (lista em `docs/MODULOS.md`) |
| Progresso, decisões, code review, prompts | um arquivo por módulo/pessoa (`progress/Mx.md`, `docs/decisoes/Mx.md`, `ia_log/code_review/Mx.md`, `ia_log/prompts/<autor>.md`) |
| Contratos (`src/*/contracts.py`), `tests/conftest.py`, `tests/fakes/`, `config/base.yaml`, `requirements.txt`, `docs/INTERFACES.md` | só o líder (M0) altera, via PR; os demais pedem por issue |
| Configuração nova de um módulo | `config/modulos/Mx.yaml` |
| `PROGRESS.md` (quadro geral) | só o líder, ao integrar |

Se ainda assim houver conflito ao rodar `git merge origin/main`: mantenha a versão de `main` em
arquivos que não são seus e peça à IA para resolver apenas os arquivos do seu módulo.

## 4. Mudança de contrato (quando a interface congelada não serve)
1. A IA para e escreve o pedido em `progress/Mx.md` ("Pedidos de mudança de contrato").
2. Você abre uma *issue* no GitHub marcando o líder e os módulos afetados.
3. O líder faz o PR mudando contrato + fakes + `docs/INTERFACES.md`; todos fazem `git merge origin/main`.

## 5. Tags de código bruto (Post-Mortem)
- Toda etapa cria a tag `raw-Exx` com o código **antes** das correções.
- Envie-as: `git push origin --tags` (o protocolo da IA já faz isso).
- Para ver o que mudou depois do código bruto: `git diff raw-E05 main -- src/access/bplus.py`.

## 6. Integração (líder)
- Ordem de merge da Fase 1: M0 → M2 (record/page) → M1 → M3, M4 → M5 → M5J → M6, M7.
- Após o merge de M1 e de M2, avisar o grupo para atualizar a branch: os testes passam a usar
  as implementações reais no lugar dos fakes. As falhas que surgirem aí vão para o code review.
- Atualizar o quadro de `PROGRESS.md` e os "Marcos de integração".
