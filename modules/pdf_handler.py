import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import re
import time
import tempfile
import os
import base64
from io import BytesIO
import pdfplumber
from streamlit_pdf_viewer import pdf_viewer
from utils.ui import display_header

# Constants
DEFAULT_MODEL_NAME = "gemini-flash-latest"

NC_BOUNDARY_RULES = """
CRITICAL RULES FOR NON-CONFORMITY EXTRACTION:

- A new Non-Conformity (NC) may ONLY start when an explicit anchor is detected:
  "Indicator:", "NC number:", or a numbered NC section header.

- STOP extracting the current NC immediately when the NEXT NC anchor appears,
  even if it is on the SAME PAGE.

- DO NOT carry forward, infer, reuse, or merge information from a previous NC.

- Each NC is an isolated record.
  If a field is missing for an NC, return null or empty string.

- DO NOT include Observations, Conclusions, or other sections
  unless they are explicitly inside the NC table.
"""

NC_COLUMNS = {
    "NC number": "List every NC number recorded. If none, return 'None'.",
    "Client name": "List the client name(s) associated with the NCs. Use 'Unknown' if not stated.",
    "Indicator": "Copy the referenced Indicator in the standard for each NC.",
    "Grade": "State the grade (Major, Minor, Critical, Non-critical, Opportunities for Improvement etc.) for each NC.",
    "Status": "Open or Closed. Open if there is no closed date, closed if there is one.",
    "Issue Date": "Provide the date each NC was issued. Use the format (DD-MM-YYYY).",
    "Closed date": "Provide the date each NC was closed. Use the format (DD-MM-YYYY).",
    "Scope Definition": "Summarize the scope definition or description for each NC."
}

DEFAULT_NC_SCHEMA = [{"Column Name": col, "Question": desc} for col, desc in NC_COLUMNS.items()]
NC_SPLIT_COLUMNS = {"NC number", "Client name", "Indicator", "Grade", "Status", "Issue Date", "Closed date"}

NC_SECTIONS = [
    {
        "key": "audit_nc",
        "title": "4.3.1 Non-Conformities Identified during this Audit",
        "instruction_array": """
        Focus strictly on Section 4.3.1 Non-Conformities Identified during this Audit.

        Extract ONLY Non-Conformity tables that belong to this section.

        Each NC MUST:
        - Start at an explicit anchor (Indicator or NC number)
        - End before the next NC anchor or next section header

        Return a JSON ARRAY where each element represents exactly ONE NC.
        """,
        "instruction_fallback": "Focus strictly on Section 4.3.1. Return a JSON object with ';' separated values.",
        "file_name": "non_conformities_current_audit.csv"
    },
    {
        "key": "previous_nc",
        "title": "4.3.2 Non-Conformities Identified during the last ASA",
        "instruction_array": """Focus strictly on Section 4.3.2 Non-Conformities Identified during the last ASA.

        Extract ONLY Non-Conformity tables that belong to this section.

        Each NC MUST:
        - Start at an explicit anchor (Indicator or NC number)
        - End before the next NC anchor or next section header

        Return a JSON ARRAY where each element represents exactly ONE NC.
        """,
        "instruction_fallback": "Focus strictly on Section 4.3.2. Return a JSON object with ';' separated values.",
        "file_name": "non_conformities_last_asa.csv"
    }
]

DEFAULT_SCHEMA = [
    {"Column Name": "CH ID", "Question": "Unique ID (to be generated)"},
    {"Column Name": "Report", "Question": "Name of the audit report"},
    {"Column Name": "Audit ID", "Question": "Unique code for the audit report"},
    {"Column Name": "Certificate holder", "Question": "Full name from RSPO certificate"},
    {"Column Name": "Certified Mill Name", "Question": "Name of the mill"},
    {"Column Name": "Certified Mill's Location/Address", "Question": "Address of the mill"},
    {"Column Name": "Country", "Question": "Country"},
    {"Column Name": "Province", "Question": "Province"},
]

def _clean_json_payload(raw_text):
    payload = (raw_text or "").strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```(?:json)?", "", payload, flags=re.IGNORECASE).strip()
        payload = re.sub(r"```$", "", payload).strip()
    return payload

def generate_gemini_schema(schema_dict, as_array=False):
    properties = {}
    required = []
    for col_name, question in schema_dict.items():
        properties[col_name] = {
            "type": "OBJECT",
            "properties": {
                "answer": {"type": "STRING", "description": question},
                "source_quote": {"type": "STRING", "description": "Exact substring from text."},
                "page_number": {"type": "INTEGER", "description": "1-indexed page number."}
            },
            "required": ["answer", "source_quote", "page_number"]
        }
        required.append(col_name)
    
    base_obj = {"type": "OBJECT", "properties": properties, "required": required}
    return {"type": "ARRAY", "items": base_obj} if as_array else base_obj

