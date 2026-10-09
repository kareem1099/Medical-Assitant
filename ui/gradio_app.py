"""Gradio layout for the Smart Medical Assistant.

This file only declares components and wires events. All behaviour lives in
``ui/handlers.py`` (``AppHandlers``), which is what the tests exercise.
"""

import logging

import gradio as gr

from db import mongo_client
from src.stores.metadata.MongoMetadataProvider import MongoMetadataProvider
from ui.handlers import SOURCES_IDLE, AppHandlers

logger = logging.getLogger(__name__)

CSS = """
:root { --brand: #0d9488; --brand-2: #2563eb; --ink: #0f172a; --glass: rgba(255,255,255,.72); --ring: rgba(13,148,136,.28); }
.dark { --glass: rgba(15,23,42,.62); --ink: #e2e8f0; }
body, .gradio-container { background:
    radial-gradient(1100px 520px at 8% -10%, rgba(13,148,136,.16), transparent 60%),
    radial-gradient(900px 480px at 100% 0%, rgba(37,99,235,.14), transparent 55%),
    var(--background-fill-primary) !important; }
.gradio-container { max-width: 1320px !important; margin: auto; font-family: 'Inter', system-ui, sans-serif !important; }

/* hero */
#hero { text-align: center; padding: 34px 18px 8px; }
#hero .badge { display:inline-block; padding: 4px 14px; border-radius: 999px; font-size:.74rem; letter-spacing:.08em; text-transform: uppercase;
    font-weight:600; color: var(--brand); background: rgba(13,148,136,.12); border: 1px solid var(--ring); }
#hero h1 { margin: 14px 0 6px !important; font-size: 2.5rem !important; font-weight: 800; letter-spacing: -.02em; line-height: 1.15;
    background-image: linear-gradient(120deg, #14b8a6, #3b82f6) !important; -webkit-background-clip: text; background-clip: text; color: transparent !important; }
#hero p { margin: 0 auto; max-width: 560px; color: var(--body-text-color-subdued); font-size: 1.02rem; }
#features { display:flex; gap:10px; justify-content:center; flex-wrap:wrap; margin: 16px 0 4px; }
#features span { padding: 6px 14px; border-radius: 999px; font-size:.84rem; background: var(--glass); border:1px solid var(--border-color-primary); backdrop-filter: blur(8px); }

/* auth card */
#auth-card { max-width: 460px; margin: 18px auto 0; padding: 26px 26px 18px; border-radius: 22px; background: var(--glass);
    border: 1px solid var(--border-color-primary); backdrop-filter: blur(14px); box-shadow: 0 24px 60px -24px rgba(15,23,42,.35); }

/* top bar */
#topbar { align-items:center; padding: 12px 18px; margin-bottom: 14px; border-radius: 16px; background: var(--glass);
    border:1px solid var(--border-color-primary); backdrop-filter: blur(12px); box-shadow: 0 8px 28px -16px rgba(15,23,42,.3); }
#topbar h1 { margin:0; font-size:1.25rem; font-weight:700; }
#welcome { text-align:end; color: var(--body-text-color-subdued); }

/* sidebar */
.sidebar { background: var(--glass); border:1px solid var(--border-color-primary); border-radius: 18px; padding: 14px 16px !important;
    backdrop-filter: blur(12px); box-shadow: 0 10px 34px -20px rgba(15,23,42,.35); }
.section-title { margin: 14px 0 4px 0; font-weight: 700; font-size:.82rem !important; letter-spacing:.07em; text-transform: uppercase; color: var(--brand); }
.section-title h3 { font-size:.82rem !important; margin:0 !important; }

/* chat */
#chat-card { background: var(--glass); border:1px solid var(--border-color-primary); border-radius: 18px; padding: 10px;
    backdrop-filter: blur(12px); box-shadow: 0 10px 34px -20px rgba(15,23,42,.35); }
#chatbot { border: none !important; background: transparent !important; }
#chatbot .message { border-radius: 16px !important; line-height: 1.6; }
#chatbot .user { background: linear-gradient(135deg, #0d9488, #2563eb) !important; color: #fff !important; border: none !important; }
#chatbot .bot { background: var(--background-fill-secondary) !important; }
#question textarea { border-radius: 14px !important; font-size: 1rem; }
#question textarea:focus { box-shadow: 0 0 0 3px var(--ring) !important; border-color: var(--brand) !important; }

/* buttons & inputs */
button.primary { background: linear-gradient(135deg, #0d9488, #2563eb) !important; border: none !important; color:#fff !important;
    font-weight: 600; border-radius: 12px !important; transition: transform .12s ease, box-shadow .12s ease; box-shadow: 0 8px 20px -10px var(--brand); }
button.primary:hover { transform: translateY(-1px); box-shadow: 0 12px 24px -10px var(--brand); }
button.secondary, button.stop { border-radius: 12px !important; font-weight: 600; }
.gradio-container input, .gradio-container textarea, .gradio-container .wrap { border-radius: 12px !important; }

/* sources & footer */
#sources-panel { background: var(--background-fill-secondary); border-radius: 12px; padding: 8px 14px; border-left: 3px solid var(--brand); }
#disclaimer { font-size: .78rem; color: var(--body-text-color-subdued); text-align: center; margin-top: 10px; }
footer { display: none !important; }

/* Mixed Arabic / English messages: every paragraph picks its own direction. */
.message, .message p, .message li, #question textarea { unicode-bidi: plaintext; text-align: start; }
"""

