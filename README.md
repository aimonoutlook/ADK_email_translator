# ADK_email_translator
This workflow is quite complex, involving external systems (email, file formats, potentially translation/editing APIs), conditional logic, file handling, state management, and sensitive data handling. ADK is well-suited for orchestrating this, but it will require implementing several custom tools and potentially custom agent logic.

Core ADK Concepts Involved:

- LlmAgent: For reasoning, classification (email type), generating text (replies), and deciding when to use tools.

- Workflow Agents (SequentialAgent, possibly Custom Agent): To orchestrate the steps of the pipeline in a defined order and handle conditional branching (translation vs. review).

- Tools (FunctionTool, possibly AgentTool): To perform external actions like downloading files, extracting text, interacting with translation/editing APIs, checking translation quality, and sending emails.

- Session and State Management: To maintain context across the workflow steps, store data (sender info, file paths, extracted text, results, etc.), and pass information between agents and tools.

- Callbacks (specifically before_tool_callback and after_tool_callback): For inspecting and modifying tool arguments and results, crucial for handling sensitive data.

- Artifacts: For storing and managing the attached files and generated documents persistently within the session/user context.

Proposed Architecture:

The overall process will likely involve an external trigger (an email system webhook or script) that extracts the initial email data and calls into your ADK application's Runner. The Runner will orchestrate a sequence of agents and tools.

Here's a possible breakdown using these components:

- External Email System Trigger:

  - This is outside ADK.

    - A system (e.g., a script polling an inbox, a server with a webhook receiving emails) detects a new email.

        It extracts: Sender's email, Subject, Body content, Attached files (downloads them temporarily).

        It then calls your ADK application (e.g., a FastAPI endpoint hosted by adk api_server or a custom application using the ADK Runner), passing this extracted information as the initial input, possibly serializing the attachments as bytes or storing them temporarily and passing paths.

    ADK Application Entrypoint (Runner & Root Agent):

    - Your application receives the incoming email data.

        It initializes or retrieves a user session (using a SessionService).

        It passes the email data (subject, body, temporary file paths/bytes) to the Root Agent using the Runner. The email data could be put directly into session state as initial state or passed as the user content.

    Email Processing and Routing (Root Agent Orchestration):

    - Root Agent (LlmAgent or SequentialAgent orchestrating an LlmAgent): This agent receives the email data.

        Instruction: Its instruction should guide it to first classify the email type and then delegate to the appropriate workflow.

        Email Classifier Agent (LlmAgent):

       - Instruction: Focuses only on reading the email subject and body (from state) and determining if it's a "Translation Request", "Request for Review the Translation", or something else.

            Output: Saves the classification result (e.g., "translation", "review", "other") and the sender's info (email address) into the session state using output_key.

        Routing Logic (within Root Agent or a Custom Agent): Based on the classification result in the state, the Root Agent decides which path to take.

      - If "translation" or "review": Continue the workflow.

        - If "other": Generate a simple "cannot process" reply or escalate.

    Common Workflow Steps (SequentialAgent):

    - Once the email type is identified, a SequentialAgent or a Custom Agent can orchestrate the common steps needed for both translation and review requests.

        Initial Reply Generator Agent (LlmAgent):

      - Instruction: Reads the sender's name/email (from state) and email type (from state). Generates the standardized "We have received..." reply text.

        - Output: Saves the generated reply text into the session state (output_key="initial_reply_text").

        Download Attachments Tool:

        - Tool Function: Receives temporary file paths/bytes (from initial input or state). Downloads the actual files to persistent storage accessible to the agent (e.g., a local temp directory, cloud storage).

            Artifact Integration: Ideally, saves the downloaded files as Artifacts using tool_context.save_artifact. This manages file persistence and versioning within the session.

            Output: Saves the Artifact filenames/versions or new local paths to the session state (tool_context.state).

        Extract Text Tool:

        - Tool Function: Takes the Artifact filenames/versions or paths (from state). Reads the file content (requires libraries for different file formats like Word (.docx), PDF, etc.). Extracts the original text/phrases.

            Output: Saves the extracted original text into the session state (tool_context.state). Stores the format of the original file (e.g., "docx") in state.

    Conditional Processing (Translation vs. Review Branches):

    - The workflow now splits based on the email type (translation vs. review), potentially orchestrated by a Custom Agent with if/else logic or two separate Sequential Agents the Root Agent delegates to.

        State Check: This branch point reads the email type from the session state.

        Branch A: Translation Request Workflow (SequentialAgent):

      - Reads extracted original text (from state).

        - Translation Agent/Tool Orchestrator (LlmAgent):

          - Instruction: Orchestrates the translation process. Might use a TranslateTextTool multiple times or call a translation API tool.

            - TranslateTextTool (FunctionTool interacting with Translation API):

              - before_tool_callback (FOR SENSITIVE DATA HANDLING):

                - Purpose: Intercepts the arguments (original text chunks) before they are sent to the external Translation API or processed by the tool's internal logic.

                  - Logic: Analyzes the text chunk argument. Identifies sensitive patterns (names, PII, confidential terms) based on predefined rules or a separate classification tool. Replaces sensitive snippets with unique placeholders (e.g., __VAR_1__, __VAR_2__). Stores the mapping (e.g., {"__VAR_1__": "Actual Sensitive Name", "__VAR_2__": "Actual Sensitive ID"}) in the session state (tool_context.state["sensitive_map"]). The tool function then receives the obfuscated text.

                    after_tool_callback (FOR SENSITIVE DATA HANDLING):

                    - Purpose: Intercepts the tool's result (the translated text, which will contain placeholders).

                        Logic: Reads the sensitive_map from session state. Replaces the placeholders (__VAR_1__, __VAR_2__) in the translated text result with the actual sensitive values from the map.

                    Tool Function: Calls the translation API or performs the translation. Returns the (now potentially re-inserted sensitive) translated text.

                Output: Saves the translated text into the session state (tool_context.state["translated_text"]).

            Translation Quality Check Tool:

            - Tool Function: Reads original text and translated text (from state). Compares them for quality and accuracy. This likely requires an LLM call or specialized NLP libraries (could be its own LlmAgent or a FunctionTool calling an API). Apply before_tool_callback / after_tool_callback here as well if the comparison/scoring process itself handles sensitive data.

                Output: Saves the quality check result/feedback (e.g., score, list of issues) into the session state.

            Convert to Word Tool:

            - Tool Function: Reads translated text (from state) and original file format (from state). Converts the translated text into a Word document file (requires a library like python-docx).

                Artifact Integration: Saves the generated Word document file as an Artifact using tool_context.save_artifact.

                Output: Saves the Artifact filename/version of the translated Word doc to session state.

        Branch B: Request for Review Workflow (SequentialAgent):

        - Reads extracted original text and translated text (from state, extracted from the document provided in the email).

            Translation Check Tool:

          - Tool Function: Reads original text and translated text (from state). Compares them to identify necessary edits. Creates edit instructions (requires an LLM call or specialized libraries). Apply before_tool_callback / after_tool_callback here as well if the comparison/scoring process itself handles sensitive data.

            - Output: Saves the edit instructions into session state.

            Document Editor Agent/Tool Orchestrator (LlmAgent):

            - Instruction: Orchestrates the editing process. Uses an EditWordDocTool.

                EditWordDocTool (FunctionTool):

              - before_tool_callback (FOR SENSITIVE DATA HANDLING): Intercepts arguments (edit instructions, document reference). Obfuscates sensitive data in instructions and potentially in the document content if loaded temporarily. Stores mapping in state.

                - after_tool_callback (FOR SENSITIVE DATA HANDLING): Intercepts tool result (edited document reference). Re-inserts sensitive data based on the map in state.

                    Tool Function: Takes original document Artifact reference, loads it. Takes edit instructions (from state). Applies edits to the document file using track change mode (requires a library like python-docx or an external editing service API).

                    Artifact Integration: Saves the edited Word document file as a new version of the original document Artifact (or a new Artifact) using tool_context.save_artifact.

                Output: Saves the Artifact filename/version of the edited Word doc to session state.

    Final Email Sending (Common Step):

    - After either the Translation or Review branch completes, the workflow converges to the final email sending step. This can be the last step in the Root Sequential Agent.

        Reads sender info, initial reply text, and the final edited/translated document Artifact filename/version (all from state).

        Send Email Tool:

      - Tool Function: Takes required parameters (recipient email, subject, body text, attachment Artifact filename/version). Loads the attachment file data from the Artifact using tool_context.load_artifact. Sends the email (requires interaction with an email sending API or service).

        - Output: Returns a status (success/fail).

