import streamlit as st
import requests
import pandas as pd
import time
import plotly.graph_objects as go

# --- CONFIGURAÇÃO E FUNÇÕES DO AGENTE ---

st.set_page_config(page_title="Agente de Análise de Mercado B3", layout="wide")

@st.cache_data(ttl=3600)
def get_all_market_data():
    """Busca metadados de todos os ativos disponíveis na Brapi API."""
    try:
        response = requests.get("https://brapi.dev/api/quote/list")
        response.raise_for_status()
        data = response.json()['stocks']
        df = pd.DataFrame(data)
        # Mantemos stock, name, sector e type
        df = df[['stock', 'name', 'sector', 'type']].dropna(subset=['type'])
        return df
    except Exception as e:
        st.error(f"Falha ao buscar a lista de ativos da B3: {e}")
        return pd.DataFrame()

MARKET_DATA_DF = get_all_market_data()
SETORES_ALTO_CRESCIMENTO = ["Tecnologia", "Varejo", "Consumo"]

def calcular_cagr(valor_inicial, valor_final, periodos):
    if valor_inicial is None or valor_final is None or valor_inicial <= 0 or periodos <= 0:
        return None
    return ((valor_final / valor_inicial) ** (1 / periodos)) - 1

def analisar_ativo(ticker, criterios, tipo_ativo):
    """
    Analisa um ativo (Ação ou FII) com base em critérios específicos.
    """
    try:
        # Buscamos dados fundamentalistas e histórico de 1 ano
        url = f"https://brapi.dev/api/quote/{ticker}?modules=balanceSheetHistory&fundamental=true&range=1y"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()["results"][0]
        
        nome = data.get("longName", ticker)
        setor = data.get("sector", "N/A")
        chart_data = data.get("historicalDataPrice")
        
        # --- LÓGICA PARA AÇÕES ---
        if tipo_ativo == 'stock':
            p_l = data.get("priceEarnings")
            p_vp = data.get("priceToBook")
            roe = data.get("returnOnEquity")
            roic = data.get("returnOnInvestedCapital")
            
            # Verificação de dados mínimos para ações
            if p_l is None or p_vp is None:
                return {"Ação": ticker, "Nome": nome, "Status": "Dados Insuficientes", "Setor": setor}

            # Cálculo do PEG Ratio
            peg_ratio = None
            if "balanceSheetHistory" in data and "balanceSheetStatements" in data["balanceSheetHistory"]:
                historico_lpa = [b["eps"]["raw"] for b in data["balanceSheetHistory"]["balanceSheetStatements"] if b.get("periodType") == "ANNUAL" and b.get("eps")]
                if len(historico_lpa) >= 2:
                    historico_lpa.reverse()
                    crescimento_lpa = calcular_cagr(historico_lpa[0], historico_lpa[-1], len(historico_lpa) - 1)
                    if crescimento_lpa and crescimento_lpa > 0:
                        peg_ratio = p_l / (crescimento_lpa * 100)

            # Aplicação dos filtros de Ações
            passou_valor = (p_l <= criterios["P/L_MAX"]) and (p_vp <= criterios["P/VP_MAX"])
            passou_rentabilidade = (roe is not None and roe >= criterios["ROE_MIN"]) and (roic is not None and roic >= criterios["ROIC_MIN"])
            
            passou_peg = False
            if peg_ratio is not None:
                is_alto = any(s in setor for s in SETORES_ALTO_CRESCIMENTO)
                if is_alto and peg_ratio <= criterios["PEG_MAX_ALTO"]:
                    passou_peg = True
                elif not is_alto and criterios["PEG_MIN_BAIXO"] <= peg_ratio <= criterios["PEG_MAX_BAIXO"]:
                    passou_peg = True
            
            status = "Aprovada ✅" if passou_valor and passou_rentabilidade and passou_peg else "Reprovada ❌"
            
            return {
                "Ativo": ticker, "Nome": nome, "Setor": setor, "Status": status,
                "P/L": p_l, "P/VP": p_vp, "ROE (%)": roe, "ROIC (%)": roic, "PEG Ratio": peg_ratio,
                "ChartData": chart_data
            }

        # --- LÓGICA PARA FIIs ---
        elif tipo_ativo == 'fund':
            p_vp = data.get("priceToBook")
            dy = data.get("dividendYield") # A Brapi costuma fornecer o DY atualizado
            
            if p_vp is None or dy is None:
                return {"Ativo": ticker, "Nome": nome, "Status": "Dados Insuficientes", "Setor": setor}
            
            passou_fii = (p_vp <= criterios["P/VP_MAX_FII"]) and (dy >= criterios["DY_MIN_FII"])
            status = "Aprovada ✅" if passou_fii else "Reprovada ❌"
            
            return {
                "Ativo": ticker, "Nome": nome, "Setor": setor, "Status": status,
                "P/VP": p_vp, "Dividend Yield (%)": dy,
                "ChartData": chart_data
            }
            
        else:
            return {"Ativo": ticker, "Status": "Tipo não suportado", "Setor": setor}

    except Exception as e:
        return {"Ativo": ticker, "Status": f"Erro: {str(e)}", "Setor": "N/A"}

