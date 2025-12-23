import streamlit as st
import requests
import pandas as pd
import time

# --- CONFIGURAÇÃO INICIAL ---

# Lista completa de ações que o usuário pode escolher.
# Podemos aumentar esta lista significativamente.
LISTA_COMPLETA_ACOES = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "WEGE3", "MGLU3", 
    "LREN3", "SUZB3", "ABEV3", "BBAS3", "ELET3", "RENT3", "RADL3"
]
SETORES_ALTO_CRESCIMENTO = ["Tecnologia", "Varejo", "Consumo"]

# --- FUNÇÕES DO AGENTE (ADAPTADAS PARA RECEBER CRITÉRIOS) ---

def calcular_cagr(valor_inicial, valor_final, periodos):
    if valor_inicial is None or valor_final is None or valor_inicial <= 0 or periodos <= 0:
        return None
    return ((valor_final / valor_inicial) ** (1 / periodos)) - 1

# NOVO: A função agora recebe os critérios como um argumento
def analisar_acao(ticker, criterios_atuais):
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

        # NOVO: As verificações usam os critérios recebidos da interface
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
            "Ação": ticker, "P/L": f"{p_l:.2f}" if p_l is not None else "N/A",
            "P/VP": f"{p_vp:.2f}" if p_vp is not None else "N/A",
            "ROE (%)": f"{roe:.2f}" if roe is not None else "N/A",
            "ROIC (%)": f"{roic:.2f}" if roic is not None else "N/A",
            "PEG Ratio": f"{peg_ratio:.2f}" if peg_ratio is not None else "N/A", "Status": status
        }

    except Exception:
        return {
            "Ação": ticker, "P/L": "Erro", "P/VP": "Erro", "ROE (%)": "Erro",
            "ROIC (%)": "Erro", "PEG Ratio": "Erro", "Status": "Falha na Análise ⚠️"
        }

# --- CONSTRUÇÃO DA INTERFACE COM STREAMLIT ---

st.set_page_config(page_title="Agente de Análise de Ações", layout="wide")
st.title("🤖 Agente de IA para Análise de Ações da B3")
st.markdown("Use a barra lateral para definir seus critérios de investimento e selecionar as ações para análise.")

# NOVO: Barra lateral para os filtros
st.sidebar.header("Defina seus Critérios")

# NOVO: Seletor de ações
acoes_selecionadas = st.sidebar.multiselect(
    "Selecione as Ações para Analisar",
    options=LISTA_COMPLETA_ACOES,
    default=["PETR4", "VALE3", "ITUB4", "MGLU3"] # Ações pré-selecionadas
)

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

# NOVO: Agrupa os critérios da interface em um dicionário
criterios_da_interface = {
    "P/L_MAX": p_l_max, "P/VP_MAX": p_vp_max, "ROE_MIN": roe_min, "ROIC_MIN": roic_min,
    "PEG_MAX_ALTO_CRESCIMENTO": peg_max_alto, "PEG_MIN_BAIXO_CRESCIMENTO": peg_min_baixo,
    "PEG_MAX_BAIXO_CRESCIMENTO": peg_max_baixo,
}

if 'resultados' not in st.session_state:
    st.session_state.resultados = pd.DataFrame()

if st.button("▶️ Iniciar Análise com os Critérios Definidos"):
    if not acoes_selecionadas:
        st.warning("Por favor, selecione pelo menos uma ação na barra lateral.")
    else:
        st.session_state.resultados = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, acao in enumerate(acoes_selecionadas):
            status_text.text(f"Analisando {i+1}/{len(acoes_selecionadas)}: {acao}...")
            # NOVO: Passa os critérios da interface para a função de análise
            resultado = analisar_acao(acao, criterios_da_interface)
            st.session_state.resultados.append(resultado)
            progress_bar.progress((i + 1) / len(acoes_selecionadas))
            time.sleep(0.5)

        status_text.success("Análise completa!")
        st.session_state.resultados = pd.DataFrame(st.session_state.resultados)

if not st.session_state.resultados.empty:
    st.subheader("Resultados da Análise")
    df = st.session_state.resultados
    
    ver_aprovadas = st.checkbox("Mostrar apenas ações Aprovadas")
    if ver_aprovadas:
        df_filtrado = df[df["Status"] == "Aprovada ✅"]
        st.dataframe(df_filtrado, use_container_width=True, hide_index=True)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
