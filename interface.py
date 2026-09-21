import streamlit as st
import re
from openai import OpenAI

# Configura a página
st.set_page_config(page_title="DeepSeek Local", page_icon="🐋")
st.title("DeepSeek-R1: Interface de Teste")

# Conecta ao Docker local
client = OpenAI(base_url="http://localhost:12434/v1", api_key="docker-local")

# Inicializa o histórico de mensagens
if "mensagens" not in st.session_state:
    st.session_state.mensagens = []

# Exibe as mensagens antigas na tela
for msg in st.session_state.mensagens:
    st.chat_message(msg["role"]).write(msg["content"])

# Caixa de texto para o usuário digitar
if prompt := st.chat_input("Digite sua mensagem para o DeepSeek..."):
    
    # Adiciona a mensagem do usuário ao histórico e exibe
    st.session_state.mensagens.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    # Prepara o espaço para a resposta do assistente
    with st.chat_message("assistant"):
        resposta = client.chat.completions.create(
            model="ai/deepseek-r1-distill-llama",
            messages=st.session_state.mensagens,
            stream=False # Para visualização simples, vamos aguardar a resposta completa
        )
        
        texto_bruto = resposta.choices[0].message.content
        
        # Limpa o bloco <think> do DeepSeek para exibir apenas a resposta final
        texto_limpo = re.sub(r'<think>.*?</think>', '', texto_bruto, flags=re.DOTALL).strip()
        
        st.write(texto_limpo)
        st.session_state.mensagens.append({"role": "assistant", "content": texto_limpo})