def criar_grafico(chart_data, nome_ativo):
    if not chart_data: return None
    df_chart = pd.DataFrame(chart_data)
    df_chart['date'] = pd.to_datetime(df_chart['date'], unit='s')
    fig = go.Figure(data=[go.Candlestick(x=df_chart['date'], open=df_chart['open'], high=df_chart['high'], low=df_chart['low'], close=df_chart['close'])])
    fig.update_layout(title=f'Histórico - {nome_ativo}', xaxis_title='Data', yaxis_title='Preço (R$)', xaxis_rangeslider_visible=False, template='plotly_dark')
    return fig

# --- INTERFACE STREAMLIT ---

st.sidebar.header("1. Seleção de Ativos")
tipo_selecionado = st.sidebar.selectbox("Tipo de Ativo", options=["Ações (stock)", "FIIs (fund)"])
tipo_key = "stock" if "stock" in tipo_selecionado else "fund"

lista_setores = ["Todos"] + sorted(MARKET_DATA_DF[MARKET_DATA_DF['type'] == tipo_key]['sector'].unique().tolist())
setor_selecionado = st.sidebar.selectbox("Filtrar por Setor", options=lista_setores)

df_filtrado = MARKET_DATA_DF[MARKET_DATA_DF['type'] == tipo_key]
if setor_selecionado != "Todos":
    df_filtrado = df_filtrado[df_filtrado['sector'] == setor_selecionado]

acoes_selecionadas = st.sidebar.multiselect(
    "Selecione os Ativos", 
    options=sorted(df_filtrado['stock'].unique()),
    default=sorted(df_filtrado['stock'].unique()) if setor_selecionado != "Todos" else []
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

# --- EXECUÇÃO ---

st.title(f"🤖 Agente de Análise: {'Ações' if tipo_key == 'stock' else 'FIIs'}")

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
        df_res = pd.DataFrame(resultados)
        
        st.subheader("Resultados")
        # Colunas para exibir dependendo do tipo
        cols_to_show = ["Ativo", "Nome", "Setor", "Status", "P/VP"]
        if tipo_key == "stock":
            cols_to_show += ["P/L", "ROE (%)", "ROIC (%)", "PEG Ratio"]
        else:
            cols_to_show += ["Dividend Yield (%)"]
            
        st.dataframe(df_res[cols_to_show].style.format(precision=2, na_rep="-"), use_container_width=True)
        
        # Download
        csv = df_res[cols_to_show].to_csv(index=False).encode('utf-8')
        st.download_button("📥 Baixar CSV", csv, f"analise_{tipo_key}.csv", "text/csv")
        
        # Gráficos
        st.subheader("Gráficos (Aprovados)")
        aprovados = df_res[df_res['Status'] == 'Aprovada ✅']
        if aprovados.empty:
            st.info("Nenhum ativo aprovado.")
        else:
            for _, row in aprovados.iterrows():
                with st.expander(f"📊 {row['Ativo']} - {row['Nome']}"):
                    fig = criar_grafico(row['ChartData'], row['Nome'])
                    if fig: st.plotly_chart(fig, use_container_width=True)
