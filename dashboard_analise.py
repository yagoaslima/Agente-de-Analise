import streamlit as st
import requests
import pandas as pd
import time
import plotly.graph_objects as go

# --- CONFIGURAÇÃO E FUNÇÕES DO AGENTE ---

st.set_page_config(page_title="Agente de Análise B3", layout="wide")

def fetch_data(url, token=None):
    """Realiza a requisição adicionando o token se disponível."""
    if token:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={token}"
    return requests.get(url)

@st.cache_data(ttl=3600)
def get_all_market_data(token=None):
    """Busca a lista de ativos disponíveis na B3."""
    try:
        url = "https://brapi.dev/api/quote/list"
        response = fetch_data(url, token)
        response.raise_for_status()
        data = response.json().get('stocks', [])
        df = pd.DataFrame(data)
        for col in ['stock', 'name', 'sector', 'type']:
            if col not in df.columns: df[col] = "N/A"
            else: df[col] = df[col].fillna("N/A").astype(str)
        return df[['stock', 'name', 'sector', 'type']]
    except Exception:
        return pd.DataFrame(columns=['stock', 'name', 'sector', 'type'])

# --- SIDEBAR: TOKEN ---
st.sidebar.header("🔑 Autenticação")
api_token = st.sidebar.text_input("Brapi API Token", type="password", help="Obtenha seu token gratuito em brapi.dev")

# Carregamento inicial
MARKET_DATA_DF = get_all_market_data(api_token)

if MARKET_DATA_DF.empty:
    if not api_token:
        st.warning("👉 Insira seu **API Token** da Brapi na barra lateral para começar. [brapi.dev](https://brapi.dev)")
    else:
        st.error("⚠️ Erro ao carregar dados. Verifique seu Token.")
    st.stop()

def analisar_ativo(ticker, criterios, tipo_ativo, token):
    """Analisa o ativo usando apenas o módulo 'fundamental' (compatível com plano gratuito)."""
    try:
        # Otimizado para plano gratuito: removido 'balanceSheetHistory' que causa erro 403
        url = f"https://brapi.dev/api/quote/{ticker}?fundamental=true&range=1mo&interval=1d"
        response = fetch_data(url, token)
        
        if response.status_code == 403:
            return {"Ativo": ticker, "Status": "Erro 403: Plano não permite este dado", "Setor": "N/A"}
        if response.status_code == 401:
            return {"Ativo": ticker, "Status": "Erro 401: Token Inválido", "Setor": "N/A"}
            
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

            # Análise baseada nos critérios disponíveis no plano gratuito
            passou = (p_l <= criterios["P/L_MAX"]) and (p_vp <= criterios["P/VP_MAX"]) and \
                     (roe is not None and roe >= criterios["ROE_MIN"]) and \
                     (roic is not None and roic >= criterios["ROIC_MIN"])
            
            res["Status"] = "Aprovada ✅" if passou else "Reprovada ❌"
            res.update({"P/L": p_l, "P/VP": p_vp, "ROE (%)": roe, "ROIC (%)": roic})
            
        elif tipo_ativo == 'fund':
            p_vp = data.get("priceToBook")
            dy = data.get("dividendYield")
            if p_vp is None or dy is None:
                res["Status"] = "Dados Insuficientes"
                return res
            passou = (p_vp <= criterios["P/VP_MAX_FII"]) and (dy >= criterios["DY_MIN_FII"])
            res["Status"] = "Aprovada ✅" if passou else "Reprovada ❌"
            res.update({"P/VP": p_vp, "Dividend Yield (%)": dy})
            
        return res
    except Exception as e:
        return {"Ativo": ticker, "Status": f"Erro: {str(e)}", "Setor": "N/A"}

# --- INTERFACE ---

st.title("🤖 Agente de Análise Fundamentalista B3")

st.sidebar.header("1. Seleção")
tipos = sorted(MARKET_DATA_DF['type'].unique().tolist())
tipo_sel = st.sidebar.selectbox("Tipo", options=tipos, index=tipos.index("stock") if "stock" in tipos else 0)

df_t = MARKET_DATA_DF[MARKET_DATA_DF['type'] == tipo_sel]
setores = ["Todos"] + sorted([s for s in df_t['sector'].unique().tolist() if s and s != "N/A"])
setor_sel = st.sidebar.selectbox("Setor", options=setores)

df_f = df_t.copy()
if setor_sel != "Todos": df_f = df_f[df_f['sector'] == setor_sel]

acoes_sel = st.sidebar.multiselect("Ativos", options=sorted(df_f['stock'].unique().tolist()), 
                                  default=sorted(df_f['stock'].unique().tolist())[:5] if setor_sel == "Todos" else sorted(df_f['stock'].unique().tolist()))

st.sidebar.header("2. Critérios")
crit = {}
if tipo_sel == "stock":
    crit["P/L_MAX"] = st.sidebar.number_input("P/L Máximo", 11.0)
    crit["P/VP_MAX"] = st.sidebar.number_input("P/VP Máximo", 1.2)
    crit["ROE_MIN"] = st.sidebar.number_input("ROE Mínimo (%)", 15.0)
    crit["ROIC_MIN"] = st.sidebar.number_input("ROIC Mínimo (%)", 15.0)
else:
    crit["P/VP_MAX_FII"] = st.sidebar.number_input("P/VP Máximo", 1.0)
    crit["DY_MIN_FII"] = st.sidebar.number_input("DY Mínimo (%)", 8.0)

if st.button("▶️ Iniciar Análise"):
    if not api_token:
        st.error("❌ Por favor, insira seu API Token na barra lateral.")
    elif not acoes_sel:
        st.warning("Selecione ativos.")
    else:
        res_list = []
        bar = st.progress(0)
        for i, t in enumerate(acoes_sel):
            res_list.append(analisar_ativo(t, crit, tipo_sel, api_token))
            bar.progress((i + 1) / len(acoes_sel))
            time.sleep(0.2)
        
        df_res = pd.DataFrame(res_list)
        st.subheader("Resultados")
        cols = ["Ativo", "Nome", "Setor", "Status", "P/VP"]
        if tipo_sel == "stock": cols += ["P/L", "ROE (%)", "ROIC (%)"]
        else: cols += ["Dividend Yield (%)"]
        
        st.dataframe(df_res[[c for c in cols if c in df_res.columns]].style.format(precision=2, na_rep="-"), use_container_width=True)
        
        st.subheader("Gráficos (Aprovados)")
        aprov = df_res[df_res['Status'] == 'Aprovada ✅']
        for _, r in aprov.iterrows():
            with st.expander(f"📊 {r['Ativo']} - {r['Nome']}"):
                if r.get('ChartData'):
                    df_c = pd.DataFrame(r['ChartData'])
                    df_c['date'] = pd.to_datetime(df_c['date'], unit='s')
                    fig = go.Figure(data=[go.Scatter(x=df_c['date'], y=df_c['close'], mode='lines', name='Preço')])
                    fig.update_layout(template='plotly_dark', margin=dict(l=10, r=10, t=10, b=10))
                    st.plotly_chart(fig, use_container_width=True)
