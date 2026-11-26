# Log de prompts — Emanuel

> **Módulo:** M5J — Sort-Merge Join e Partition-Hash Join  
> **Etapa:** E12  
> **Ferramenta:** ChatGPT  
> **Tipo de registro:** Reconstruído a partir do histórico de desenvolvimento; não é transcrição literal.

## 1. Implementação do Partition-Hash Join

**Objetivo dos prompts:** implementar o algoritmo de junção por particionamento, respeitando o limite de memória `M`, com particionamento recursivo e escolha da menor partição para construção da tabela hash.

## 2. Testes e correções do Hash Join

**Objetivo dos prompts:** analisar falhas nos testes, tratar chaves nulas e duplicadas, limitar recursos de memória e verificar a liberação de memória e arquivos temporários no encerramento antecipado do iterador.

## 3. Implementação do Sort-Merge Join

**Objetivo dos prompts:** implementar a ordenação das relações, intercalação das chaves e tratamento de grupos com valores duplicados.

## 4. Testes e correções do Sort-Merge Join

**Objetivo dos prompts:** comparar os resultados com um oráculo, testar duplicatas e chaves nulas e verificar a exclusão dos arquivos temporários quando o iterador é fechado antecipadamente.

## 5. Validação final

**Objetivo dos prompts:** executar os testes específicos e a suíte completa, interpretar falhas, atualizar a documentação e preparar o commit e o Pull Request.

## 6. Resultado

- Testes específicos: 15 aprovados.
- Suíte completa: 449 passed, 70 xfailed.
- Pull Request integrado à `main`.