Sensitive Data Handling with Callbacks (before_tool_callback, after_tool_callback) Detailed:

This is the key to handling sensitive data without exposing it to the LLM unnecessarily.

- Apply Callbacks to Tools: Identify the specific tools that will process or interact with sensitive data (TranslateTextTool, CheckTranslationTool, EditWordDocTool). Assign before_tool_callback and after_tool_callback functions to these specific Tool definitions.

    before_tool_callback(tool, args, tool_context):

  - This function runs after the LLM has decided to call tool and generated args, but before tool's main function body executes.

    - It receives the tool name, the arguments generated by the LLM/previous steps, and the tool_context.

        Inside this callback:

      - Access args (the dictionary/map of arguments).

        - Access tool_context.state.

            Identify arguments/parts within arguments that contain sensitive data (e.g., the text chunk to translate, the text to check).

            Replace sensitive snippets in args with unique placeholders (e.g., __VAR_1__, __VAR_2__).

            Store the mapping from placeholders to actual sensitive values in tool_context.state["sensitive_map_<tool_name>"]. Use a key specific to the tool name to avoid conflicts.

            Return None: This tells ADK to proceed with executing the tool using the modified args dictionary. The tool function never sees the original sensitive data.

    after_tool_callback(tool, args, tool_context, tool_response):

    - This function runs after tool's main function body has executed and returned tool_response.

        It receives the tool name, the (potentially modified) args that were passed to the tool, the tool_context, and tool_response (the dictionary/map result from the tool).

        Inside this callback:

      - Access tool_response.

        - Access tool_context.state.

            Retrieve the sensitive_map_<tool_name> from tool_context.state.

            Replace the placeholders (__VAR_1__, etc.) in the tool_response (e.g., in the translated text result) with the actual sensitive values from the map.

            Return the modified tool_response dictionary/map: This tells ADK to use this modified result for subsequent processing (e.g., sending back to the LLM for summarization or saving to state).

    Why this works: The sensitive data is obfuscated before the tool logic (which might interact with external APIs) and before the tool's result is processed by the LLM or saved directly to state. The LLM sees the tool call with potentially obfuscated args (depending on how they are represented), and it sees the tool result after the after_tool_callback has done the re-insertion. If the tool is configured with skip_summarization=True, the LLM doesn't even process the raw tool result directly; it only sees the tool call and then receives the result after the callback has run.

Key Implementation Details & Considerations:

- File Format Parsing: You will need to use Python libraries like python-docx (for .docx), PyPDF2 or fitz (MuPDF, for .pdf), etc., within your Extract Text Tool and Edit Word Doc Tool. Handling complex formatting, tables, images within documents adds significant complexity. Libraries like python-docx can create/edit simple structures but track changes might require more advanced tools or APIs.

    Translation/Editing APIs: You'll likely integrate with external APIs for translation or document editing services unless you plan to run LLMs for these tasks yourself (which increases model cost and complexity).

    Error Handling: Implement robust error handling in all tools and within the agent orchestration (e.g., what if a file download fails, parsing fails, an API returns an error, the LLM generates an invalid tool call?).

    State Management: Carefully design your state keys and ensure data is saved and retrieved consistently across all steps. Use prefixes (user:, app:, temp:) appropriately.

    Asynchronous Operations: Many tasks (API calls, file operations, LLM calls) are asynchronous. Your tools and custom agents should use async def and await correctly within the ADK run_async execution model.

    Dependencies: Your requirements.txt (or pyproject.toml) will need ADK, python-dotenv, email/file format libraries, API client libraries, etc.

    Scalability: For high volume, consider using a persistent SessionService (like DatabaseSessionService or VertexAiSessionService) and potentially deploying agents on a scalable platform like Cloud Run or Agent Engine.

This architecture leverages ADK's strengths in orchestration, state management, and interception via callbacks to build the complex workflow you described, while specifically addressing the sensitive data handling requirement.

Important Notes:

  - Placeholders: This code provides the structure and demonstrates the ADK components. The actual logic for file parsing (Word/PDF), interacting with external translation/editing APIs, sending emails, and implementing the detailed quality checks will need to be added using appropriate Python libraries and API calls. We'll use placeholder functions (pass or simple return) for these complex external interactions.

    File Handling Complexity: Parsing and editing complex document formats (especially retaining formatting and handling track changes in .docx) is challenging. python-docx is mentioned but has limitations, especially with track changes. You might need to explore other libraries or commercial APIs for robust document processing.

    Sensitive Data Rules: The sensitive data handling callbacks provided here are illustrative. You need to implement the actual logic to identify sensitive patterns and the logic to re-insert the data based on your specific sensitive data types and rules.

    Scalability/Persistence: This example uses InMemorySessionService and InMemoryArtifactService for simplicity. For production, you'd switch to persistent services (Database, GCS, Vertex AI).

    External Trigger: The initial part (email coming in and triggering the workflow) is outside ADK. The main.py here simulates receiving email data and starting the ADK process.

