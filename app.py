import streamlit as st
import os
import json
from autodeck_core.agents.ingestion_agent import IngestionAgent
from autodeck_core.agents.outline_agent import SlideOutlineAgent
from autodeck_core.agents.content_agent import SlideContentAgent

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

# Tabs
tab1, tab2, tab3 = st.tabs(["1. Ingestion", "2. Outline", "3. Content"])

# --- TAB 1: INGESTION ---
with tab1:
    st.header("Document Ingestion")
    if selected_pdf:
        st.write(f"Selected Document: **{selected_pdf}**")
        if st.button("Ingest Document"):
            with st.spinner("Ingesting... This may take a while."):
                agent = get_ingestion_agent()
                pdf_path = os.path.join(pdf_dir, selected_pdf)
                
                # Capture output? For now just run it.
                # In a real app we might want to capture stdout or have the agent return status
                try:
                    agent.ingest(pdf_path)
                    st.success("Ingestion Complete! Document processed and stored in Vector DB.")
                except Exception as e:
                    st.error(f"Ingestion Failed: {e}")
    else:
        st.info("Please add a PDF file to the '0. Input Data' directory.")

# --- TAB 2: OUTLINE ---
with tab2:
    st.header("📝 Slide Outline")
    
    col1, col2 = st.columns(2)
    with col1:
        topic = st.text_input("Presentation Topic", value="Overview of Document")
    with col2:
        audience = st.text_input("Target Audience", value="General Audience")
        
    if st.button("✨ Generate Outline"):
        with st.spinner("Generating Outline..."):
            agent = get_outline_agent()
            outline = agent.generate_outline(topic, audience)
            st.session_state['outline'] = outline
            # Initialize comments dict
            if 'slide_comments' not in st.session_state:
                st.session_state['slide_comments'] = {}
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
                        "💬 Comments / Highlights",
                        value=existing_comment,
                        key=comment_key,
                        height=80,
                        placeholder="Add notes or feedback for this slide..."
                    )
                    if comment != existing_comment:
                        st.session_state['slide_comments'][idx] = comment
                
                with col2:
                    if st.button("❌ Delete", key=f"delete_{idx}", use_container_width=True):
                        st.session_state['outline'].pop(idx)
                        # Clean up comment
                        if idx in st.session_state.get('slide_comments', {}):
                            del st.session_state['slide_comments'][idx]
                        st.rerun()
                
                with col3:
                    if st.button("➕ Insert After", key=f"insert_{idx}", use_container_width=True):
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
        st. subheader("🔧 Refine Entire Outline")
        feedback = st.text_area(
            "Describe changes to make across the outline",
            placeholder="e.g., 'Add a slide about cost-effectiveness after introduction'"
        )
        if st.button("🔄 Refine Outline"):
            with st.spinner("Refining..."):
                agent = get_outline_agent()
                refined_outline = agent.refine_outline(st.session_state['outline'], feedback)
                st.session_state['outline'] = refined_outline
                st.rerun()


# --- TAB 3: CONTENT ---
with tab3:
    st.header("Slide Content")
    
    if 'outline' in st.session_state:
        slides = st.session_state['outline']
        slide_titles = [s['title'] for s in slides]
        selected_slide_idx = st.selectbox("Select Slide to Edit", range(len(slide_titles)), format_func=lambda x: slide_titles[x])
        
        selected_slide = slides[selected_slide_idx]
        st.write(f"**Description:** {selected_slide['description']}")
        
        if st.button("Generate Content for Slide"):
            with st.spinner("Generating Content..."):
                agent = get_content_agent()
                content = agent.generate_slide_content(selected_slide['title'], selected_slide['description'])
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
            if st.button("Refine Slide"):
                with st.spinner("Refining..."):
                    agent = get_content_agent()
                    refined_content = agent.refine_content(content, feedback)
                    st.session_state[f'content_{selected_slide_idx}'] = refined_content
                    st.rerun()
            
    else:
        st.info("Please generate an outline in Tab 2 first.")
