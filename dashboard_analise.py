import streamlit as st
import requests
import pandas as pd
import time
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- CONFIGURAÇÃO E FUNÇÕES DO AGENTE ---

st.set_page_config(page_title="Agente de Análise de Mercado B3", layout="wide")

@st.cache_data(ttl=3600)
def get_all_market_data():
    """Busca metadados de todos os ativos disponíveis na Brapi API."""
    try:
        response = requests.get("https://brapi.dev/api/quote/list")
        response.raise_for_status()
        data = response.json().get('stocks', [])
        if not data:
            return pd.DataFrame(columns=['stock', 'name', 'sector', 'type'])
        
        df = pd.DataFrame(data)
        
        # Garantir que as colunas existam e preencher nulos com "N/A"
        for col in ['stock', 'name', 'sector', 'type']:
            if col not in df.columns:
                df[col] = "N/A"
            else:
                df[col] = df[col].fillna("N/A").astype(str)
        
        return df[['stock', 'name', 'sector', 'type']]
    except Exception as e:
        return pd.DataFrame(columns=['stock', 'name', 'sector', 'type'])

# Carregamento inicial com verificação
MARKET_DATA_DF = get_all_market_data()

if MARKET_DATA_DF.empty:
    st.error("⚠️ Não foi possível carregar os dados da B3. Verifique sua conexão ou tente novamente mais tarde.")
    st.stop()

SETORES_ALTO_CRESCIMENTO = ["Tecnologia", "Varejo", "Consumo"]

def calcular_cagr(valor_inicial, valor_final, periodos):
    if valor_inicial is None or valor_final is None or valor_inicial <= 0 or periodos <= 0:
        return None
    return ((valor_final / valor_inicial) ** (1 / periodos)) - 1

def analisar_ativo(ticker, criterios, tipo_ativo):
    try:
        url = f"https://brapi.dev/api/quote/{ticker}?modules=balanceSheetHistory&fundamental=true&range=5y&interval=1d"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()["results"][0]
        
        nome = data.get("longName", ticker)
        setor = data.get("sector", "N/A")
        chart_data = data.get("historicalDataPrice")
        
        res = {"Ativo": ticker, "Nome": nome, "Setor": setor, "ChartData": chart_data}
        
        if tipo_ativo == 'stock':
            p_l = data.get("priceEarnings")
            p_vp = data.get("priceToBook")
            roe = data.get("returnOnEquity")
            roic = data.get("returnOnInvestedCapital")
            
            if p_l is None or p_vp is None:
                res["Status"] = "Dados Insuficientes"
                return res

            peg_ratio = None
            if "balanceSheetHistory" in data and "balanceSheetStatements" in data["balanceSheetHistory"]:
                historico_lpa = [b["eps"]["raw"] for b in data["balanceSheetHistory"]["balanceSheetStatements"] if b.get("periodType") == "ANNUAL" and b.get("eps")]
                if len(historico_lpa) >= 2:
                    historico_lpa.reverse()
                    crescimento_lpa = calcular_cagr(historico_lpa[0], historico_lpa[-1], len(historico_lpa) - 1)
                    if crescimento_lpa and crescimento_lpa > 0:
                        peg_ratio = p_l / (crescimento_lpa * 100)

            passou_valor = (p_l <= criterios["P/L_MAX"]) and (p_vp <= criterios["P/VP_MAX"])
            passou_rentabilidade = (roe is not None and roe >= criterios["ROE_MIN"]) and (roic is not None and roic >= criterios["ROIC_MIN"])
            
            passou_peg = False
            if peg_ratio is not None:
                is_alto = any(s in setor for s in SETORES_ALTO_CRESCIMENTO)
                if is_alto and peg_ratio <= criterios["PEG_MAX_ALTO"]:
                    passou_peg = True
                elif not is_alto and criterios["PEG_MIN_BAIXO"] <= peg_ratio <= criterios["PEG_MAX_BAIXO"]:
                    passou_peg = True
            
            res["Status"] = "Aprovada ✅" if passou_valor and passou_rentabilidade and passou_peg else "Reprovada ❌"
            res.update({"P/L": p_l, "P/VP": p_vp, "ROE (%)": roe, "ROIC (%)": roic, "PEG Ratio": peg_ratio})
            
        elif tipo_ativo == 'fund':
            p_vp = data.get("priceToBook")
            dy = data.get("dividendYield")
            if p_vp is None or dy is None:
                res["Status"] = "Dados Insuficientes"
                return res
            passou_fii = (p_vp <= criterios["P/VP_MAX_FII"]) and (dy >= criterios["DY_MIN_FII"])
            res["Status"] = "Aprovada ✅" if passou_fii else "Reprovada ❌"
            res.update({"P/VP": p_vp, "Dividend Yield (%)": dy})
            
        return res
    except Exception as e:
        return {"Ativo": ticker, "Status": f"Erro: {str(e)}", "Setor": "N/A"}

