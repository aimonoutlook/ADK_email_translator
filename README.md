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
