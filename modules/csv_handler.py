import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
from PIL import Image
from utils.ui import display_header

def analyze_prompt_intent(prompt, df_columns):
    """Asks Gemini to classify the user's prompt."""
    model = genai.GenerativeModel('gemini-flash-latest')
    
    classification_prompt = f"""
    You are a data assistant.
    The user is asking a question about a DataFrame with these columns: {df_columns}
    
    User Query: "{prompt}"
    
    Analyze the user's intent. 
    1. Does the user want to FILTER/SELECT a subset of data? (e.g., "Show me red ones", "Filter by status Open", "Remove X")
    2. Does the user want to ask a QUESTION about the data? (e.g., "Why are they red?", "Summarize this", "What is the count?", "Explain the findings")
    
    Respond with a JSON object exactly like this:
    {{"filter": true, "question": false}}
    """
    
    try:
        response = model.generate_content(classification_prompt)
        text = response.text.replace('```json', '').replace('```', '').strip()
        result = json.loads(text)
        return result
    except:
        return {"filter": False, "question": True}

def filter_data_with_gemini(df, prompt):
    """Uses Gemini to generate Pandas filtering code based on the user's prompt."""
    columns_info = df.dtypes.to_string()
    sample_data = df.head(3).to_markdown(index=False)
    
    model = genai.GenerativeModel('gemini-flash-latest')
    
    base_prompt = f"""
    You are a Python data expert. 
    Given the following DataFrame `df` with columns:
    {columns_info}
    
    And sample data:
    {sample_data}
    
    Write a SINGLE LINE of Python code to filter `df` based on this user request:
    "{prompt}"
    
    The code must assign the result to a variable named `filtered_df`.
    Example: filtered_df = df[df['Status'] == 'Open']
    
    IMPORTANT:
    - Return ONLY the code. No markdown formatting.
    - The result `filtered_df` MUST be a Pandas DataFrame.
    - Handle case sensitivity by using .str.contains(..., case=False) if searching text.
    """
    
    current_prompt = base_prompt
    max_retries = 2
    
    for attempt in range(max_retries + 1):
        try:
            response = model.generate_content(current_prompt)
            generated_code = response.text.strip().replace('```python', '').replace('```', '').strip()
            
            local_vars = {'df': df, 'pd': pd}
            st.info(f"Generated Filter Code (Attempt {attempt+1}): `{generated_code}`")
            exec(generated_code, {}, local_vars)
            
            if 'filtered_df' in local_vars:
                result = local_vars['filtered_df']
                if not isinstance(result, pd.DataFrame):
                    if isinstance(result, pd.Series):
                        result = result.to_frame()
                    else:
                        result = pd.DataFrame(result)
                return result, generated_code
            else:
                raise ValueError("Code did not generate 'filtered_df' variable.")
                
        except Exception as e:
            error_msg = str(e)
            st.warning(f"Attempt {attempt+1} failed: {error_msg}. Retrying...")
            current_prompt = f"{base_prompt}\n\nThe previous code:\n{generated_code}\n\nFailed with this error:\n{error_msg}\n\nPlease fix the code."
            
    st.error("Failed to generate valid filtering code after retries.")
    return pd.DataFrame(), None

def explain_filter_code(code):
    """Uses Gemini to explain the generated Pandas filtering code in plain English."""
    if not code:
        return "No filtering code was generated."
    
    model = genai.GenerativeModel('gemini-flash-latest')
    explanation_prompt = f"Explain the following Pandas filtering code in one sentence in plain English. Code:\n{code}"
    
    try:
        response = model.generate_content(explanation_prompt)
        return response.text.strip()
    except Exception as e:
        return f"Error generating explanation: {e}"

def get_answer(filtered_df, prompt, history_context=""):
    """Generates an answer using Gemini API based on the filtered data."""
    if filtered_df.empty:
        return f"No relevant data found to answer the question: '{prompt}'"
    
    data_context = filtered_df.to_csv(index=False)
    model = genai.GenerativeModel('gemini-flash-latest') 
    
    full_prompt = f"""
    Answer the following question based on the provided data context and history.
    
    Data Context (CSV):
    {data_context}
    
    History:
    {history_context}
    
    Question:
    {prompt}
    """
    
    try:
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"Error generating answer: {e}"