def criar_grafico_comparativo(df_performance, periodo_nome):
    fig = go.Figure()
    for coluna in df_performance.columns:
        fig.add_trace(go.Scatter(x=df_performance.index, y=df_performance[coluna], name=coluna, mode='lines'))
    
    fig.update_layout(
        title=f'Performance Acumulada ({periodo_nome}) - Sua Carteira vs IBOVESPA',
        xaxis_title='Data',
        yaxis_title='Retorno Acumulado (%)',
        template='plotly_dark',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

# --- INTERFACE STREAMLIT ---

st.sidebar.header("1. Seleção de Ativos")

# Limpeza e preparação de tipos
tipos_disponiveis = sorted(MARKET_DATA_DF['type'].unique().tolist())
tipo_selecionado = st.sidebar.selectbox("Tipo de Ativo", options=tipos_disponiveis, index=tipos_disponiveis.index("stock") if "stock" in tipos_disponiveis else 0)
tipo_key = tipo_selecionado

# Filtragem segura de setores
df_tipo = MARKET_DATA_DF[MARKET_DATA_DF['type'] == tipo_key]
setores_unicos = [s for s in df_tipo['sector'].unique().tolist() if s and s != "nan" and s != "N/A"]
lista_setores = ["Todos"] + sorted(setores_unicos)
setor_selecionado = st.sidebar.selectbox("Filtrar por Setor", options=lista_setores)

df_filtrado = df_tipo.copy()
if setor_selecionado != "Todos":
    df_filtrado = df_filtrado[df_filtrado['sector'] == setor_selecionado]

lista_acoes_disponiveis = sorted(df_filtrado['stock'].unique().tolist())

acoes_selecionadas = st.sidebar.multiselect(
    "Selecione os Ativos", 
    options=lista_acoes_disponiveis,
    default=lista_acoes_disponiveis[:5] if setor_selecionado == "Todos" and len(lista_acoes_disponiveis) > 0 else lista_acoes_disponiveis
)

st.sidebar.header("2. Critérios de Análise")
criterios = {}
if tipo_key == "stock":
    criterios["P/L_MAX"] = st.sidebar.number_input("P/L Máximo", value=11.0, step=0.5)
    criterios["P/VP_MAX"] = st.sidebar.number_input("P/VP Máximo", value=1.2, step=0.1)
    criterios["ROE_MIN"] = st.sidebar.number_input("ROE Mínimo (%)", value=15.0, step=1.0)
    criterios["ROIC_MIN"] = st.sidebar.number_input("ROIC Mínimo (%)", value=15.0, step=1.0)
    criterios["PEG_MIN_BAIXO"] = st.sidebar.number_input("PEG Mín. (Baixo Cresc.)", value=0.5, step=0.1)
    criterios["PEG_MAX_BAIXO"] = st.sidebar.number_input("PEG Máx. (Baixo Cresc.)", value=1.0, step=0.1)
    criterios["PEG_MAX_ALTO"] = st.sidebar.number_input("PEG Máx. (Alto Cresc.)", value=3.0, step=0.2)
else:
    criterios["P/VP_MAX_FII"] = st.sidebar.number_input("P/VP Máximo (FII)", value=1.0, step=0.05)
    criterios["DY_MIN_FII"] = st.sidebar.number_input("Dividend Yield Mínimo (%)", value=8.0, step=0.5)

st.sidebar.header("3. Configuração do Backtesting")
periodo_backtest = st.sidebar.selectbox("Período de Simulação", options=["1 Ano", "2 Anos", "5 Anos"])
dias_map = {"1 Ano": 365, "2 Anos": 730, "5 Anos": 1825}

# --- EXECUÇÃO ---

st.title(f"🤖 Agente de Análise e Backtesting: {tipo_key.upper()}")

tab1, tab2 = st.tabs(["🔍 Análise Atual", "📈 Backtesting de Performance"])

with tab1:
    if st.button("▶️ Iniciar Análise"):
        if not acoes_selecionadas:
            st.warning("Selecione ao menos um ativo.")
        else:
            resultados = []
            progresso = st.progress(0)
            status_msg = st.empty()
            for i, ticker in enumerate(acoes_selecionadas):
                status_msg.text(f"Analisando {ticker}...")
                res = analisar_ativo(ticker, criterios, tipo_key)
                resultados.append(res)
                progresso.progress((i + 1) / len(acoes_selecionadas))
                time.sleep(0.1)
            status_msg.success("Análise concluída!")
            st.session_state.df_res = pd.DataFrame(resultados)
            
    if 'df_res' in st.session_state:
        df_res = st.session_state.df_res
        st.subheader("Resultados da Estratégia")
        
        # Colunas dinâmicas baseadas no tipo
        cols_to_show = ["Ativo", "Nome", "Setor", "Status", "P/VP"]
        if tipo_key == "stock":
            cols_to_show += ["P/L", "ROE (%)", "ROIC (%)", "PEG Ratio"]
        else:
            cols_to_show += ["Dividend Yield (%)"]
        
        cols_existentes = [c for c in cols_to_show if c in df_res.columns]
        st.dataframe(df_res[cols_existentes].style.format(precision=2, na_rep="-"), use_container_width=True)
        
        # Gráficos Individuais
        st.subheader("Gráficos de Preço (Aprovados)")
        if "Status" in df_res.columns:
            aprovados = df_res[df_res['Status'] == 'Aprovada ✅']
            if aprovados.empty:
                st.info("Nenhum ativo aprovado nos critérios atuais.")
            else:
                for _, row in aprovados.iterrows():
                    with st.expander(f"📊 {row['Ativo']} - {row['Nome']}"):
                        if row.get('ChartData'):
                            df_chart = pd.DataFrame(row['ChartData'])
                            df_chart['date'] = pd.to_datetime(df_chart['date'], unit='s')
                            fig = go.Figure(data=[go.Candlestick(x=df_chart['date'], open=df_chart['open'], high=df_chart['high'], low=df_chart['low'], close=df_chart['close'])])
                            fig.update_layout(xaxis_rangeslider_visible=False, template='plotly_dark', margin=dict(l=20, r=20, t=20, b=20))
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.warning("Dados de gráfico não disponíveis.")

with tab2:
    st.subheader("Simulação: Como as ações aprovadas hoje renderam no passado?")
    if 'df_res' not in st.session_state:
        st.warning("Primeiro, execute a 'Análise Atual' na primeira aba.")
    else:
        df_res = st.session_state.df_res
        if "Status" in df_res.columns:
            aprovados = df_res[df_res['Status'] == 'Aprovada ✅']
            if aprovados.empty:
                st.error("Não há ações aprovadas para realizar o backtesting.")
            else:
                if st.button("🚀 Rodar Simulação Histórica"):
                    with st.spinner("Buscando dados históricos..."):
                        try:
                            res_ibov = requests.get("https://brapi.dev/api/quote/%5EBVSP?range=5y&interval=1d").json()["results"][0]
                            df_ibov = pd.DataFrame(res_ibov["historicalDataPrice"])
                            df_ibov['date'] = pd.to_datetime(df_ibov['date'], unit='s')
                            df_ibov.set_index('date', inplace=True)
                            
                            data_inicio = datetime.now() - timedelta(days=dias_map[periodo_backtest])
                            df_ibov = df_ibov[df_ibov.index >= data_inicio]
                            ibov_inicio = df_ibov['close'].iloc[0]
                            df_ibov['IBOVESPA (%)'] = (df_ibov['close'] / ibov_inicio - 1) * 100
                            
                            performances = []
                            for _, row in aprovados.iterrows():
                                if row.get('ChartData'):
                                    df_stock = pd.DataFrame(row['ChartData'])
                                    df_stock['date'] = pd.to_datetime(df_stock['date'], unit='s')
                                    df_stock.set_index('date', inplace=True)
                                    df_stock = df_stock[df_stock.index >= data_inicio]
                                    if not df_stock.empty:
                                        stock_inicio = df_stock['close'].iloc[0]
                                        df_stock[row['Ativo']] = (df_stock['close'] / stock_inicio - 1) * 100
                                        performances.append(df_stock[row['Ativo']])
                            
                            if performances:
                                df_final = pd.concat(performances, axis=1).fillna(method='ffill')
                                df_final['SUA CARTEIRA (%)'] = df_final.mean(axis=1)
                                df_final = df_final.join(df_ibov['IBOVESPA (%)'], how='inner')
                                st.plotly_chart(criar_grafico_comparativo(df_final[['SUA CARTEIRA (%)', 'IBOVESPA (%)']], periodo_backtest), use_container_width=True)
                                c1, c2, c3 = st.columns(3)
                                c1.metric("Retorno da Carteira", f"{df_final['SUA CARTEIRA (%)'].iloc[-1]:.2f}%")
                                c2.metric("Retorno IBOVESPA", f"{df_final['IBOVESPA (%)'].iloc[-1]:.2f}%")
                                c3.metric("Alpha", f"{df_final['SUA CARTEIRA (%)'].iloc[-1] - df_final['IBOVESPA (%)'].iloc[-1]:.2f}%")
                            else:
                                st.error("Dados históricos insuficientes.")
                        except Exception as e:
                            st.error(f"Erro: {e}")
