---
description: Executa a próxima etapa do SEU módulo (ex.: /modulo M3) — uma etapa por sessão
argument-hint: M0 | M1 | M2 | M3 | M4 | M5 | M5J | M6 | M7 | M8 | M9 | M10 | M11 | RC | M12 | M13 | M14 | M15
---

Módulo: **$ARGUMENTS** (se vazio, pergunte ao usuário qual é o módulo dele antes de qualquer coisa).

Siga **exatamente** o "Protocolo de execução" do `CLAUDE.md`, passos 0 a 12:

1. Confira/crie a branch `mod/<módulo>-<nome>` (nome no `progress/<módulo>.md`) e faça `git fetch origin && git merge origin/main`.
2. Leia `progress/<módulo>.md` e pegue a primeira etapa `pendente`/`em andamento`.
3. Leia só a seção `### <módulo>` de `docs/MODULOS.md`, a seção `## <etapa>` de `docs/PLANO_EXECUCAO.md`,
   `docs/INTERFACES.md` e os `contracts.py` relevantes.
4. Antes de codificar, mostre em até 5 linhas: etapa, arquivos que vai criar/editar (só os do módulo) e se vai usar fakes ou implementações reais.
5. Implemente com testes → commit `ia-raw(Exx)` + tag `raw-Exx` → rode testes e corrija (registrando em `ia_log/code_review/<módulo>.md`).
6. Suíte completa verde → decisões em `docs/decisoes/<módulo>.md` → `progress/<módulo>.md` atualizado → commit `feat(Exx)` → push com tags → PR (via `gh`, se disponível).
7. **Pare** ao fim da etapa.

Se o módulo é `RC` (code review cruzado): pergunte qual integrante você é (P1–P5), revise o módulo
indicado na tabela de `docs/MODULOS.md` seguindo a E15, registre achados com prefixo `[RC por Px]`
no `ia_log/code_review/<módulo revisado>.md` e **não corrija** o código alheio — escreva o teste
que reproduz o defeito e deixe a correção para o dono.

Se faltar algo que só o usuário sabe (nomes/DRE, credenciais do GitHub), pergunte em vez de inventar.
