# Projeto exemplo — BIMOFFICE Knowledge

Tudo nesta pasta é **FICTÍCIO**, criado para demonstrar e testar o sistema. Não use em obra.

| Pasta | Conteúdo |
|---|---|
| `projeto_exemplo/Escola_SENAI_Bloco_B_EXEMPLO.ifc` | IFC4 de uma escola de 2 pavimentos: 197 elementos (arquitetura, estrutura de concreto, cobertura metálica, hidrossanitário, elétrica, climatização). Tem **lacunas propositais** (vigas sem volume, divisória sem quantitativos, 2 elementos genéricos) para mostrar as pendências. |
| `memoriais_referencia/` | 3 memoriais de referência em DOCX (arquitetura e acabamentos; estrutura e fundações; instalações), com normas ABNT reais citadas. Textos fictícios. |
| `saida/` | O memorial **produzido pelo sistema** a partir dos itens acima (minuta DOCX, ainda **não revisada**). |

## Ver sem instalar (GitHub Pages)
Abra https://brunno100barros-del.github.io/BIMOFFICE-Knowledge/ e clique em
**“Abrir demonstração com o projeto exemplo”**. É uma demonstração **somente leitura**: os dados (inventário,
memorial, biblioteca) são as respostas reais do sistema para este exemplo, gravadas em `frontend/demo/` por
`python scripts/exemplo/gerar_demo_estatico.py`. Enviar arquivos, editar, gerar e pesquisar por significado
exigem o programa instalado (a pesquisa não é simulada na demonstração).
Ao mudar o sistema ou o exemplo, rode o script de novo para atualizar a demonstração.

## Como reproduzir no seu computador
Opção A — pela interface (recomendado para conhecer o fluxo):
1. **Biblioteca** → Importar → selecione os 3 DOCX de `memoriais_referencia/`.
2. **Projetos (IFC)** → crie um projeto → arraste o IFC de `projeto_exemplo/` → aguarde o processamento.
3. Na página do projeto → **Gerar memorial descritivo**.
4. Em cada capítulo: confira os dados do IFC, abra **Sugestões da biblioteca** e clique em **Inserir** nos trechos que fazem sentido; **adapte** o texto; **aprove**.
5. **Exportar minuta (DOCX)** a qualquer momento; **Exportar final** quando todos os capítulos estiverem aprovados.

Opção B — automático (cria tudo de uma vez, sem inserir trechos):
```
python scripts/exemplo/criar_projeto_exemplo.py
```

Para gerar novamente os arquivos de exemplo:
```
python scripts/exemplo/gerar_ifc_exemplo.py
python scripts/exemplo/gerar_memoriais_referencia.py
```

## O que a minuta de `saida/` mostra
- Cada capítulo começa com o texto montado **só com dados do IFC** (quantidades, materiais, dimensões).
- Em seguida vem o trecho de referência que foi **escolhido e inserido** (no teste: o trecho do assunto
  correspondente, sugerido pela pesquisa semântica).
- Atenção: os textos de referência são de uma **reforma** e o projeto exemplo é uma **obra nova** — por isso
  aparecem frases como "demolições e remoções" que precisariam ser adaptadas. É exatamente o trabalho de
  revisão do engenheiro, e por isso a minuta é marcada "NÃO REVISADA".
- "Impermeabilização" ficou sem texto: não há dado no IFC nem trecho de referência sobre o assunto.
