# Leitor IFC e Projetos — BIMOFFICE Knowledge v0.4

## 1. Fase 0 — análise de compatibilidade (resultado medido em 16/11/2026)

| Item | Resultado |
|---|---|
| Biblioteca | **IfcOpenShell 0.9.0.post1** (PyPI), licença **LGPL-3.0** (uso como biblioteca é permitido sem abrir o código do sistema) |
| Python | pacotes prontos para 3.10 a 3.15 (Windows x64/ARM, Linux x64/ARM glibc ≥ 2.31, macOS). Projeto padronizado em **3.13** (o PyTorch do modelo E5 ainda não existe para 3.14+) |
| Windows | **testado de verdade** no GitHub Actions (`windows-latest`, Python 3.12 e 3.13): 86 testes passaram, 3 pulados (só os que exigem o modelo E5) — workflow `.github/workflows/testes-windows.yml` |
| Linux (desenvolvimento) | Python 3.13.18: todos os testes passam |
| Conflitos | nenhum: reaproveita o numpy 2.5 já instalado; `pip check` sem problemas; não altera PyTorch/sentence-transformers |
| Tamanho | ~43 MB para baixar, **~200 MB instalado** (+ shapely, lark, isodate, ~5 MB) |
| Versões IFC abertas | **IFC2X3, IFC4, IFC4X3** (modelos oficiais da buildingSMART + modelos de teste gerados). IFC2X2 e anteriores: recusados com mensagem clara |
| Extração | elementos, pavimentos, tipos, Property Sets, quantidades (Qto), materiais (camadas, perfis, constituintes, listas), sistemas, classificações — tudo verificado por testes |
| Geometria | volume e áreas pela **malha real** conferem com o esperado: parede 5×3×0,14 m → 2,100 m³ e 15,000 m² |
| Desempenho | modelo de **47 MB / 20.000 elementos**: abre em 1,3 s; propriedades/materiais/pavimentos em 2,9 s; 361 MB de RAM. Geometria de 20.000 elementos: 11 s (4 núcleos) |
| Hospedagem online | precisa de servidor com Python 3.13 + glibc ≥ 2.31 (Ubuntu 20.04+, Debian 11+, imagem Docker `python:3.13-slim`). **Não serve:** Alpine/musl, funções "serverless" com limite de tamanho (IfcOpenShell + PyTorch passam de 1 GB), serviços sem disco permanente. Recomendado: 4 GB de RAM |

**Decisão:** sem serviço separado nem fila externa por enquanto. O IfcOpenShell roda no próprio backend
FastAPI, mas **fora da requisição**: uma fila de tarefas persistida no SQLite com um trabalhador em
segundo plano (`backend/jobs.py`). Se no futuro os modelos ficarem muito pesados, o mesmo contrato de
tarefa pode ir para um processo/servidor dedicado sem mudar a interface.
O GitHub Pages continua servindo só a interface; nenhum IFC é processado no navegador.

## 2. Como funciona

```
Envio (interface ou API)  ──►  arquivo gravado em partes (data/projects/<sha256>.ifc, somente leitura)
                                │  duplicado?  -> recusado (409)     mesmo nome, conteúdo novo -> versão +1
                                ▼
                         tarefa "ifc_parse" na fila (tabela jobs)
                                ▼  trabalhador em segundo plano (progresso, cancelamento, retomada)
   backend/ifc/reader.py   abre, confere versão e final do arquivo, lê elementos e propriedades,
                           converte unidades para SI, calcula geometria só do que falta
   backend/ifc/classify.py classifica disciplina por regras explicáveis
   backend/ifc/inventory.py monta o inventário (somatórios por regra)
                                ▼
                 ifc_models (resumo) + ifc_elements (um registro por elemento, JSON completo)
```

### Origem de cada informação (nada é inventado)

| Método | Significado |
|---|---|
| `explicito` | gravado no IFC: `IfcElementQuantity` (Qto_*), camadas de material (soma das espessuras) |
| `atributo` | atributo do próprio elemento, ex.: `IfcDoor.OverallHeight` |
| `geometrico` | calculado pela **malha triangulada do sólido** (IfcOpenShell geom). Não usa a caixa envolvente. Só para elementos **sem** a quantidade explícita equivalente. Aproximação — não é quantitativo executivo |
| `regra` | somatórios do inventário, sempre separados por método e só para medidas aditivas (área, volume, comprimento, massa, contagem). Alturas/larguras/espessuras **não** são somadas |
| não encontrado | a informação não existe no IFC — aparece em "Informações ausentes" |

### Classificação por disciplina

Disciplinas: Arquitetura, Estrutura, Estrutura metálica, Hidrossanitário, Elétrica, Climatização,
Instalações (indefinida), Outros, **Pendente**. Evidências, da mais forte para a mais fraca:
classe IFC → tipo associado (essencial no IFC2X3, onde tubos são `IfcFlowSegment`) → tipo do sistema
(`IfcDistributionSystem.PredefinedType`) → `LoadBearing` (paredes/lajes) e material (aço → metálica)
→ nome do sistema. **O nome do elemento nunca classifica sozinho**: gera só uma *sugestão* de baixa
confiança, e o elemento fica "Pendente". Cada decisão guarda os motivos (`reasons`).

### Informações esperadas para o memorial (análise de completude inicial)

Paredes: material, espessura, comprimento, altura, área · Lajes: material, espessura, área ·
Portas/janelas: largura, altura · Pilares/vigas/fundações: material, volume · Ambientes: área ·
Todos: pavimento. Status por item: explícito / calculado / não encontrado.

