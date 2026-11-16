# Versão grátis: app no navegador + banco no Google Drive (v0.7 — em andamento)

Pedido do usuário (2026-11-16): usar de graça, até 10 pessoas, **cada uma com o próprio login**, e o
"banco de dados" numa **pasta do Google Drive dele**; Gemini vinculado pelo login mestre dentro do site.
Aprovado: "pode seguir com o caminho".

## 1. Arquitetura
```
GitHub Pages (site, grátis) ──► navegador de cada pessoa
                                   ├─ login Google (conta própria de cada um)
                                   ├─ leitura IFC (web-ifc, WASM)          ┐ rodam no PC
                                   ├─ pesquisa E5 + palavras (FTS5) + RRF   │ de quem usa,
                                   ├─ geração do memorial / exportação DOCX ┘ nada vai a terceiros
                                   └─ Google Drive API ──► pasta "BIMOFFICE" do usuário mestre
                                   └─ (opcional) Gemini API — só com autorização do mestre
```
- **Permissões reais = compartilhamento do Drive** (o Google bloqueia gravação de quem é "Leitor").
  `BIMOFFICE/Biblioteca` (todos leem; quem o mestre escolher adiciona), `BIMOFFICE/Projetos/<projeto>`
  (só a equipe do projeto), `BIMOFFICE/Registro` (auditoria + histórico de versões do próprio Drive).
- **Dados em vários arquivos pequenos** (um por documento/capítulo/projeto) em vez de um arquivo único: duas
  pessoas trabalham em capítulos diferentes ao mesmo tempo; no mesmo capítulo, o salvamento confere a versão do
  arquivo no Drive e **não sobrescreve** o trabalho do outro (avisa e mostra as duas versões).
- **Índice de pesquisa**: vetores dos trechos calculados uma vez (por quem importa o documento) e guardados na
  pasta; cada navegador só calcula o vetor da pergunta. SQLite (WASM, com FTS5) local como cache.
- A versão instalável (`iniciar.bat`, backend Python) e a preparação para nuvem paga (v0.6) continuam funcionando.

## 2. Teste de viabilidade (feito, medido) — `scripts/viabilidade_navegador/`
Chromium sem servidor de aplicação; comparado com o sistema atual (Python) nos mesmos dados.

| Peça | Resultado |
|---|---|
| SQLite 3.54.1 WASM com FTS5 (`unicode61 remove_diacritics 2`, igual ao backend) | funciona (120 ms) |
| **E5 no navegador, precisão fp16 (555 MB)** | vetores **idênticos** ao Python (cosseno 1,000); **50/50** resultados iguais no top-5 das 10 pesquisas; mesmos top-3 em 10/10; top-1 9/10 (o único caso é empate exato de nota entre dois trechos) |
| E5 quantizado q8 (279 MB) | cosseno 0,98–0,99; top-5 46/50; top-1 8/10 (ex.: "forro de gesso" pôs *drywall* à frente de *forros*) |
| Tempos (fp16, CPU deste servidor de testes) | carregar o modelo 6 s; indexar 33 trechos 16 s; cada pesquisa ~0,1 s |
| **IFC com web-ifc 0.0.79 (MPL-2.0)** no exemplo (197 elementos) e nas 5 amostras buildingSMART (IFC2X3, IFC4, IFC4X3) | **todos os elementos** encontrados, mesmas classes, **propriedades 92/92 iguais** ao IfcOpenShell; diferença: o web-ifc também lista Site/Building/Storey como elemento (filtro trivial) |
| Geometria 3D (web-ifc) | malhas geradas (serve também para o visualizador 3D) |

**Decisão:** usar o modelo **fp16** (resultados iguais aos de hoje). Custo: baixar ~555 MB na 1ª vez em cada
computador (fica guardado no navegador). O q8 fica como opção para PCs/redes fracas, com aviso de que a ordem
pode variar um pouco.

**Ainda NÃO testado (depende do usuário):** login Google e leitura/gravação no Drive (precisa do Client ID);
Gemini (precisa da chave); IFC grande real (desempenho depende do PC de quem usa).

## 3. Gemini
- A assinatura do app Gemini (Google One/Gemini Advanced) **não** dá acesso pela programação; é preciso uma
  **chave da API do Gemini** (Google AI Studio, tem cota gratuita).
- **Atenção (termos do Google):** no nível gratuito o Google pode usar o conteúdo enviado para melhorar os
  produtos (com revisão humana). No nível pago, não. Por isso: envio só com autorização explícita do mestre, só os
  trechos necessários (nunca o arquivo inteiro), e cada envio registrado em `Registro`.
- **Papel do Gemini:** interpretar a pergunta, resumir/explicar resultados e sugerir redação — **nunca** substitui
  a pesquisa E5 + palavras nem inventa valores; todo texto sugerido mostra a origem e passa por revisão humana.
- **Vincular pelo site (login mestre):** Configurações → "Conectar Gemini": botão para abrir a página da chave,
  campo para colar, botão "Testar", aviso dos termos, "Desconectar". Sem servidor próprio, a chave precisa estar
  acessível ao navegador de quem usa: fica num arquivo da pasta (só a equipe lê) e deve ser **restringida no Google
  Cloud** ao site do BIMOFFICE e à API do Gemini — fora do site ela não funciona. Alternativa: cada pessoa conecta
  a própria chave.

## 4. Próximas etapas
1. Client ID do Google (usuário cria; passo a passo fornecido) → login + pasta do Drive (testar de verdade).
2. Biblioteca no navegador (DOCX/PDF → seções/trechos, igual ao backend, com teste de paridade).
3. Pesquisa híbrida no navegador (fp16) + índice na pasta.
4. Projetos/IFC (web-ifc) com paridade do leitor Python (quantidades, materiais, sistemas, classificação).
5. Memorial em elaboração + exportação DOCX; visualizador 3D.
6. Gemini (com autorização).
