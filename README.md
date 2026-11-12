# BIMOFFICE Knowledge

Biblioteca inteligente de memoriais descritivos (SENAI) com pesquisa semântica local.
Status: **Etapa 1 de 7** (biblioteca + importação DOCX + busca textual). Veja `docs` abaixo.

## Como executar (Windows)
1. Instale o Python 3.11+ (python.org) marcando "Add to PATH".
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

## Limitações conhecidas
- Numeração automática do Word não é lida; cabeçalhos/rodapés/caixas de texto não são indexados.
- Página do trecho é apenas ESTIMADA (o DOCX não guarda paginação).
- Pesquisa semântica (embeddings), editor, exportação e interface Liquid Glass: etapas 2–6.
- Camada HTTP (FastAPI) ainda não foi executada em testes automatizados; os serviços foram.

## Privacidade
`data/` (documentos, banco, backups) está no `.gitignore`: documentos da instituição não vão ao GitHub.
