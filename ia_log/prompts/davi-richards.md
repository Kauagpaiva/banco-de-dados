# Log de prompts — Davi Richards Nascimento (P3)

> **Módulos:** M3 (Árvore B+ primária, E05–E06) e M14 (Relatório de IA + POST_MORTEM, E19)
> **Ferramenta:** Claude Code (modelo Claude Sonnet 5.5), seguindo o protocolo do `CLAUDE.md`
> **Tipo de registro:** reconstruído a partir da conversa da sessão (não havia hook de log de prompts
> ativo nesta conta). Os prompts abaixo são **literais** (erros de digitação preservados); entre colchetes,
> o que a IA fez em resposta. Datas: 27–28/11/2026.

## M3 — Árvore B+ primária

| # | Prompt (literal) | Resposta / efeito |
|---|---|---|
| 1 | `faca o M3 do arquivo progress.md` | A IA localizou `PROGRESS.md`, aplicou o protocolo e executou **só a E05** (busca, faixa, inserção/split) — interpretação restritiva: o protocolo manda 1 etapa por sessão. Código bruto: tag `raw-E05`. |
| 2 | `ta feito o m3 da parte 1?` | Confirmação de que a E05 estava feita e enviada à branch `mod/M3-bplus`; E06 pendente. |
| 3 | `envia para o github` | Verificado que branch e tag já estavam no remoto; `gh` local não era o GitHub CLI → link para abrir o PR. |
| 4 | `esta ja no github?:` | Confirmação via `git ls-remote`. |
| 5 | `recebi um email q deu erro, confere` | A IA informou que não tem acesso ao Gmail e pediu o texto do erro. |
| 6 | `commita direto na main, sem o pr` | Merge fast-forward de `mod/M3-bplus` em `main` e push (autorizado explicitamente). |
| 7 | `eu fiquei responsavel por fazer o m3, tudo o que esta nesse modulo foi feito?` | A IA reconheceu que só metade (E05) estava pronta; listou o que faltava da E06. |
| 8 | `faca tudo do m3 entao` | Executada a **E06** (remoção, NOT UNIQUE, bulk load, reorganize) + testes (hypothesis etc.). Tag `raw-E06`. |
| 9 | `sim` (ao "faço o merge direto na main?") | Merge/push do M3 completo em `main`. |
| 10 | `por que voce nao fez completo de uma vez??` | A IA admitiu o erro de interpretação (seguiu o protocolo "1 etapa por sessão" sem perguntar). |
| 11 | *(mensagem do grupo colada, sem texto do autor)* — CI do M11 falhando em `delete`/`reorganize` do B+ | A IA explicou: o M3 já estava na `main`; a branch do M11 só precisava de `git merge origin/main`. |
| 12 | `autaliza o codigo` | `git fetch` + fast-forward da `main`; reexecução dos testes do B+ com o `RecordCodec`/`SlottedPage` reais do M2. |

## M14 — Relatório de IA e POST_MORTEM

| # | Prompt (literal) | Resposta / efeito |
|---|---|---|
| 13 | `faca o modulo M14` | Execução da E19 (este relatório): consolidação dos logs, bateria de testes, estresse, `POST_MORTEM.md`. |

## Código bruto

Como obter o código antes de qualquer correção manual: `git show raw-E05:src/access/bplus.py`
e `git show raw-E06:src/access/bplus.py` (ver ressalva sobre a `raw-E06` em `ia_log/code_review/M3.md`).
