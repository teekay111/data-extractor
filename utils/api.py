import streamlit as st
import os
import google.generativeai as genai

def get_configured_api_key():
    """Load the API key from Streamlit secrets or environment variables."""
    secret_key = None
    try:
        secret_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        secret_key = None
    return secret_key or os.environ.get("GEMINI_API_KEY")

def configure_gemini():
    """Configure the Gemini API with the loaded API key."""
    api_key = get_configured_api_key()
    if api_key:
        genai.configure(api_key=api_key)
    return api_key
