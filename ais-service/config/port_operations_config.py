"""
Configuração por porto.

Regra do projeto: nada é inventado. Todo número tem fonte; o que não tem
fonte fica None e aparece como "sem dado" no painel.

- Calado máximo e descrição de canal/berços: página oficial do porto
  (fonte_oficial, ultima_verificacao). Calado muda com dragagem —
  reconferir antes de qualquer decisão.
- Limites operacionais: LISTA de limites por operação (navegação no canal,
  atracação, carga, fechamento da barra), cada um com documento, data e
  confiança. Um porto não tem "um" limite de vento: depende da operação e
  do navio. Fontes principais: NPCP da Capitania e normas da autoridade
  portuária (PDFs baixados manualmente em docs/fontes/).
- Índice operacional: só é calculado quando o porto tem TODOS os parâmetros
  do cálculo com fonte (maré mínima/ideal, vento ideal/limite, onda
  ideal/limite). Os valores genéricos que vinham do fork MareAgora (iguais
  em todos os portos) foram removidos por não terem fonte.
"""

from dataclasses import dataclass, field

NOS_PARA_KMH = 1.852


@dataclass
class LimiteOperacional:
    operacao: str  # "navegacao_canal" | "atracacao" | "carga" | "fechamento_barra"
    fonte: str     # URL ou nome do documento
    documento: str
    data_documento: str
    confianca: str  # "alta" (norma lida no original) | "media" (resumo/relatório) | "baixa" (terceiro)
    vento_kn: float | None = None
    onda_hs_m: float | None = None
    visibilidade_mn: float | None = None
    corrente_kn: float | None = None
    mare_minima_m: float | None = None
    aplica_a: str = "todos"
    observacao: str | None = None


@dataclass
class PortConfig:
    porto: str
    dhn_id: str
    lat: float
    lon: float
    canal: str
    estado: str = ""
    berços: str = ""
    calado_maximo_m: float | None = None
    zona_praticagem: str | None = None
    fonte_oficial: str | None = None
    ultima_verificacao: str | None = None
    calado_confianca: str | None = None  # quando a fonte do calado não é a autoridade portuária
    limites: list[LimiteOperacional] = field(default_factory=list)
    # Parâmetros do índice operacional — None = sem fonte = índice não calculado
    mare_minima_m: float | None = None
    mare_ideal_m: float | None = None
    vento_ideal_kmh: float | None = None
    vento_limite_kmh: float | None = None
    onda_ideal_m: float | None = None
    onda_limite_m: float | None = None

    @property
    def indice_calculavel(self) -> bool:
        return None not in (
            self.mare_minima_m, self.mare_ideal_m, self.vento_ideal_kmh,
            self.vento_limite_kmh, self.onda_ideal_m, self.onda_limite_m,
        )

    def limite_mais_restritivo(self, campo: str) -> float | None:
        """Menor valor de um campo (vento_kn, onda_hs_m...) entre os limites
        com fonte — usado pelos alertas de vento/ressaca."""
        valores = [getattr(lim, campo) for lim in self.limites if getattr(lim, campo) is not None]
        return min(valores) if valores else None


_NPCP_SC = "NPCP-SC/2022 e Portaria CPSC nº 44/2023 (não lidas)"

