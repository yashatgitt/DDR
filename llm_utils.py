"""
OpenAI API utilities for DDR generation.

Handles:
- Structured data extraction from PDFs (JSON format)
- Final DDR report formatting
- Error handling and retries
- Token-aware chunking
"""

import os
import json
import logging
import signal
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
import google.generativeai as genai
from functools import wraps
import time

load_dotenv()

logger = logging.getLogger(__name__)

# Timeout configuration (in seconds)
DEFAULT_TIMEOUT = int(os.getenv("API_TIMEOUT", 120))  # 2 minutes default
REPORT_GEN_TIMEOUT = int(os.getenv("REPORT_GEN_TIMEOUT", 180))  # 3 minutes for report generation


class TimeoutError(Exception):
    """Custom timeout error."""
    pass


def timeout_handler(signum, frame):
    """Handle timeout signal."""
    raise TimeoutError("Operation exceeded maximum allowed time")


def with_timeout(timeout_seconds):
    """Decorator to add timeout to functions (Unix-based systems only)."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Note: signal.alarm() is only available on Unix/Linux
            # Windows will just run without the timeout decorator
            # Timeout is handled by OpenAI client timeout parameter instead
            if hasattr(signal, 'SIGALRM'):
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(timeout_seconds)
                try:
                    result = func(*args, **kwargs)
                    signal.alarm(0)  # Cancel alarm
                    return result
                except TimeoutError as e:
                    logger.error(f"Timeout in {func.__name__}: {e}")
                    raise
                finally:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
            else:
                # Windows: just call the function normally
                # OpenAI client timeout handles the timeout
                return func(*args, **kwargs)
        return wrapper
    return decorator


class LLMExtractor:
    """Handles LLM calls for extraction and report generation using Google Gemini."""

    def __init__(self):
        """Initialize Google Gemini client."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in .env")
        
        genai.configure(api_key=api_key)
        # Using Gemini 2.5 Flash (newest, fastest, best for DDR reports)
        # Other options: 'gemini-2.5-pro', 'gemini-2.0-flash', 'gemini-flash-latest'
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        self.max_retries = int(os.getenv("MAX_RETRIES", 2))
        logger.info("Initialized Gemini LLM Extractor")

    def extract_structured_data(
        self, 
        inspection_text: str, 
        thermal_text: str
    ) -> Dict[str, Any]:
        """
        Extract structured data from inspection and thermal PDFs.
        
        Returns strict JSON with areas, findings, and conflicts.
        Retries once if JSON is invalid.
        """
        prompt = self._build_extraction_prompt(inspection_text, thermal_text)
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Extraction attempt {attempt + 1}/{self.max_retries}")
                
                # Call Gemini API
                response = self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,
                        max_output_tokens=8000  # Increased to handle larger PDFs
                    )
                )
                
                content = response.text
                
                # Find and parse JSON
                json_str = self._extract_json(content)
                data = json.loads(json_str)
                
                # Validate structure
                if self._validate_extraction_data(data):
                    logger.info("Successfully extracted structured data")
                    return data
                else:
                    raise ValueError("Invalid extraction data structure")
                    
            except json.JSONDecodeError as e:
                logger.warning(f"Attempt {attempt + 1}: JSON parsing failed: {e}")
                if attempt == self.max_retries - 1:
                    raise ValueError(f"Failed to extract valid JSON after {self.max_retries} attempts")
            except Exception as e:
                error_str = str(e).lower()
                
                # Handle quota/rate limit errors
                if "quota" in error_str or "rate_limit" in error_str or "429" in error_str:
                    logger.error(f"API Rate Limit: {e}")
                    raise ValueError(
                        "GEMINI RATE LIMIT: You have exceeded the free tier rate limit.\n\n"
                        "Free tier: 60 requests per minute\n\n"
                        "Solutions:\n"
                        "1. Wait a few minutes and try again\n"
                        "2. Use smaller PDF files\n"
                        "3. Switch to paid tier for higher limits\n\n"
                        "See OPENAI_vs_GEMINI_COMPARISON.md for more info."
                    )
                else:
                    logger.error(f"API error on attempt {attempt + 1}: {e}")
                    if attempt == self.max_retries - 1:
                        raise

    def generate_ddr_report(self, merged_data: Dict[str, Any]) -> str:
        """
        Generate final DDR report from merged structured data.
        
        Returns formatted report text.
        """
        prompt = self._build_ddr_prompt(merged_data)
        
        try:
            logger.info(f"Generating DDR report")
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=10000  # Increased for comprehensive DDR reports
                )
            )
            
            report = response.text
            logger.info("Successfully generated DDR report")
            return report
            
        except Exception as e:
            error_str = str(e).lower()
            if "rate_limit" in error_str or "quota" in error_str:
                logger.error(f"Rate limit during DDR generation: {e}")
                raise ValueError(
                    "GEMINI RATE LIMIT: Free tier rate limit reached.\n\n"
                    "Please wait a few minutes before trying again.\n"
                    "Or upgrade to a paid tier for higher limits."
                )
            logger.error(f"Failed to generate DDR report: {e}")
            raise

    def _build_extraction_prompt(
        self, 
        inspection_text: str, 
        thermal_text: str
    ) -> str:
        """Build prompt for structured data extraction."""
        return f"""Extract findings from inspection and thermal reports into structured JSON format.

INSPECTION REPORT:
{inspection_text[:3000]}

THERMAL REPORT:
{thermal_text[:3000]}

TASK: Extract findings for each area/room mentioned in the reports.

CRITICAL RULES FOR JSON OUTPUT (MUST FOLLOW EXACTLY):
1. Return ONLY valid JSON - nothing else before or after, no markdown
2. Complete all fields - never leave arrays empty in the middle
3. All fields must have complete values - do not cut off or truncate
4. No trailing commas before ] or }}
5. No comments or explanatory text in JSON
6. All strings use double quotes, properly escaped
7. All field names exactly as specified - case sensitive
8. Empty arrays should be: []
9. Never use null - use [] for empty arrays or "" for empty strings

REQUIRED JSON STRUCTURE (Complete Example):
{{
  "areas": [
    {{
      "area_name": "Hall",
      "inspection_findings": ["Skirting level Dampness", "Common Bathroom tile hollowness"],
      "thermal_findings": ["Temperature variation near door"],
      "conflicts": ["None observed"],
      "missing_info": []
    }},
    {{
      "area_name": "Kitchen",
      "inspection_findings": [],
      "thermal_findings": ["High temperature near stove"],
      "conflicts": [],
      "missing_info": ["Ventilation assessment"]
    }}
  ]
}}

VALIDATION CHECKLIST:
- "areas" array is complete and closed with ]
- Each area object has all 5 fields
- Each field (except area_name) is properly closed array with ]
- No incomplete arrays like "thermal_findings": [ without closing ]
- No trailing commas like ["item1", "item2",]
- Valid JSON parseable with json.loads()

Return ONLY the complete, valid JSON. No explanations. No code blocks."""

    def _build_ddr_prompt(self, merged_data: Dict[str, Any]) -> str:
        """Build prompt for final DDR report generation - BALANCED REASONING."""
        return f"""Generate the Detailed Diagnostic Report (DDR) using the provided structured inspection and thermal data.

STRUCTURED DATA TO ANALYZE:
{json.dumps(merged_data, indent=2)}

RULES

Do NOT invent new facts.
Do NOT infer root causes unless explicitly mentioned.
If root cause is not explicitly stated, write: "Root cause not explicitly specified in the provided documents."

You ARE allowed to reason logically from observed findings.
You ARE allowed to assign severity based on impact described in findings.
You ARE allowed to suggest practical corrective actions based on the identified issue.

Do NOT exaggerate severity.
Use neutral professional tone.
Output clean plain text only. No markdown symbols.

SEVERITY GUIDELINES

Assign severity based on inspection findings:

If active leakage, concealed plumbing issue, or continuous water flow → High
If visible dampness, seepage, tile hollowness → Moderate
If minor cosmetic defect without moisture indication → Low
If insufficient data → Not Available

Do NOT invent severity beyond evidence.
Explain reasoning clearly in 2–4 sentences per area.

RECOMMENDED ACTION GUIDELINES

You may recommend logical repair steps based on the observed issue.

Examples:
- Dampness → investigate source, waterproofing repair, drying
- Concealed plumbing leakage → open section, repair pipe, re-seal
- Crack in external wall → structural inspection, sealing
- Tile hollowness → remove and re-fix tiles

Do NOT assume hidden structural failure.
Do NOT add unverified causes.

THERMAL HANDLING

If thermal data exists but is not area-mapped, state:
"Thermal imaging contains temperature readings; however, specific area mapping is not available, therefore direct correlation cannot be confirmed."

Do NOT ignore thermal presence.

REQUIRED STRUCTURE

DETAILED DIAGNOSTIC REPORT (DDR)

PROPERTY ISSUE SUMMARY
Write 2–3 structured paragraphs summarizing overall condition and risk.

AREA-WISE OBSERVATIONS
For each area:
- Inspection Findings
- Thermal Findings
- Analysis (logical explanation of impact)

PROBABLE ROOT CAUSE
Only if explicitly mentioned.
Otherwise use required fallback sentence.

SEVERITY ASSESSMENT (WITH REASONING)
Assign level and explain logically.

RECOMMENDED ACTIONS
Provide practical corrective steps based on findings.

ADDITIONAL NOTES
Include limitations of document-based assessment.

MISSING OR UNCLEAR INFORMATION
List missing measurements or mapping gaps.

CRITICAL REQUIREMENTS

The report must show analytical thinking, not just restating data.
Do not leave severity and recommendations as "Not Available" if logical reasoning can be applied.
Only restrict yourself from inventing new causes.
Use neutral, professional language.
Output plain text only, no markdown formatting."""

    def _extract_json(self, text: str) -> str:
        """Extract JSON from text (handles markdown code blocks and fixes common issues)."""
        if not text:
            raise ValueError("Empty response received")
        
        text = text.strip()
        
        try:
            # Method 1: Look for ```json ... ``` blocks
            if "```json" in text:
                start = text.find("```json") + 7
                end = text.find("```", start)
                if end > start:
                    json_str = text[start:end].strip()
                    if json_str:
                        try:
                            json.loads(json_str)  # Validate
                            logger.debug("Extracted JSON from ```json block")
                            return json_str
                        except json.JSONDecodeError as e:
                            logger.warning(f"JSON in ```json block is malformed: {e}")
                            # Try to fix it
                            json_str = self._fix_json(json_str)
                            json.loads(json_str)  # Validate fixed version
                            return json_str
            
            # Method 2: Look for ``` ... ``` blocks (without json label)
            if "```" in text:
                first_mark = text.find("```")
                after_open = first_mark + 3
                if after_open < len(text) and text[after_open:after_open+1] == "\n":
                    after_open += 1
                end = text.find("```", after_open)
                if end > after_open:
                    json_str = text[after_open:end].strip()
                    if json_str:
                        try:
                            json.loads(json_str)  # Validate
                            logger.debug("Extracted JSON from ``` block")
                            return json_str
                        except json.JSONDecodeError as e:
                            logger.warning(f"JSON in ``` block is malformed: {e}")
                            json_str = self._fix_json(json_str)
                            json.loads(json_str)  # Validate fixed version
                            return json_str
            
            # Method 3: Try parsing entire response as JSON (no code blocks)
            if "{" in text:
                start_idx = text.find("{")
                end_idx = text.rfind("}")
                if end_idx > start_idx:
                    json_str = text[start_idx:end_idx+1].strip()
                    if json_str:
                        try:
                            json.loads(json_str)  # Validate
                            logger.debug("Extracted JSON from raw text")
                            return json_str
                        except json.JSONDecodeError as e:
                            logger.warning(f"JSON in raw text is malformed: {e}")
                            json_str = self._fix_json(json_str)
                            json.loads(json_str)  # Validate fixed version
                            return json_str
            
            # Method 4: Last resort - try entire text
            json.loads(text)
            logger.debug("Parsed entire response as JSON")
            return text
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to extract valid JSON: {e}")
            logger.error(f"Response text sample: {text[:300]}")
            raise ValueError(
                f"Failed to extract valid JSON from response.\\n"
                f"Error: {str(e)}\\n"
                f"Response sample: {text[:200]}"
            )
    
    def _fix_json(self, json_str: str) -> str:
        """Try to fix common JSON formatting issues from LLM responses."""
        try:
            # Remove common issues
            # 1. Remove trailing commas before ] or }
            json_str = json_str.replace(",]", "]").replace(",}", "}")
            
            # 2. Remove any // comments
            lines = json_str.split("\\n")
            cleaned_lines = []
            for line in lines:
                if "//" in line:
                    line = line[:line.index("//")]
                cleaned_lines.append(line)
            json_str = "\\n".join(cleaned_lines)
            
            # 3. Complete any incomplete JSON (unclosed arrays/objects)
            json_str = self._complete_json(json_str)
            
            # Try to parse the fixed version
            json.loads(json_str)
            logger.info("Successfully fixed malformed JSON")
            return json_str
        except Exception as e:
            logger.warning(f"Could not auto-fix JSON: {e}")
            return json_str  # Return best effort
    
    def _complete_json(self, json_str: str) -> str:
        """Close any unclosed arrays and objects in incomplete JSON."""
        # Count open and close brackets
        open_brackets = json_str.count("[") - json_str.count("]")
        open_braces = json_str.count("{") - json_str.count("}")
        
        # Close any unclosed arrays
        for _ in range(open_brackets):
            json_str = json_str.rstrip() + "]"
        
        # Close any unclosed objects
        for _ in range(open_braces):
            json_str = json_str.rstrip() + "}"
        
        logger.debug(f"Completed JSON: added {open_brackets} brackets and {open_braces} braces")
        return json_str

    def _validate_extraction_data(self, data: Dict[str, Any]) -> bool:
        """Validate extracted data structure."""
        if not isinstance(data, dict):
            return False
        
        if "areas" not in data or not isinstance(data["areas"], list):
            return False
        
        if len(data["areas"]) == 0:
            logger.warning("No areas found in extracted data")
            return False
        
        for area in data["areas"]:
            if not isinstance(area, dict):
                return False
            
            # Validate area_name is a non-empty string
            if not isinstance(area.get("area_name"), str) or not area.get("area_name").strip():
                logger.warning(f"Area missing or invalid area_name: {area}")
                return False
            
            required_fields = {
                "inspection_findings", 
                "thermal_findings",
                "conflicts", 
                "missing_info"
            }
            if not all(field in area for field in required_fields):
                logger.warning(f"Area '{area.get('area_name')}' missing required fields")
                return False
            
            if not all(isinstance(area.get(field, []), list) for field in required_fields):
                logger.warning(f"Area '{area.get('area_name')}' has non-list field values")
                return False
        
        return True
