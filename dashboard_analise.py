import streamlit as st
import requests
import pandas as pd
import time

# --- ETAPA 1: CONFIGURAÇÃO E FUNÇÕES DO AGENTE (Nosso código anterior adaptado) ---

# Critérios de investimento (agora podem ser ajustados na interface)
CRITERIOS = {
    "P/L_MAX": 11.0,
    "P/VP_MAX": 1.2,
    "ROE_MIN": 15.0,
    "ROIC_MIN": 15.0,
    "PEG_MAX_ALTO_CRESCIMENTO": 3.0,
    "PEG_MIN_BAIXO_CRESCIMENTO": 0.5,
    "PEG_MAX_BAIXO_CRESCIMENTO": 1.0,
}

ACOES_PARA_ANALISAR = ["PETR4", "MGLU3", "VALE3", "ITUB4", "WEGE3", "BBDC4", "LREN3", "SUZB3"]
SETORES_ALTO_CRESCIMENTO = ["Tecnologia", "Varejo", "Consumo"]

def calcular_cagr(valor_inicial, valor_final, periodos):
    if valor_inicial is None or valor_final is None or valor_inicial <= 0 or periodos <= 0:
        return None
    return ((valor_final / valor_inicial) ** (1 / periodos)) - 1

def analisar_acao(ticker):
    """Busca dados e retorna um dicionário com os resultados da análise."""
    try:
        url = f"https://brapi.dev/api/quote/{ticker}?modules=balanceSheetHistory&fundamental=true"
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

        passou_valor = (p_l is not None and p_l <= CRITERIOS["P/L_MAX"]) and (p_vp is not None and p_vp <= CRITERIOS["P/VP_MAX"])
        passou_rentabilidade = (roe is not None and roe >= CRITERIOS["ROE_MIN"]) and (roic is not None and roic >= CRITERIOS["ROIC_MIN"])
        passou_peg = False
        if peg_ratio is not None and setor is not None:
            is_alto_crescimento = any(s in setor for s in SETORES_ALTO_CRESCIMENTO)
            if is_alto_crescimento and peg_ratio <= CRITERIOS["PEG_MAX_ALTO_CRESCIMENTO"]:
                passou_peg = True
            elif not is_alto_crescimento and CRITERIOS["PEG_MIN_BAIXO_CRESCIMENTO"] <= peg_ratio <= CRITERIOS["PEG_MAX_BAIXO_CRESCIMENTO"]:
                passou_peg = True

        status = "Aprovada ✅" if passou_valor and passou_rentabilidade and passou_peg else "Reprovada ❌"

        return {
            "Ação": ticker,
            "P/L": f"{p_l:.2f}" if p_l is not None else "N/A",
            "P/VP": f"{p_vp:.2f}" if p_vp is not None else "N/A",
            "ROE (%)": f"{roe:.2f}" if roe is not None else "N/A",
            "ROIC (%)": f"{roic:.2f}" if roic is not None else "N/A",
            "PEG Ratio": f"{peg_ratio:.2f}" if peg_ratio is not None else "N/A",
            "Status": status
        }

    except Exception:
        return {
            "Ação": ticker, "P/L": "Erro", "P/VP": "Erro", "ROE (%)": "Erro",
            "ROIC (%)": "Erro", "PEG Ratio": "Erro", "Status": "Falha na Análise ⚠️"
        }

# --- ETAPA 2: CONSTRUÇÃO DA INTERFACE COM STREAMLIT ---

st.set_page_config(page_title="Agente de Análise de Ações", layout="wide")
st.title("🤖 Agente de IA para Análise de Ações da B3")
st.markdown("Este dashboard utiliza um agente de IA para analisar ações com base em critérios fundamentalistas pré-definidos.")

if 'resultados' not in st.session_state:
    st.session_state.resultados = []

if st.button("Iniciar Análise Completa"):
    st.session_state.resultados = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, acao in enumerate(ACOES_PARA_ANALISAR):
        status_text.text(f"Analisando {i+1}/{len(ACOES_PARA_ANALISAR)}: {acao}...")
        resultado = analisar_acao(acao)
        st.session_state.resultados.append(resultado)
        progress_bar.progress((i + 1) / len(ACOES_PARA_ANALISAR))
        time.sleep(0.5) # Pequena pausa para não sobrecarregar a API e melhorar a visualização

    status_text.success("Análise completa!")

if st.session_state.resultados:
    st.subheader("Resultados da Análise")
    
    # Converte a lista de dicionários em um DataFrame do Pandas para melhor visualização
    df = pd.DataFrame(st.session_state.resultados)
    
    # Filtro para visualizar apenas as aprovadas
    ver_aprovadas = st.checkbox("Mostrar apenas ações Aprovadas")
    if ver_aprovadas:
        df_filtrado = df[df["Status"] == "Aprovada ✅"]
        st.dataframe(df_filtrado, use_container_width=True)
    else:
        st.dataframe(df, use_container_width=True)

