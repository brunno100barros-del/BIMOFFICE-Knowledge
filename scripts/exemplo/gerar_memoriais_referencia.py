"""Gera 3 MEMORIAIS DE REFERÊNCIA de EXEMPLO (DOCX) para demonstrar a biblioteca.

Textos fictícios, escritos para demonstração do BIMOFFICE Knowledge, no estilo de especificações
técnicas usuais. Citam normas ABNT existentes, mas NÃO substituem o projeto e a revisão de um
responsável técnico. Não usar em obra sem revisão.

Uso:  python scripts/exemplo/gerar_memoriais_referencia.py [pasta_saida]
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt

OUT = Path(__file__).resolve().parents[2] / "exemplos" / "memoriais_referencia"
AVISO = ("DOCUMENTO DE EXEMPLO — texto fictício elaborado para demonstração do BIMOFFICE Knowledge. "
         "Não utilizar em obra sem revisão de responsável técnico habilitado.")

ARQ = ("Memorial de referência — Reforma do Bloco A (EXEMPLO) — Arquitetura e acabamentos", [
    ("1 DISPOSIÇÕES GERAIS", 1, [
        "Este memorial estabelece os materiais, as técnicas e os critérios de execução dos serviços de "
        "arquitetura e acabamentos. Os serviços seguirão as normas da ABNT aplicáveis, em especial a "
        "ABNT NBR 15575 (desempenho de edificações habitacionais, como referência de desempenho) e a "
        "ABNT NBR 9050 (acessibilidade).",
        "Em caso de divergência entre desenhos e este memorial, a fiscalização deverá ser consultada antes "
        "da execução. Todos os materiais deverão ser novos, de primeira qualidade e aprovados previamente."]),
    ("2 SERVIÇOS PRELIMINARES", 1, [
        "A obra será mantida limpa e sinalizada, com tapumes onde houver circulação de alunos, conforme a NR-18. "
        "As demolições e remoções serão executadas com cuidado para preservar os elementos que permanecerão."]),
    ("3 ALVENARIAS E VEDAÇÕES", 1, []),
    ("3.1 Alvenaria de blocos cerâmicos", 2, [
        "As paredes de vedação serão executadas em blocos cerâmicos vazados, conforme a ABNT NBR 15270-1, "
        "assentados com argamassa mista de cimento, cal e areia no traço 1:2:8 (em volume), com juntas de "
        "aproximadamente 10 mm, prumo e alinhamento rigorosos, conforme a ABNT NBR 8545.",
        "A fixação da alvenaria à estrutura (encunhamento) será feita somente após a execução das lajes superiores, "
        "com argamassa expansiva ou espuma de poliuretano, e telas metálicas de amarração nos pilares a cada duas fiadas.",
        "Sobre os vãos de portas e janelas serão executadas vergas e, sob as janelas, contravergas de concreto armado, "
        "ultrapassando o vão em no mínimo 30 cm de cada lado."]),
    ("3.2 Divisórias de gesso acartonado (drywall)", 2, [
        "As divisórias internas leves serão em chapas de gesso acartonado fixadas em estrutura de perfis de aço "
        "galvanizado (guias e montantes), conforme a ABNT NBR 15758. Em áreas molhadas serão usadas chapas "
        "resistentes à umidade (RU, cor verde). O espaço interno receberá lã mineral quando houver exigência acústica."]),
    ("4 REVESTIMENTOS", 1, []),
    ("4.1 Chapisco, emboço e reboco", 2, [
        "As paredes de alvenaria receberão chapisco de cimento e areia grossa (1:3), emboço e reboco de argamassa "
        "industrializada ou mista, com espessura total entre 20 e 25 mm, executados conforme a ABNT NBR 7200 e a "
        "ABNT NBR 13749. A superfície final deverá ficar desempenada, sem fissuras e pronta para pintura."]),
    ("4.2 Revestimento cerâmico em áreas molhadas", 2, [
        "As paredes dos sanitários receberão revestimento cerâmico até o teto, assentado com argamassa colante "
        "AC-II (ABNT NBR 14081) sobre emboço desempenado, conforme a ABNT NBR 13754. As juntas serão preenchidas "
        "com rejunte flexível, com largura indicada pelo fabricante.",
        "As peças serão assentadas com juntas alinhadas, iniciando pelos cantos visíveis; recortes ficarão nas áreas menos aparentes."]),
    ("5 PISOS", 1, []),
    ("5.1 Contrapiso", 2, [
        "Será executado contrapiso de argamassa de cimento e areia (1:4) com espessura média de 4 cm, "
        "nivelado e com caimento de 1% em direção aos ralos nas áreas molhadas."]),
    ("5.2 Porcelanato nas salas de aula", 2, [
        "As salas de aula receberão piso em porcelanato retificado, assentado com argamassa colante AC-III com "
        "dupla colagem, juntas de 2 mm e rodapé do mesmo material com 7 cm de altura, conforme a ABNT NBR 13753."]),
    ("5.3 Piso antiderrapante nos sanitários", 2, [
        "Os sanitários receberão piso cerâmico antiderrapante (classe de atrito adequada a áreas molhadas), "
        "assentado com argamassa colante AC-II, com caimento para os ralos sifonados."]),
    ("6 FORROS", 1, [
        "Os forros serão em placas de gesso acartonado fixadas em estrutura metálica pendurada na laje por "
        "tirantes reguláveis, com tabicas no encontro com as paredes. Nos sanitários serão usadas chapas resistentes "
        "à umidade. O acabamento final será em pintura acrílica branca fosca."]),
    ("7 ESQUADRIAS", 1, []),
    ("7.1 Portas de madeira", 2, [
        "As portas internas serão de madeira semi-oca, com folhas de 35 mm, batentes de madeira maciça e "
        "guarnições, ferragens cromadas (dobradiças, fechadura e maçanetas tipo alavanca) e pintura em esmalte."]),
    ("7.2 Esquadrias de alumínio", 2, [
        "As janelas serão em perfis de alumínio anodizado, de correr, com vidros temperados de 6 mm, fixadas por "
        "contramarcos e vedadas com silicone, atendendo à ABNT NBR 10821 quanto à estanqueidade e resistência "
        "a cargas de vento."]),
    ("7.3 Acessibilidade", 2, [
        "As portas de acesso a sanitários acessíveis terão vão livre mínimo de 80 cm e barra horizontal de puxar "
        "no lado oposto à abertura, conforme a ABNT NBR 9050."]),
    ("8 PINTURA", 1, [
        "As paredes internas receberão selador acrílico, massa corrida PVA (ou acrílica em áreas úmidas) e duas "
        "demãos de tinta acrílica fosca, conforme a ABNT NBR 13245. As cores serão definidas pela fiscalização."]),
    ("9 COBERTURA", 1, [
        "A cobertura será em telhas metálicas termoacústicas tipo sanduíche, com núcleo isolante, fixadas sobre "
        "terças metálicas com parafusos autobrocantes e arruelas de vedação. Cumeeiras, rufos e contrarrufos "
        "serão em chapa de aço galvanizado. As calhas terão caimento mínimo de 0,5% para os condutores."]),
    ("10 LIMPEZA FINAL", 1, [
        "Ao término dos serviços, a obra será entregue limpa, com remoção de entulhos, restos de materiais e "
        "manchas, e com as instalações testadas."]),
])

EST = ("Memorial de referência — Estrutura e fundações (EXEMPLO)", [
    ("1 GENERALIDADES", 1, [
        "A estrutura será executada conforme o projeto estrutural e as normas ABNT NBR 6118 (projeto de estruturas "
        "de concreto), ABNT NBR 14931 (execução de estruturas de concreto), ABNT NBR 6122 (fundações) e "
        "ABNT NBR 8800 (estruturas de aço)."]),
    ("2 FUNDAÇÕES", 1, [
        "As fundações serão do tipo sapatas isoladas de concreto armado, apoiadas sobre lastro de concreto magro "
        "com 5 cm de espessura, na cota e com as dimensões indicadas no projeto estrutural. A cota de assentamento "
        "deverá ser confirmada após a abertura das cavas, com verificação do solo.",
        "Antes da concretagem, as cavas serão limpas e as formas e armaduras conferidas pela fiscalização."]),
    ("3 ESTRUTURA DE CONCRETO ARMADO", 1, []),
    ("3.1 Concreto", 2, [
        "O concreto estrutural terá a resistência característica (fck) indicada no projeto estrutural, preparado "
        "em central e lançado em no máximo duas horas após a mistura. O adensamento será feito com vibradores de imersão."]),
    ("3.2 Formas e armaduras", 2, [
        "As formas serão em chapas de compensado plastificado, escoradas para não sofrerem deformações. As armaduras "
        "serão de aço CA-50 e CA-60, conforme a ABNT NBR 7480, com cobrimentos garantidos por espaçadores."]),
    ("3.3 Cura", 2, [
        "As peças concretadas serão mantidas úmidas por no mínimo 7 dias. As lajes serão desformadas somente nos "
        "prazos previstos na ABNT NBR 14931."]),
    ("4 ESTRUTURA METÁLICA DA COBERTURA", 1, [
        "A estrutura da cobertura será composta por tesouras e terças em perfis de aço, com ligações soldadas ou "
        "parafusadas conforme o projeto, dimensionadas segundo a ABNT NBR 8800 e, para perfis formados a frio, "
        "a ABNT NBR 14762. Todas as peças receberão limpeza, fundo anticorrosivo e pintura de acabamento.",
        "As terças serão fixadas às tesouras por chapas de ligação (consoles) e travadas por correntes rígidas."]),
    ("5 ESCADAS E GUARDA-CORPOS", 1, [
        "A escada será em concreto armado moldado no local. Os guarda-corpos terão altura mínima de 1,10 m, "
        "em tubos de aço com pintura eletrostática, e corrimãos em ambos os lados, conforme a ABNT NBR 9050."]),
])

INST = ("Memorial de referência — Instalações hidrossanitárias, elétricas e climatização (EXEMPLO)", [
    ("1 INSTALAÇÕES DE ÁGUA FRIA", 1, [
        "As instalações de água fria serão executadas conforme a ABNT NBR 5626, com tubos e conexões de PVC "
        "rígido soldável, alimentadas pelo reservatório superior. Cada ambiente com pontos de consumo terá registro "
        "de gaveta para manutenção.",
        "Antes do fechamento das paredes, a rede será submetida a ensaio de estanqueidade com pressão, por no mínimo 1 hora."]),
    ("2 ESGOTO SANITÁRIO", 1, [
        "As instalações de esgoto sanitário seguirão a ABNT NBR 8160, com tubos e conexões de PVC série normal, "
        "caimento mínimo de 2% para diâmetros até 75 mm e de 1% para diâmetros maiores. Os ralos serão sifonados, "
        "com grelha de aço inox, e haverá ventilação das colunas."]),
    ("3 LOUÇAS E METAIS", 1, [
        "As bacias sanitárias serão de louça branca com caixa acoplada de duplo acionamento. Os lavatórios serão de "
        "louça com torneiras de fechamento automático. Nos sanitários acessíveis serão instaladas barras de apoio "
        "conforme a ABNT NBR 9050."]),
    ("4 ÁGUAS PLUVIAIS", 1, [
        "As águas pluviais serão captadas por calhas e conduzidas por condutores verticais de PVC até a rede de "
        "drenagem, conforme a ABNT NBR 10844."]),
    ("5 INSTALAÇÕES ELÉTRICAS", 1, [
        "As instalações elétricas de baixa tensão seguirão a ABNT NBR 5410. Os circuitos partirão do quadro de "
        "distribuição, com disjuntores termomagnéticos e dispositivo diferencial-residual (DR) nos circuitos de "
        "tomadas de áreas molhadas. Os condutores serão de cobre com isolação antichama.",
        "As tomadas seguirão o padrão brasileiro (ABNT NBR 14136), com 2P+T. A distribuição será feita por "
        "eletrodutos e eletrocalhas metálicas, com tampas nos trechos aparentes."]),
    ("6 ILUMINAÇÃO", 1, [
        "A iluminação das salas de aula será feita por luminárias de LED de embutir, dimensionadas para atender "
        "aos níveis de iluminância da ABNT NBR ISO/CIE 8995-1 para ambientes de ensino. Os comandos serão por "
        "interruptores, separando as fileiras próximas às janelas."]),
    ("7 CLIMATIZAÇÃO E EXAUSTÃO", 1, [
        "A climatização das salas será feita por condicionadores de ar do tipo split, com capacidade definida no "
        "projeto de climatização, atendendo à ABNT NBR 16401. Os drenos serão conduzidos à rede pluvial e as linhas "
        "frigorígenas terão isolamento térmico.",
        "Os sanitários sem ventilação natural suficiente receberão exaustores mecânicos ligados ao circuito de iluminação."]),
])


def write(path: Path, title: str, sections) -> Path:
    d = Document()
    st = d.styles["Normal"]
    st.font.name = "Arial"
    st.font.size = Pt(11)
    d.add_heading(title, level=0)
    p = d.add_paragraph(AVISO)
    p.runs[0].italic = True
    for heading, level, paras in sections:
        d.add_heading(heading, level=level)
        for t in paras:
            d.add_paragraph(t)
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(path)
    return path


def main(out: Path = OUT) -> list[Path]:
    return [write(out / "Referencia_Arquitetura_e_Acabamentos_EXEMPLO.docx", *ARQ),
            write(out / "Referencia_Estrutura_e_Fundacoes_EXEMPLO.docx", *EST),
            write(out / "Referencia_Instalacoes_EXEMPLO.docx", *INST)]


if __name__ == "__main__":
    for p in main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT):
        print("gerado:", p)
