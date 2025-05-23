# email-agent-workflow/email_workflow_agent/subagents/translation_agent/agent.py
from google.adk.agents import SequentialAgent
# Import specific tools used in this workflow branch
from ..tools.tools import translate_text_tool, check_translation_tool, convert_to_word_tool

# Define the Sequential Workflow for Translation Requests
translation_workflow_agent = SequentialAgent(
    name="TranslationWorkflowAgent",
    # Order of sub-agents/tools is crucial in SequentialAgent
    sub_agents=[
        # LlmAgent to orchestrate text translation using the tool
        # (The tool call happens within this LlmAgent's execution)
        LlmAgent(
            name="TextTranslationOrchestrator",
            model="gemini-2.0-flash", # Use a capable model for translation orchestration
            instruction="Use the translate_text_tool to translate the extracted text from state['extracted_text'] to the target language.",
            tools=[translate_text_tool], # Provide the translation tool
            output_key="translated_text", # Save translated text to state
        ),
        # LlmAgent to orchestrate quality check using the tool
         LlmAgent(
            name="QualityCheckOrchestrator",
            model="gemini-2.0-flash", # Model for quality check interpretation
            instruction="Use the check_translation_tool to assess the quality of the translated text in state['translated_text'] compared to the original text in state['extracted_text'].",
            tools=[check_translation_tool], # Provide the quality check tool
            output_key="translation_quality_feedback", # Save feedback to state
        ),
        # LlmAgent to orchestrate Word conversion using the tool
        LlmAgent(
            name="WordConversionOrchestrator",
            model="gemini-2.0-flash", # Minimal model
            instruction="Use the convert_to_word_tool to create a Word document from the translated text in state['translated_text'], using the original format from state['original_file_format'].",
            tools=[convert_to_word_tool], # Provide the conversion tool
            output_key="translated_document_artifact", # Save final artifact name to state
        ),
    ],
    description="Handles the process for translation requests: translates, checks quality, converts to Word.",
)