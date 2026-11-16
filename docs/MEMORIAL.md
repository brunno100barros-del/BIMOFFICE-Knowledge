# Memorial em elaboração — v0.5 (sem IA generativa)

## Fluxo
1. Projeto com modelo IFC processado → **Gerar memorial descritivo**.
2. O sistema monta os capítulos (ordem usual: apresentação, serviços preliminares, ambientes, fundações,
   estrutura, estrutura metálica, vedações, impermeabilização, revestimentos, pisos, forros, pintura,
   esquadrias, escadas, cobertura, hidrossanitário, elétrica, climatização, limpeza, pendências).
3. Para cada capítulo: **texto gerado do IFC**, **dados usados** (origem/método/GlobalIds), **pendências**,
   **quadros** (ambientes, esquadrias) e **sugestões da biblioteca** (pesquisa híbrida E5 + FTS5).
4. Usuário insere sugestões, edita, aprova; exporta minuta ou final (DOCX).

## Regras garantidas por código e testes
| Regra (CLAUDE.md) | Como |
|---|---|
| Não inventar informação | o texto é montado só com dados do inventário IFC; teste confere que **todo número** do texto vem do IFC |
| Nunca substituir automaticamente | trechos da biblioteca ficam em `suggestions` até o usuário clicar "Inserir"; regerar não apaga texto editado sem confirmação |
| Origem + original × adaptado | `generated_text` (original do IFC) e `text` (atual) separados; cada inserção guarda documento, seção e **texto original** em `inserted_refs`; histórico de versões em `memorial_versions` |
| Revisão humana antes da exportação | exportação final só com todos os capítulos aprovados; editar um capítulo aprovado o devolve a rascunho; a minuta sai marcada "MINUTA — NÃO REVISADA" |
| Separar biblioteca e memorial | tabelas próprias; editar o memorial não altera a biblioteca nem o IFC |

Capítulos sem nenhum elemento no IFC são omitidos (exceto os "complementares", que entram vazios com pendência).

## API
| Método | Rota |
|---|---|
| GET | `/api/memorials` · `/api/projects/{pid}/memorials` · `/api/memorials/{mid}` |
| POST | `/api/projects/{pid}/memorials` `{model_id?, title?}` → gera |
| PATCH/DELETE | `/api/memorials/{mid}` (título) |
| POST | `/api/memorials/{mid}/chapters` `{title, after_id?}` |
| PATCH/DELETE | `/api/memorial-chapters/{cid}` `{text?, title?}` |
| POST | `/api/memorial-chapters/{cid}/approve?approved=` · `/insert-reference?chunk_id=` · `/suggestions?q=` · `/regenerate?replace_text=` · `/move?direction=±1` |
| GET | `/api/memorial-chapters/{cid}/history` |
| GET | `/api/memorials/{mid}/export?draft=true|false` → DOCX (final: 409 se houver capítulo não aprovado) |

## Tabelas
`memorials` (projeto, modelo, título) · `memorial_chapters` (posição, chave, título, generated_text, text,
status, facts, pending, tables_json, suggestions, inserted_refs, query, element_ids) · `memorial_versions` (histórico).

## Limitações (v0.5)
- Texto gerado é **descritivo e direto** (frases montadas por regras), não redação elaborada — o Gemini
  (próxima fase) entra para redigir/adaptar, sempre com os mesmos dados e a mesma rastreabilidade.
- Sugestões são trechos inteiros da biblioteca; adaptar ao projeto é tarefa do revisor.
- Exportação em estilo simples (Arial, títulos numerados, quadros). **Ainda não** preenche um modelo DOCX
  institucional (cabeçalho/rodapé/estilos próprios) nem insere imagens.
- Sem edição de quadros (ambientes/esquadrias) na interface: são regerados do IFC.
- Nome do arquivo exportado sem acentos (compatibilidade); o conteúdo mantém os acentos.

## Memorial 3D (v0.7)
- **Vínculo capítulo ↔ elementos do IFC:** ao gerar (ou regerar) um capítulo, o sistema grava em `element_ids` os
  **GlobalIds** de todos os elementos que a regra do capítulo usou (`Ctx.where`), e cada dado em `facts` guarda a lista
  completa dos GlobalIds de onde veio. O memorial guarda o modelo/versão (`memorials.model_id`). Consultar outro grupo
  só para escrever uma frase (ex.: cobertura citando a estrutura metálica) **não** cria vínculo.
- **Tela "Memorial 3D"** (`#/modelo3d/<modelo>?memorial=<id>&cap=<capítulo>`): o IFC original é aberto **no navegador**
  (web-ifc + three.js, em `frontend/vendor/bim3d/`, licenças MIT/MPL-2.0 em `LICENCAS.txt`). Capítulo → destaca os
  elementos e enquadra; elemento (clique no 3D ou na lista) → ficha técnica (mesmos dados do inventário, com origem e
  método de cada quantidade) + "Descrito no memorial" (capítulos que usam o elemento). Filtros por pavimento e disciplina,
  vistas, ambientes (IfcSpace) liga/desliga, painéis recolhíveis. Botões "Ver em 3D" (inventário), "Memorial 3D"
  (memorial) e "Ver no 3D (n)" em cada capítulo.
- Se o memorial foi gerado de outra versão do modelo, a tela avisa e marca os GlobalIds que não existem nesta versão.
- **Somente leitura:** a tela não altera o IFC nem o memorial.

### Limitações (v0.7)
- Elementos sem geometria no IFC aparecem na lista do capítulo como "sem forma 3D" (ex.: IfcRoof que só agrupa).
- Modelos muito grandes dependem da memória/placa de vídeo do computador (uma malha por elemento, sem otimização LOD).
- Comparação entre versões do IFC (diff) e marcação automática de capítulos afetados: **ainda não** (próxima etapa).
- Os vínculos de memoriais gerados **antes** da v0.7 ficam vazios até o capítulo ser regerado.
