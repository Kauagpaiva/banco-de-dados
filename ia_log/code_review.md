# Code review do código gerado por IA

> Cada defeito encontrado ao rodar os testes de uma etapa (código bruto na tag `raw-Exx`).
> Formato definido no `CLAUDE.md`.

### [E00] Analisador de imports perdia o nome importado em `from ..pkg import mod`
- Arquivo: tests/test_arquitetura.py:33  | Categoria: outro
- Como foi detectado: teste `test_detector_pega_violacao`
- Código bruto (E00 não tem tag raw — infraestrutura): `nomes = [mod] if no.module else [f"{mod}.{a.name}" ...]`
- Correção: imports relativos passam a registrar o módulo **e** `módulo.nome`, igual aos absolutos; também o lookup do módulo no monkeypatch usava `__import__(__name__)` (devolve o pacote `tests`) → `sys.modules[__name__]`.
