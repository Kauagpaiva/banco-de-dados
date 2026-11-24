# Referência do livro (Silberschatz, Korth, Sudarshan — Database System Concepts, 7ª ed.)

Arquivo: `material/Abraham-Silberschatz-...-2019.pdf`. **Página do PDF = página impressa + 29.**
Use este resumo em vez de abrir o PDF. Se for indispensável abrir: no máximo 3 páginas por leitura.
As fórmulas das §6 e §7 foram conferidas no livro (págs. 696, 703–704, 706–707, 711, 716–717).

Notação: tT = tempo de transferência de 1 bloco; tS = tempo de seek; br, bs = nº de blocos de r, s;
nr, ns = nº de tuplas; hi = altura do índice; n = nº de registros buscados; b = nº de blocos com
registros que satisfazem a condição; M = páginas de memória disponíveis; bb = blocos de buffer por run/partição;
nh = nº de partições. **Na bancada, reportamos transferências e seeks separadamente** (não somamos tempo).

## §1 Armazenamento físico — Cap. 12
| Seção | Página (impr./PDF) |
|---|---|
| 12.3 Magnetic Disks (seek, latência, transferência) | 563 / 592 |
| 12.6 Disk-Block Access (acesso sequencial × aleatório, buffering, scheduling) | 577 / 606 |

## §2 Estruturas de armazenamento e buffer — Cap. 13
| Seção | Página |
|---|---|
| 13.2 File Organization — registros fixos/variáveis, Fig. 13.5 (registro variável com null bitmap), Fig. 13.6 (slotted page) | 588 / 617 |
| 13.3 Organization of Records in Files — heap (13.3.1), sequencial, *multitable clustering*, particionamento | 595 / 624 |
| 13.4 Data-Dictionary Storage (catálogo) | 602 / 631 |
| 13.5 Database Buffer — buffer manager, *pinned blocks*, *forced output*, estratégias de substituição (LRU, MRU, *toss-immediate*) | 604 / 633 |
| 19.5 Buffer Management (WAL, forced output, interação com SO) | 926 / 955 |

Pontos-chave 13.5: LRU é ruim para o scan repetido da interna no nested-loop; para esse padrão
o livro recomenda **toss-immediate** + **MRU**. Blocos de catálogo/índice merecem retenção.

## §3 Registros e catálogo
Ver 13.2 e 13.4 acima. Slotted page: cabeçalho com nº de entradas, fim do espaço livre e vetor
(offset, tamanho) por slot; registros crescem do fim do bloco para o início; compactação move registros
mas não muda o slot (ponteiros externos apontam para o slot).

## §4 Índices ordenados e B+ — Cap. 14
| Seção | Página |
|---|---|
| 14.1 Basic Concepts / 14.2 Ordered Indices (clustering × secundário, denso × esparso, multinível) | 623 / 652 e 625 / 654 |
| 14.3 B+-Tree Index Files (estrutura, consulta, inserção, remoção, chaves não únicas) | 634 / 663 |
| 14.4 B+-Tree Extensions — organização de arquivo B+, índices secundários e realocação de registros, *bulk loading* | 650 / 679 |
| 14.5 Hash Indices (hashing estático, buckets, overflow chaining, skew) | 658 / 687 |
| 14.6 Multiple-Key Access / 14.7 Creation of Indices | 661 / 690 e 664 / 693 |

- Nó com n ponteiros: folha guarda entre ⌈(n−1)/2⌉ e n−1 valores; nó interno entre ⌈n/2⌉ e n ponteiros (raiz: ≥ 2).
- Altura de busca ≤ ⌈log_{⌈n/2⌉}(N)⌉ para N chaves.
- Chaves não únicas: tornar a chave única acrescentando um atributo (ex.: uniquificador/chave primária).
- Organização B+: registros nas folhas; splits movem registros → índices secundários devem guardar a
  chave de busca da organização primária em vez do ponteiro físico (custo extra de uma travessia).

## §5 Hash estático — 14.5
- Bucket = unidade de armazenamento (aqui, 1 bloco). Overflow por encadeamento (*overflow chaining*).
- Causas de *skew*: muitos registros com mesma chave; função de hash mal distribuída.
- nB deve ser > nr/fr com fator de folga (o livro cita ~20%: nB = (nr/fr)·(1+d), d≈0,2).
- Custo de busca por igualdade ≈ 1 leitura do bucket + nº de blocos de overflow na cadeia.

