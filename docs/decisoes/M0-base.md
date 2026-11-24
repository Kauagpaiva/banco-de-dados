# DECISÕES de projeto (alimenta o relatório técnico)

> Cada decisão: valor escolhido · justificativa · alternativa preterida. Novas decisões são
> acrescentadas ao fim, com a etapa em que surgiram.

## Decisões fixadas (E00)

| # | Decisão | Justificativa | Alternativa preterida |
|---|---|---|---|
| D01 | Bloco de 4096 B | Tamanho de página típico de SO/SGBD; fan-out de B+ e fr realistas sem tornar a base enorme. | 2048/8192 só como variação de experimento. |
| D02 | Alocação por extents de 8 blocos | Mantém blocos de uma estrutura quase contíguos (menos seeks em scan), como SGBDs reais (Silberschatz 13.2). | Contígua (exige saber o tamanho final) / encadeada (cada bloco vira seek). |
| D03 | 1 arquivo do SO por estrutura, bloco 0 = cabeçalho | Isola contagem de I/O por estrutura e simplifica o catálogo; cabeçalho guarda metadados persistentes. | Um único arquivo para tudo (exigiria gerente de espaço global). |
| D04 | Lista encadeada de blocos livres com cabeça no cabeçalho | Reuso O(1) de blocos liberados sem estrutura extra. | Bitmap de blocos livres (mais I/O para varrer). |
| D05 | Um braço de disco global: (fid,b) é sequencial se o último acesso físico foi (fid,b−1) | Modela tS do livro de forma simples e determinística; intercalar estruturas gera seek, como no disco real. | Braço por arquivo (subestimaria seeks em junções). |
| D06 | RID = (bloco, slot) | Indireção do slot permite mover registros dentro da página sem invalidar ponteiros (Fig. 13.6). | (bloco, offset) — quebra ao compactar. |
| D07 | Slotted page, blocagem *unspanned* | Padrão do livro (13.2.2); registros variáveis sem atravessar blocos simplificam leitura e contagem. | Spanned (economiza espaço, mas 1 registro pode custar 2 I/Os). |
| D08 | Registro: null bitmap + parte fixa + (offset,len) + área variável; multivalorados serializados | Formato da Fig. 13.5; offsets validados contra o bloco. | Delimitadores (exige varrer o registro para achar campos). |
| D09 | Buffer de 256 páginas | Pequeno o bastante para forçar I/O nos volumes de teste, grande o bastante para M=64. | Buffer proporcional à base (dificulta comparação entre perfis). |
| D10 | Áreas fixas: catalogo 8 · indice 64 · dados 120 · trabalho M=64 | Isola efeitos: scan de dados não expulsa índice; M fixo torna custos de junção/ordenação previsíveis. | Pool único compartilhado (resultados dependem de interferência entre operadores). |
| D11 | Políticas LRU/MRU/FIFO/Clock por área, base LRU | Permite reproduzir o caso do livro (MRU + toss-immediate no nested-loop, 13.5). | Só LRU (não mostraria o efeito da política). |
| D12 | Contador de pins; página pinada nunca expulsa | Garante correção de iteradores que mantêm página em uso (13.5). | Pin booleano (não suporta pins aninhados). |
| D13 | Toss-immediate opcional por chamada | Operador sabe quando a página não será reutilizada (scan). | Global (prejudicaria índices). |
| D14 | Forced output via `flush()` explícito, contado à parte | Separa custo de persistência do custo do algoritmo. | Escrever a cada unpin dirty (infla escritas). |
| D15 | Prioridade de índice via área `indice` separada | Retém raiz/níveis superiores sem política especial. | Marcação de prioridade por página. |
| D16 | Prefetch opcional (k), desligado na base | Medição base fica igual às fórmulas do livro; prefetch é experimento à parte. | Prefetch sempre ligado (distorce comparação com o modelo). |
| D17 | Hash estático, nB = ⌈nr/(fr·0,8)⌉, bucket = 1 bloco, overflow encadeado, FNV-1a 64 | Folga de 20% reduz overflow; FNV-1a é simples, rápido e determinístico (ao contrário de `hash()` do Python, randomizado). | Hash extensível/linear (fora do escopo; complexidade maior). |
| D18 | B+: nó = 1 bloco, fan-out calculado do bloco; NOT UNIQUE via (chave, uniquificador); bulk loading na carga | Cada acesso a nó = 1 I/O, como no livro (14.3); uniquificador evita chaves duplicadas nos nós internos; bulk load gera folhas cheias e sequenciais (14.5). | Inserção um a um na carga (folhas ~67% cheias, mais lenta). |
| D19 | Índice secundário NOT UNIQUE: folha guarda chave → ponteiro p/ bloco(s) de lista de RIDs | Exigência do enunciado; evita repetir chave nas folhas (14.3.5). | Repetir (chave,RID) por ocorrência. |
| D20 | Python 3.11 + pytest + hypothesis + pyyaml + pandas + matplotlib; SQLite como referência | Ecossistema conhecido; hypothesis para testes de propriedade das estruturas; SQLite valida resultados das consultas. | C/Java (mais rápido, mas o que se mede é I/O de bloco, não tempo de CPU). |
| D21 | Configuração em `config/base.yaml` + `load_config()` com overrides | Experimentos variam só parâmetros; `Config` imutável evita alteração acidental durante uma medição. | Constantes no código / variáveis globais mutáveis. |
| D22 | Regra de camadas verificada por teste (`ast`) | Critério de avaliação; regressões de arquitetura quebram a suíte imediatamente. | Revisão manual. |
| D23 | PDFs de `material/` mantidos no git | Já estavam versionados no commit `init`; ignorá-los agora não os removeria do histórico. | Ignorar `material/*.pdf` (padrão do plano). |
