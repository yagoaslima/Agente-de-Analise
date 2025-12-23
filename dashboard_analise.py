import streamlit as st
import requests
import pandas as pd
import time
import plotly.graph_objects as go

# --- CONFIGURAÇÃO E FUNÇÕES DO AGENTE ---

st.set_page_config(page_title="Agente de Análise de Mercado", layout="wide")

# ALTERADO: Função agora busca e armazena metadados completos (ticker, setor, tipo)
@st.cache_data(ttl=3600)
def get_all_market_data():
    """Busca metadados de todos os ativos disponíveis na Brapi API."""
    try:
        response = requests.get("https://brapi.dev/api/quote/list" )
        response.raise_for_status()
        data = response.json()['stocks']
        
        # Cria um DataFrame do Pandas com todos os dados para facilitar a filtragem
        df = pd.DataFrame(data)
        df = df[['stock', 'name', 'sector', 'type']]
        df = df.dropna(subset=['sector', 'type']) # Remove ativos sem setor ou tipo definido
        return df
    except requests.exceptions.RequestException as e:
        st.error(f"Falha ao buscar a lista de ativos da B3: {e}")
        return pd.DataFrame()

# Carrega todos os dados do mercado
MARKET_DATA_DF = get_all_market_data()
SETORES_ALTO_CRESCIMENTO = ["Tecnologia", "Varejo", "Consumo"]

# (As funções 'calcular_cagr', 'analisar_acao' e 'criar_grafico' permanecem as mesmas)
def calcular_cagr(valor_inicial, valor_final, periodos):
    if valor_inicial is None or valor_final is None or valor_inicial <= 0 or periodos <= 0:
        return None
    return ((valor_final / valor_inicial) ** (1 / periodos)) - 1

def analisar_acao(ticker, criterios_atuais):
    try:
        url = f"https://brapi.dev/api/quote/{ticker}?modules=balanceSheetHistory&fundamental=true&range=1y"
        response = requests.get(url )
        response.raise_for_status()
        data = response.json()["results"][0]
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
        return {
            "Ação": ticker, "Nome": data.get("longName", ticker), "Setor": setor,
            "P/L": p_l, "P/VP": p_vp, "ROE (%)": roe, "ROIC (%)": roic, "PEG Ratio": peg_ratio,
            "Status": status, "ChartData": data.get("historicalDataPrice")
        }
    except Exception:
        return { "Ação": ticker, "Status": "Falha na Análise ⚠️", "Setor": "N/A" }

def criar_grafico(chart_data, nome_acao):
    if not chart_data:
        return None
    df_chart = pd.DataFrame(chart_data)
    df_chart['date'] = pd.to_datetime(df_chart['date'], unit='s')
    fig = go.Figure(data=[go.Candlestick(x=df_chart['date'], open=df_chart['open'], high=df_chart['high'], low=df_chart['low'], close=df_chart['close'])])
    fig.update_layout(title=f'Histórico de Preços - {nome_acao}', xaxis_title='Data', yaxis_title='Preço (R$)', xaxis_rangeslider_visible=False, template='plotly_dark')
    return fig

# --- INTERFACE STREAMLIT ---

st.title("🤖 Agente de Análise de Mercado B3")
st.markdown("Filtre por setor ou tipo de ativo, defina seus critérios e inicie a análise.")

st.sidebar.header("1. Filtros de Seleção de Ativos")

# NOVO: Lógica para os filtros de Setor e Tipo
lista_setores = ["Todos"] + sorted(MARKET_DATA_DF['sector'].unique())
setor_selecionado = st.sidebar.selectbox("Filtrar por Setor", options=lista_setores)

lista_tipos = ["Todos"] + sorted(MARKET_DATA_DF['type'].unique())
tipo_selecionado = st.sidebar.selectbox("Filtrar por Tipo de Ativo", options=lista_tipos)

# Filtra o DataFrame principal com base nas seleções
acoes_filtradas_df = MARKET_DATA_DF.copy()
if setor_selecionado != "Todos":
    acoes_filtradas_df = acoes_filtradas_df[acoes_filtradas_df['sector'] == setor_selecionado]
if tipo_selecionado != "Todos":
    acoes_filtradas_df = acoes_filtradas_df[acoes_filtradas_df['type'] == tipo_selecionado]

lista_acoes_disponiveis = sorted(acoes_filtradas_df['stock'].unique())