def analyze_document_with_gemini(filename, file_path, schema_dict, api_key, model_name, extra_instruction=None, expect_list=False):
    try:
        genai.configure(api_key=api_key)
        uploaded_file = genai.upload_file(path=file_path, display_name=filename)
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = genai.get_file(uploaded_file.name)
            
        schema = generate_gemini_schema(schema_dict, as_array=expect_list)
        model = genai.GenerativeModel(model_name=model_name, generation_config={"response_mime_type": "application/json", "response_schema": schema})

        prompt = "Extract information according to JSON schema. Provide Answer, Exact Source Quote, and Page Number."
        if extra_instruction: prompt += f" {extra_instruction}"

        response = model.generate_content([uploaded_file, prompt])
        data = json.loads(_clean_json_payload(getattr(response, "text", "") or "") or ("[]" if expect_list else "{}"))
        
        if expect_list:
            if isinstance(data, dict): data = [data]
            for row in data: row['filename'] = filename
        else:
            data['filename'] = filename
        return data
    except Exception as e:
        st.error(f"Extraction failed for {filename}: {e}")
        err_row = {key: "Error" for key in schema_dict.keys()}
        err_row['filename'] = filename
        return [err_row] if expect_list else err_row

def flatten_data(rich_data):
    flat_data = []
    for item in rich_data:
        flat_row = {k: (v["answer"] if isinstance(v, dict) and "answer" in v else v) for k, v in item.items()}
        flat_data.append(flat_row)
    return flat_data

def expand_nc_rows_from_single(single_entry, column_names, filename):
    if not single_entry: return []
    processed = {}
    max_len = 0
    rich_metadata = {}
    
    for column in column_names:
        val_obj = single_entry.get(column, "")
        if isinstance(val_obj, dict) and "answer" in val_obj:
            raw_val = str(val_obj["answer"] or "")
            rich_metadata[column] = val_obj
        else:
            raw_val = str(val_obj or "")
            rich_metadata[column] = None

        segments = [seg.strip() for seg in re.split(r";|\n", raw_val) if seg.strip()] if column in NC_SPLIT_COLUMNS else [raw_val.strip()]
        if not segments: segments = [""]
        processed[column] = segments
        max_len = max(max_len, len(segments))

    rows = []
    for idx in range(max(max_len, 1)):
        row = {"filename": filename}
        for column in column_names:
            values = processed[column]
            answer_val = values[idx] if idx < len(values) else values[-1]
            meta = rich_metadata.get(column)
            if meta:
                new_obj = meta.copy()
                new_obj['answer'] = answer_val
                row[column] = new_obj
            else:
                row[column] = answer_val
        rows.append(row)
    return rows

@st.dialog("Source Verification", width="large")
def show_source_verification(row_data, current_files, title):
    st.markdown(f"### {title}")
    target_filename = row_data.get("filename")
    pdf_file_buffer = next((f for f in current_files if f.name == target_filename), None)
    
    if not pdf_file_buffer:
        st.error(f"Could not find PDF: {target_filename}")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        field_keys = [k for k in row_data.keys() if k != "filename"]
        selected_field_key = st.radio("Select field:", field_keys)
        if selected_field_key:
            st.divider()
            val = row_data[selected_field_key]
            if isinstance(val, dict):
                st.markdown(f"**Answer:** {val.get('answer', 'N/A')}")
                st.info(f"**Source Quote:** \"{val.get('source_quote', 'N/A')}\"")
                st.markdown(f"**Page:** {val.get('page_number', 1)}")
                selected_field = {"page": val.get('page_number', 1), "quote": val.get('source_quote', "")}
            else:
                st.markdown(f"**Value:** {val}")
                selected_field = {"page": 1, "quote": ""}

    with col2:
        binary_data = pdf_file_buffer.getvalue()
        page_num = selected_field["page"]
        quote_text = selected_field["quote"]
        annotations = []
        if quote_text:
            try:
                with pdfplumber.open(BytesIO(binary_data)) as pdf:
                    if 0 <= page_num - 1 < len(pdf.pages):
                        page = pdf.pages[page_num - 1]
                        words = page.search(quote_text, case=False)
                        for w in words:
                            annotations.append({"page": page_num, "x": w["x0"]-2, "y": w["top"]-2, "width": (w["x1"]-w["x0"])+4, "height": (w["bottom"]-w["top"])+4, "color": "yellow", "opacity": 0.4})
            except: pass
        pdf_viewer(input=binary_data, height=800, pages_to_render=[page_num], annotations=annotations)

