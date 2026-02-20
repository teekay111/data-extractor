import streamlit as st
from utils.api import configure_gemini
from utils.ui import inject_custom_css, inject_logo
from modules.homepage import display_homepage
from modules.csv_handler import handle_csv_app
from modules.pdf_handler import handle_pdf_app

def main():
    st.set_page_config(page_title="Data Extractor Homepage", page_icon="📄", layout="wide")
    
    # Configure API
    api_key = configure_gemini()
    if not api_key:
        st.warning("Please set GEMINI_API_KEY in secrets or environment variables.")
        st.stop()
    
    # Inject styling and logo
    inject_custom_css()
    inject_logo()
    
    # Sidebar for app selection
    # Using a radio button in the main area for the initial choice as requested
    if 'app_mode' not in st.session_state:
        st.session_state.app_mode = None

    if st.session_state.app_mode is None:
        display_homepage()
    else:
        # Back button will be positioned via CSS next to the logo
        st.markdown('<div id="fixed-back-container">', unsafe_allow_html=True)
        if st.button("🏠 Back to Homepage", key="global_back_button"):
            st.session_state.app_mode = None
            for key in list(st.session_state.keys()):
                if key != 'app_mode':
                    del st.session_state[key]
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Route to the selected app
        if st.session_state.app_mode == "CSV":
            handle_csv_app()
        elif st.session_state.app_mode == "PDF":
            handle_pdf_app()

if __name__ == "__main__":
    main()
