# email-agent-workflow/email_workflow_agent/subagents/review_agent/agent.py
from google.adk.agents import SequentialAgent
# Import specific tools used in this workflow branch
from ..tools.tools import check_translation_tool, edit_word_doc_tool

# Define the Sequential Workflow for Review Requests
review_workflow_agent = SequentialAgent(
    name="ReviewWorkflowAgent",
    # Order of sub-agents/tools is crucial in SequentialAgent
    sub_agents=[
        # LlmAgent to orchestrate quality check using the tool (similar to translation branch)
        LlmAgent(
            name="ReviewCheckOrchestrator",
            model="gemini-2.0-flash", # Model for quality check interpretation
            instruction="Use the check_translation_tool to identify necessary edits by comparing the extracted original text in state['extracted_text'] with the extracted translated text in state['translated_text'].",
            tools=[check_translation_tool], # Provide the quality check tool
            output_key="review_edit_instructions", # Save edit instructions to state
        ),
        # LlmAgent to orchestrate document editing using the tool
        LlmAgent(
            name="DocumentEditorOrchestrator",
             model="gemini-2.0-flash", # Model for editing orchestration
            instruction="Use the edit_word_doc_tool to apply the edit instructions from state['review_edit_instructions'] to the document artifact from state['attachment_artifacts'].", # Note: Needs clearer way to reference original doc artifact
            tools=[edit_word_doc_tool], # Provide the editing tool
             output_key="edited_document_artifact", # Save final artifact name to state
        ),
    ],
    description="Handles the process for translation review requests: checks translation, edits document.",
)