# ALTERADO: O multiselect agora usa a lista de ações já filtrada
st.sidebar.header("2. Escolha as Ações")
acoes_selecionadas = st.sidebar.multiselect(
    "Ativos disponíveis após filtragem",
    options=lista_acoes_disponiveis,
    default=lista_acoes_disponiveis if setor_selecionado != "Todos" else [] # Pré-seleciona todos se um setor for escolhido
)

st.sidebar.header("3. Defina seus Critérios de Análise")
# ... (Critérios de P/L, ROE, etc. - sem alterações) ...
p_l_max = st.sidebar.number_input("P/L Máximo", value=11.0, step=0.5)
p_vp_max = st.sidebar.number_input("P/VP Máximo", value=1.2, step=0.1)
roe_min = st.sidebar.number_input("ROE Mínimo (%)", value=15.0, step=1.0)
roic_min = st.sidebar.number_input("ROIC Mínimo (%)", value=15.0, step=1.0)
peg_min_baixo = st.sidebar.number_input("PEG Mín. (Baixo Cresc.)", value=0.5, step=0.1)
peg_max_baixo = st.sidebar.number_input("PEG Máx. (Baixo Cresc.)", value=1.0, step=0.1)
peg_max_alto = st.sidebar.number_input("PEG Máx. (Alto Cresc.)", value=3.0, step=0.2)
criterios_da_interface = {
    "P/L_MAX": p_l_max, "P/VP_MAX": p_vp_max, "ROE_MIN": roe_min, "ROIC_MIN": roic_min,
    "PEG_MAX_ALTO_CRESCIMENTO": peg_max_alto, "PEG_MIN_BAIXO_CRESCIMENTO": peg_min_baixo,
    "PEG_MAX_BAIXO_CRESCIMENTO": peg_max_baixo,
}

# --- LÓGICA PRINCIPAL E EXIBIÇÃO DE RESULTADOS ---
# (O restante do código para rodar a análise e exibir os resultados permanece o mesmo)
if 'resultados_df' not in st.session_state:
    st.session_state.resultados_df = pd.DataFrame()

if st.button("▶️ Iniciar Análise de Mercado"):
    if not acoes_selecionadas:
        st.warning("Por favor, selecione pelo menos uma ação na barra lateral.")
    else:
        resultados_lista = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        for i, acao in enumerate(acoes_selecionadas):
            status_text.text(f"Analisando {i+1}/{len(acoes_selecionadas)}: {acao}...")
            resultado = analisar_acao(acao, criterios_da_interface)
            resultados_lista.append(resultado)
            progress_bar.progress((i + 1) / len(acoes_selecionadas))
            time.sleep(0.1)
        status_text.success("Análise completa!")
        st.session_state.resultados_df = pd.DataFrame(resultados_lista)

if not st.session_state.resultados_df.empty:
    # ... (Toda a lógica de exibição de tabelas, gráficos e botões de download permanece a mesma) ...
    df = st.session_state.resultados_df.copy()
    st.subheader("Resultados da Análise Individual")
    colunas_numericas = ["P/L", "P/VP", "ROE (%)", "ROIC (%)", "PEG Ratio"]
    for col in colunas_numericas:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df_display = df.drop(columns=['ChartData'])
    st.dataframe(df_display.style.format({col: '{:.2f}' for col in colunas_numericas}, na_rep="N/A"), use_container_width=True)
    csv_individual = df_display.to_csv(index=False).encode('utf-8')
    st.download_button(label="📥 Baixar Relatório Individual (CSV)", data=csv_individual, file_name=f"analise_individual_{time.strftime('%Y-%m-%d')}.csv", mime="text/csv")
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
    st.subheader("Análise Comparativa de Setores")
    df_setores = df.dropna(subset=colunas_numericas)
    if not df_setores.empty:
        media_setores = df_setores.groupby('Setor')[colunas_numericas].mean()
        media_setores['Num. Ações Analisadas'] = df_setores.groupby('Setor').size()
        st.dataframe(media_setores.style.format('{:.2f}'), use_container_width=True)
        csv_setorial = media_setores.to_csv().encode('utf-8')
        st.download_button(label="📥 Baixar Relatório Setorial (CSV)", data=csv_setorial, file_name=f"analise_setorial_{time.strftime('%Y-%m-%d')}.csv", mime="text/csv")
    else:
        st.info("Não há dados suficientes para gerar uma análise setorial.")
