# CLAUDE.md — Bancada de Teste de SBD (Avaliação 2, CDB 2026.2 / UFRJ)

Este arquivo é lido automaticamente em toda sessão. Ele define **como trabalhar**.
O **que fazer** está em `docs/PLANO_EXECUCAO.md`; **onde parou** está em `PROGRESS.md`.

## Objetivo do projeto
Bancada de teste em Python que mede **blocos transferidos entre disco simulado e buffer pool**
para comparar configurações do Gerente de Armazenamento (organização primária, índices,
política de buffer, algoritmo de junção/seleção). Enunciado: `material/Avaliacao_2_v2_*.pdf`.

## Protocolo de execução (seguir SEMPRE, em toda sessão)
1. Ler `PROGRESS.md` → identificar a **primeira etapa com status `pendente` ou `em andamento`**.
   Se estiver `em andamento`, ler a nota de handoff dela e continuar dali.
2. Ler **somente a seção dessa etapa** em `docs/PLANO_EXECUCAO.md`
   (use Grep por `^## E07` e Read com offset/limit — não leia o plano inteiro).
   Ler também a seção "Decisões fixadas" do plano na primeira etapa de cada camada.
3. Ler `docs/INTERFACES.md` para conhecer a API das camadas já prontas.
   **Não** abra o código de outras camadas, a não ser que um teste falhe por causa delas.
4. Marcar a etapa como `em andamento` no `PROGRESS.md`.
5. Implementar código **e** testes da etapa.
6. **Antes de rodar os testes**: `git add -A && git commit -m "ia-raw(Exx): <resumo>"` e
   `git tag raw-Exx` (evidência do código bruto da IA, exigida no Post-Mortem).
7. Rodar os testes da etapa e corrigir até passar. Cada defeito encontrado nesse ciclo vira uma
   entrada em `ia_log/code_review.md` (formato no fim deste arquivo).
   Commit das correções: `fix(Exx): <defeito corrigido>`.
8. Rodar a suíte completa: `.venv/Scripts/python -m pytest -q -x` (nada pode quebrar).
9. Atualizar `docs/INTERFACES.md` com as assinaturas públicas novas (só assinaturas + 1 linha).
10. Atualizar `PROGRESS.md`: status `concluída`, nota de handoff (≤ 8 linhas: o que foi feito,
    decisões tomadas e por quê, pendências). Registrar decisões novas em `docs/DECISOES.md`
    (alimenta o relatório: toda escolha precisa de justificativa e alternativa preterida).
11. `git commit -m "feat(Exx): <resumo>"`.
12. **Parar** e dizer ao usuário: "Etapa Exx concluída. Rode `/clear` e depois `/proxima-etapa`."
    Não emende a etapa seguinte na mesma sessão (economia de contexto).

### Economia de tokens
- Uma etapa por sessão. Se o contexto ficar grande no meio da etapa: commit `wip(Exx)`,
  escreva a nota de handoff com o próximo passo exato, marque `em andamento` e pare.
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
- Python 3.11, venv em `.venv` (`.venv/Scripts/python` no Windows). Dependências em `requirements.txt`.
- Código e comentários em português; docstring de cada algoritmo cita a seção do Silberschatz.
- Configuração em `config/*.yaml`; nada de números mágicos espalhados.
- Dados gerados em `data/` (fora do git); resultados em `results/` (no git).
- Commits pequenos, prefixos: `ia-raw`, `fix`, `feat`, `test`, `docs`, `wip`.

## Formato de entrada em `ia_log/code_review.md`
```
### [Exx] <título do defeito>
- Arquivo: src/...:linha  | Categoria: (buffer fora do BM | pin/unpin | dirty | busca binária | B+ | hash overflow | memória da junção | offset | eficiência | outro)
- Como foi detectado: <teste / revisão>
- Código bruto (tag raw-Exx): <trecho curto>
- Correção: <o que mudou e por quê>
```
