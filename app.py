import streamlit as st
import os
import json
from autodeck_core.agents.ingestion_agent import IngestionAgent
from autodeck_core.agents.outline_agent import SlideOutlineAgent
from autodeck_core.agents.content_agent import SlideContentAgent
from autodeck_core.session_manager import SessionManager

# Page Config
st.set_page_config(page_title="AutoDeck", layout="wide")
st.title("AutoDeck: AI Presentation Generator")

# Sidebar
st.sidebar.header("Configuration")
pdf_dir = "0. Input Data"
if not os.path.exists(pdf_dir):
    os.makedirs(pdf_dir)
    
pdf_files = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]
selected_pdf = st.sidebar.selectbox("Select PDF", pdf_files)

# Theme Selector
theme = st.sidebar.selectbox("Theme", ["Default", "Black & Gold"])

if theme == "Black & Gold":
    st.markdown("""
    <style>
    /* Global Variables */
    :root {
        --gold: #D4AF37;
        --dark-bg: #0E1117;
        --card-bg: #1E1E1E;
        --text-color: #E0E0E0;
    }
    
    /* Main Background */
    .stApp {
        background-color: var(--dark-bg);
        color: var(--text-color);
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #000000;
        border-right: 1px solid var(--gold);
    }
    
    /* Headers */
    h1, h2, h3, .stHeader {
        color: var(--gold) !important;
        font-family: 'Helvetica Neue', sans-serif;
        font-weight: 600;
    }
    
    /* Normal Text */
    p, li, label, .stMarkdown {
        color: var(--text-color) !important;
    }
    
    /* Inputs */
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
        background-color: var(--card-bg) !important;
        color: var(--gold) !important;
        border: 1px solid #333 !important;
        border-radius: 8px;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: var(--gold) !important;
        box-shadow: 0 0 5px rgba(212, 175, 55, 0.5);
    }
    
    /* Buttons */
    .stButton button {
        background-color: transparent !important;
        color: var(--gold) !important;
        border: 1px solid var(--gold) !important;
        border-radius: 20px;
        transition: all 0.3s ease;
    }
    .stButton button:hover {
        background-color: var(--gold) !important;
        color: #000000 !important;
        border-color: var(--gold) !important;
    }
    
    /* Primary Buttons (Solid Gold) */
    .stButton button[kind="primary"] {
        background-color: var(--gold) !important;
        color: #000000 !important;
        font-weight: bold;
    }
    
    /* Expanders/Cards */
    .streamlit-expanderHeader {
        background-color: var(--card-bg) !important;
        color: var(--gold) !important;
        border: 1px solid #333;
        border-radius: 8px;
    }
    
    /* Progress Bar */
    .stProgress > div > div > div > div {
        background-color: var(--gold) !important;
    }
    
    /* Dividers */
    hr {
        border-color: #333 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# Initialize Agents (Lazy Load)
@st.cache_resource
def get_ingestion_agent():
    return IngestionAgent()

@st.cache_resource
def get_outline_agent():
    return SlideOutlineAgent()

@st.cache_resource
def get_content_agent():
    return SlideContentAgent()

@st.cache_resource
def get_session_manager():
    return SessionManager()

# Initialize Session Manager
session_mgr = get_session_manager()

# Initialize Session
if 'current_session_id' not in st.session_state:
    # Create a new session on first run
    st.session_state['current_session_id'] = session_mgr.create_new_session()

# Initialize state from session
if 'outline' not in st.session_state:
    session_data = session_mgr.load_session(st.session_state['current_session_id'])
    if session_data:
        st.session_state['outline'] = session_data.get('outline', [])
        st.session_state['slide_comments'] = session_data.get('slide_comments', {})
        st.session_state['logs'] = session_data.get('logs', [])
        # Load content for each slide
        for slide_idx, content in session_data.get('content', {}).items():
            st.session_state[f'content_{slide_idx}'] = content

# Session Management UI in Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader(":material/workspaces: Session Management")

# Session selector
sessions = session_mgr.list_sessions()
if sessions:
    session_options = {s['id']: f"{s['name']} ({s['slide_count']} slides)" for s in sessions}
    current_session = st.session_state.get('current_session_id')
    
    selected_session = st.sidebar.selectbox(
        "Current Session",
        options=list(session_options.keys()),
        format_func=lambda x: session_options[x],
        index=list(session_options.keys()).index(current_session) if current_session in session_options else 0,
        key="session_selector"
    )
    
    # Load selected session if different
    if selected_session != st.session_state.get('current_session_id'):
        session_data = session_mgr.load_session(selected_session)
        if session_data:
            st.session_state['current_session_id'] = selected_session
            st.session_state['outline'] = session_data.get('outline', [])
            st.session_state['slide_comments'] = session_data.get('slide_comments', {})
            st.session_state['logs'] = session_data.get('logs', [])
            # Clear and reload content
            for key in list(st.session_state.keys()):
                if key.startswith('content_'):
                    del st.session_state[key]
            for slide_idx, content in session_data.get('content', {}).items():
                st.session_state[f'content_{slide_idx}'] = content
            st.rerun()

# Session action buttons
col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button(":material/save: Save", use_container_width=True, help="Save current session"):
        # Gather all content
        content_dict = {}
        for key in st.session_state.keys():
            if key.startswith('content_'):
                idx = key.replace('content_', '')
                content_dict[idx] = st.session_state[key]
        
        session_data = {
            "outline": st.session_state.get('outline', []),
            "content": content_dict,
            "logs": st.session_state.get('logs', []),
            "slide_comments": st.session_state.get('slide_comments', {})
        }
        
        if session_mgr.save_session(st.session_state['current_session_id'], session_data):
            st.sidebar.success("Saved!", icon=":material/check_circle:")
        else:
            st.sidebar.error("Save failed!", icon=":material/error:")

with col2:
    if st.button(":material/add: New", use_container_width=True, help="Create new session"):
        new_session_id = session_mgr.create_new_session()
        st.session_state['current_session_id'] = new_session_id
        st.session_state['outline'] = []
        st.session_state['slide_comments'] = {}
        st.session_state['logs'] = []
        # Clear content
        for key in list(st.session_state.keys()):
            if key.startswith('content_'):
                del st.session_state[key]
        st.rerun()

# Delete button (separate row)
if st.sidebar.button(":material/delete: Delete Session", use_container_width=True, type="secondary", help="Delete current session"):
    if len(sessions) > 1:  # Don't delete if it's the last session
        if session_mgr.delete_session(st.session_state['current_session_id']):
            # Load first available session
            remaining = session_mgr.list_sessions()
            if remaining:
                st.session_state['current_session_id'] = remaining[0]['id']
                st.rerun()
    else:
        st.sidebar.warning("Cannot delete the last session", icon=":material/warning:")


# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["Ingestion", "Outline", "Content", "Logs"])

# Initialize Logs
if 'logs' not in st.session_state:
    st.session_state['logs'] = []

# Live Log Count in Sidebar (no dynamic updates - Streamlit limitation)  
st.sidebar.markdown("---")
log_count = len(st.session_state.get('logs', []))
st.sidebar.metric("System Logs", log_count, help="View all logs in the Logs tab")

def log_message(msg):
    """Add a log message to session state"""
    st.session_state['logs'].append(msg)

# --- TAB 1: INGESTION ---
with tab1:
    st.header("Document Ingestion", divider="gray")
    if selected_pdf:
        st.write(f"Selected Document: **{selected_pdf}**")
        
        # Controls
        col1, col2 = st.columns([1, 1])
        with col1:
            start_btn = st.button("Ingest / Resume Document", icon=":material/play_arrow:", use_container_width=True)
        with col2:
            stop_btn = st.button("Stop Ingestion", icon=":material/stop:", type="primary", use_container_width=True)
        
        # Progress UI
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        if stop_btn:
            st.session_state['stop_ingestion'] = True
            st.warning("Stopping after current page...")
        
        if start_btn:
            st.session_state['stop_ingestion'] = False
            
            def update_progress(progress, message):
                progress_bar.progress(progress)
                status_text.text(message)
                
            def check_stop():
                return st.session_state.get('stop_ingestion', False)

            with st.spinner("Initializing..."):
                agent = get_ingestion_agent()
                pdf_path = os.path.join(pdf_dir, selected_pdf)
                
                try:
                    agent.ingest(pdf_path, progress_callback=update_progress, stop_check=check_stop, log_callback=log_message)
                    if not st.session_state.get('stop_ingestion', False):
                        st.success("Ingestion Complete! Document processed and stored in Vector DB.")
                    else:
                        st.info("Ingestion Paused. Click 'Ingest / Resume' to continue later.")
                except Exception as e:
                    st.error(f"Ingestion Failed: {e}")
                    log_message(f"Error: {e}")
    else:
        st.info("Please add a PDF file to the '0. Input Data' directory.")

# --- TAB 2: OUTLINE ---
with tab2:
    st.header("Slide Outline", divider="gray")
    
    col1, col2 = st.columns(2)
    with col1:
        topic = st.text_input("Presentation Topic", value="Overview of Document")
    with col2:
        audience = st.text_input("Target Audience", value="General Audience")
        
    if st.button("Generate Outline", icon=":material/auto_awesome:", type="primary"):
        with st.spinner("Generating Outline..."):
            agent = get_outline_agent()
            outline = agent.generate_outline(topic, audience, log_callback=log_message)
            st.session_state['outline'] = outline
            # Initialize comments dict
            if 'slide_comments' not in st.session_state:
                st.session_state['slide_comments'] = {}
            
            # Auto-name session based on topic and audience
            if audience and audience != "General Audience":
                session_name = f"{topic} ({audience})"
            else:
                session_name = topic
            # Limit length
            session_name = session_name[:60] if len(session_name) > 60 else session_name
            session_mgr.rename_session(st.session_state['current_session_id'], session_name)
            
            st.success("Outline Generated!")

    if 'outline' in st.session_state:
        st.markdown("---")
        st.subheader("Current Outline")
        
        # Display slides as cards with controls
        slides = st.session_state['outline']
        
        for idx, slide in enumerate(slides):
            with st.expander(f"**Slide {idx + 1}: {slide['title']}**", expanded=True):
                col1, col2, col3 = st.columns([3, 1, 1])
                
                with col1:
                    st.markdown(f"**Description:** {slide['description']}")
                    
                    # Comment section
                    comment_key = f"comment_{idx}"
                    if 'slide_comments' not in st.session_state:
                        st.session_state['slide_comments'] = {}
                    
                    existing_comment = st.session_state['slide_comments'].get(idx, "")
                    comment = st.text_area(
                        "Comments / Highlights",
                        value=existing_comment,
                        key=comment_key,
                        height=80,
                        placeholder="Add notes or feedback for this slide..."
                    )
                    if comment != existing_comment:
                        st.session_state['slide_comments'][idx] = comment
                
                with col2:
                    if st.button("Delete", key=f"delete_{idx}", icon=":material/delete:", use_container_width=True):
                        st.session_state['outline'].pop(idx)
                        # Clean up comment
                        if idx in st.session_state.get('slide_comments', {}):
                            del st.session_state['slide_comments'][idx]
                        st.rerun()
                
                with col3:
                    if st.button("Insert After", key=f"insert_{idx}", icon=":material/add_circle:", use_container_width=True):
                        # Show form to insert new slide
                        st.session_state[f'show_insert_{idx}'] = True
                        st.rerun()
                
                # Insert form (if triggered)
                if st.session_state.get(f'show_insert_{idx}', False):
                    with st.form(key=f"insert_form_{idx}"):
                        st.write("**Insert New Slide**")
                        new_title = st.text_input("Title", key=f"new_title_{idx}")
                        new_desc = st.text_area("Description", key=f"new_desc_{idx}")
                        
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.form_submit_button("Insert"):
                                if new_title and new_desc:
                                    new_slide = {"title": new_title, "description": new_desc}
                                    st.session_state['outline'].insert(idx + 1, new_slide)
                                    st.session_state[f'show_insert_{idx}'] = False
                                    st.rerun()
                        with col_b:
                            if st.form_submit_button("Cancel"):
                                st.session_state[f'show_insert_{idx}'] = False
                                st.rerun()
        
        # Global Refinement
        st.markdown("---")
        st.subheader("Refine Entire Outline", divider="gray")
        feedback = st.text_area(
            "Describe changes to make across the outline",
            placeholder="e.g., 'Add a slide about cost-effectiveness after introduction'"
        )
        if st.button("Refine Outline", icon=":material/refresh:"):
            with st.spinner("Refining..."):
                agent = get_outline_agent()
                refined_outline = agent.refine_outline(st.session_state['outline'], feedback, log_callback=log_message)
                st.session_state['outline'] = refined_outline
                st.rerun()


# --- TAB 3: CONTENT ---
with tab3:
    st.header("Slide Content", divider="gray")
    
    if 'outline' in st.session_state:
        slides = st.session_state['outline']
        slide_titles = [s['title'] for s in slides]
        selected_slide_idx = st.selectbox("Select Slide to Edit", range(len(slide_titles)), format_func=lambda x: slide_titles[x])
        
        if selected_slide_idx is not None:
            selected_slide = slides[selected_slide_idx]
            st.write(f"**Description:** {selected_slide['description']}")
        
            if st.button("Generate Content for Slide", icon=":material/draw:", type="primary"):
                with st.spinner("Generating Content..."):
                    agent = get_content_agent()
                    content = agent.generate_slide_content(selected_slide['title'], selected_slide['description'], log_callback=log_message)
                    st.session_state[f'content_{selected_slide_idx}'] = content
                    st.success("Content Generated!")
            
            # Display Content
            if f'content_{selected_slide_idx}' in st.session_state:
                content = st.session_state[f'content_{selected_slide_idx}']
                
                st.markdown("---")
                st.subheader(content.get('title', 'Untitled'))
                
                # Layout: Image Left, Bullets Right
                c1, c2 = st.columns([1, 2])
                with c1:
                    img_path = content.get('image_suggestion')
                    if img_path and isinstance(img_path, str) and os.path.exists(img_path):
                        st.image(img_path, caption="Suggested Image")
                    else:
                        st.warning(f"Image not found or placeholder: {img_path}")
                
                with c2:
                    st.write("### Key Points")
                    for bullet in content.get('bullet_points', []):
                        st.write(f"- {bullet}")
                
                st.write("### Speaker Notes")
                st.info(content.get('speaker_notes', ''))
                
                # Feedback Loop
                st.markdown("---")
                feedback = st.text_area("Refine Slide Content (e.g., 'Make bullets shorter')")
                if st.button("Refine Slide", icon=":material/refresh:"):
                    with st.spinner("Refining..."):
                        agent = get_content_agent()
                        refined_content = agent.refine_content(content, feedback, log_callback=log_message)
                        st.session_state[f'content_{selected_slide_idx}'] = refined_content
                        st.rerun()
        else:
            st.warning("Please select a slide to edit")
            
    else:
        st.info("Please generate an outline in Tab 2 first.")

# --- TAB 4: LOGS ---
with tab4:
    st.header("System Logs", divider="gray")
    
    # Controls row
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.metric("Total Logs", len(st.session_state.get('logs', [])))
    with col3:
        if st.button("Clear All", icon=":material/delete_sweep:", type="primary", use_container_width=True):
            st.session_state['logs'] = []
            st.rerun()
    
    st.markdown("---")
    
    if 'logs' in st.session_state and st.session_state['logs']:
        # Display all logs in reverse chronological order
        for i, msg in enumerate(reversed(st.session_state['logs']), 1):
            log_num = len(st.session_state['logs']) - i + 1
            
            # Parse log level and message
            if '[ERROR]' in msg:
                with st.container():
                    st.markdown(f"""
                    <div style="
                        padding: 12px 16px;
                        border-left: 4px solid #f44336;
                        background-color: rgba(244, 67, 54, 0.1);
                        border-radius: 4px;
                        margin-bottom: 8px;
                    ">
                        <div style="color: #666; font-size: 12px; margin-bottom: 4px;">
                            #{log_num} • ERROR
                        </div>
                        <div style="color: #f44336; font-family: monospace; font-size: 14px;">
                            {msg.replace('[ERROR] ', '')}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            elif '[WARNING]' in msg:
                with st.container():
                    st.markdown(f"""
                    <div style="
                        padding: 12px 16px;
                        border-left: 4px solid #ff9800;
                        background-color: rgba(255, 152, 0, 0.1);
                        border-radius: 4px;
                        margin-bottom: 8px;
                    ">
                        <div style="color: #666; font-size: 12px; margin-bottom: 4px;">
                            #{log_num} • WARNING
                        </div>
                        <div style="color: #ff9800; font-family: monospace; font-size: 14px;">
                            {msg.replace('[WARNING] ', '')}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            elif '[INFO]' in msg:
                with st.container():
                    st.markdown(f"""
                    <div style="
                        padding: 12px 16px;
                        border-left: 4px solid #2196f3;
                        background-color: rgba(33, 150, 243, 0.05);
                        border-radius: 4px;
                        margin-bottom: 8px;
                    ">
                        <div style="color: #666; font-size: 12px; margin-bottom: 4px;">
                            #{log_num} • INFO
                        </div>
                        <div style="color: #424242; font-family: monospace; font-size: 14px;">
                            {msg.replace('[INFO] ', '')}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                with st.container():
                    st.markdown(f"""
                    <div style="
                        padding: 12px 16px;
                        border-left: 4px solid #9e9e9e;
                        background-color: rgba(0, 0, 0, 0.02);
                        border-radius: 4px;
                        margin-bottom: 8px;
                    ">
                        <div style="color: #666; font-size: 12px; margin-bottom: 4px;">
                            #{log_num}
                        </div>
                        <div style="color: #424242; font-family: monospace; font-size: 14px;">
                            {msg}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
    else:
        st.info("No logs yet. Logs will appear here when you generate outlines, content, or ingest documents.", icon=":material/info:")