## Folder Structure:
```
./email-agent-workflow/
├── .env.example             # Environment variables (API keys, etc.)
├── main.py                  # Entry point to simulate receiving email and running ADK workflow
├── requirements.txt         # Python dependencies
└── email_workflow_agent/    # Root ADK agent package
    ├── __init__.py          # Package initialization
    ├── agent.py             # Defines the Custom Orchestrator Agent (root_agent)
    ├── subagents/           # Directory for specialized sub-agents
    │   ├── __init__.py
    │   ├── classifier_agent/ # Agent to classify email type
    │   │   ├── __init__.py
    │   │   └── agent.py
    │   ├── reply_agent/      # Agent to generate initial reply
    │   │   ├── __init__.py
    │   │   └── agent.py
    │   ├── translation_agent/ # Workflow for translation request
    │   │   ├── __init__.py
    │   │   └── agent.py      # SequentialAgent for translation steps
    │   ├── review_agent/      # Workflow for review request
    │   │   ├── __init__.py
    │   │   └── agent.py      # SequentialAgent for review steps
    │   └── sender_agent/      # Agent to send final email
    │       ├── __init__.py
    │       └── agent.py      # SequentialAgent for sending
    └── tools/               # Directory for custom tools and callbacks
        ├── __init__.py
        ├── callbacks.py       # Callbacks for sensitive data handling
        └── tools.py           # Tool function definitions
```

## Code Snippets:

### Place the following code into the corresponding files:

email-agent-workflow/requirements.txt

```
google-adk
python-dotenv
python-docx  # For Word docs (.docx) - limited track change support
PyPDF2       # For reading PDFs
requests     # Example for calling external APIs
# Add any other libraries needed for file parsing, API calls, etc.
```

email-agent-workflow/.env.example

```
GOOGLE_API_KEY=your_google_generative_ai_api_key_here

# Add API keys for any external services you integrate:
# TRANSLATION_API_KEY=your_translation_api_key
# EMAIL_SEND_API_KEY=your_email_send_api_key

# Optional: Path for temporary local file storage if not using Artifacts for initial download
# LOCAL_DOWNLOAD_PATH=/tmp/email_attachments
```
email-agent-workflow/main.py
```python
import asyncio
import os
import uuid
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts import InMemoryArtifactService
from google.genai import types
from email_workflow_agent.agent import root_agent # Import the custom orchestrator agent

# Load environment variables from .env file
load_dotenv()

# --- Services ---
# Using in-memory services for simplicity. Replace with persistent options for production.
session_service = InMemorySessionService()
artifact_service = InMemoryArtifactService()

# --- Agent Runner Setup ---
APP_NAME = "email_translation_workflow"
# In a real app, USER_ID might come from an authenticated user session
# or be derived from the email sender. Using a fixed one for demo.
USER_ID = "email_sender_user" # Example user ID

runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
    artifact_service=artifact_service, # Provide artifact service
)

# --- Simulate Receiving an Email and Running Workflow ---

async def run_email_workflow(sender_email: str, subject: str, body: str, attachments: list):
    """Simulates receiving an email and triggering the ADK workflow."""
    session_id = str(uuid.uuid4()) # Unique session ID per email

    # Initial state to pass email details to the workflow
    initial_state = {
        "email_sender_email": sender_email,
        "email_subject": subject,
        "email_body": body,
        # Attachments could be passed as a list of dicts:
        # [{"filename": "report.docx", "bytes": b"...", "mime_type": "..."}]
        # Or as temp file paths after initial download outside ADK
        "initial_attachments": attachments # Passing simplified list of filenames for demo
        # In a real scenario, you'd handle byte data or temp paths here
    }

    # Create a new session for this email
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
        state=initial_state,
    )

    print(f"--- Starting workflow for email from {sender_email} (Session ID: {session_id[:8]}) ---")
    print(f"Subject: {subject}\n")

    # Provide the email body as the user's initial input to the agent
    # The agent's instruction will guide it to read subject/attachments from state
    user_message = types.Content(role="user", parts=[types.Part(text=body)])

    final_response_text = "Workflow completed."

    try:
        # Run the agent asynchronously
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=user_message, # Pass the email body as the initial user message
        ):
            # Log events for debugging
            # print(f"  Event: {event.author} - Type: {type(event).__name__} - Final: {event.is_final_response()}")
            # if event.content and event.content.parts:
            #      print(f"    Content: {str(event.content.parts[0].text)[:100]}...")
            # if event.actions:
            #      print(f"    Actions: {event.actions}")

            if event.is_final_response():
                if event.content and event.content.parts:
                     final_response_text = event.content.parts[0].text
                     print(f"--- Workflow Step Output ({event.author}): ---\n{final_response_text}\n")
                elif event.actions and event.actions.transfer_to_agent:
                     print(f"--- Workflow Decision: Transfer to {event.actions.transfer_to_agent} ---")
                else:
                     print("--- Workflow Step Output (Non-text final event) ---")


    except Exception as e:
        print(f"\n!!! Workflow encountered an ERROR: {e} !!!")
        import traceback
        traceback.print_exc()

    print(f"\n--- Workflow finished for Session ID: {session_id[:8]} ---")

# --- Example Usage ---
async def main():
    # Simulate two incoming emails
    await run_email_workflow(
        sender_email="translator1@example.com",
        subject="Translation Request for Q3 Report",
        body="Hi team, please translate the attached Q3 report (report_q3_en.docx) from English to French.",
        attachments=["report_q3_en.docx"] # Simplified attachment representation
    )

    print("\n" + "="*50 + "\n")

    await run_email_workflow(
        sender_email="officer2@example.com",
        subject="Request for Review the Translation (Policy Manual)",
        body="Hello team, please review the translation of the policy manual (policy_manual_fr.docx) against the English original (policy_manual_en.docx).",
        attachments=["policy_manual_fr.docx", "policy_manual_en.docx"] # Simplified attachment representation
    )

if __name__ == "__main__":
    # Use asyncio.run() for top-level execution in a script
    try:
        asyncio.run(main())
    except RuntimeError as e:
        # Handle the case where this is run in an already-running event loop (like some notebooks)
        if "cannot be called from a running event loop" in str(e):
            print("Info: Cannot run asyncio.run from a running event loop (e.g., Jupyter/Colab).")
            print("If in Jupyter/Colab, run 'await main()' in a cell instead.")
        else:
            raise e
```

email-agent-workflow/email_workflow_agent/__init__.py
```python
      
# email-agent-workflow/email_workflow_agent/__init__.py
from .agent import root_agent

# You might need to import subagents here if the root_agent needs them
# directly in its __init__ for structure definition, although CustomAgent
# allows more flexibility in referencing instance attributes.
# For CustomAgent, importing in agent.py for the class definition is sufficient.

```
email-agent-workflow/email_workflow_agent/agent.py
```python
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
```

email-agent-workflow/email_workflow_agent/subagents/__init__.py
```python
      
# email-agent-workflow/email_workflow_agent/subagents/__init__.py
# This file can be empty or import sub-agents for easier reference if needed,
# but the root agent imports them directly by path.

```

email-agent-workflow/email_workflow_agent/subagents/classifier_agent/__init__.py
```python
# email-agent-workflow/email_workflow_agent/subagents/classifier_agent/__init__.py
from .agent import classifier_agent
```