def handle_pdf_app():
    display_header("ASI Audit Intelligence Platform", "Automated analysis of audit reports with structured data export.")
    
    if "schema_df" not in st.session_state: st.session_state.schema_df = pd.DataFrame(DEFAULT_SCHEMA)
    
    st.subheader("1. Define your Data Columns")
    edited_schema = st.data_editor(st.session_state.schema_df, num_rows="dynamic", use_container_width=True)
    
    st.subheader("2. Upload Documents")
    uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)
    scan_nc = st.checkbox("Scan for non-conformities?")
    
    if scan_nc:
        for section in NC_SECTIONS:
            key = f"nc_schema_df_{section['key']}"
            if key not in st.session_state: st.session_state[key] = pd.DataFrame(DEFAULT_NC_SCHEMA)
            st.markdown(f"**{section['title']}**")
            st.session_state[key] = st.data_editor(st.session_state[key], num_rows="dynamic", use_container_width=True, key=f"editor_{key}")

    if st.button("🚀 Start Extraction", type="primary"):
        if not uploaded_files: st.error("Upload PDFs first.")
        else:
            schema_dict = pd.Series(edited_schema.Question.values, index=edited_schema['Column Name']).to_dict()
            results = []
            nc_results = {s["key"]: [] for s in NC_SECTIONS}
            progress = st.progress(0)
            status_text = st.empty()
            
            st.divider()
            st.subheader("Live Extraction Results")
            main_placeholder = st.empty()
            nc_placeholders = {}
            if scan_nc:
                for s in NC_SECTIONS:
                    st.markdown(f"**{s['title']}**")
                    nc_placeholders[s["key"]] = st.empty()
            
            for i, pdf_file in enumerate(uploaded_files):
                status_text.text(f"Processing {pdf_file.name}...")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(pdf_file.getvalue())
                    tmp_path = tmp.name
                
                try:
                    res = analyze_document_with_gemini(pdf_file.name, tmp_path, schema_dict, st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY"), DEFAULT_MODEL_NAME)
                    results.append(res)
                    if scan_nc:
                        for s in NC_SECTIONS:
                            s_schema = pd.Series(st.session_state[f"nc_schema_df_{s['key']}"].Question.values, index=st.session_state[f"nc_schema_df_{s['key']}"]['Column Name']).to_dict()
                            nc_instruction = f"{s['instruction_array']}\n\n{NC_BOUNDARY_RULES}"
                            s_data = analyze_document_with_gemini(pdf_file.name, tmp_path, s_schema, st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY"), DEFAULT_MODEL_NAME, extra_instruction=nc_instruction, expect_list=True)
                            if not s_data:
                                nc_fallback_instruction = f"{s['instruction_fallback']}\n\n{NC_BOUNDARY_RULES}"
                                fallback = analyze_document_with_gemini(pdf_file.name, tmp_path, s_schema, st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY"), DEFAULT_MODEL_NAME, extra_instruction=nc_fallback_instruction, expect_list=False)
                                s_data = expand_nc_rows_from_single(fallback, list(s_schema.keys()), pdf_file.name)
                            nc_results[s["key"]].extend(s_data)
                            
                            # Live update NC tables
                            nc_df_live = pd.DataFrame(flatten_data(nc_results[s["key"]]))
                            nc_placeholders[s["key"]].dataframe(nc_df_live, use_container_width=True)
                    
                    # Live update main table
                    main_df_live = pd.DataFrame(flatten_data(results))
                    main_placeholder.dataframe(main_df_live, use_container_width=True)
                    
                finally: os.remove(tmp_path)
                progress.progress((i + 1) / len(uploaded_files))
            
            status_text.text("Extraction complete!")
            
            st.session_state.rich_results_main = results
            st.session_state.schema_dict = schema_dict
            if scan_nc:
                for s in NC_SECTIONS: st.session_state[f"rich_results_{s['key']}"] = nc_results[s["key"]]
            st.rerun()

    if "selection_history" not in st.session_state: st.session_state.selection_history = {}
    pending_dialog = None

    if st.session_state.get("rich_results_main"):
        st.divider()
        st.subheader("3. Extracted Data")
        df = pd.DataFrame(flatten_data(st.session_state.rich_results_main))
        event = st.dataframe(df, use_container_width=True, on_select="rerun", selection_mode="single-row", key="main_table")
        if event.selection.rows != st.session_state.selection_history.get("main_table", []):
            st.session_state.selection_history["main_table"] = event.selection.rows
            if event.selection.rows: pending_dialog = (st.session_state.rich_results_main[event.selection.rows[0]], uploaded_files, "Main Extraction")
        st.download_button("📥 Download CSV", df.to_csv(index=False), "extracted.csv", "text/csv")

    if scan_nc:
        for s in NC_SECTIONS:
            res_key = f"rich_results_{s['key']}"
            if st.session_state.get(res_key):
                st.divider()
                st.subheader(s["title"])
                df_nc = pd.DataFrame(flatten_data(st.session_state[res_key]))
                event_nc = st.dataframe(df_nc, use_container_width=True, on_select="rerun", selection_mode="single-row", key=f"nc_table_{s['key']}")
                if event_nc.selection.rows != st.session_state.selection_history.get(f"nc_table_{s['key']}", []):
                    st.session_state.selection_history[f"nc_table_{s['key']}"] = event_nc.selection.rows
                    if event_nc.selection.rows: pending_dialog = (st.session_state[res_key][event_nc.selection.rows[0]], uploaded_files, s["title"])
                st.download_button(f"📥 Download {s['title']}", df_nc.to_csv(index=False), s["file_name"], "text/csv")

    if pending_dialog: show_source_verification(*pending_dialog)