## §6 Seleção — 15.2/15.3 (Fig. 15.3, pág. 696 / PDF 725)
| Alg. | Caso | Custo |
|---|---|---|
| A1 | Busca linear | tS + br·tT |
| A1 | Linear, igualdade em chave (média) | tS + (br/2)·tT (pior caso br) |
| A2 | Índice clustering B+, igualdade em chave | (hi + 1)·(tT + tS) |
| A3 | Índice clustering B+, igualdade em não-chave | hi·(tT + tS) + tS + b·tT |
| A4 | Índice secundário B+, igualdade em chave | (hi + 1)·(tT + tS) |
| A4 | Índice secundário B+, igualdade em não-chave | (hi + n)·(tT + tS) |
| A5 | Índice clustering B+, comparação | hi·(tT + tS) + tS + b·tT (idêntico a A3) |
| A6 | Índice secundário B+, comparação | (hi + n)·(tT + tS) |

Notas do livro: com organização B+ economiza-se 1 acesso em A2 (registro está na folha); modelar
nós internos em memória ⇒ hi efetivo = 1. A5 para `A < v`: scan do início do arquivo, índice não usado.

## §7 Ordenação e junção — 15.4/15.5
**Ordenação externa (sort-merge), pág. 703–704:**
- Transferências: br·(2⌈log_{⌊M/bb⌋−1}(br/M)⌉ + 1)  (não inclui gravar o resultado final)
- Seeks: 2⌈br/M⌉ + ⌈br/bb⌉·(2⌈log_{⌊M/bb⌋−1}(br/M)⌉ − 1)
- Exemplo do livro: br=12, M=3, bb=1 → 60 transferências, 44 seeks.

**Nested-loop (15.5.1, pág. 704):** pior caso nr·bs + br transferências, nr + br seeks.

**Block nested-loop (15.5.2, págs. 706–707):**
- Pior caso: br·bs + br transferências; 2·br seeks. Melhor caso (interna cabe): br + bs transferências, 2 seeks.
- Com M blocos: ⌈br/(M−2)⌉·bs + br transferências; 2·⌈br/(M−2)⌉ seeks.
- Exemplo: student (b=100, n=5000) ⋈ takes (b=400, n=10000) → 40 100 transferências + 200 seeks.
- Melhorias: parar na 1ª correspondência se a junção é em chave da interna; varrer a interna alternando direção.

**Indexed nested-loop (15.5.3, pág. 707–708):** br·(tT + tS) + nr·c, c = custo de uma seleção em s.
Exemplo: 100 + 5000·5 = 25 100 acessos. Use a relação com menos tuplas como externa.

**Merge join (15.5.4, págs. 708–711):** entradas ordenadas: br + bs transferências; ⌈br/bb⌉ + ⌈bs/bb⌉ seeks
(contagem de seeks: conferir na pág. 710 / PDF 739 ao implementar o cost_model).
Exemplo sem ordenação prévia, M=3: total 9 100 transferências + 8 932 seeks. Com M=25: 2 500 transferências.
Grupos de mesma chave (Ss) devem caber em memória.

**Hash join (15.5.5, págs. 712–717):**
- nh ≥ ⌈bs/M⌉ (s = build input, a menor); na prática nh = ⌈bs/M⌉·f, fator de *fudge* f≈1,2.
- Sem recursão: 3(br + bs) + 4·nh transferências; 2(⌈br/bb⌉ + ⌈bs/bb⌉) + 2·nh seeks.
- Recursão necessária se nh ≥ M (≈ M > √bs é suficiente para evitar).
  Transferências: 2(br + bs)·⌈log_{⌊M/bb⌋−1}(bs/M)⌉ + br + bs; seeks: 2(⌈br/bb⌉ + ⌈bs/bb⌉)·⌈log_{⌊M/bb⌋−1}(bs/M)⌉.
- Build input inteiro em memória: br + bs transferências, 2 seeks.
- Exemplo: takes ⋈ student, M=20, bb=3 → 1 500 transferências, 336 seeks.
- Hybrid hash join (15.5.5.5, pág. 717) — opcional.

## Esquema universitário de referência
Apêndice A — Detailed University Schema, pág. 1287 / PDF 1316.
