import os
from openai import OpenAI
from dotenv import load_dotenv
import json
import re
from typing import Dict, Optional, Any, Tuple, List

load_dotenv()

client = OpenAI(
    api_key=os.environ.get("GOOGLE_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    default_headers={"x-goog-api-key": os.environ.get("GOOGLE_API_KEY")}
)

# ---- NEW: Global list to store LLM calls ----
LLM_CALL_LOG = []
# --------------------------------------------


def call_llm(
    model: str, messages: list[dict], temperature: float = 0
) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
    """
    Calls the LLM API, logs the interaction, and returns content and usage.
    Returns (None, None) on API error.
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            n=1,
            temperature=temperature,
        )

        output_content = response.choices[0].message.content
        usage_stats = (
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
        )

        # ---- NEW: Log the call details ----
        log_entry = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "output": output_content,
            "usage": {
                "prompt_tokens": usage_stats[0],
                "completion_tokens": usage_stats[1],
            },
        }
        LLM_CALL_LOG.append(log_entry)
        # -----------------------------------

        return output_content, usage_stats

    except Exception as e:
        print(f"ERROR: LLM API call failed for model {model}: {e}")
        # Log the error attempt? Maybe not for the clean log requested.
        # You could add a separate error log if needed.
        # ---- NEW: Log the failed attempt ----
        # log_entry = {
        #     "model": model,
        #     "messages": messages,
        #     "temperature": temperature,
        #     "output": None,
        #     "error": str(e),
        #     "usage": None
        # }
        # LLM_CALL_LOG.append(log_entry)
        # ------------------------------------
        return None, None  # Indicate failure


# ---- NEW: Function to save the log ----
def save_llm_log_to_json(filename: str = "llm_calls_log.json"):
    """Saves the accumulated LLM call log to a JSON file."""
    print(f"Attempting to save {len(LLM_CALL_LOG)} LLM calls to {filename}...")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(LLM_CALL_LOG, f, indent=2, ensure_ascii=False)
        print(f"LLM call log successfully saved to {filename}")
    except Exception as e:
        print(f"ERROR: Failed to save LLM call log to {filename}: {e}")


# Option 1: Automatically save on exit (use with caution in notebooks)
# atexit.register(save_llm_log_to_json, filename="llm_calls_log_autosave.json")
# ---------------------------------------


def parse_llm_json_output(
    llm_output: Optional[str],
    expected_schema: Optional[
        Dict
    ] = None,  # Currently unused, but placeholder for future validation
) -> Optional[Dict]:
    """
    Safely parses JSON from LLM output, handling markdown code fences.

    Args:
        llm_output: The raw string output from the LLM.
        expected_schema: Optional schema for basic validation (not implemented yet).

    Returns:
        The parsed dictionary or None if parsing fails or input is None.
    """
    if llm_output is None:
        # print("Debug: parse_llm_json_output received None input.") # Optional debug print
        return None

    # Regex to find JSON within ```json ... ``` blocks
    match = re.search(r"```json\s*(\{.*?\})\s*```", llm_output, re.DOTALL)

    json_string = None
    if match:
        json_string = match.group(1).strip()
        # print("Debug: Found JSON within ```json fences.") # Optional debug print
    else:
        # print("Debug: No ```json fences found. Checking if entire string is JSON.") # Optional debug print
        # Fallback: Check if the entire string is valid JSON (maybe without fences)
        # Be cautious with this fallback as LLMs often add extra text
        temp_string = llm_output.strip()
        if temp_string.startswith("{") and temp_string.endswith("}"):
            # print("Debug: Entire string looks like JSON.") # Optional debug print
            json_string = temp_string
        # else: # Removed risky loose brace finding

    if json_string:
        try:
            parsed_json = json.loads(json_string)
            if isinstance(parsed_json, dict):
                # Optional: Add basic schema validation here if needed
                # if expected_schema and not all(key in parsed_json for key in expected_schema):
                #     print("Warning: Parsed JSON missing expected keys.")
                #     return None # Or handle differently
                # print("Debug: Successfully parsed JSON string into dict.") # Optional debug print
                return parsed_json
            else:
                print(f"Warning: Parsed JSON is not a dictionary: {type(parsed_json)}")
                return None
        except json.JSONDecodeError as e:
            print(
                f"ERROR: Failed to decode JSON: {e}\nInput string (first 500 chars): {json_string[:500]}..."
            )
            return None
        except Exception as e:
            print(f"ERROR: Unexpected error parsing JSON: {e}")
            return None
    else:
        # print(f"Warning: No valid JSON structure found in LLM output (first 500 chars): {llm_output[:500]}...") # Keep this warning
        return None