PORT_CONFIGS: dict[str, PortConfig] = {
    "santos": PortConfig(
        porto="Santos", dhn_id="50228", lat=-23.956778, lon=-46.308111, estado="SP",
        calado_maximo_m=14.5,
        canal="Canal principal com calado operacional de 15m (dragagem em andamento para 16m em 2026)",
        berços="90+ berços distribuídos em 8 terminais",
        # ZP-16: título da Portaria CPSP nº 138/2025 ("parâmetros de praticabilidade da ZP-16")
        zona_praticagem="ZP-16",
        fonte_oficial="https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/calados-operacionais-dos-bercos-de-atracacao/",
        ultima_verificacao="2026-07-22",
    ),
    "suape": PortConfig(
        porto="Suape", dhn_id="30686", lat=-8.393333, lon=-34.960000, estado="PE",
        calado_maximo_m=17.3,
        canal="Canal externo dragado a 20m; canal interno ampliado para 16,2m (concluído jan/2026)",
        berços="5 berços públicos ativos (15,5m) + terminais arrendados (Tecon Suape, APM Terminals)",
        fonte_oficial="https://www.suape.pe.gov.br/pt/73-porto/infraestutura-portuaria/guia-portuario",
        ultima_verificacao="2026-07-22",
        limites=[
            LimiteOperacional(
                operacao="atracacao", vento_kn=20, aplica_a="bacia externa",
                fonte="https://www.normasbrasil.com.br/norma/portaria-102-2025-pe_484572.html",
                documento="Portaria SUAPE nº 102 (resumo publicado; Anexo Único não lido)",
                data_documento="2025-10-02", confianca="media",
            ),
            LimiteOperacional(
                operacao="navegacao_canal", vento_kn=20, aplica_a="entrada/saída da bacia interna, LOA > 210m",
                fonte="https://www.normasbrasil.com.br/norma/portaria-102-2025-pe_484572.html",
                documento="Portaria SUAPE nº 102 (resumo publicado; Anexo Único não lido)",
                data_documento="2025-10-02", confianca="media",
                observacao="Limite de onda (Hs) está no Anexo Único, ainda não lido.",
            ),
        ],
    ),
    "vitoria": PortConfig(
        porto="Vitória", dhn_id="40256", lat=-20.321667, lon=-40.335944, estado="ES",
        calado_maximo_m=12.5,
        canal="Canal interno e externo com 14m de profundidade (Normap 84/2018)",
        berços="Cais Comercial, Capuaba e Paul, calados de 9m a 12,5m por berço",
        fonte_oficial="https://vports.com.br/",
        ultima_verificacao="2026-07-22",
    ),
    "itaqui": PortConfig(
        porto="Itaqui", dhn_id="30110", lat=-2.575472, lon=-44.369806, estado="MA",
        calado_maximo_m=22.3,
        canal="Canal natural profundo (baía de São Marcos); berços de 12m a 19,8m conforme terminal",
        berços="9 berços operacionais com profundidades de 12m a 19m",
        fonte_oficial="https://www.portodoitaqui.com/porto-do-itaqui/infraestrutura",
        ultima_verificacao="2026-07-22",
    ),
    "recife": PortConfig(
        porto="Recife", dhn_id="30645", lat=-8.056778, lon=-34.866472, estado="PE",
        calado_maximo_m=10.0,
        canal="Berços com profundidades entre 8m e 11m conforme trecho, após dragagem de manutenção",
        fonte_oficial="https://www.portodorecife.pe.gov.br/noticia-int.php?id=1624364720",
        ultima_verificacao="2026-07-22",
    ),
    "salvador": PortConfig(
        porto="Salvador", dhn_id="40141", lat=-12.973750, lon=-38.517222, estado="BA",
        calado_maximo_m=10.0,
        canal="Baía de Todos os Santos — canal principal dragado p/ 15m; sistema ReDRAFT p/ navios classe 366m",
        berços="~10 berços operacionais (cais comercial + Tecon Salvador)",
        fonte_oficial="https://www.codeba.gov.br/eficiente/sites/portalcodeba/pt-br/porto_salvador.php",
        ultima_verificacao="2026-07-22",
    ),
    "itaguai": PortConfig(
        porto="Itaguaí", dhn_id="50145", lat=-22.932083, lon=-43.842278, estado="RJ",
        calado_maximo_m=19.8,
        canal="Canal Principal e Canal da Ilha das Cabras — calado operacional de 18,3m (máx. do canal: 20m)",
        fonte_oficial="https://www.portosrio.gov.br/pt-br/node/2820",
        ultima_verificacao="2026-07-22",
    ),
    "rio_de_janeiro": PortConfig(
        porto="Rio de Janeiro", dhn_id="50140", lat=-22.896694, lon=-43.166000, estado="RJ",
        calado_maximo_m=14.6,
        canal="Canal de acesso ampliado para 16,2m de profundidade mínima",
        berços="Berços operacionais com calado de até 15,3m para navios New Panamax",
        fonte_oficial="https://www.portosrio.gov.br/",
        ultima_verificacao="2025-04-07",
    ),
    "itajai": PortConfig(
        porto="Itajaí", dhn_id="60235", lat=-26.906667, lon=-48.649167, estado="SC",
        calado_maximo_m=14.0,
        canal="Canal externo 14,0m; interno 13,6m; bacias de evolução 13,5m-13,6m",
        berços="Berços 1, 2 e 4 (13,8m), Berço 3 (13,7m), Portonave (13,5m)",
        fonte_oficial="https://www.portoitajai.com.br/Menor-profundidade-observada-(MPO)",
        ultima_verificacao="2026-07-08",
    ),
    "rio_grande": PortConfig(
        porto="Rio Grande", dhn_id="60380", lat=-32.138611, lon=-52.103611, estado="RS",
        # 12,80m desde 23/07/2024 segundo circular de agência marítima (terceiro).
        # Não é a autoridade portuária — confirmar na NPCP-RS / Portos RS.
        calado_maximo_m=12.8,
        calado_confianca="baixa — fonte de terceiro (Inchcape/ISS, 24/07/2024), a confirmar",
        canal="Calado de 12,80m desde 23/07/2024, com previsão de voltar a 14,50m após dragagem (fonte de terceiro)",
        fonte_oficial="https://www.portosrs.com.br/",
        ultima_verificacao="2024-07-24",
    ),
    "paranagua": PortConfig(
        porto="Paranaguá", dhn_id="60132", lat=-25.501667, lon=-48.531667, estado="PR",
        calado_maximo_m=12.8,
        canal="Canal da Galheta: calado máximo 12,80m; referência de 12,50m com maré zero, acima disso só "
              "com maré positiva (tabela de folga: 12,20m com -30cm a 12,80m com +30cm). Datum: NR da Marinha",
        berços="12,80m (201, 202, 204, 209, 211-214) · 12,00m (205, 206) · 12,50/11,00m (208) · 12,30m (215) · "
               "13,00m (216, 218) · 9,50m (219) · 11,60m (inflamáveis)",
        fonte_oficial="NTMPAPPA Edição 2023 Rev. VII — Portaria APPA nº 029/2024 (itens 5.2.1, 8.1); revisões são frequentes",
        ultima_verificacao="2024-02-02",
        limites=[
            LimiteOperacional(
                operacao="navegacao_canal", vento_kn=27, visibilidade_mn=1.5, aplica_a="Canal da Galheta",
                fonte="NTMPAPPA Rev. VII", documento="NTMPAPPA Edição 2023 Rev. VII, itens 8.2 e 8.7.1",
                data_documento="2024-02-02", confianca="media",
                observacao="Mar até força 5 e vento até força 6 Beaufort (27 nós = limite superior da força 6). "
                           "À noite, mar e vento até força 5.",
            ),
            LimiteOperacional(
                operacao="atracacao", vento_kn=21, visibilidade_mn=1.5,
                fonte="NTMPAPPA Rev. VII", documento="NTMPAPPA Edição 2023 Rev. VII, item 8.3",
                data_documento="2024-02-02", confianca="media",
                observacao="Vento até força 5 (21 nós).",
            ),
            LimiteOperacional(
                operacao="fechamento_barra", vento_kn=28, onda_hs_m=2.5, visibilidade_mn=0.5,
                fonte="NTMPAPPA Rev. VII", documento="NTMPAPPA Edição 2023 Rev. VII, item 8.10",
                data_documento="2024-02-02", confianca="media",
                observacao="A praticagem PODE sugerir fechar com vento força 7 (a partir de 28 nós), "
                           "visibilidade abaixo de meia milha ou ondas acima de 2,5m — citado como exemplo, não regra fixa.",
            ),
        ],
    ),
    "sao_sebastiao": PortConfig(
        porto="São Sebastião", dhn_id="50210", lat=-23.810000, lon=-45.398333, estado="SP",
        calado_maximo_m=9.4,
        canal="Canal de acesso com até 25m de profundidade; calado operacional do berço público principal: 9,4m",
        berços="1 berço principal (150m) + 2 berços internos; TEBAR/Petrobras com 14m a 26m",
        fonte_oficial="https://www.portoss.sp.gov.br/cdss/infra_portu%C3%A1ria/o_porto",
        ultima_verificacao="2026-07-22",
    ),
    "sao_francisco_do_sul": PortConfig(
        porto="São Francisco do Sul", dhn_id="60225", lat=-26.244528, lon=-48.640861, estado="SC",
        calado_maximo_m=12.80,
        canal="CMR 12,80m (berços 101, 301, 901/902-Itapoá); FAQ de 10% do calado e maré mínima de 1m "
              "nas manobras de atracação/desatracação",
        berços="101: 12,80m · 102/103: 12,00m · 201: 10,30m · 300: 12,00/12,40m · 301: 12,80m · "
               "302: 8,40-11,50m conforme LOA · Itapoá 901/902: 12,80m",
        fonte_oficial="https://portosaofrancisco.com.br/public/uploads/resolucoes/134.pdf",
        ultima_verificacao="2026-10-16",
        limites=[
            LimiteOperacional(
                operacao="atracacao", mare_minima_m=1.0,
                fonte="https://portosaofrancisco.com.br/public/uploads/resolucoes/134.pdf",
                documento="Resolução SCPAR nº 080, Art. 4º, I e III (cópia em docs/fontes/)",
                data_documento="2026-08-13", confianca="alta",
                observacao="FAQ de 10% do calado; berços 300-302 com manobra no estofo da preamar. "
                           "Vento/onda: a resolução remete à " + _NPCP_SC + ".",
            ),
        ],
    ),
    # Sem fonte pública de calado: ficam só com maré/clima até achar a norma.
    "belem": PortConfig(
        porto="Belém", dhn_id="10519", lat=-1.395917, lon=-48.492583, estado="PA",
        canal="Sem dado de calado com fonte pública (NPCP-AOR não lida).",
    ),
    "vila_do_conde": PortConfig(
        porto="Vila do Conde", dhn_id="10566", lat=-1.539139, lon=-48.753278, estado="PA",
        canal="Sem dado de calado com fonte pública (NPCP-AOR e Portaria CPAOR 58/2026 não lidas).",
    ),
    "fortaleza": PortConfig(
        porto="Fortaleza (Mucuripe)", dhn_id="30340", lat=-3.715250, lon=-38.477389, estado="CE",
        canal="Sem dado de calado com fonte pública (critérios da ZP-5 não publicados pela Capitania).",
    ),
}

# Manaus: DELIBERADAMENTE fora do PORT_CONFIGS — porto fluvial, sem tábua
# de maré. Usa o nível do Rio Negro (nivel_rio_manaus.py).

# Navegantes/Itapoá: sem estação DHN própria — usar "sao_francisco_do_sul"
# acima como referência de maré.
