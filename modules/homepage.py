import streamlit as st

def display_homepage():
    """Displays the welcome screen and application selection buttons."""
    
    # Marker for CSS targeting (to hide sidebar on homepage)
    st.markdown('<div id="homepage-marker"></div>', unsafe_allow_html=True)

    st.title("Welcome to the Data Extractor Homepage")
    st.write("Please select the tool you would like to use:")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("CSV Query & Filter App", use_container_width=True):
            st.session_state.app_mode = "CSV"
            st.rerun()
    with col2:
        if st.button("PDF Data Extractor", use_container_width=True):
            st.session_state.app_mode = "PDF"
            st.rerun()
