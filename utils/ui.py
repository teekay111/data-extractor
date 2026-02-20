import streamlit as st
import base64
import os

def get_image_base64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode()
    return None

def inject_custom_css():
    css_path = os.path.join("styles", "main.css")
    if os.path.exists(css_path):
        with open(css_path, "r") as f:
            css = f.read()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

def inject_logo():
    logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logo.png")
    logo_b64 = get_image_base64(logo_path)
    if logo_b64:
        logo_html = f'<img src="data:image/png;base64,{logo_b64}" class="fixed-logo">'
        st.markdown(logo_html, unsafe_allow_html=True)

def display_header(title, subtitle):
    st.markdown(f"""
        <div class="header-bar">
            <div class="header-content">
                <h1>{title}</h1>
                <p>{subtitle}</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
