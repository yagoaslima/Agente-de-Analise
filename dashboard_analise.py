import streamlit as st
import requests
import pandas as pd
import time
import plotly.graph_objects as go # NOVO: Biblioteca para criar os gráficos

# --- CONFIGURAÇÃO E FUNÇÕES DO AGENTE ---

st.set_page_config(page_title="Agente de Análise de Ações", layout="wide")

@st.cache_data(ttl=3600)
def get_all_tickers():
    try:
        response = requests.get("https://brapi.dev/api/quote/list" )
        response.raise_for_status()
        data = response.json()
        return sorted([stock['stock'] for stock in data['stocks']])
    except requests.exceptions.RequestException as e:
        st.error(f"Falha ao buscar a lista de ações da B3: {e}")
        return []

LISTA_COMPLETA_ACOES = get_all_tickers()
SETORES_ALTO_CRESCIMENTO = ["Tecnologia", "Varejo", "Consumo"]

def calcular_cagr(valor_inicial, valor_final, periodos):
    if valor_inicial is None or valor_final is None or valor_inicial <= 0 or periodos <= 0:
        return None
    return ((valor_final / valor_inicial) ** (1 / periodos)) - 1

# ALTERADO: A função de análise agora também retorna o setor para uso posterior
def analisar_acao(ticker, criterios_atuais):
    try:
        # NOVO: Pedimos o histórico de preços ('range=1y') e o nome da empresa
        url = f"https://brapi.dev/api/quote/{ticker}?modules=balanceSheetHistory&fundamental=true&range=1y"
        response = requests.get(url )
        response.raise_for_status()
        data = response.json()["results"][0]
        
        # ... (lógica de extração e cálculo de P/L, P/VP, ROE, ROIC, PEG Ratio - sem alterações) ...
        p_l = data.get("priceEarnings")
        p_vp = data.get("priceToBook")
        roe = data.get("returnOnEquity")
        roic = data.get("returnOnInvestedCapital")
        setor = data.get("sector", "N/A")
        peg_ratio = None
        crescimento_lpa = None
        if "balanceSheetHistory" in data and "balanceSheetStatements" in data["balanceSheetHistory"]:
            historico_lpa = [b["eps"]["raw"] for b in data["balanceSheetHistory"]["balanceSheetStatements"] if b.get("periodType") == "ANNUAL" and b.get("eps")]
            if len(historico_lpa) >= 2:
                historico_lpa.reverse()
                crescimento_lpa = calcular_cagr(historico_lpa[0], historico_lpa[-1], len(historico_lpa) - 1)
                if crescimento_lpa is not None and crescimento_lpa > 0 and p_l is not None and p_l > 0:
                    peg_ratio = p_l / (crescimento_lpa * 100)
        passou_valor = (p_l is not None and p_l <= criterios_atuais["P/L_MAX"]) and (p_vp is not None and p_vp <= criterios_atuais["P/VP_MAX"])
        passou_rentabilidade = (roe is not None and roe >= criterios_atuais["ROE_MIN"]) and (roic is not None and roic >= criterios_atuais["ROIC_MIN"])
        passou_peg = False
        if peg_ratio is not None and setor is not None:
            is_alto_crescimento = any(s in setor for s in SETORES_ALTO_CRESCIMENTO)
            if is_alto_crescimento and peg_ratio <= criterios_atuais["PEG_MAX_ALTO_CRESCIMENTO"]:
                passou_peg = True
            elif not is_alto_crescimento and criterios_atuais["PEG_MIN_BAIXO_CRESCIMENTO"] <= peg_ratio <= criterios_atuais["PEG_MAX_BAIXO_CRESCIMENTO"]:
                passou_peg = True
        status = "Aprovada ✅" if passou_valor and passou_rentabilidade and passou_peg else "Reprovada ❌"

        # NOVO: Retorna também o setor e os dados do gráfico
        return {
            "Ação": ticker, "Nome": data.get("longName", ticker), "Setor": setor,
            "P/L": p_l, "P/VP": p_vp, "ROE (%)": roe, "ROIC (%)": roic, "PEG Ratio": peg_ratio,
            "Status": status, "ChartData": data.get("historicalDataPrice")
        }
    except Exception:
        return { "Ação": ticker, "Status": "Falha na Análise ⚠️", "Setor": "N/A" }

# NOVO: Função para criar o gráfico de preços
def criar_grafico(chart_data, nome_acao):
    if not chart_data:
        return None
    df_chart = pd.DataFrame(chart_data)
    df_chart['date'] = pd.to_datetime(df_chart['date'], unit='s')
    
    fig = go.Figure(data=[go.Candlestick(x=df_chart['date'],
                                           open=df_chart['open'],
                                           high=df_chart['high'],
                                           low=df_chart['low'],
                                           close=df_chart['close'])])
    fig.update_layout(
        title=f'Histórico de Preços - {nome_acao}',
        xaxis_title='Data',
        yaxis_title='Preço (R$)',
        xaxis_rangeslider_visible=False,
        template='plotly_dark'
    )
    return fig

