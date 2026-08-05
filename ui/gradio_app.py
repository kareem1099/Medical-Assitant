"""
Gradio user interface for the Smart Medical Assistant.

Provides a web-based chat interface with:
- Multi-project support (create/select an isolated workspace)
- PDF upload scoped to the selected project
- Chat that searches PubMed and/or the selected project's documents
"""

import logging
from typing import List, Tuple

import gradio as gr
from langchain_core.messages import HumanMessage

from db import mongo_client
from tools.pdf_loader import process_pdf_for_project
from tools.rag_tool import set_current_project


logger = logging.getLogger(__name__)


def _project_choices() -> List[Tuple[str, str]]:
    """Return [(label, project_id), ...] for the project dropdown."""
    projects = mongo_client.list_projects()
    return [(p["name"], p["id"]) for p in projects]


def create_gradio_interface(workflow) -> gr.Blocks:
    """
    Create Gradio interface for the medical assistant.

    Builds a three-part Gradio interface with:
    - Project panel: create/select the active project (workspace)
    - Left panel: PDF upload and document management (scoped to the project)
    - Right panel: Chat interface with conversation history and citations

    Args:
        workflow: Compiled LangGraph workflow for query processing

    Returns:
        Gradio Blocks interface ready to launch
    """
    logger.info("Creating Gradio interface")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def handle_create_project(name: str, description: str):
        """Create a new project and refresh the project dropdown."""
        if not name or not name.strip():
            gr.Warning("من فضلك اكتب اسم للمشروع.")
            choices = _project_choices()
            return gr.update(choices=choices), None, "❌ اسم المشروع مطلوب."

        try:
            project_id = mongo_client.create_project(name.strip(), description or "")
            choices = _project_choices()
            logger.info(f"Project created via UI: {name} ({project_id})")
            return (
                gr.update(choices=choices, value=project_id),
                project_id,
                f"✅ تم إنشاء المشروع **{name.strip()}**",
            )
        except Exception as e:
            logger.error(f"Error creating project: {e}", exc_info=True)
            choices = _project_choices()
            return gr.update(choices=choices), None, f"❌ فشل إنشاء المشروع: {str(e)}"

    def handle_select_project(project_id: str):
        """User picked a project from the dropdown; refresh file list."""
        if not project_id:
            return project_id, "_لا يوجد ملفات بعد._"
        return project_id, _format_file_list(project_id)

    def _format_file_list(project_id: str) -> str:
        try:
            files = mongo_client.list_files(project_id)
        except Exception as e:
            return f"_تعذر تحميل قائمة الملفات: {e}_"

        if not files:
            return "_لا يوجد ملفات مرفوعة في هذا المشروع بعد._"

        lines = ["| الملف | الصفحات | Chunks | الحالة |", "|---|---|---|---|"]
        for f in files:
            lines.append(f"| {f['filename']} | {f['num_pages']} | {f['num_chunks']} | {f['status']} |")
        return "\n".join(lines)

    def handle_pdf_upload(pdf_file, project_id: str) -> Tuple[str, str]:
        """Process an uploaded PDF into the currently selected project."""
        if not project_id:
            return "❌ من فضلك اختر أو أنشئ مشروع أولاً.", gr.update()

        if pdf_file is None:
            return "❌ لم يتم اختيار ملف. من فضلك اختر ملف PDF.", gr.update()

        logger.info(f"Processing PDF upload for project {project_id}: {pdf_file}")

        try:
            result = process_pdf_for_project(pdf_file, project_id)

            if result["success"]:
                status_msg = f"✅ تم معالجة **{result['filename']}**\n"
                status_msg += f"📄 تم استخراج {result['num_chunks']} chunk\n"
                status_msg += f"💾 تمت الإضافة لقاعدة معرفة المشروع"
                logger.info(f"PDF upload successful: {result['filename']}")
            else:
                status_msg = f"❌ فشلت معالجة **{result['filename']}**\n"
                status_msg += f"السبب: {result['message']}"
                logger.warning(f"PDF upload failed: {result['message']}")

            return status_msg, _format_file_list(project_id)

        except Exception as e:
            error_msg = f"❌ خطأ غير متوقع أثناء معالجة الملف: {str(e)}"
            logger.error(f"PDF upload error: {e}", exc_info=True)
            return error_msg, gr.update()

    def handle_user_message(
        message: str,
        history: List[Tuple[str, str]],
        project_id: str,
    ) -> Tuple[List[Tuple[str, str]], str]:
        """Process user message through workflow and return response."""
        if not message or not message.strip():
            return history, "## 📚 Sources\n_No query submitted_"

        if not project_id:
            history.append([message, "❌ من فضلك اختر أو أنشئ مشروع أولاً من اللوحة العلوية."])
            return history, "## 📚 Sources\n_No project selected_"

        message = message.strip()
        logger.info(f"Processing user message (project={project_id}): {message[:100]}...")

        history.append([message, None])

        try:
            # Scope the RAG tool to the currently selected project for this request
            set_current_project(project_id)

            state = {
                "messages": [HumanMessage(content=message)],
                "user_query": message,
                "project_id": project_id,
                "retrieved_docs": [],
                "pubmed_results": [],
                "tool_outputs": [],
                "final_answer": ""
            }

            logger.info("Invoking workflow")
            result = workflow.invoke(state)

            answer = result.get("final_answer", "")
            if not answer:
                answer = "I apologize, but I couldn't generate an answer. Please try rephrasing your question."

            citations = extract_citations_from_answer(answer)
            history[-1][1] = answer

            logger.info(f"Response generated ({len(answer)} chars)")
            return history, citations

        except Exception as e:
            error_msg = f"I encountered an error while processing your question: {str(e)}\n\nPlease try again or rephrase your question."
            history[-1][1] = error_msg
            logger.error(f"Error processing message: {e}", exc_info=True)
            return history, "## 📚 Sources\n_Error occurred_"
        finally:
            set_current_project(None)

    def extract_citations_from_answer(answer: str) -> str:
        """Extract and format citations from the answer."""
        import re

        citations = re.findall(r'\[([^\]]+)\]', answer)

        if not citations:
            return "## 📚 Sources\n_No citations found in answer_"

        citations_md = "## 📚 Sources\n\n"
        seen = set()
        citation_list = []

        for citation in citations:
            if citation not in seen and len(citation) > 5:
                seen.add(citation)
                citation_list.append(citation)

        if not citation_list:
            return "## 📚 Sources\n_No citations found in answer_"

        for idx, citation in enumerate(citation_list, start=1):
            citations_md += f"{idx}. {citation}\n"

        return citations_md

    def clear_chat() -> Tuple[List, str]:
        """Clear chat history and citations."""
        logger.info("Chat cleared by user")
        return [], "## 📚 Sources\n_Citations will appear here after asking a question_"

    # ------------------------------------------------------------------
    # Build Gradio interface
    # ------------------------------------------------------------------
    with gr.Blocks(
        title="Smart Medical Assistant",
        theme=gr.themes.Soft(
            primary_hue="blue",
            secondary_hue="green",
            neutral_hue="slate"
        )
    ) as demo:
        # Track the currently selected project id across events
        current_project = gr.State(value=None)

        gr.Markdown("# 🏥 Smart Medical Assistant")
        gr.Markdown(
            "Ask medical questions and get answers from recent PubMed research and/or your uploaded medical documents. "
            "**Note**: This is for informational purposes only - always consult healthcare professionals for medical advice."
        )

        # Project panel
        with gr.Accordion("📁 المشروع (Project)", open=True):
            with gr.Row():
                project_dropdown = gr.Dropdown(
                    label="اختر مشروع",
                    choices=_project_choices(),
                    value=None,
                    interactive=True,
                )
                refresh_projects_btn = gr.Button("🔄", scale=0)

            with gr.Row():
                new_project_name = gr.Textbox(label="اسم مشروع جديد", scale=2)
                new_project_desc = gr.Textbox(label="وصف (اختياري)", scale=3)
                create_project_btn = gr.Button("➕ إنشاء مشروع", variant="secondary", scale=1)

            project_status = gr.Markdown("")

        with gr.Row():
            # Left panel: PDF Upload
            with gr.Column(scale=1):
                gr.Markdown("## 📄 Upload Medical Documents")
                pdf_upload = gr.File(
                    label="Select PDF File",
                    file_types=[".pdf"],
                    type="filepath"
                )
                upload_status = gr.Textbox(
                    label="Upload Status",
                    interactive=False,
                    lines=4,
                    placeholder="Upload status will appear here..."
                )
                upload_btn = gr.Button("📤 Process PDF", variant="primary")

                gr.Markdown("---")
                gr.Markdown("### 📚 ملفات هذا المشروع")
                files_list = gr.Markdown("_اختر مشروع لعرض ملفاته._")

                gr.Markdown("---")
                gr.Markdown(
                    "**Tips:**\n"
                    "- كل مشروع له ملفاته وقاعدة معرفة منفصلة\n"
                    "- Multiple PDFs can be uploaded sequentially\n"
                    "- Documents persist across sessions"
                )

            # Right panel: Chat Interface
            with gr.Column(scale=2):
                gr.Markdown("## 💬 Ask Medical Questions")

                chatbot = gr.Chatbot(
                    label="Conversation",
                    height=500,
                    show_copy_button=True
                )

                with gr.Row():
                    msg = gr.Textbox(
                        label="Your Question",
                        placeholder="Ask a medical question... (e.g., 'What are the latest diabetes treatment guidelines?')",
                        scale=4,
                        lines=2
                    )
                    submit_btn = gr.Button("🔍 Send", scale=1, variant="primary")

                clear_btn = gr.Button("🗑️ Clear Chat")

                gr.Markdown("---")

                citations = gr.Markdown(
                    "## 📚 Sources\n_Citations will appear here after asking a question_"
                )

        # ------------------------------------------------------------
        # Wire event handlers
        # ------------------------------------------------------------
        create_project_btn.click(
            fn=handle_create_project,
            inputs=[new_project_name, new_project_desc],
            outputs=[project_dropdown, current_project, project_status]
        )

        refresh_projects_btn.click(
            fn=lambda: gr.update(choices=_project_choices()),
            outputs=[project_dropdown]
        )

        project_dropdown.change(
            fn=handle_select_project,
            inputs=[project_dropdown],
            outputs=[current_project, files_list]
        )

        upload_btn.click(
            fn=handle_pdf_upload,
            inputs=[pdf_upload, current_project],
            outputs=[upload_status, files_list]
        )

        submit_btn.click(
            fn=handle_user_message,
            inputs=[msg, chatbot, current_project],
            outputs=[chatbot, citations]
        ).then(
            fn=lambda: "",
            outputs=[msg]
        )

        msg.submit(
            fn=handle_user_message,
            inputs=[msg, chatbot, current_project],
            outputs=[chatbot, citations]
        ).then(
            fn=lambda: "",
            outputs=[msg]
        )

        clear_btn.click(
            fn=clear_chat,
            outputs=[chatbot, citations]
        )

    logger.info("Gradio interface created successfully")

    return demo
