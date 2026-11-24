---
description: Executa a próxima etapa pendente do plano da bancada de teste (uma etapa por sessão)
---

Execute a próxima etapa do projeto seguindo **exatamente** o "Protocolo de execução" do `CLAUDE.md`:

1. Leia `PROGRESS.md` e identifique a etapa atual (primeira `em andamento` ou, se não houver, primeira `pendente`).
2. Leia somente a seção dessa etapa em `docs/PLANO_EXECUCAO.md` (Grep por `^## Exx` e Read com offset/limit) e `docs/INTERFACES.md`.
3. Antes de codificar, mostre em até 5 linhas o que vai fazer nesta etapa.
4. Implemente com testes, fazendo o commit `ia-raw(Exx)` + tag `raw-Exx` antes de rodar os testes.
5. Corrija até a etapa e a suíte completa passarem, registrando cada defeito em `ia_log/code_review.md`.
6. Atualize `docs/INTERFACES.md`, `docs/DECISOES.md` e `PROGRESS.md` (status + nota de handoff), faça o commit final e **pare**.

Se faltar uma informação que só o usuário tem (ex.: nomes/DRE), pergunte em vez de inventar.
Argumento opcional: $ARGUMENTS (ex.: um número de etapa para forçar, como `E07`).