# --- INTERFACE STREAMLIT ---

st.title("🤖 Agente de Análise de Mercado B3")
st.markdown("Defina seus critérios, analise ações individualmente e compare o desempenho médio dos setores.")

# ... (Barra lateral com os filtros - sem alterações) ...
st.sidebar.header("Defina seus Critérios")
acoes_selecionadas = st.sidebar.multiselect("Busque e Selecione as Ações para Analisar", options=LISTA_COMPLETA_ACOES, default=["PETR4", "VALE3", "ITUB4", "MGLU3"])
st.sidebar.subheader("Filtros de Valor")
p_l_max = st.sidebar.number_input("P/L Máximo", value=11.0, step=0.5)
p_vp_max = st.sidebar.number_input("P/VP Máximo", value=1.2, step=0.1)
st.sidebar.subheader("Filtros de Rentabilidade")
roe_min = st.sidebar.number_input("ROE Mínimo (%)", value=15.0, step=1.0)
roic_min = st.sidebar.number_input("ROIC Mínimo (%)", value=15.0, step=1.0)
st.sidebar.subheader("Filtros de Crescimento (PEG Ratio)")
peg_min_baixo = st.sidebar.number_input("PEG Mín. (Baixo Cresc.)", value=0.5, step=0.1)
peg_max_baixo = st.sidebar.number_input("PEG Máx. (Baixo Cresc.)", value=1.0, step=0.1)
peg_max_alto = st.sidebar.number_input("PEG Máx. (Alto Cresc.)", value=3.0, step=0.2)
criterios_da_interface = {
    "P/L_MAX": p_l_max, "P/VP_MAX": p_vp_max, "ROE_MIN": roe_min, "ROIC_MIN": roic_min,
    "PEG_MAX_ALTO_CRESCIMENTO": peg_max_alto, "PEG_MIN_BAIXO_CRESCIMENTO": peg_min_baixo,
    "PEG_MAX_BAIXO_CRESCIMENTO": peg_max_baixo,
}

if 'resultados_df' not in st.session_state:
    st.session_state.resultados_df = pd.DataFrame()

if st.button("▶️ Iniciar Análise de Mercado"):
    # ... (Lógica do botão de análise - sem alterações) ...
    if not acoes_selecionadas:
        st.warning("Por favor, busque e selecione pelo menos uma ação na barra lateral.")
    else:
        resultados_lista = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        for i, acao in enumerate(acoes_selecionadas):
            status_text.text(f"Analisando {i+1}/{len(acoes_selecionadas)}: {acao}...")
            resultado = analisar_acao(acao, criterios_da_interface)
            resultados_lista.append(resultado)
            progress_bar.progress((i + 1) / len(acoes_selecionadas))
            time.sleep(0.1) # Reduzi o sleep para análises maiores
        status_text.success("Análise completa!")
        st.session_state.resultados_df = pd.DataFrame(resultados_lista)

if not st.session_state.resultados_df.empty:
    df = st.session_state.resultados_df.copy()
    
    st.subheader("Resultados da Análise Individual")
    
    # Formata as colunas numéricas para exibição
    colunas_numericas = ["P/L", "P/VP", "ROE (%)", "ROIC (%)", "PEG Ratio"]
    for col in colunas_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df_display = df.drop(columns=['ChartData', 'Nome'])
    st.dataframe(df_display.style.format({col: '{:.2f}' for col in colunas_numericas}, na_rep="N/A"), use_container_width=True)

    # NOVO: Seção de Gráficos para ações aprovadas
    st.subheader("Análise Gráfica das Ações Aprovadas")
    acoes_aprovadas = df[df['Status'] == 'Aprovada ✅']
    if acoes_aprovadas.empty:
        st.info("Nenhuma ação foi aprovada nos critérios para análise gráfica.")
    else:
        for _, row in acoes_aprovadas.iterrows():
            with st.expander(f"📊 {row['Nome']} ({row['Ação']})"):
                fig = criar_grafico(row['ChartData'], row['Nome'])
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Não foi possível gerar o gráfico para esta ação.")

    # NOVO: Seção de Análise Setorial
    st.subheader("Análise Comparativa de Setores")
    df_setores = df.dropna(subset=colunas_numericas) # Remove ações com dados faltantes para a média
    if not df_setores.empty:
        media_setores = df_setores.groupby('Setor')[colunas_numericas].mean()
        media_setores['Num. Ações Analisadas'] = df_setores.groupby('Setor').size()
        st.dataframe(media_setores.style.format('{:.2f}'), use_container_width=True)
    else:
        st.info("Não há dados suficientes para gerar uma análise setorial.")