## 3. Banco de dados (novas tabelas, migração automática)

| Tabela | Conteúdo |
|---|---|
| `projects` | nome, descrição, localização, disciplinas, datas, exclusão lógica |
| `project_files` | tipo (ifc/pdf/docx/image), nome, sha256, tamanho, disciplina, **versão**, versão anterior, situação, erro |
| `ifc_models` | um por arquivo IFC: schema, cabeçalho, unidades, **inventário (JSON)**, nº de elementos, tempo |
| `ifc_elements` | um por elemento: classe, nome, tipo, pavimento, disciplina, confiança, ausentes + JSON completo |
| `jobs` | fila de tarefas: tipo, situação, progresso, mensagem, erro, cancelamento, tentativas |
| `project_history` | histórico de alterações e processamentos do projeto |

As tabelas da biblioteca de memoriais não foram alteradas. Projetos nunca alteram a biblioteca.

## 4. API (prefixo `/api`)

| Método | Rota | Para quê |
|---|---|---|
| GET/POST | `/projects` | listar / criar projeto |
| GET/PATCH/DELETE | `/projects/{id}` | ver / alterar / mover para a lixeira |
| GET | `/projects/{id}/history` | histórico |
| GET/POST | `/projects/{id}/files` | listar / enviar **um** arquivo (multipart `file`, `discipline`) → `{file, job}` |
| DELETE | `/projects/{id}/files/{fid}` | remover do projeto (original continua no disco) |
| POST | `/projects/{id}/files/{fid}/reprocess` | ler o IFC de novo |
| GET | `/projects/{id}/files/{fid}/original` | baixar o original (`?inline=true` para PDF/imagem) |
| GET | `/projects/{id}/ifc-models` | modelos com inventário |
| GET | `/ifc-models/{mid}` | um modelo |
| GET | `/ifc-models/{mid}/elements` | elementos com filtros `discipline`, `ifc_class`, `storey`, `q`, `missing` (`any` ou item), `limit`, `offset` |
| GET | `/ifc-models/{mid}/export` | inventário completo, contrato **`bimoffice.ifc-inventory/1`** (para o Coordix e outras integrações) |
| GET | `/ifc-elements/{eid}` | elemento completo (psets, materiais, quantidades com origem, verificações) |
| GET | `/jobs?project_id=&active=` · `/jobs/{id}` | acompanhar tarefas |
| POST | `/jobs/{id}/cancel` | cancelar |

## 5. Configuração (variáveis de ambiente)

| Variável | Padrão | Uso |
|---|---|---|
| `BIMOFFICE_MAX_IFC_MB` | 500 | tamanho máximo de IFC |
| `BIMOFFICE_IFC_GEOMETRY_SECONDS` | 120 | tempo máximo do cálculo geométrico por modelo (depois disso é interrompido e avisado) |
| `BIMOFFICE_JOB_WORKER` | 1 | liga o trabalhador de segundo plano junto com o servidor |

## 6. Limitações conhecidas (v0.4)

- Aceita IFC em formato STEP (`.ifc`). **IFCZIP e ifcXML ainda não.**
- Um trabalhador processa uma tarefa por vez (modelos grandes ficam na fila).
- Cancelamento acontece nos pontos de verificação (a cada 200 elementos / a cada peça de geometria).
- Propriedades herdadas do **tipo** aparecem junto com as da ocorrência (sem distinguir a fonte).
- Valores de Property Sets são guardados como estão no IFC (sem conversão de unidade); só as
  quantidades (Qto) e dimensões são convertidas para SI.
- Área lateral de parede pela malha considera uma face; paredes curvas/inclinadas podem divergir.
- Arquivos PDF, DOCX e imagens enviados a projetos são **guardados**, mas ainda **não lidos**
  (Fase 2). Não há OCR nem interpretação de imagens ainda.
- Sem usuários individuais: a separação de dados por usuário depende da futura autenticação.
- O inventário é lido do IFC; ainda **não há** correção manual de valores (matriz de informações — Fase 2).

## 7. DWG — estratégia (não implementado de propósito)

Não existe biblioteca Python livre e confiável para ler DWG diretamente (formato fechado da Autodesk).
Opções, em ordem de recomendação:
1. **Exportar IFC** do software de origem (Revit, ArchiCAD, etc.) — melhor caminho.
2. **Converter para DXF** (ODA File Converter, gratuito, executável externo) e ler o DXF com `ezdxf`
   (MIT): textos, camadas, blocos e cotas — mas sem semântica BIM (não há "parede", só linhas).
3. Serviço comercial (Autodesk Platform Services) — exige conta paga e envio do arquivo para fora.
Hoje o sistema recusa DWG com essa orientação, em vez de fingir que lê.

## 8. Próximas fases (do plano do usuário)

- **Fase 2:** leitura de PDF/DOCX/imagens dos projetos, matriz de informações (aprovar, corrigir,
  rejeitar, valor original × corrigido com histórico), pendências e divergências entre arquivos.
- **Fase 3:** Gemini (SDK oficial `google-genai`), chave só no backend (`GEMINI_API_KEY`), envio
  apenas de dados já extraídos e resumidos (nunca o IFC inteiro), registro de consumo.
  **Requer a chave e a autorização do usuário para enviar conteúdo ao Google.**
- **Fase 4:** memorial por capítulos (modelo DOCX, editor, exportação Word).
- **Fase 5:** imagens nos memoriais. **Fase 6:** integração Coordix pelo contrato `bimoffice.ifc-inventory/1`.