email-agent-workflow/email_workflow_agent/subagents/classifier_agent/agent.py
```python
# email-agent-workflow/email_workflow_agent/subagents/classifier_agent/agent.py
from google.adk.agents import LlmAgent

# Use a defined model constant or string
GEMINI_MODEL = "gemini-2.0-flash"

# Define the Email Classifier Agent
classifier_agent = LlmAgent(
    name="EmailClassifierAgent",
    model=GEMINI_MODEL,
    # Instruction to classify email type based on subject and body (read from state)
    instruction="""You are an Email Classifier AI.
    Your task is to determine the type of the email provided in the session state
    based on the subject and body content.

    Read the email subject from state['email_subject'] and body from state['email_body'].

    Classify the email into one of these types:
    - "translation" if the subject indicates a request for translation (e.g., "Translation Request", "Please translate").
    - "review" if the subject indicates a request for reviewing a translation (e.g., "Request for Review", "Translation Check").
    - "other" for any other type of email.

    Output ONLY the classification type as a single word ("translation", "review", or "other").
    Do not add any explanations or other text.
    """,
    description="Classifies incoming email as 'translation', 'review', or 'other'.",
    output_key="email_type", # Save the classification result to state['email_type']
)
```

email-agent-workflow/email_workflow_agent/subagents/reply_agent/__init__.py
```python
# email-agent-workflow/email_workflow_agent/subagents/reply_agent/__init__.py
from .agent import initial_reply_agent
```

email-agent-workflow/email_workflow_agent/subagents/reply_agent/agent.py
```python
# email-agent-workflow/email_workflow_agent/subagents/reply_agent/agent.py
from google.adk.agents import LlmAgent

# Use a defined model constant or string
GEMINI_MODEL = "gemini-2.0-flash"

# Define the Initial Reply Agent
initial_reply_agent = LlmAgent(
    name="InitialReplyAgent",
    model=GEMINI_MODEL,
    # Instruction to generate the initial reply based on sender and email type (read from state)
    instruction="""You are an Email Auto-Responder.
    Your task is to generate a standardized initial reply based on the email type.

    Read the sender's email from state['email_sender_email'].
    Read the email type from state['email_type'].

    If the email type is "translation" or "review":
    Generate this exact reply:
    "Dear [Email Sender], We have received your email and we will be working on it. Kind regards, [Translator 1], [Translator 2]."
    Replace "[Email Sender]" with the actual email sender's address.
    Replace "[Translator 1]" and "[Translator 2]" with appropriate names (e.g., "AI Agent Team").

    If the email type is "other":
    Generate this exact reply:
    "Dear [Email Sender], We have received your email, but it does not appear to be a translation or review request. Please ensure the subject line is correct. Kind regards, AI Agent Team."
     Replace "[Email Sender]" with the actual email sender's address.


    Output ONLY the reply text. Do not add a subject line or any other text.
    """,
    description="Generates initial email reply text.",
    output_key="initial_reply_text", # Save the generated reply text to state
)
```

email-agent-workflow/email_workflow_agent/subagents/translation_agent/__init__.py
```python
# email-agent-workflow/email_workflow_agent/subagents/translation_agent/__init__.py
from .agent import translation_workflow_agent
```

email-agent-workflow/email_workflow_agent/subagents/translation_agent/agent.py
```python
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
```

email-agent-workflow/email_workflow_agent/subagents/review_agent/__init__.py
```python
# email-agent-workflow/email_workflow_agent/subagents/review_agent/__init__.py
from .agent import review_workflow_agent
```

email-agent-workflow/email_workflow_agent/subagents/review_agent/agent.py
```python
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
```

email-agent-workflow/email_workflow_agent/subagents/sender_agent/__init__.py
```python
# email-agent-workflow/email_workflow_agent/subagents/sender_agent/__init__.py
from .agent import email_sender_agent
```

email-agent-workflow/email_workflow_agent/subagents/sender_agent/agent.py
```python
# email-agent-workflow/email_workflow_agent/subagents/sender_agent/agent.py
from google.adk.agents import SequentialAgent
# Import specific tools used in this workflow branch
from ..tools.tools import send_email_tool

# Define the Sequential Workflow for Sending the Final Email
email_sender_agent = SequentialAgent(
    name="EmailSenderAgent",
    # Order: Prepare data, then send
    sub_agents=[
        # Minimal LlmAgent to orchestrate email sending tool
        LlmAgent(
             name="SendEmailOrchestrator",
             model="gemini-2.0-flash", # Minimal model
             instruction="Use the send_email_tool to send the final email. Get recipient from state['email_sender_email'], body from state['initial_reply_text'], and attachment artifact from state['translated_document_artifact'] or state['edited_document_artifact'] depending on email type.", # Instruction needs refinement to pick correct artifact based on type
             tools=[send_email_tool], # Provide the send email tool
             # output_key=None, # Don't save sender result to state typically
        ),
        # You could add a final confirmation agent here if needed
        LlmAgent(
             name="CompletionConfirmer",
             model="gemini-2.0-flash",
             instruction="Confirm to the user that the workflow is complete and the email has been sent.",
             # output_key=None,
        )
    ],
    description="Sends the final email with the processed document.",
)
```

email-agent-workflow/email_workflow_agent/tools/__init__.py
```python
      
# email-agent-workflow/email_workflow_agent/tools/__init__.py
from .tools import (
    download_attachments_tool,
    extract_text_tool,
    translate_text_tool,
    check_translation_tool,
    convert_to_word_tool,
    edit_word_doc_tool,
    send_email_tool,
)
# Sensitive handling callbacks are assigned *within* tools.py
# and imported/used there, not necessarily re-exported here.

```