def handle_csv_app():
    display_header("CSV Query App", "Automated CSV analysis and filtering powered by Gemini.")
    st.markdown("Upload a CSV file and filter it based on your query.")
    
    # Load logo for avatar
    try:
        logo_img = Image.open("logo.png")
    except:
        logo_img = "🤖"

    uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])
    
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            st.info("CSV uploaded successfully!")
            
            st.subheader("Step 1: Filter the Data")
            filter_prompt = st.text_area("Enter your filtering criteria:", height=100, key="filter_prompt")
            
            if st.button("Filter Data"):
                if filter_prompt:
                    with st.spinner("Filtering data..."):
                        filtered_data, generated_code = filter_data_with_gemini(df, filter_prompt)
                        explanation = explain_filter_code(generated_code)
                        
                        st.session_state['filtered_data'] = filtered_data
                        st.session_state['explanation'] = explanation
                        st.session_state['filter_applied'] = True
                        st.session_state.messages = []
                        st.session_state['chat_df'] = filtered_data.copy()
                else:
                    st.warning("Please enter a filtering criteria.")
            
            if st.session_state.get('filter_applied', False):
                filtered_data = st.session_state['filtered_data']
                explanation = st.session_state.get('explanation', '')
                
                if explanation:
                    st.info(f"**Filter Explanation:** {explanation}")
                
                st.subheader("Filtered Data")
                st.dataframe(filtered_data)
                st.info(f"Showing {len(filtered_data)} rows")
                
                st.subheader("Step 2: Ask Questions or Apply Further Filters")
                
                if "messages" not in st.session_state:
                    st.session_state.messages = []

                for message in st.session_state.messages:
                    if message.get("type") == "dataframe":
                        st.dataframe(message["content"])
                    elif message.get("type") == "info":
                        st.info(message["content"])
                    else:
                        avatar = logo_img if message["role"] == "assistant" else "👤"
                        with st.chat_message(message["role"], avatar=avatar):
                             st.markdown(message["content"])

                if prompt := st.chat_input("Ask a question or apply a filter..."):
                    st.chat_message("user", avatar="👤").markdown(prompt)
                    st.session_state.messages.append({"role": "user", "content": prompt})
                    
                    history_context = ""
                    for msg in st.session_state.messages[:-1]:
                        role = "User" if msg["role"] == "user" else "Assistant"
                        history_context += f"{role}: {msg['content']}\n"

                    with st.spinner("Thinking..."):
                        if 'chat_df' not in st.session_state:
                             st.session_state['chat_df'] = st.session_state.get('filtered_data', df).copy()

                        current_df = st.session_state['chat_df']
                        intent = analyze_prompt_intent(prompt, current_df.columns.to_list())
                        
                        if intent.get('filter', False):
                            st.chat_message("assistant", avatar=logo_img).write("Applying filter logic...")
                            new_filtered_data, generated_code = filter_data_with_gemini(current_df, prompt)
                            
                            if not new_filtered_data.empty:
                                st.session_state['chat_df'] = new_filtered_data
                                current_df = new_filtered_data 
                                explanation = explain_filter_code(generated_code)
                                st.info(f"**Filter Logic:** {explanation}")
                                st.dataframe(current_df)
                                st.session_state.messages.append({"role": "assistant", "content": f"**Filter Logic:** {explanation}", "type": "info"})
                                st.session_state.messages.append({"role": "assistant", "content": current_df, "type": "dataframe"})
                            else:
                                st.chat_message("assistant", avatar=logo_img).warning("Filter returned no results.")

                        if intent.get('question', False):
                            response = get_answer(current_df, prompt, history_context)
                            with st.chat_message("assistant", avatar=logo_img):
                                st.markdown(response)
                            st.session_state.messages.append({"role": "assistant", "content": response})
                        
        except Exception as e:
            st.error(f"Error reading CSV: {e}")
