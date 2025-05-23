      
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