email-agent-workflow/email_workflow_agent/tools/callbacks.py
```python
      
# email-agent-workflow/email_workflow_agent/tools/callbacks.py
import re
import copy
from typing import Any, Dict, Optional, List
from google.adk.tools.tool_context import ToolContext
from google.adk.tools.base_tool import BaseTool # For type hinting in callbacks

# --- Sensitive Data Handling Callbacks ---

# Key in state to store the mapping from placeholders to sensitive values
SENSITIVE_MAP_KEY_PREFIX = "sensitive_map_"

def identify_and_replace_sensitive_data(text: str, sensitive_map: Dict[str, str]) -> str:
    """
    Placeholder logic to identify and replace sensitive data with placeholders.
    You NEED to customize this based on your sensitive data patterns.
    This is a simplified example.
    """
    # Example: Replace dummy sensitive patterns
    patterns = {
        r"\b(Confidential Info \d+)\b": "__CONFIDENTIAL_{count}__",
        r"\b(\d{4}-\d{2}-\d{2})\b": "__DATE_{count}__", # Example date pattern
        # Add more patterns for names, PII, specific terms etc.
    }
    obfuscated_text = text
    placeholder_count = 0
    updated_sensitive_map = sensitive_map.copy()

    for pattern, placeholder_template in patterns.items():
        def replace_match(match):
            nonlocal placeholder_count
            placeholder_count += 1
            placeholder = placeholder_template.format(count=placeholder_count)
            updated_sensitive_map[placeholder] = match.group(0)
            return placeholder

        obfuscated_text = re.sub(pattern, replace_match, obfuscated_text)

    # Return obfuscated text and updated map
    return obfuscated_text, updated_sensitive_map

def replace_placeholders_with_sensitive_data(text: str, sensitive_map: Dict[str, str]) -> str:
    """
    Replace placeholders in text with actual sensitive data from the map.
    """
    reconstructed_text = text
    # Replace placeholders from the map
    for placeholder, sensitive_value in sensitive_map.items():
        reconstructed_text = reconstructed_text.replace(placeholder, sensitive_value)
    return reconstructed_text


async def handle_sensitive_before(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """
    Callback executed BEFORE a tool runs.
    Identifies and replaces sensitive data in tool arguments with placeholders.
    Stores the mapping in session state.
    """
    tool_name = tool.name
    logger.info(f"[Callback: BeforeTool] Running for tool: {tool_name}")
    logger.info(f"[Callback: BeforeTool] Original args: {args}") # WARNING: Contains sensitive data here!

    # Determine which argument(s) contain text that needs processing for THIS tool
    # You NEED to customize this logic based on the arguments of the tools
    # this callback is attached to.

    text_to_process = None
    text_arg_name = None

    if tool_name == "translate_text_tool" and "text" in args:
        text_to_process = args.get("text")
        text_arg_name = "text"
    elif tool_name == "check_translation_tool" and "original_text" in args:
         # For translation check, might need to process original AND translated
         # Simplification: Process original text argument
         text_to_process = args.get("original_text")
         text_arg_name = "original_text"
         # Note: Handling multiple sensitive args needs more complex logic here

    # Add logic for edit_word_doc_tool if it takes text instructions directly
    # or if you load document content temporarily in the tool and need to process it before editing API call

    if text_to_process and isinstance(text_to_process, str):
        sensitive_map_key = f"{SENSITIVE_MAP_KEY_PREFIX}{tool_name}"
        current_sensitive_map = tool_context.state.get(sensitive_map_key, {})

        obfuscated_text, updated_sensitive_map = identify_and_replace_sensitive_data(
            text_to_process, current_sensitive_map
        )

        if obfuscated_text != text_to_process:
            logger.info(f"[Callback: BeforeTool] Sensitive data obfuscated in args.")
            # Update the argument dictionary with the obfuscated text
            # Make a copy of args to avoid modifying immutable inputs if they were
            modified_args = copy.deepcopy(args)
            modified_args[text_arg_name] = obfuscated_text

            # Store the updated sensitive map in state
            tool_context.state[sensitive_map_key] = updated_sensitive_map
            logger.info(f"[Callback: BeforeTool] Updated sensitive map in state['{sensitive_map_key}'].")

            # Return None: Proceed with tool execution using the modified_args
            return None # ADK will pass modified_args to the tool function

    logger.info(f"[Callback: BeforeTool] No sensitive data processed or no relevant args found. Proceeding.")
    # Return None: Proceed with tool execution using the original args
    return None


async def handle_sensitive_after(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext, tool_response: Dict
) -> Optional[Dict]:
    """
    Callback executed AFTER a tool runs.
    Replaces placeholders in the tool's response with actual sensitive data
    using the map stored in session state.
    """
    tool_name = tool.name
    logger.info(f"[Callback: AfterTool] Running for tool: {tool_name}")
    logger.info(f"[Callback: AfterTool] Original tool_response: {tool_response}") # WARNING: Contains placeholders here!

    sensitive_map_key = f"{SENSITIVE_MAP_KEY_PREFIX}{tool_name}"
    sensitive_map = tool_context.state.get(sensitive_map_key)

    # Determine which part(s) of the tool_response contain text with placeholders
    # You NEED to customize this logic based on the expected output structure
    # of the tools this callback is attached to.

    response_text_to_process = None
    response_key_name = None # Key in the tool_response dict containing the text

    if tool_name == "translate_text_tool" and "translated_text" in tool_response:
        response_text_to_process = tool_response.get("translated_text")
        response_key_name = "translated_text"
    elif tool_name == "check_translation_tool" and "feedback_text" in tool_response:
         # For quality check, process the feedback text generated by the tool
         response_text_to_process = tool_response.get("feedback_text")
         response_key_name = "feedback_text"
    # Add logic for edit_word_doc_tool if its result includes text summary or
    # if you process doc bytes *after* the tool runs and need to re-insert into bytes

    if sensitive_map and response_text_to_process and isinstance(response_text_to_process, str):
         logger.info(f"[Callback: AfterTool] Sensitive map found. Reconstructing text in response.")

         reconstructed_text = replace_placeholders_with_sensitive_data(
             response_text_to_process, sensitive_map
         )

         if reconstructed_text != response_text_to_process:
             logger.info(f"[Callback: AfterTool] Placeholders replaced in tool response.")
             # Update the tool_response dictionary with the reconstructed text
             # Make a copy to avoid modifying immutable response if it was
             modified_tool_response = copy.deepcopy(tool_response)
             modified_tool_response[response_key_name] = reconstructed_text

             # Optionally, clear the sensitive map from state after use in this step
             # del tool_context.state[sensitive_map_key] # Careful if map is needed downstream!

             # Return the modified tool_response
             return modified_tool_response

    logger.info(f"[Callback: AfterTool] No sensitive map found or no relevant response text. Proceeding.")
    # Return None: Use the original tool_response
    return None

```