HERO_HTML = """
<div id="hero">
  <span class="badge">AI · Evidence-based</span>
  <h1>Smart Medical Assistant</h1>
  <p>Answers grounded in <b>your own documents</b> and <b>recent PubMed research</b> - with sources you can check.</p>
  <div id="features"><span>📄 Your PDFs</span><span>🔬 PubMed</span><span>💬 Arabic &amp; English</span><span>🔒 Private workspaces</span></div>
</div>
"""

DISCLAIMER = ("⚠️ Educational information only - not medical advice. "
              "Always consult a qualified healthcare professional for diagnosis or treatment.")


def create_gradio_interface(workflow) -> gr.Blocks:
    """Build the authenticated, workspace-based chat interface."""
    metadata = MongoMetadataProvider(mongo_client.get_db())
    h = AppHandlers(metadata, workflow)

    theme = gr.themes.Soft(
        primary_hue="teal", secondary_hue="blue", neutral_hue="slate", radius_size=gr.themes.sizes.radius_lg,
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
    )
    with gr.Blocks(title="Smart Medical Assistant", theme=theme, css=CSS) as demo:
        user_id = gr.State(value=None)
        current_session = gr.State(value=None)
        current_project = gr.State(value=None)

        # ------------------------------------------------------------- sign in
        with gr.Column(visible=True) as auth_panel:
            gr.HTML(HERO_HTML)
            with gr.Column(elem_id="auth-card"):
                with gr.Tab("Sign in"):
                    login_email = gr.Textbox(label="Email", type="email", placeholder="you@example.com")
                    login_password = gr.Textbox(label="Password", type="password")
                    login_btn = gr.Button("Sign in", variant="primary", size="lg")
                with gr.Tab("Create account"):
                    register_name = gr.Textbox(label="Display name")
                    register_email = gr.Textbox(label="Email", type="email", placeholder="you@example.com")
                    register_password = gr.Textbox(label="Password", type="password", info="At least 8 characters")
                    register_btn = gr.Button("Create account", variant="primary", size="lg")
                auth_status = gr.Markdown("")
            gr.Markdown(DISCLAIMER, elem_id="disclaimer")

        # ----------------------------------------------------------------- app
        with gr.Column(visible=False) as app_panel:
            with gr.Row(equal_height=True, elem_id="topbar"):
                with gr.Column(scale=4):
                    gr.Markdown("# 🏥 Smart Medical Assistant", elem_id="app-title")
                with gr.Column(scale=3):
                    welcome = gr.Markdown("", elem_id="welcome")
                with gr.Column(scale=0, min_width=110):
                    logout_btn = gr.Button("Sign out", size="sm")

            with gr.Row():
                # ---------------------------------------------------- sidebar
                with gr.Column(scale=1, min_width=320, elem_classes="sidebar"):
                    gr.Markdown("### 📁 Workspace", elem_classes="section-title")
                    project_dropdown = gr.Dropdown(label="Current workspace", choices=[], interactive=True,
                                                   info="Documents and conversations belong to a workspace.")
                    with gr.Accordion("➕ New workspace", open=False):
                        new_project_name = gr.Textbox(label="Name", placeholder="e.g. Diabetes protocols")
                        new_project_desc = gr.Textbox(label="Description (optional)")
                        create_project_btn = gr.Button("Create workspace")
                    project_status = gr.Markdown("")

                    gr.Markdown("### 💬 Conversations", elem_classes="section-title")
                    conversation_dropdown = gr.Dropdown(label="Conversation", choices=[], interactive=True)
                    with gr.Row():
                        new_conversation_btn = gr.Button("＋ New", variant="primary")
                        delete_conversation_btn = gr.Button("Delete", variant="stop")

                    gr.Markdown("### 📄 Documents", elem_classes="section-title")
                    pdf_upload = gr.File(label="Upload a PDF to this workspace", file_types=[".pdf"],
                                         type="filepath")
                    upload_btn = gr.Button("Add to workspace", variant="secondary")
                    upload_status = gr.Markdown("")
                    files_list = gr.Markdown("_No documents yet - upload a PDF to ground the answers in your own files._")
                    with gr.Accordion("Remove a document", open=False):
                        file_select = gr.Dropdown(label="Document", choices=[], interactive=True)
                        delete_file_btn = gr.Button("Remove document", variant="stop")

                    with gr.Accordion("⚙️ Settings", open=False):
                        ncbi_email = gr.Textbox(
                            label="NCBI email (for PubMed)", type="email", placeholder="you@example.com",
                            info="NCBI requires an email to identify requests. Needed only for PubMed searches; it is not stored.")
                    with gr.Accordion("🗑️ Danger zone", open=False):
                        confirm_delete = gr.Checkbox(label="I understand: delete this workspace, its documents and conversations")
                        delete_project_btn = gr.Button("Delete workspace", variant="stop")

                # --------------------------------------------------- conversation
                with gr.Column(scale=3, elem_id="chat-card"):
                    chatbot = gr.Chatbot(label="Conversation", height=540, show_copy_button=True,
                                         bubble_full_width=False, elem_id="chatbot")
                    with gr.Row():
                        # Gradio 4 submits on Enter only for single-line boxes (multi-line ones need
                        # Shift+Enter); max_lines lets long questions still grow while typing.
                        msg = gr.Textbox(label="Your question", placeholder="Ask a medical question…  (Enter to send)",
                                         lines=1, max_lines=6, scale=6, elem_id="question")
                        with gr.Column(scale=1, min_width=120):
                            submit_btn = gr.Button("Send", variant="primary")
                            clear_btn = gr.Button("Clear chat", size="sm")
                    gr.Examples(
                        examples=[
                            "What is hypertension and how is it usually treated?",
                            "What does recent research say about GLP-1 agonists for type 2 diabetes?",
                            "Summarize the document I uploaded.",
                            "How does our protocol compare with recent studies?",
                        ],
                        inputs=msg, label="Try asking",
                    )
                    with gr.Accordion("📚 Sources used for the last answer", open=True):
                        sources = gr.Markdown(render_sources_placeholder(), elem_id="sources-panel")
                    gr.Markdown(DISCLAIMER, elem_id="disclaimer")

        # --------------------------------------------------------------- wiring
        ctx = [current_project, project_dropdown, conversation_dropdown, current_session,
               chatbot, sources, files_list, file_select]
        auth_out = [user_id, auth_panel, app_panel, auth_status, welcome] + ctx

        login_btn.click(h.login, [login_email, login_password], auth_out, api_name=False)
        login_password.submit(h.login, [login_email, login_password], auth_out, api_name=False)
        register_btn.click(h.register, [register_name, register_email, register_password], auth_out, api_name=False)
        register_password.submit(h.register, [register_name, register_email, register_password], auth_out, api_name=False)
        logout_btn.click(h.logout, None, auth_out, api_name=False)

        # `.input` fires only for the person's own clicks - never when code updates a dropdown -
        # so choosing a workspace/conversation can no longer trigger a cascade of reloads.
        project_dropdown.input(h.select_workspace, [project_dropdown, user_id], ctx, api_name=False)
        create_project_btn.click(h.create_workspace, [new_project_name, new_project_desc, user_id],
                                 [project_status, new_project_name, new_project_desc] + ctx, api_name=False)
        delete_project_btn.click(h.delete_workspace, [current_project, user_id, confirm_delete],
                                 [project_status, confirm_delete] + ctx, api_name=False)

        conversation_dropdown.input(h.load_conversation, [user_id, conversation_dropdown],
                                    [current_session, chatbot, sources], api_name=False)
        conv_out = [conversation_dropdown, current_session, chatbot, sources]
        new_conversation_btn.click(h.new_conversation, [user_id, current_project], conv_out, api_name=False)
        delete_conversation_btn.click(h.delete_conversation, [user_id, current_session, current_project], conv_out, api_name=False)
        clear_btn.click(h.clear_conversation, [user_id, current_session], [chatbot, sources], api_name=False)

        upload_btn.click(h.upload_pdf, [pdf_upload, current_project, user_id],
                         [upload_status, files_list, file_select, pdf_upload], api_name=False)
        delete_file_btn.click(h.delete_file, [file_select, current_project, user_id],
                              [upload_status, files_list, file_select], api_name=False)

        send_in = [msg, chatbot, current_project, ncbi_email, user_id, current_session]
        send_out = [msg, chatbot, sources, current_session, conversation_dropdown]
        submit_btn.click(h.send_message, send_in, send_out, api_name=False)
        msg.submit(h.send_message, send_in, send_out, api_name=False)

    demo.handlers = h          # exposed for tests / debugging
    logger.info("Gradio interface created successfully")
    return demo


def render_sources_placeholder() -> str:
    from src.services.citations import render_sources
    return render_sources([], [], empty=SOURCES_IDLE)
