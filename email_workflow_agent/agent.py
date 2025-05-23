# email-agent-workflow/email_workflow_agent/agent.py
import asyncio
import logging
from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from typing import AsyncGenerator
from typing_extensions import override # Requires typing_extensions installed

# Import sub-agents
from .subagents.classifier_agent.agent import classifier_agent
from .subagents.reply_agent.agent import initial_reply_agent
from .subagents.translation_agent.agent import translation_workflow_agent
from .subagents.review_agent.agent import review_workflow_agent
from .subagents.sender_agent.agent import email_sender_agent
from .tools.tools import download_attachments_tool, extract_text_tool # Import necessary initial tools

logger = logging.getLogger(__name__)

# Define a Custom Agent to handle the conditional workflow
class EmailWorkflowOrchestrator(BaseAgent):
    """
    Orchestrates the email translation/review workflow.
    Classifies email, generates reply, downloads/extracts content,
    routes to translation or review branches, and sends final email.
    """

    # Define agents and tools as instance attributes for Pydantic (implicitly used by BaseAgent)
    classifier_agent: LlmAgent
    initial_reply_agent: LlmAgent
    translation_workflow_agent: SequentialAgent
    review_workflow_agent: SequentialAgent
    email_sender_agent: SequentialAgent
    download_attachments_tool: object # Use object or BaseTool/FunctionTool type hint
    extract_text_tool: object

    # Pydantic config - arbitrary_types_allowed is often needed for Agent type hints
    model_config = {"arbitrary_types_allowed": True}

    def __init__(
        self,
        name: str,
        classifier_agent: LlmAgent,
        initial_reply_agent: LlmAgent,
        translation_workflow_agent: SequentialAgent,
        review_workflow_agent: SequentialAgent,
        email_sender_agent: SequentialAgent,
        download_attachments_tool: object, # Tools also passed in
        extract_text_tool: object,
        # Pass sub_agents list to the BaseAgent constructor for framework introspection
        # Include only direct children that this orchestrator calls at the top level
        # (Classifier, Reply, Sender, and the two branch workflows)
        sub_agents: list[BaseAgent] # Type hint for the list
    ):
        super().__init__(
            name=name,
            classifier_agent=classifier_agent,
            initial_reply_agent=initial_reply_agent,
            translation_workflow_agent=translation_workflow_agent,
            review_workflow_agent=review_workflow_agent,
            email_sender_agent=email_sender_agent,
            download_attachments_tool=download_attachments_tool,
            extract_text_tool=extract_text_tool,
            sub_agents=sub_agents
        )

    @override
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        """Implements the custom orchestration logic."""
        logger.info(f"[{self.name}] Starting email workflow orchestration.")

        # Ensure initial email data is in state (assuming main.py put it there)
        # You might want to add validation here

        # --- Step 1: Classify Email ---
        logger.info(f"[{self.name}] Running Email Classifier Agent.")
        # The classifier reads state['email_subject'] and state['email_body']
        async for event in self.classifier_agent.run_async(ctx):
            yield event # Yield events from sub-agent

        email_type = ctx.session.state.get("email_type")
        logger.info(f"[{self.name}] Email classified as: {email_type}")

        # Check if classification happened successfully
        if email_type not in ["translation", "review"]:
             logger.warning(f"[{self.name}] Unknown email type '{email_type}'. Ending workflow.")
             # Optionally generate a final "cannot process" response
             yield Event(
                 author=self.name,
                 content=types.Content(parts=[types.Part(text=f"Cannot process email type: {email_type}. Workflow ended.")])
             )
             return # Stop workflow

        # --- Step 2: Generate Initial Reply ---
        logger.info(f"[{self.name}] Running Initial Reply Agent.")
        # The reply agent reads state['email_sender_email'] and state['email_type']
        async for event in self.initial_reply_agent.run_async(ctx):
            yield event # Yield events from sub-agent

        initial_reply_text = ctx.session.state.get("initial_reply_text")
        logger.info(f"[{self.name}] Initial reply generated (saved to state).")

        # --- Step 3: Download Attachments (using a Tool) ---
        logger.info(f"[{self.name}] Downloading attachments.")
        # This tool needs the initial attachments list from state
        # It will save them as Artifacts and update state with artifact names/versions
        # Run tool directly from CustomAgent using tool_context.actions.run_tool
        # Or wrap tool in a minimal Agent if direct tool calling isn't supported by base class RunAsync method
        # Simplest for CustomAgent: Just call the tool function if it takes InvocationContext or State directly
        # Let's assume tools are wrapped in FunctionTool and can be called via runner utility or similar
        # A cleaner ADK pattern is to call tools from LlmAgents, or pass InvocationContext/State to tools
        # For CustomAgent, calling the tool function directly and manually handling events is possible but complex.
        # Let's make a minimal LlmAgent wrapper for these initial tools for clarity.

        # Re-architecting Step 3-4 slightly for better ADK patterns within CustomAgent:
        # Use temporary LlmAgents to run the tools and yield events.

        download_agent = LlmAgent(
            name="DownloadAgent",
            model="gemini-2.0-flash", # Minimal model, maybe even a non-LLM agent could run tools?
            instruction="Run the download_attachments_tool.",
            tools=[download_attachments_tool],
            description="Internal agent to download attachments tool."
        )
        extract_agent = LlmAgent(
            name="ExtractAgent",
            model="gemini-2.0-flash", # Minimal model
            instruction="Run the extract_text_tool on artifacts listed in state.",
            tools=[extract_text_tool],
            description="Internal agent to extract text tool."
        )

        logger.info(f"[{self.name}] Running Download Agent.")
        async for event in download_agent.run_async(ctx):
             yield event # Yield events from download tool

        attachment_artifacts = ctx.session.state.get("attachment_artifacts")
        if not attachment_artifacts:
            logger.error(f"[{self.name}] Failed to download attachments. Aborting workflow.")
            yield Event(
                 author=self.name,
                 content=types.Content(parts=[types.Part(text="Failed to download attachments. Workflow ended.")])
             )
            return

        # --- Step 4: Extract Text (using a Tool) ---
        logger.info(f"[{self.name}] Running Extract Text Agent.")
        # This tool reads artifact names from state, loads artifacts, extracts text, updates state
        async for event in extract_agent.run_async(ctx):
             yield event # Yield events from extract tool

        extracted_text = ctx.session.state.get("extracted_text")
        if not extracted_text:
             logger.error(f"[{self.name}] Failed to extract text from attachments. Aborting workflow.")
             yield Event(
                 author=self.name,
                 content=types.Content(parts=[types.Part(text="Failed to extract text from attachments. Workflow ended.")])
             )
             return

        # --- Step 5: Conditional Workflow Branching ---
        if email_type == "translation":
            logger.info(f"[{self.name}] Routing to Translation Workflow.")
            async for event in self.translation_workflow_agent.run_async(ctx):
                yield event # Yield events from the entire translation sequence

            final_document_artifact = ctx.session.state.get("translated_document_artifact") # Get result from state
            # Check if translation succeeded
            if not final_document_artifact:
                 logger.error(f"[{self.name}] Translation workflow failed. Aborting.")
                 yield Event(
                     author=self.name,
                     content=types.Content(parts=[types.Part(text="Translation workflow failed. Cannot send email.")])
                 )
                 return

        elif email_type == "review":
            logger.info(f"[{self.name}] Routing to Review Workflow.")
            async for event in self.review_workflow_agent.run_async(ctx):
                yield event # Yield events from the entire review sequence

            final_document_artifact = ctx.session.state.get("edited_document_artifact") # Get result from state
            # Check if review succeeded
            if not final_document_artifact:
                 logger.error(f"[{self.name}] Review workflow failed. Aborting.")
                 yield Event(
                     author=self.name,
                     content=types.Content(parts=[types.Part(text="Review workflow failed. Cannot send email.")])
                 )
                 return
        else:
             # This case should already be handled, but as a safeguard:
             logger.error(f"[{self.name}] Workflow reached branching with unhandled type: {email_type}. Aborting.")
             yield Event(
                 author=self.name,
                 content=types.Content(parts=[types.Part(text=f"Internal error: Unknown email type '{email_type}' at branching step. Workflow ended.")])
             )
             return

        # --- Step 6: Send Final Email ---
        logger.info(f"[{self.name}] Running Email Sender Agent.")
        # The sender agent reads email sender, initial reply text, and final document artifact from state
        async for event in self.email_sender_agent.run_async(ctx):
            yield event # Yield events from the sender tool

        logger.info(f"[{self.name}] Workflow finished successfully.")
        # The very last event from the sender agent will be the final response.

# Instantiate the custom orchestrator agent and its sub-agents/tools
# Tools needed for the Orchestrator's logic (Download, Extract) are passed directly
root_agent = EmailWorkflowOrchestrator(
    name="EmailWorkflowOrchestrator",
    classifier_agent=classifier_agent,
    initial_reply_agent=initial_reply_agent,
    translation_workflow_agent=translation_workflow_agent,
    review_workflow_agent=review_workflow_agent,
    email_sender_agent=email_sender_agent,
    download_attachments_tool=download_attachments_tool, # Pass the tool instance
    extract_text_tool=extract_text_tool, # Pass the tool instance
    sub_agents=[
        classifier_agent,
        initial_reply_agent,
        translation_workflow_agent,
        review_workflow_agent,
        email_sender_agent,
        # Also include the temporary agents used for download/extract for introspection
        LlmAgent(name="DownloadAgent_tmp", model="gemini-2.0-flash", tools=[download_attachments_tool]),
        LlmAgent(name="ExtractAgent_tmp", model="gemini-2.0-flash", tools=[extract_text_tool]),
    ]
)