email-agent-workflow/email_workflow_agent/tools/tools.py
```python
# email-agent-workflow/email_workflow_agent/tools/tools.py
import os
import uuid
import logging
import requests # Example for external API calls
from typing import Any, Dict, Optional, List
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types
# Import the sensitive data handling callbacks
from .callbacks import handle_sensitive_before, handle_sensitive_after

logger = logging.getLogger(__name__)

# --- Custom Tool Functions ---

# Tool 1: Download and Save Attachments as Artifacts
# This tool is called by the Custom Orchestrator agent
async def download_attachments(tool_context: ToolContext) -> Dict[str, Any]:
    """
    Tool to download attachments from the initial email state
    and save them as artifacts.

    Reads from state['initial_attachments'].
    Writes artifact filenames/versions to state['attachment_artifacts'].
    Writes original file format to state['original_file_format'] for later use.
    """
    logger.info(f"[Tool] download_attachments called.")
    initial_attachments = tool_context.state.get("initial_attachments", [])
    saved_artifact_details = {}
    original_file_format = None # Assuming first attachment dictates format

    if not initial_attachments:
        logger.warning(f"[Tool] No attachments found in initial state.")
        tool_context.state["attachment_artifacts"] = saved_artifact_details # Save empty dict
        tool_context.state["original_file_format"] = original_file_format
        return {"status": "success", "message": "No attachments to process."}

    # In a real scenario, `initial_attachments` would contain file data (bytes)
    # or temporary paths accessible to the agent.
    # For this demo, we simulate by creating dummy artifacts.
    logger.info(f"[Tool] Simulating download and saving {len(initial_attachments)} attachments as artifacts.")

    for filename in initial_attachments:
        # Simulate reading file bytes (replace with actual file read/download logic)
        dummy_bytes = b"Dummy content for " + filename.encode('utf-8')
        # Determine mime type (replace with actual detection or mapping)
        mime_type = "application/octet-stream"
        if filename.lower().endswith(".docx"):
             mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
             if original_file_format is None: original_file_format = "docx"
        elif filename.lower().endswith(".pdf"):
             mime_type = "application/pdf"
             if original_file_format is None: original_file_format = "pdf"
        # Add other types as needed

        artifact_part = types.Part.from_data(data=dummy_bytes, mime_type=mime_type)

        try:
            # Save the artifact using the context method
            # Use original filename, ArtifactService handles versioning and scoping
            version = await tool_context.save_artifact(filename=filename, artifact=artifact_part)
            saved_artifact_details[filename] = version
            logger.info(f"[Tool] Saved artifact '{filename}' version {version}.")
        except ValueError as e:
             logger.error(f"[Tool] Error saving artifact '{filename}': {e}")
             return {"status": "error", "message": f"Failed to save artifact {filename}: {e}"}
        except Exception as e:
             logger.error(f"[Tool] Unexpected error saving artifact '{filename}': {e}")
             return {"status": "error", "message": f"Failed to save artifact {filename}: {e}"}


    # Update state with the names and versions of the saved artifacts
    tool_context.state["attachment_artifacts"] = saved_artifact_details
    # Store the format of the first attachment for later conversion/editing
    tool_context.state["original_file_format"] = original_file_format

    return {"status": "success", "message": f"Attachments processed and saved as artifacts.", "artifacts": saved_artifact_details}

# Wrap the tool function in a FunctionTool
download_attachments_tool = FunctionTool(func=download_attachments)


# Tool 2: Extract Text from Document Artifacts
# This tool is called by the Custom Orchestrator agent
async def extract_text(tool_context: ToolContext) -> Dict[str, Any]:
    """
    Tool to extract text from document artifacts.

    Reads artifact names/versions from state['attachment_artifacts'].
    Loads artifacts, extracts text (handles .docx, .pdf etc.).
    Writes extracted text(s) and potentially original format to state.
    """
    logger.info(f"[Tool] extract_text called.")
    attachment_artifacts = tool_context.state.get("attachment_artifacts", {})
    extracted_texts = {} # Use a dict to store text from multiple files if needed
    original_file_format = None

    if not attachment_artifacts:
        logger.warning(f"[Tool] No attachment artifacts found in state.")
        tool_context.state["extracted_text"] = "" # Save empty string
        return {"status": "success", "message": "No artifacts to extract text from."}

    # Assuming we only process the first document attachment for simplicity in this workflow
    # In a real app, you might need to process multiple documents (e.g., original and translated)
    first_artifact_name = list(attachment_artifacts.keys())[0]
    first_artifact_version = attachment_artifacts[first_artifact_name]

    try:
        # Load the artifact content
        artifact_part = await tool_context.load_artifact(
            filename=first_artifact_name, version=first_artifact_version
        )

        if not artifact_part or not artifact_part.inline_data:
             logger.error(f"[Tool] Failed to load or artifact has no inline data: {first_artifact_name} v{first_artifact_version}.")
             return {"status": "error", "message": f"Failed to load artifact {first_artifact_name} for text extraction."}

        # Extract text based on MIME type
        mime_type = artifact_part.inline_data.mime_type
        file_content_bytes = artifact_part.inline_data.data
        extracted_text_content = ""

        # --- Placeholder: Text Extraction Logic ---
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            logger.info(f"[Tool] Extracting text from DOCX: {first_artifact_name}")
            try:
                from docx import Document # Requires python-docx
                from io import BytesIO
                doc = Document(BytesIO(file_content_bytes))
                extracted_text_content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
                original_file_format = "docx"
                logger.info(f"[Tool] Extracted {len(extracted_text_content)} chars from DOCX.")
            except ImportError:
                logger.error("[Tool] python-docx not installed. Cannot extract text from DOCX.")
                return {"status": "error", "message": "Python-docx library not found. Cannot extract text from DOCX."}
            except Exception as e:
                logger.error(f"[Tool] Error extracting text from DOCX: {e}")
                return {"status": "error", "message": f"Error extracting text from DOCX: {e}"}

        elif mime_type == "application/pdf":
             logger.info(f"[Tool] Extracting text from PDF: {first_artifact_name}")
             try:
                 from PyPDF2 import PdfReader # Requires PyPDF2
                 from io import BytesIO
                 reader = PdfReader(BytesIO(file_content_bytes))
                 extracted_text_content = "".join([page.extract_text() for page in reader.pages if page.extract_text()])
                 original_file_format = "pdf"
                 logger.info(f"[Tool] Extracted {len(extracted_text_content)} chars from PDF.")
             except ImportError:
                 logger.error("[Tool] PyPDF2 not installed. Cannot extract text from PDF.")
                 return {"status": "error", "message": "PyPDF2 library not found. Cannot extract text from PDF."}
             except Exception as e:
                 logger.error(f"[Tool] Error extracting text from PDF: {e}")
                 return {"status": "error", "message": f"Error extracting text from PDF: {e}"}
        else:
            logger.warning(f"[Tool] Unsupported MIME type for text extraction: {mime_type} for {first_artifact_name}. Attempting raw text.")
            try:
                 # Attempt decoding as text if possible (e.g., .txt files or simple encodings)
                 extracted_text_content = file_content_bytes.decode('utf-8', errors='ignore')
                 original_file_format = "txt" # Assume if decode works
                 logger.info(f"[Tool] Decoded {len(extracted_text_content)} chars as text.")
            except Exception as e:
                 logger.error(f"[Tool] Failed to decode content as text: {e}")
                 return {"status": "error", "message": f"Unsupported file type for text extraction: {mime_artifact.mime_type}"}
        # --- End Placeholder ---

        # Save the extracted text (and original format) to state
        tool_context.state["extracted_text"] = extracted_text_content
        tool_context.state["original_file_format"] = original_file_format

        return {"status": "success", "message": f"Text extracted from {first_artifact_name}.", "extracted_char_count": len(extracted_text_content)}

    except Exception as e:
        logger.error(f"[Tool] Unexpected error during text extraction: {e}")
        return {"status": "error", "message": f"Unexpected error during text extraction: {e}"}

# Wrap the tool function
extract_text_tool = FunctionTool(func=extract_text)


# Tool 3: Translate Text (Applies Sensitive Data Callbacks)
# Called by TranslationWorkflowAgent
# Attach the sensitive data callbacks to this tool
async def translate_text(tool_context: ToolContext, text: str, target_language: str = "French") -> Dict[str, Any]:
    """
    Tool to translate text using an external API.
    Sensitive data handling callbacks are attached to this tool.

    Reads text argument (may contain placeholders).
    Reads target_language argument.
    Returns translated text (may contain placeholders initially).
    """
    logger.info(f"[Tool] translate_text called for {len(text)} chars to {target_language}.")

    # --- Placeholder: Call External Translation API ---
    try:
        # In a real app, you'd call an API like Google Cloud Translation, DeepL, etc.
        # Example using requests (install it first: pip install requests)
        # api_url = "https://translation.googleapis.com/language/translate/v2" # Example
        # api_key = os.getenv("TRANSLATION_API_KEY") # Get from .env
        # if not api_key:
        #     logger.error("[Tool] TRANSLATION_API_KEY not set.")
        #     return {"status": "error", "message": "Translation API key not configured."}
        #
        # response = requests.post(api_url, params={'key': api_key}, json={
        #     'q': text,
        #     'target': target_language,
        #     'source': 'en', # Assuming source is always English based on prompt
        # })
        # response.raise_for_status() # Raise an exception for bad status codes
        # result = response.json()
        # translated_text_content = result['data']['translations'][0]['translatedText']

        # Simulate translation (placeholders are carried through)
        translated_text_content = f"Translated: {text} (to {target_language})" # Placeholders like __VAR_1__ will be here

        logger.info(f"[Tool] Simulated translation.")
        return {"status": "success", "translated_text": translated_text_content}

    except Exception as e:
        logger.error(f"[Tool] Error calling translation API: {e}")
        return {"status": "error", "message": f"Translation failed: {e}"}
    # --- End Placeholder ---

# Wrap the tool function and ATTACH THE SENSITIVE DATA CALLBACKS
translate_text_tool = FunctionTool(
    func=translate_text,
    before_tool_callback=handle_sensitive_before, # Apply sensitive data handler before
    after_tool_callback=handle_sensitive_after,   # Apply sensitive data handler after
)


# Tool 4: Check Translation Quality (Applies Sensitive Data Callbacks)
# Called by TranslationWorkflowAgent or ReviewWorkflowAgent
# Attach the sensitive data callbacks to this tool
async def check_translation(tool_context: ToolContext, original_text: str, translated_text: str) -> Dict[str, Any]:
    """
    Tool to check the quality and accuracy of translated text against the original.
    Sensitive data handling callbacks are attached to this tool.

    Reads original_text argument (may contain placeholders).
    Reads translated_text argument (may contain placeholders).
    Returns feedback/score (may contain placeholders initially).
    """
    logger.info(f"[Tool] check_translation called for {len(original_text)} vs {len(translated_text)} chars.")

    # --- Placeholder: Translation Quality Check Logic ---
    try:
        # In a real app, you might use:
        # - Another LLM call specifically for evaluation
        # - NLP libraries for similarity scores
        # - Comparison against a Translation Memory (TM)
        # The texts passed here will have sensitive data replaced by placeholders *if* the callback ran.

        # Simulate quality check feedback (placeholders are carried through)
        feedback_text = f"Quality check feedback: The translation seems reasonable, but pay attention to terms like {translated_text.split(' ')[-1]} (from original {original_text.split(' ')[-1]}). Score: 85/100."
        # Placeholders like __VAR_1__ will be in original_text/translated_text args
        # and potentially generated in feedback_text by the simulation here.

        logger.info(f"[Tool] Simulated quality check.")
        return {"status": "success", "feedback_text": feedback_text, "score": 85} # Example structure

    except Exception as e:
        logger.error(f"[Tool] Error during translation quality check: {e}")
        return {"status": "error", "message": f"Quality check failed: {e}"}
    # --- End Placeholder ---

# Wrap the tool function and ATTACH THE SENSITIVE DATA CALLBACKS
check_translation_tool = FunctionTool(
    func=check_translation,
    before_tool_callback=handle_sensitive_before, # Apply sensitive data handler before
    after_tool_callback=handle_sensitive_after,   # Apply sensitive data handler after
)


# Tool 5: Edit Word Document with Track Changes (Applies Sensitive Data Callbacks)
# Called by ReviewWorkflowAgent
# Attach the sensitive data callbacks to this tool
async def edit_word_doc(tool_context: ToolContext, artifact_name: str, artifact_version: int, edit_instructions: str) -> Dict[str, Any]:
    """
    Tool to load a Word document artifact, apply edits with track changes,
    and save the edited document as a new artifact version.
    Sensitive data handling callbacks are attached to this tool.

    Reads document artifact by name/version.
    Reads edit_instructions argument (may contain placeholders).
    Saves edited document as a new artifact version.
    Returns new artifact name/version.
    """
    logger.info(f"[Tool] edit_word_doc called for artifact '{artifact_name}' v{artifact_version}.")

    try:
        # Load the document artifact content
        doc_artifact_part = await tool_context.load_artifact(filename=artifact_name, version=artifact_version)

        if not doc_artifact_part or not doc_artifact_part.inline_data:
             logger.error(f"[Tool] Failed to load document artifact or it has no inline data: {artifact_name} v{artifact_version}.")
             return {"status": "error", "message": f"Failed to load document artifact {artifact_name} for editing."}

        # --- Placeholder: Document Editing Logic with Track Changes ---
        try:
             # This is complex! python-docx has limited track changes support.
             # You might need a commercial library or API (e.g., Aspose.Words, DocuSign, Google Docs API)
             # Or a workflow involving converting to a different format, editing, and converting back.

             logger.info(f"[Tool] Applying edits with track changes based on instructions ({len(edit_instructions)} chars).")
             edited_content_bytes = b"Edited document content with track changes simulated.\n" + doc_artifact_part.inline_data.data # Simulate edit
             edited_mime_type = doc_artifact_part.inline_data.mime_type # Keep original type

             # Note: Real implementation involves parsing docx XML, applying changes, saving.
             # Placeholder text may contain placeholders *if* the callback processed it.
             # If you need to process the *document content* itself for sensitive data within the tool,
             # you'd need to do it here before calling an external editing API, and apply callbacks
             # around that internal content processing step, not just the tool args/response.
             # For simplicity, we assume sensitive data is mainly in instructions and output text feedback.

        except ImportError:
             logger.error("[Tool] python-docx not installed. Cannot edit DOCX.")
             return {"status": "error", "message": "Python-docx library not found. Cannot edit DOCX."}
        except Exception as e:
             logger.error(f"[Tool] Error during document editing: {e}")
             return {"status": "error", "message": f"Document editing failed: {e}"}
        # --- End Placeholder ---

        # Create a new artifact part for the edited document
        edited_artifact_part = types.Part.from_data(data=edited_content_bytes, mime_type=edited_mime_type)

        # Save the edited document as a *new version* of the same artifact filename
        # The artifact service handles assigning the next version number
        new_version = await tool_context.save_artifact(filename=artifact_name, artifact=edited_artifact_part)
        logger.info(f"[Tool] Saved edited document as artifact '{artifact_name}' version {new_version}.")

        return {"status": "success", "message": f"Document edited and saved as version {new_version}.", "edited_artifact_name": artifact_name, "edited_artifact_version": new_version}

    except Exception as e:
        logger.error(f"[Tool] Unexpected error during document editing workflow: {e}")
        return {"status": "error", "message": f"Unexpected error during document editing workflow: {e}"}

# Wrap the tool function and ATTACH THE SENSITIVE DATA CALLBACKS
edit_word_doc_tool = FunctionTool(
    func=edit_word_doc,
    # Apply sensitive data handling before and after
    before_tool_callback=handle_sensitive_before,
    after_tool_callback=handle_sensitive_after,
)


# Tool 6: Convert Text to Word Document Artifact
# Called by TranslationWorkflowAgent
async def convert_to_word(tool_context: ToolContext, translated_text: str, original_format: str = "docx") -> Dict[str, Any]:
    """
    Tool to convert text into a Word document artifact.

    Reads translated_text argument.
    Reads original_format argument from state.
    Creates a Word document.
    Saves the document as an artifact.
    Returns new artifact name/version.
    """
    logger.info(f"[Tool] convert_to_word called for {len(translated_text)} chars, original format '{original_format}'.")

    # --- Placeholder: Convert Text to Word Logic ---
    try:
        # Requires python-docx or similar library
        if original_format != "docx":
            logger.warning(f"[Tool] Original format '{original_format}' not DOCX. Converting to DOCX anyway.")

        try:
            from docx import Document # Requires python-docx
            from io import BytesIO
            doc = Document()
            doc.add_paragraph(translated_text)
            # Add more complex formatting if needed based on original_format or template

            buffer = BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            word_bytes = buffer.getvalue()
            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            logger.info(f"[Tool] Created DOCX document ({len(word_bytes)} bytes).")
        except ImportError:
             logger.error("[Tool] python-docx not installed. Cannot create DOCX.")
             return {"status": "error", "message": "Python-docx library not found. Cannot create DOCX."}
        except Exception as e:
             logger.error(f"[Tool] Error creating DOCX: {e}")
             return {"status": "error", "message": f"Error creating DOCX: {e}"}
        # --- End Placeholder ---

        # Create a new artifact part for the Word document
        word_artifact_part = types.Part.from_data(data=word_bytes, mime_type=mime_type)

        # Define a filename for the translated/edited document
        # Use a consistent naming convention, maybe based on original filename and status
        original_filename = tool_context.state.get("initial_attachments", [None])[0] # Get name of first attachment
        if original_filename:
             base_name = os.path.splitext(original_filename)[0]
             # Assuming this is for translated document:
             output_filename = f"{base_name}_translated.docx"
        else:
             output_filename = f"translated_document_{uuid.uuid4().hex[:6]}.docx"

        # Save the document as a new artifact
        # Versioning starts from 0 for this new filename
        version = await tool_context.save_artifact(filename=output_filename, artifact=word_artifact_part)
        logger.info(f"[Tool] Saved Word document as artifact '{output_filename}' version {version}.")

        return {"status": "success", "message": f"Document saved as artifact '{output_filename}' v{version}.", "artifact_name": output_filename, "artifact_version": version}

    except Exception as e:
        logger.error(f"[Tool] Unexpected error during Word conversion: {e}")
        return {"status": "error", "message": f"Unexpected error during Word conversion: {e}"}

# Wrap the tool function
convert_to_word_tool = FunctionTool(func=convert_to_word)


# Tool 7: Send Final Email
# Called by EmailSenderAgent
async def send_final_email(tool_context: ToolContext) -> Dict[str, Any]:
    """
    Tool to send the final email with the processed document attachment.

    Reads recipient email from state['email_sender_email'].
    Reads email body from state['initial_reply_text'].
    Reads final document artifact name/version from state
    (either 'translated_document_artifact' or 'edited_document_artifact').
    Loads artifact and sends email.
    """
    logger.info(f"[Tool] send_final_email called.")

    recipient_email = tool_context.state.get("email_sender_email")
    email_body_text = tool_context.state.get("initial_reply_text") # Use initial reply text
    email_subject = tool_context.state.get("email_subject") # Use original subject

    # Determine which artifact is the final document based on email type
    email_type = tool_context.state.get("email_type")
    if email_type == "translation":
         final_artifact_details = tool_context.state.get("translated_document_artifact")
    elif email_type == "review":
         final_artifact_details = tool_context.state.get("edited_document_artifact")
    else:
         logger.error(f"[Tool] Cannot send email, unknown email type: {email_type}")
         return {"status": "error", "message": "Cannot send email, unknown process type."}

    if not recipient_email or not email_body_text or not final_artifact_details:
         logger.error(f"[Tool] Cannot send email, missing recipient, body, or artifact details.")
         return {"status": "error", "message": "Cannot send email, missing required information."}

    final_artifact_name = final_artifact_details.get("artifact_name")
    final_artifact_version = final_artifact_details.get("artifact_version")

    if not final_artifact_name or final_artifact_version is None:
         logger.error(f"[Tool] Cannot send email, final artifact details incomplete.")
         return {"status": "error", "message": "Cannot send email, final artifact details incomplete."}


    try:
        # Load the final document artifact content
        final_doc_artifact_part = await tool_context.load_artifact(
            filename=final_artifact_name, version=final_artifact_version
        )

        if not final_doc_artifact_part or not final_doc_artifact_part.inline_data:
            logger.error(f"[Tool] Failed to load final document artifact: {final_artifact_name} v{final_artifact_version}.")
            return {"status": "error", "message": f"Failed to load final document artifact {final_artifact_name}."}

        # --- Placeholder: Send Email Logic ---
        try:
            logger.info(f"[Tool] Simulating sending email to {recipient_email}.")
            logger.info(f"[Tool] Subject: {email_subject}")
            logger.info(f"[Tool] Body: {email_body_text}")
            logger.info(f"[Tool] Attaching artifact: {final_artifact_name} ({final_doc_artifact_part.inline_data.mime_type})")

            # In a real app, use an email sending library or API (e.g., SendGrid, Mailgun, Gmail API)
            # You would attach final_doc_artifact_part.inline_data.data (bytes) with the specified mime_type and filename.

            # Example using print for simulation
            print(f"\n--- SIMULATING EMAIL SEND ---")
            print(f"To: {recipient_email}")
            print(f"Subject: {email_subject}")
            print(f"Body:\n{email_body_text}")
            print(f"Attachment: {final_artifact_name} ({len(final_doc_artifact_part.inline_data.data)} bytes, {final_doc_artifact_part.inline_data.mime_type})")
            print(f"-----------------------------\n")

            # Simulate success
            logger.info(f"[Tool] Email simulation successful.")
            return {"status": "success", "message": "Email sent successfully."}

        except Exception as e:
            logger.error(f"[Tool] Error sending email: {e}")
            return {"status": "error", "message": f"Email sending failed: {e}"}
        # --- End Placeholder ---

    except Exception as e:
        logger.error(f"[Tool] Unexpected error loading artifact or sending email: {e}")
        return {"status": "error", "message": f"Unexpected error during email sending: {e}"}


# Wrap the tool function
send_email_tool = FunctionTool(func=send_final_email)
```
## Running the Workflow:

  Save the files with the structure above.

  Install dependencies: pip install -r requirements.txt (or poetry install if using Poetry).

  Copy .env.example to .env and fill in at least your GOOGLE_API_KEY.

  Run the main.py script: python main.py.

The script will simulate receiving two emails and run them through the ADK workflow, printing the different steps and results based on the email type. Observe the logs to see how state changes and which agents/tools are called.

This provides a solid foundation for your complex email processing agent workflow. You will need to fill in the actual logic within the placeholder sections for document parsing, external API calls, and fine-tune the sensitive data handling logic based on your specific needs.

