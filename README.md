# BIMOFFICE Knowledge

Biblioteca inteligente de memoriais descritivos (SENAI) com pesquisa semântica local.
Status: **Etapa 2 de 7** (biblioteca + importação DOCX + pesquisa híbrida semântica/textual).

## Como executar (Windows)
1. Instale o Python **3.13** (python.org) marcando "Add python.exe to PATH".
   Use 3.11, 3.12 ou 3.13: versões mais novas (3.14, 3.15) ainda não têm o PyTorch,
   usado pela pesquisa semântica. O `iniciar.bat` escolhe sozinho uma versão compatível.
2. Dê dois cliques em `iniciar.bat`.
3. Abra http://127.0.0.1:8000/docs — a página permite testar a API (importar DOCX, listar, buscar).

Linux/macOS: `./iniciar.sh`

## Testes
```
python -m pytest -q
```

## Etapa 1 — o que existe
- Importação de DOCX (validação, hash SHA-256, detecção de duplicados, original somente leitura)
- Detecção de seções (estilos "Título N" + heurística de numeração/caixa alta), tabelas
- Divisão em trechos respeitando seções
- SQLite + FTS5 (busca por palavras, ignora acentos)
- Filtros, edição de metadados, exclusão lógica (lixeira) + restauração, reindexação, backup

## Etapa 2 — pesquisa inteligente
- Modelo local `intfloat/multilingual-e5-base` (prefixos "query:"/"passage:"), roda no próprio
  computador; nenhum texto de documento sai da máquina. Baixado uma vez (~1 GB).
- Vetores gravados no SQLite; busca vetorial com numpy; fusão com a busca por palavras (RRF).
- Rotas: `GET /api/search?q=...&unit=&discipline=&project=&mode=hybrid|semantic|text`,
  `GET /api/search/status`, `POST /api/search/reindex` (gera vetores pendentes; `force=true` refaz todos).
- **Relevância relativa** (0–100): 100 = 1º lugar nas duas buscas; achado por uma só ≤ ~50.
  Não é probabilidade nem equivalência técnica — sempre revise o trecho.
- Sem o modelo instalado, a pesquisa avisa e usa só a busca por palavras (nada é simulado).
- Conferir seus memoriais: coloque DOCX em `amostras/` e rode
  `python scripts/inspecionar_amostras.py` (seções/trechos) e
  `python scripts/avaliar_pesquisa.py "sua pergunta"` (resultados da pesquisa).

## Limitações conhecidas
- Numeração automática do Word não é lida; cabeçalhos/rodapés/caixas de texto não são indexados.
- Página do trecho é apenas ESTIMADA (o DOCX não guarda paginação).
- Editor, exportação e interface Liquid Glass: etapas 3–6 (ainda não há tela; use `/docs`).
- Busca por palavras não reconhece plural/singular ("elétrico" ≠ "elétricos"); a semântica cobre.
- Qualidade medida em 10 paráfrases técnicas sem palavras em comum: 8/10 em 1º lugar, todas no
  top 3 (só a parte semântica). Ainda NÃO medida com memoriais reais.
- Busca vetorial carrega os vetores a cada pesquisa: ok para milhares de trechos; para dezenas de
  milhares, trocar a camada por FAISS/Qdrant.
- O PyTorch ocupa ~1 GB no `.venv`; a 1ª pesquisa após ligar o servidor demora alguns segundos.

## Privacidade
`data/` (documentos, banco, backups) está no `.gitignore`: documentos da instituição não vão ao GitHub.
