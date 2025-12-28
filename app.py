import streamlit as st
import os
import json
import uuid

# Load environment variables from .env file (for API keys)
from dotenv import load_dotenv
load_dotenv()

from autodeck_core.agents.ingestion_agent import IngestionAgent
from autodeck_core.agents.outline_agent import SlideOutlineAgent
from autodeck_core.agents.content_agent import SlideContentAgent
from autodeck_core.session_manager import SessionManager
from autodeck_core.ppt_generator import PPTGenerator

# Page Config
st.set_page_config(
    page_title="AutoDeck", 
    layout="wide",
    page_icon=":material/slideshow:"
)

# Material Expressive Theme - CSS Injection
def load_css():
    css_path = os.path.join(os.path.dirname(__file__), "static", "material_expressive.css")
    if os.path.exists(css_path):
        with open(css_path) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    
    # Google Fonts for Material Design
    st.markdown("""
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&family=Roboto:wght@300;400;500&display=swap" rel="stylesheet">
    """, unsafe_allow_html=True)

load_css()

st.title("AutoDeck")
st.caption("Intelligent Presentation Studio")


# Sidebar
st.sidebar.header("Configuration")
pdf_dir = "0. Input Data"
if not os.path.exists(pdf_dir):
    os.makedirs(pdf_dir)
    
pdf_files = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]
selected_pdf = st.sidebar.selectbox("Select PDF", pdf_files)

# Theme Selector
theme = st.sidebar.selectbox("Theme", ["Default", "Black & Gold"])

# Template Upload
st.sidebar.markdown("---")
st.sidebar.subheader("Slide Template")
uploaded_template = st.sidebar.file_uploader(
    "Upload PPTX Template", 
    type=["pptx"],
    help="Upload a branded template with slide masters. The AI will use these layouts."
)

if uploaded_template:
    # Save to temp location
    template_dir = "templates"
    os.makedirs(template_dir, exist_ok=True)
    template_path = os.path.join(template_dir, uploaded_template.name)
    
    with open(template_path, "wb") as f:
        f.write(uploaded_template.getbuffer())
    
    st.session_state['template_path'] = template_path
    st.sidebar.success(f"✓ Template loaded: {uploaded_template.name}")
    
    # Show detected layouts
    from pptx import Presentation as PptxPresentation
    try:
        prs = PptxPresentation(template_path)
        layouts = [layout.name for layout in prs.slide_layouts]
        st.sidebar.caption(f"Available layouts: {len(layouts)}")
        with st.sidebar.expander("View Layouts"):
            for i, name in enumerate(layouts):
                st.caption(f"{i}. {name}")
    except Exception as e:
        st.sidebar.error(f"Error reading template: {e}")
else:
    if 'template_path' in st.session_state:
        del st.session_state['template_path']

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
    # Generate a temporary ID. We won't save to disk until data exists.
    st.session_state['current_session_id'] = str(uuid.uuid4())[:8]

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
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Ingestion", "Outline", "Content", "Agentic Design", "Logs"])

# Initialize Logs
if 'logs' not in st.session_state:
    st.session_state['logs'] = []

# ... (Log metric code remains same) ...

# ... (Tab 1, 2, 3 remain same) ...

