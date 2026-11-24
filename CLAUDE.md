# CLAUDE.md — Bancada de Teste de SBD (Avaliação 2, CDB 2026.2 / UFRJ)

Este arquivo é lido automaticamente em toda sessão. Ele define **como trabalhar**.
O projeto é desenvolvido **em paralelo por 5 pessoas, cada uma com sua IA, em módulos**:
- divisão, dono e arquivos de cada módulo: `docs/MODULOS.md`
- especificação técnica de cada etapa: `docs/PLANO_EXECUCAO.md` (seções `## Exx`)
- onde cada módulo parou: `progress/Mx.md` (quadro geral em `PROGRESS.md`)
- fluxo de Git/PR: `docs/GIT_FLUXO.md`

## Objetivo do projeto
Bancada de teste em Python que mede **blocos transferidos entre disco simulado e buffer pool**
para comparar configurações do Gerente de Armazenamento (organização primária, índices,
política de buffer, algoritmo de junção/seleção). Enunciado: `material/Avaliacao_2_v2_*.pdf`.

## Protocolo de execução (seguir SEMPRE, em toda sessão) — comando `/modulo Mx`
0. Saber o módulo: vem do argumento de `/modulo` (ex.: `M3`). Sem argumento → perguntar ao usuário.
   Conferir a branch: deve ser `mod/Mx-<nome>` (criar a partir de `main` se não existir).
   Atualizar: `git fetch origin && git merge origin/main` (resolver conflitos só em arquivos do seu módulo;
   em arquivos de outros, aceitar a versão de `main`).
1. Ler `progress/Mx.md` → primeira etapa `pendente` ou `em andamento` (se em andamento, seguir a nota de handoff).
   Se as dependências do módulo (ver `docs/MODULOS.md`) ainda não estão em `main`, trabalhar contra os fakes.
2. Ler **somente** a seção do módulo em `docs/MODULOS.md` e a seção da etapa em `docs/PLANO_EXECUCAO.md`
   (Grep por `^### Mx` / `^## Exx` e Read com offset/limit — não leia os arquivos inteiros).
3. Ler `docs/INTERFACES.md` e o(s) `contracts.py` que o módulo implementa/usa.
   **Não** abra o código de outros módulos, a não ser que um teste falhe por causa deles.
4. **Propriedade de arquivos:** só criar/editar arquivos do seu módulo (lista em `docs/MODULOS.md`).
   Mudança em contrato ou arquivo alheio → parar, escrever "Pedido de mudança de contrato" em
   `progress/Mx.md` e avisar o usuário. Nunca mudar uma assinatura de contrato por conta própria.
5. Marcar a etapa `em andamento` em `progress/Mx.md`. Implementar código **e** testes.
6. **Antes de rodar os testes**: `git add -A && git commit -m "ia-raw(Exx): <resumo>"` e
   `git tag raw-Exx` (evidência do código bruto da IA, exigida no Post-Mortem).
7. Rodar os testes da etapa e corrigir até passar. Cada defeito encontrado vira uma entrada em
   `ia_log/code_review/Mx.md` (formato no fim deste arquivo). Commit: `fix(Exx): <defeito>`.
8. Rodar a suíte completa: `python -m pytest -q -x` com o Python do venv (nada pode quebrar) e
   também os testes de contrato do seu módulo em `tests/contratos/`.
9. Decisões novas em `docs/decisoes/Mx.md` (valor · justificativa · alternativa preterida).
10. Atualizar `progress/Mx.md`: status `concluída` + nota de handoff (≤ 8 linhas).
11. `git commit -m "feat(Exx): <resumo>"`, `git push -u origin mod/Mx-<nome> --tags`.
    Se o `gh` estiver disponível e autenticado, abrir PR para `main` (título `Mx/Exx: <resumo>`);
    senão, dizer ao usuário para abrir o PR no GitHub.
12. **Parar** e dizer: "Etapa Exx (Mx) concluída e enviada. Rode `/clear` e depois `/modulo Mx`."
    Não emende a etapa seguinte na mesma sessão (economia de contexto).

### Economia de tokens
- Uma etapa por sessão. Se o contexto ficar grande no meio da etapa: commit `wip(Exx)`,
  escreva a nota de handoff em `progress/Mx.md` com o próximo passo exato, marque `em andamento`, faça push e pare.
- **Nunca leia os PDFs inteiros.** As fórmulas e seções do livro estão em `docs/REFERENCIA_LIVRO.md`.
  Se precisar do livro: no máximo 3 páginas por vez; página do PDF = página impressa + 29.
- Testes: `pytest -q`; em falhas, `pytest -q -x --tb=short`. Não despeje CSVs/logs grandes —
  use `head`, `tail`, `wc -l`.
- Não reescreva arquivos inteiros para mudanças pequenas; use Edit.

## Regras de arquitetura (invioláveis — são critérios de avaliação)
- 4 camadas: `src/bench` → `src/executor` → `src/access` → `src/storage`.
  Cada camada importa **apenas** a camada imediatamente inferior (+ `src/common`).
  Teste `tests/test_arquitetura.py` verifica isso por análise de imports.
- **Nenhum acesso a blocos fora do BufferManager.** Só `src/storage/buffer_manager.py`
  chama o `FileManager` para ler/gravar blocos.
- Todo `pin` tem `unpin` → use sempre o context manager `buffer.page(...)`. Iteradores/geradores
  devem soltar a página em `finally`.
- Toda página alterada é marcada dirty (`buffer.page(..., dirty=True)` ou `frame.mark_dirty()`).
- Busca binária em arquivo ordenado é **sobre blocos**, não sobre registros.
- B+: ocupação mínima, folhas encadeadas, split propaga até a raiz. `check_invariants()` obrigatório.
- Hash: busca **e** remoção percorrem toda a cadeia de overflow.
- Junção/ordenação: memória de trabalho limitada a M páginas da área `trabalho`;
  proibido acumular em list/dict/set Python mais que cabe em M páginas
  (use `MemoryBudget` de `src/executor/memory.py`).
- Offsets/tamanhos de campos variáveis sempre validados contra os limites do bloco.

## Convenções
- Python 3.11, venv em `.venv` (`.venv/Scripts/python` no Windows, `.venv/bin/python` no Linux/macOS).
  Dependências em `requirements.txt` (mudanças nele: só via PR do M0).
- Código e comentários em português; docstring de cada algoritmo cita a seção do Silberschatz.
- Configuração em `config/*.yaml`; nada de números mágicos espalhados.
- Dados gerados em `data/` (fora do git); resultados em `results/` (no git).
- Commits pequenos, prefixos: `ia-raw`, `fix`, `feat`, `test`, `docs`, `wip`.

## Formato de entrada em `ia_log/code_review/Mx.md`
```
### [Exx] <título do defeito>
- Arquivo: src/...:linha  | Categoria: (buffer fora do BM | pin/unpin | dirty | busca binária | B+ | hash overflow | memória da junção | offset | eficiência | outro)
- Como foi detectado: <teste / revisão>
- Código bruto (tag raw-Exx): <trecho curto>
- Correção: <o que mudou e por quê>
```
