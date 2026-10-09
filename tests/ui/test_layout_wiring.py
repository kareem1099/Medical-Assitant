"""Static + behavioural checks that every Gradio event is wired consistently.

A mismatch between a handler's return arity and the number of output
components is the classic Gradio bug that only shows up when a user clicks.
"""
import inspect

import pytest

from ui.gradio_app import create_gradio_interface
from tests.ui.conftest import StubWorkflow


@pytest.fixture
def demo(storage):
    return create_gradio_interface(StubWorkflow())


def events(demo):
    return [f for f in demo.fns.values() if f.fn is not None and f.name != "<lambda>" or f.fn is not None]


def run(demo, name, *args):
    fn = next(f for f in demo.fns.values() if f.name == name)
    out = fn.fn(*args)
    if inspect.isgenerator(out):
        out = list(out)[-1]
    assert len(out) == len(fn.outputs), f"{name} returns {len(out)} values for {len(fn.outputs)} outputs"
    return out


def test_every_handler_accepts_as_many_args_as_it_has_inputs(demo):
    for f in demo.fns.values():
        if f.fn is None:
            continue
        params = [p for p in inspect.signature(f.fn).parameters.values()
                  if p.default is inspect.Parameter.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        assert len(params) <= len(f.inputs) <= len(inspect.signature(f.fn).parameters), f.name


def test_no_event_exposes_a_public_api_endpoint(demo):
    assert all(f.api_name is False for f in demo.fns.values() if f.fn is not None and f.name != "<lambda>"
               and f.name not in {"load_example", "lambda"})


def test_dropdowns_use_input_events_not_change(demo):
    """`change` also fires when code updates the dropdown, which caused reload cascades."""
    for f in demo.fns.values():
        for target in f.targets:
            comp_id, event = target
            comp = demo.blocks[comp_id]
            if type(comp).__name__ == "Dropdown":
                assert event != "change", f"{f.name} listens to Dropdown.change"


def test_full_user_journey_through_the_wired_functions(demo, diabetes_pdf):
    reg = run(demo, "register", "Kareem", "k@x.co", "password-123")
    uid, project, session = reg[0], reg[5], reg[8]
    run(demo, "login", "k@x.co", "password-123")
    run(demo, "select_workspace", project, uid)
    run(demo, "create_workspace", "Second", "", uid)
    run(demo, "upload_pdf", diabetes_pdf, project, uid)
    run(demo, "send_message", "hello", [], project, "", uid, session)
    run(demo, "load_conversation", uid, session)
    run(demo, "new_conversation", uid, project)
    run(demo, "clear_conversation", uid, session)
    run(demo, "delete_conversation", uid, session, project)
    run(demo, "delete_file", None, project, uid)
    run(demo, "delete_workspace", project, uid, False)
    run(demo, "logout")


def test_layout_has_the_expected_sections(demo):
    labels = {getattr(b, "label", None) for b in demo.blocks.values()}
    for needed in ("Current workspace", "Conversation", "Your question", "Upload a PDF to this workspace", "Email", "Password"):
        assert needed in labels, needed


def test_enter_sends_the_question(demo):
    """Gradio 4 only submits on Enter when the textbox is single-line (lines=1)."""
    box = next(b for b in demo.blocks.values() if getattr(b, "elem_id", None) == "question")
    assert box.lines == 1 and box.max_lines > 1