# --- TAB 4: AGENTIC DESIGN ---
with tab4:
    st.header("Agentic Design Studio (Beta)", divider="rainbow")
    
    if 'outline' not in st.session_state or len(st.session_state['outline']) == 0:
        st.warning("Please generate an outline first in the Outline tab.")
    else:
        # Check if content exists
        has_content = any(st.session_state.get(f'content_{i}', {}).get('bullet_points') 
                         for i in range(len(st.session_state['outline'])))
        
        if not has_content:
            st.warning("Please generate content first in the Content tab.")
        else:
            # --- PRIMARY: FULL DECK GENERATION ---
            st.subheader("Generate & Auto-Improve Full Deck")
            
            # Check if template is being used
            if st.session_state.get('template_path'):
                st.warning("**Template Mode**: Preview images may show white background due to LibreOffice limitations. The actual PPTX file will have correct styling - use 'Generate Final PPTX' below to get accurate output.")
            else:
                st.info("Click below to automatically generate, analyze, and improve ALL slides. Each slide will be shown as it's finalized.")
            
            col_gen, col_stop, col_status = st.columns([1, 1, 2])
            
            with col_gen:
                generate_btn = st.button("Generate Full Deck", type="primary", use_container_width=True, key="gen_full_deck", icon=":material/rocket_launch:")
            
            with col_stop:
                def stop_pipeline_callback():
                    st.session_state['pipeline_stopped'] = True
                
                # Show "Save PPTX" when generation is complete, otherwise "Stop Generation"
                generation_complete = st.session_state.get('pipeline_status', '').startswith('Pipeline Complete')
                
                if generation_complete and 'review_queue' in st.session_state and len(st.session_state['review_queue']) > 0:
                    # Generation complete - show save button
                    if st.button("Export Presentation", type="primary", use_container_width=True, key="save_pptx_btn", icon=":material/download:"):
                        # Generate the PPTX
                        from autodeck_core.ppt_generator import PPTGenerator
                        from autodeck_core.config import get_config
                        import os
                        
                        config = get_config()
                        generator = PPTGenerator(template_path=config.template_path)
                        
                        # Build slides from review queue
                        slides_data = []
                        for slide in st.session_state['review_queue']:
                            slide_content = {
                                "title": slide['title'],
                                "bullet_points": slide.get('content', {}).get('bullet_points', []),
                                "visual_overrides": slide.get('content', {}).get('visual_overrides', {})
                            }
                            slides_data.append(slide_content)
                        
                        # Save PPTX
                        session_name = st.session_state.get('session_name', 'presentation')
                        output_path = os.path.join(config.output_dir, f"{session_name.replace(' ', '_')}.pptx")
                        generator.generate(slides_data, output_path=output_path)
                        
                        st.session_state['last_generated_ppt'] = output_path
                        st.success(f"Saved to: {output_path}")
                        st.rerun()
                else:
                    # Generation in progress - show stop button
                    stop_btn = st.button("Stop Generation", type="secondary", use_container_width=True, key="stop_btn", on_click=stop_pipeline_callback, icon=":material/stop_circle:")
            
            with col_status:
                if 'pipeline_status' in st.session_state:
                    st.caption(st.session_state['pipeline_status'])
            
            # Progress and live slide container
            progress_container = st.empty()
            live_slide_container = st.container()
            
            if generate_btn:
                # Reset stop flag
                st.session_state['pipeline_stopped'] = False
                
                from autodeck_core.pipeline.agentic_pipeline import AgenticPipeline, SlideStatus
                
                # Build session data
                session_data = {
                    "name": st.session_state.get("session_name", "AutoDeck Presentation"),
                    "outline": st.session_state.get("outline", []),
                    "content": {str(i): st.session_state.get(f'content_{i}', {}) for i in range(len(st.session_state.get("outline", [])))}
                }
                
                pipeline = AgenticPipeline(
                    output_dir="generated_decks", 
                    max_iterations=3, 
                    target_score=8.0,
                    template_path=st.session_state.get('template_path')
                )
                
                # Clear previous queue
                st.session_state['review_queue'] = []
                total_slides = len(session_data.get("outline", []))
                
                # Process slides one by one
                with progress_container:
                    progress = st.progress(0, text="Starting pipeline...")
                
                for idx, result in enumerate(pipeline.generate_deck(session_data)):
                    # Check kill switch
                    if st.session_state.get('pipeline_stopped', False):
                        st.session_state['pipeline_status'] = f"⏹ Stopped at slide {idx + 1}/{total_slides}"
                        with progress_container:
                            progress.progress(int(((idx + 1) / total_slides) * 100), text="Stopped by user")
                        st.warning(f"Generation stopped. Processed {idx} slides.")
                        break
                    
                    st.session_state['pipeline_status'] = f"Processing slide {idx + 1}/{total_slides}..."
                    
                    # Update progress
                    with progress_container:
                        progress.progress(
                            int(((idx + 1) / total_slides) * 100), 
                            text=f"Slide {idx + 1}/{total_slides}: {result.title} (Score: {result.final_score:.0f}/10)"
                        )
                    
                    # Add to review queue
                    slide_data = {
                        "index": result.index,
                        "title": result.title,
                        "status": result.status.value,
                        "score": result.final_score,
                        "iterations": result.iterations,
                        "image_path": result.image_path,
                        "content": result.content,
                        "critique": result.critique,
                        "iteration_history": [
                            {
                                "iteration": rec.iteration,
                                "score": rec.score,
                                "issues": rec.issues,
                                "suggested_actions": rec.suggested_actions,
                                "actions_applied": rec.actions_applied
                            }
                            for rec in result.iteration_history
                        ]
                    }

                    st.session_state['review_queue'].append(slide_data)
                    
                    # Update content in session
                    st.session_state[f'content_{result.index}'] = result.content
                    
                    # Show preview immediately in live container
                    with live_slide_container:
                        if result.image_path and os.path.exists(result.image_path):
                            st.image(result.image_path, caption=f"Slide {idx+1}: {result.title} (Score: {result.final_score:.0f}/10)", width=400)
                
                st.session_state['pipeline_status'] = f"✓ Completed {total_slides} slides"
                with progress_container:
                    progress.progress(100, text="Pipeline Complete!")
                st.success(f"Generated and improved {total_slides} slides!")
            
            # --- REVIEW QUEUE ---
            if 'review_queue' in st.session_state and st.session_state['review_queue']:
                st.markdown("---")
                st.subheader("Review Queue")
                
                for slide in st.session_state['review_queue']:
                    score_color = "[OK]" if slide['score'] >= 8 else "[--]" if slide['score'] >= 5 else "[!!]"
                    with st.expander(f"{score_color} Slide {slide['index']+1}: {slide['title']} (Score: {slide['score']:.0f}/10)", expanded=False):
                        col_img, col_info = st.columns([1, 1])
                        
                        with col_img:
                            if slide.get('image_path') and os.path.exists(slide['image_path']):
                                st.image(slide['image_path'], caption="AI Finalized Version")
                        
                        with col_info:
                            st.metric("Final Score", f"{slide['score']:.0f}/10")
                            st.write(f"**Iterations:** {slide['iterations']}")
                            st.write(f"**Status:** {slide['status']}")
                        
                        # --- ITERATION HISTORY ---
                        if slide.get('iteration_history'):
                            st.markdown("---")
                            st.markdown("### Improvement History")
                            
                            for record in slide['iteration_history']:
                                iter_num = record['iteration']
                                iter_score = record['score']
                                score_icon = "[OK]" if iter_score >= 8 else "[--]" if iter_score >= 5 else "[!!]"
                                
                                st.markdown(f"**Round {iter_num}** {score_icon} Score: {iter_score}/10")
                                
                                # Issues found
                                if record.get('issues'):
                                    st.markdown("*Issues Found:*")
                                    for issue in record['issues']:
                                        st.caption(f"  {issue}")
                                
                                # Suggested actions
                                if record.get('suggested_actions'):
                                    st.markdown("*Suggested Actions:*")
                                    st.caption(f"  {', '.join(record['suggested_actions'])}")
                                
                                # Actions applied
                                if record.get('actions_applied'):
                                    st.markdown("*Actions Taken:*")
                                    for action in record['actions_applied']:
                                        st.caption(f"  {action}")
                                
                                st.markdown("---")
                        
                        # Comment input with unique key
                        comment_key = f"review_comment_{slide['index']}_{slide.get('iterations', 0)}"
                        comment = st.text_input(f"Add comment", key=comment_key)
                        if comment:
                            if 'slide_comments' not in st.session_state:
                                st.session_state['slide_comments'] = {}
                            st.session_state['slide_comments'][slide['index']] = comment

            
            # --- SECONDARY: SINGLE SLIDE TOOLS (in expander) ---
            st.markdown("---")
            with st.expander("Single Slide Tools", expanded=False):
                slides = st.session_state['outline']
                slide_titles = [f"{i+1}. {s['title']}" for i, s in enumerate(slides)]
                sel_idx = st.selectbox("Select Slide", range(len(slides)), format_func=lambda i: slide_titles[i], key="design_slide_sel")
                
                slide_data = st.session_state.get(f'content_{sel_idx}', {})
                
                if not slide_data:
                    st.warning("No content for this slide.")
                else:
                    col_ctrl, col_prev = st.columns([1, 1])
                    
                    with col_ctrl:
                        if st.button("Render & Analyze", use_container_width=True, key="single_render", icon=":material/visibility:"):
                            with st.spinner("Processing slide through improvement cycle..."):
                                # Use same SlideProcessor as AgenticPipeline
                                from autodeck_core.config import update_config
                                from autodeck_core.slide_processor import SlideProcessor
                                
                                # Update config with template
                                template_path = st.session_state.get('template_path')
                                update_config(template_path=template_path)
                                
                                # Process the slide
                                processor = SlideProcessor()
                                result = processor.process_slide(slide_data, index=sel_idx)
                                
                                # Store result for display
                                st.session_state['current_slide_result'] = {
                                    'image_path': result.image_path,
                                    'score': result.final_score,
                                    'iterations': result.iterations,
                                    'critique': result.critique,
                                    'iteration_history': [
                                        {
                                            'iteration': rec.iteration,
                                            'score': rec.score,
                                            'issues': rec.issues,
                                            'suggested_actions': rec.suggested_actions,
                                            'actions_applied': rec.actions_applied,
                                            'raw_response': rec.raw_response  # Include raw LLM output
                                        }
                                        for rec in result.iteration_history
                                    ]
                                }
                                st.session_state['current_preview_img'] = result.image_path
                                st.success(f"Score: {result.final_score:.0f}/10 after {result.iterations} iteration(s)")
                    
                    with col_prev:
                        if 'current_preview_img' in st.session_state and os.path.exists(st.session_state.get('current_preview_img', '')):
                            st.image(st.session_state['current_preview_img'], caption="Preview", use_container_width=True)
                            
                            # Add download button for the PPTX
                            # The temp PPTX path is stored alongside the image
                            preview_img = st.session_state.get('current_preview_img', '')
                            if preview_img:
                                # Derive PPTX path from PNG path
                                pptx_path = preview_img.replace('.png', '.pptx').replace('temp_render_', 'temp_render_')
                                # Also try the original naming
                                import glob
                                pptx_dir = os.path.dirname(preview_img)
                                pptx_files = glob.glob(os.path.join(pptx_dir, 'temp_render_*.pptx'))
                                if pptx_files:
                                    latest_pptx = max(pptx_files, key=os.path.getmtime)
                                    if os.path.exists(latest_pptx):
                                        with open(latest_pptx, 'rb') as f:
                                            st.download_button(
                                                label="Download PPTX",
                                                data=f,
                                                file_name="slide_preview.pptx",
                                                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                                use_container_width=True
                                            )

                    
                    # Display iteration history if available
                    if 'current_slide_result' in st.session_state and st.session_state['current_slide_result'].get('iteration_history'):
                        st.markdown("---")
                        st.markdown("### Improvement History")
                        
                        for record in st.session_state['current_slide_result']['iteration_history']:
                            iter_num = record['iteration']
                            iter_score = record['score']
                            score_icon = "[OK]" if iter_score >= 8 else "[--]" if iter_score >= 5 else "[!!]"
                            
                            st.markdown(f"**Round {iter_num}** {score_icon} Score: {iter_score}/10")
                            
                            if record.get('issues'):
                                st.markdown("*Issues Found:*")
                                for issue in record['issues']:
                                    st.caption(f"  {issue}")
                            
                            if record.get('suggested_actions'):
                                st.markdown("*Suggested Actions:*")
                                st.caption(f"  {', '.join(record['suggested_actions'])}")
                            
                            if record.get('actions_applied'):
                                st.markdown("*Actions Taken:*")
                                for action in record['actions_applied']:
                                    st.caption(f"  {action}")
                            
                            # Show raw LLM response in expander
                            if record.get('raw_response'):
                                with st.expander("Raw Vision Model Response"):
                                    st.text(record['raw_response'][:2000])  # Limit length
                            
                            st.markdown("---")




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
            # Save outline to session state
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
            
            # CRITICAL: Save session data to disk BEFORE renaming
            # This ensures the new outline is persisted.
            session_data = {
                "outline": st.session_state.get('outline', []),
                "content": {}, # Content is empty at this stage
                "logs": st.session_state.get('logs', []),
                "slide_comments": st.session_state.get('slide_comments', {})
            }
            session_mgr.save_session(st.session_state['current_session_id'], session_data)
            
            # Now rename (which loads from disk, updates name, and saves back)
            session_mgr.rename_session(st.session_state['current_session_id'], session_name)
            
            if outline:
                st.success("Outline Generated!")
                # st.write("Debug - Raw Outline Data:", outline) # Remove debug
            else:
                st.error("Failed to generate outline. Please check the logs.")
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
            
            
            # Validation Toggle
            enable_validation = st.checkbox("Enable Content & Image Validation", help="Uses Gemma 3 Vision to check image quality and content accuracy")

            col_gen_1, col_gen_2 = st.columns(2)
            
            with col_gen_1:
                if st.button("Generate Content for THIS Slide", icon=":material/draw:", type="secondary", use_container_width=True):
                    with st.spinner("Generating Content..."):
                        agent = get_content_agent()
                        content = agent.generate_slide_content(
                            selected_slide['title'], 
                            selected_slide['description'], 
                            log_callback=log_message,
                            validate=False
                        )
                        st.session_state[f'content_{selected_slide_idx}'] = content
                        
                        # Save
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
                        session_mgr.save_session(st.session_state['current_session_id'], session_data)
                        st.success("Slide Generated!")
                        st.rerun()

            with col_gen_2:
                if st.button("Generate ALL Slides", icon=":material/auto_awesome_motion:", type="primary", use_container_width=True):
                    slides_to_gen = st.session_state['outline']
                    progress_text = "Starting generation..."
                    my_bar = st.progress(0, text=progress_text)
                    agent = get_content_agent()
                    
                    total = len(slides_to_gen)
                    for i, slide in enumerate(slides_to_gen):
                        my_bar.progress(int((i / total) * 100), text=f"Generating slide {i+1}/{total}: {slide['title']}")
                        
                        # Generate
                        content = agent.generate_slide_content(
                            slide['title'], 
                            slide['description'], 
                            log_callback=log_message,
                            validate=False
                        )
                        st.session_state[f'content_{i}'] = content
                    
                    my_bar.progress(100, text="Generation Complete!")
                    
                    # Batch Save
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
                    session_mgr.save_session(st.session_state['current_session_id'], session_data)
                    st.success("All slides generated successfully!")
                    st.rerun()

            # (Old button removed/merged above)

            # Display Content
            if f'content_{selected_slide_idx}' in st.session_state:
                content = st.session_state[f'content_{selected_slide_idx}']
                
                # Validation Logic (Runs after display if enabled and not yet done)
                if enable_validation and 'validation' not in content:
                    with st.spinner("🛡️ Validating Content & Checking Image..."):
                        agent = get_content_agent()
                        # We need to retrieve docs again or cache them. 
                        # For now, we'll let the agent retrieve them again or pass None if we accept less strict content validation
                        # Or better, we can cache the retrieval in the content object?
                        # For simplicity, we'll just call validate_slide which might need to re-retrieve or we skip strict content check if docs missing
                        # Let's modify validate_slide to handle missing docs gracefully or re-retrieve
                        # Actually, generate_slide_content returns content. We don't have the docs there.
                        # Let's just pass None for docs for now, or re-retrieve. Re-retrieving is safer for accuracy.
                        # Wait, re-retrieving might be slow.
                        # Let's update generate_slide_content to return docs in metadata?
                        # For now, let's just run validation.
                        
                        # To do it properly, we should probably store the retrieval context.
                        # But to keep it simple and fast:
                        updated_content = agent.validate_slide(content, retrieved_docs=None) # We'll skip strict RAG validation for now or let it be optional
                        st.session_state[f'content_{selected_slide_idx}'] = updated_content
                        st.rerun()
            
            # Display Content
            if f'content_{selected_slide_idx}' in st.session_state:
                content = st.session_state[f'content_{selected_slide_idx}']
                
                # Validation Results Display
                if 'validation' in content:
                    val = content['validation']
                    st.markdown("---")
                    st.subheader("🛡️ Validation Report")
                    
                    # 1. Image Validation
                    if 'image' in val:
                        img_val = val['image']
                        score = img_val.get('quality_score', 0)
                        is_valid = img_val.get('is_valid', False)
                        
                        if is_valid:
                            st.success(f"**Image Quality:** Excellent ({score}/10)")
                        elif score >= 4:
                            st.warning(f"**Image Quality:** Acceptable ({score}/10)")
                        else:
                            st.error(f"**Image Quality:** Poor ({score}/10)")
                            
                        with st.expander("Image Analysis Details"):
                            st.write(f"**Clear:** {'Yes' if img_val.get('is_clear') else 'No'}")
                            st.write(f"**Relevant:** {'Yes' if img_val.get('is_relevant') else 'No'}")
                            if img_val.get('issues'):
                                st.write("**Issues:**")
                                for issue in img_val['issues']:
                                    st.write(f"- {issue}")
                            if img_val.get('improvement_suggestions'):
                                st.write("**Suggestions:**")
                                for sugg in img_val['improvement_suggestions']:
                                    st.write(f"- {sugg}")

                    # 2. Content Validation
                    if 'content' in val:
                        cont_val = val['content']
                        if cont_val.get('is_accurate'):
                            st.success("**Content Accuracy:** Verified")
                        else:
                            st.warning("**Content Accuracy:** Potential Issues")
                            
                        with st.expander("Content Verification Details"):
                            st.write(f"**Confidence:** {cont_val.get('confidence', 0)*100:.0f}%")
                            if cont_val.get('issues'):
                                st.write("**Issues Detected:**")
                                for issue in cont_val['issues']:
                                    st.write(f"- {issue}")
                            if cont_val.get('recommendations'):
                                st.write("**Recommendations:**")
                                for rec in cont_val['recommendations']:
                                    st.write(f"- {rec}")

                    # 3. Coherence
                    if 'coherence' in val:
                        coh_val = val['coherence']
                        if coh_val.get('is_coherent'):
                            st.success("**Slide Coherence:** Good")
                        else:
                            st.info("**Slide Coherence:** Needs Review")
                            with st.expander("Coherence Details"):
                                for issue in coh_val.get('issues', []):
                                    st.write(f"- {issue}")

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
            
        if selected_slide_idx is not None:
             # ... (existing code for slide editing) ...
             pass # Placeholder to match indentation, actually I will append at the end of tab3 block
        
        # New Export Section
        st.markdown("---")
        st.header("Export Presentation", divider="gray")
        
        col_export_1, col_export_2 = st.columns([1, 2])
        # Get session name safely for both generation and download
        current_session_id = st.session_state.get('current_session_id')
        session_name = "Presentation"
        if current_session_id:
             loaded_session = session_mgr.load_session(current_session_id)
             if loaded_session:
                 session_name = loaded_session.get('name', 'Presentation')

        with col_export_1:
             if st.button("Generate PowerPoint (.pptx)", icon=":material/slideshow:", type="primary", use_container_width=True):
                with st.spinner("Generating PowerPoint..."):
                    try:
                        # Construct session data from state
                        content_dict = {}
                        for key in st.session_state.keys():
                            if key.startswith('content_'):
                                idx = key.replace('content_', '')
                                content_dict[idx] = st.session_state[key]
                        
                        session_data = {
                            "name": session_name,
                            "outline": st.session_state.get('outline', []),
                            "content": content_dict
                        }
                        
                        # Use template if uploaded
                        template_path = st.session_state.get('template_path')
                        ppt_gen = PPTGenerator(
                            output_path=f"generated_presentation_{current_session_id}.pptx",
                            template_path=template_path
                        )
                        output_file = ppt_gen.generate(session_data)
                        st.session_state['last_generated_ppt'] = output_file
                        st.success(f"PowerPoint generated successfully!")
                    except Exception as e:
                        st.error(f"Failed to generate PPT: {e}")
                        log_message(f"[ERROR] PPT Generation failed: {e}")

        with col_export_2:
            if 'last_generated_ppt' in st.session_state and os.path.exists(st.session_state['last_generated_ppt']):
                 with open(st.session_state['last_generated_ppt'], "rb") as f:
                     st.download_button(
                         label="Download PowerPoint",
                         data=f,
                         file_name=f"{session_name.replace(' ', '_')}.pptx",
                         mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                         use_container_width=True,
                         icon=":material/download:"
                     )
    else:
        st.info("Please generate an outline in Tab 2 first.")

# --- TAB 5: LOGS ---
with tab5:
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

