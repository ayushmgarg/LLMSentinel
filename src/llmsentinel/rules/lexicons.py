"""Pattern inventory for the rule engine.

Everything the rules match lives here so that the patterns can be reviewed,
ablated and unit-tested independently of the scoring logic.  Each entry carries
a short name that appears verbatim in the explanation shown to the user.

Precision notes are attached to the patterns that were tightened after they
misfired on hard negatives during development; keep the notes when editing.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "ACTION_VERBS",
    "ASSISTANT_ADDRESS_PATTERNS",
    "CITATION_MARKERS",
    "DESTINATION_PATTERNS",
    "DESTRUCTIVE_PATTERNS",
    "METADATA_PATTERNS",
    "META_INSTRUCTION_PATTERNS",
    "PERSISTENCE_PATTERNS",
    "SECRECY_PATTERNS",
    "SENSITIVE_OBJECTS",
    "TOOL_INVOCATION_PATTERNS",
    "compile_named",
]

NamedPatterns = tuple[tuple[str, str, float], ...]
"""(name, regex source, weight) triples.  Weight is the rule's prior confidence."""


def compile_named(patterns: NamedPatterns) -> tuple[tuple[str, re.Pattern[str], float], ...]:
    """Compile a pattern table once, case-insensitively."""

    return tuple(
        (name, re.compile(source, re.IGNORECASE | re.MULTILINE), weight)
        for name, source, weight in patterns
    )


# --------------------------------------------------------- meta instructions
META_INSTRUCTION_PATTERNS: Final[NamedPatterns] = (
    (
        "override_previous_instructions",
        r"\b(ignore|disregard|forget|discard|delete|drop|override|bypass|skip)\b"
        r"(?:\W+\w+){0,4}?\W+"
        r"\b(previous|prior|above|earlier|preceding|initial|original|former|all)\b"
        r"(?:\W+\w+){0,3}?\W+"
        r"\b(instruction|prompt|message|direction|rule|command|guideline|context|constraint)s?\b",
        0.92,
    ),
    (
        "ignore_the_instructions",
        # Up to two modifiers may sit between the determiner and the noun
        # ("disregard the operator instructions"); without this the pattern
        # missed a whole payload family on the dev split.
        r"\b(ignore|disregard)\b\W+\b(the|any|all)\b(?:\W+\w+){0,2}?\W+"
        r"\b(instruction|prompt|rule|guideline|restriction|policy|polic(?:y|ies))\w*\b",
        0.80,
    ),
    (
        "reveal_system_prompt",
        r"\b(reveal|print|show|repeat|output|display|disclose|dump|summari[sz]e)\b"
        r"(?:\W+\w+){0,4}?\W+\b(system|initial|original|hidden|developer)\b\W+"
        r"\b(prompt|instruction|message)s?\b",
        0.90,
    ),
    (
        "role_reassignment",
        r"\byou\s+are\s+(?:now|no\s+longer|actually|really)\b|"
        r"\bfrom\s+now\s+on,?\s+you\b|"
        r"\bact\s+as\s+(?:a|an|the)\s+\w+|"
        r"\bpretend\s+(?:to\s+be|you\s+are)\b|"
        r"\byour\s+(?:new|real|actual|true)\s+(?:role|task|goal|objective|purpose|instruction)s?\b",
        0.78,
    ),
    (
        "fake_role_token",
        # Chat-template control tokens have no business inside retrieved content.
        r"<\|(?:im_start|im_end|system|endoftext|eot_id|start_header_id)\|>|"
        r"\[/?INST\]|<<SYS>>|</?s>\s*\[INST\]|"
        r"(?:^|\n)\s*(?:#{2,3}\s*)?(?:system|assistant)\s*:\s*(?=\S)",
        0.72,
    ),
    (
        "new_instruction_announcement",
        r"(?:^|\n|\.|\s)\s*(?:#{1,4}\s*)?"
        r"\b(new|updated|revised|important|additional|urgent|override|special|admin|priority)\b\s+"
        r"\b(instruction|directive|task|system\s+message|command|rule|prompt)s?\b\s*[:\-]",
        0.82,
    ),
    (
        "instruction_precedence",
        r"\b(this|these|the\s+following)\b\W+\w{0,12}\W*"
        r"\b(instruction|message|directive|command)s?\b"
        r"(?:\W+\w+){0,4}?\W+"
        r"\b(take[s]?\s+precedence|override[s]?|supersede[s]?|are\s+more\s+important|"
        r"must\s+be\s+(?:followed|obeyed)|highest\s+priority)\b",
        0.88,
    ),
)

#: Attempts to change the agent's behaviour *beyond the current turn*, or to
#: claim an approval that was never given.  Added after dev-split error analysis
#: showed whole payload families scoring zero (see docs/EXPERIMENTS.md); the
#: patterns are written for the underlying move -- persisting a rule, asserting
#: prior authorisation -- rather than for the corpus strings that exposed them.
PERSISTENCE_PATTERNS: Final[NamedPatterns] = (
    (
        "persist_rule",
        r"\b(?:store|save|remember|add|keep|record)\b(?:\W+\w+){0,6}?\W+"
        r"\b(?:memory|preferences?|settings?|profile|rules?|instructions?)\b",
        0.80,
    ),
    (
        "future_conversations",
        r"\b(?:in|for)\s+(?:every|all|any|each)\s+(?:future|subsequent|later|following)\s+"
        r"(?:conversation|session|request|turn|interaction)s?\b"
        r"|\bfrom\s+now\s+on\b(?:\W+\w+){0,6}?\W+\balways\b",
        0.82,
    ),
    (
        "claimed_preauthorisation",
        r"\b(?:already|previously|pre-?)\s*(?:approved|authoris|authoriz|confirmed|permitted)\w*\b"
        r"|\b(?:no|without)\s+(?:further\s+)?(?:confirmation|approval|permission)\s+"
        r"(?:is\s+)?(?:required|needed|necessary)\b"
        r"|\bskip\s+(?:the\s+)?(?:confirmation|approval|verification)\b"
        # Passive phrasing is the natural way to say this inside a tool
        # description ("the approval step can be skipped"), and the active-voice
        # forms above missed it entirely on the dev split.
        r"|\b(?:confirmation|approval|verification|permission)\s+(?:step\s+)?"
        r"(?:can|may|need\s+not)\s+be\s+(?:skipped|omitted|bypassed|ignored|waived)\b"
        r"|\b(?:confirmation|approval|verification)\s+(?:is|are)\s+not\s+"
        r"(?:required|needed|necessary)\b",
        0.85,
    ),
)

#: Instructions to conceal behaviour from the user.  Legitimate documents do not
#: tell the reader's assistant to keep something from the reader.
SECRECY_PATTERNS: Final[NamedPatterns] = (
    (
        "conceal_from_user",
        r"\b(do\s+not|don't|never|avoid)\b(?:\W+\w+){0,3}?\W+"
        r"\b(tell|inform|mention|reveal|show|disclose|notify|alert|warn)\b"
        r"(?:\W+\w+){0,3}?\W+\b(the\s+)?(user|human|customer|operator|anyone|them)\b",
        0.90,
    ),
    (
        "silent_execution",
        r"\b(silently|quietly|secretly|covertly|without\s+(?:telling|informing|notifying|asking)"
        r"|without\s+(?:the\s+)?(?:user|human)'?s?\s+(?:knowledge|consent|permission))\b",
        0.80,
    ),
    (
        "suppress_output",
        r"\b(do\s+not|don't)\b\W+\b(mention|include|output|print|display|repeat)\b"
        r"(?:\W+\w+){0,4}?\W+\b(this|these|that|the\s+(?:instruction|message|note|text))\b",
        0.76,
    ),
)

# ------------------------------------------------------- assistant addressing
ASSISTANT_ADDRESS_PATTERNS: Final[NamedPatterns] = (
    (
        "explicit_assistant_address",
        r"\b(?:attention|note|message|important)\s*[:,]?\s*"
        r"(?:to\s+)?(?:the\s+)?(?:ai|llm|assistant|chatbot|agent|model|copilot|claude|chatgpt|gpt)\b"
        r"|\b(?:dear|hey|hello)\s+(?:ai|assistant|agent|model)\b"
        r"|\bif\s+you\s+are\s+an?\s+(?:ai|llm|assistant|language\s+model|agent)\b",
        0.88,
    ),
    (
        "second_person_directive",
        r"\byou\s+(?:must|should|shall|need\s+to|have\s+to|are\s+required\s+to|are\s+instructed\s+to)\b",
        0.45,
    ),
    (
        "before_responding",
        r"\b(?:before|prior\s+to|when|after)\s+"
        r"(?:you\s+)?(?:answer|respond|reply|continue|summari[sz]e|proceed)\w*\b"
        r"(?:\W+\w+){0,6}?\W+\b(?:you\s+)?(?:must|should|please|first|always|make\s+sure)\b",
        0.70,
    ),
    (
        "task_reassignment",
        r"\byour\s+(?:only\s+)?(?:task|job|goal|instruction|objective)\s+is\s+(?:now\s+)?to\b",
        0.80,
    ),
)

# ------------------------------------------------------------- exfiltration
#: Verbs that move data outward.  ``share`` and ``send`` are common in benign
#: prose, so the exfiltration rule requires a sensitive object *and* a
#: destination before it assigns a high score.
ACTION_VERBS: Final[NamedPatterns] = (
    ("send", r"\bsend(?:s|ing)?\b", 1.0),
    ("email", r"\b(?:e-?mail|mail)(?:s|ing|ed)?\b", 1.0),
    ("forward", r"\bforward(?:s|ing|ed)?\b", 1.0),
    ("post", r"\bpost(?:s|ing|ed)?\b", 0.9),
    ("upload", r"\bupload(?:s|ing|ed)?\b", 1.0),
    ("transmit", r"\btransmit(?:s|ting|ted)?\b", 1.0),
    ("exfiltrate", r"\bexfiltrat(?:e|es|ing|ed)\b", 1.0),
    ("leak", r"\bleak(?:s|ing|ed)?\b", 0.9),
    ("disclose", r"\bdisclos(?:e|es|ing|ed)\b", 0.9),
    ("share", r"\bshar(?:e|es|ing|ed)\b", 0.7),
    ("publish", r"\bpublish(?:es|ing|ed)?\b", 0.8),
    ("export", r"\bexport(?:s|ing|ed)?\b", 0.8),
    ("fetch_to", r"\b(?:curl|wget|fetch|request)\b", 0.7),
    ("append_to_url", r"\bappend(?:s|ing|ed)?\b", 0.7),
    ("include_in_response", r"\binclude\b(?:\W+\w+){0,3}\W+\b(?:in|into)\b", 0.6),
)

SENSITIVE_OBJECTS: Final[NamedPatterns] = (
    ("api_key", r"\bapi[_\-\s]?keys?\b", 1.0),
    ("access_token", r"\b(?:access|bearer|auth(?:orisation|orization)?|refresh)[_\-\s]?tokens?\b", 1.0),
    ("password", r"\bpass(?:word|wd|phrase)s?\b", 1.0),
    ("credential", r"\bcredentials?\b", 1.0),
    ("secret", r"\bsecrets?\b|\bclient[_\-\s]?secret\b", 0.9),
    ("private_key", r"\b(?:private|ssh|signing|pgp)[_\-\s]?keys?\b", 1.0),
    ("env_file", r"(?:^|\W)\.env\b|\benvironment\s+variables?\b", 0.9),
    ("session_cookie", r"\b(?:session\s+)?cookies?\b|\bsession\s+ids?\b", 0.8),
    ("system_prompt", r"\bsystem\s+prompt\b|\binitial\s+instructions?\b", 0.9),
    ("conversation", r"\b(?:conversation|chat|message)\s+(?:history|log|transcript|contents?)\b", 0.9),
    ("personal_data", r"\b(?:personal\s+data|pii|social\s+security|ssn|passport\s+number)\b", 0.9),
    ("financial", r"\b(?:credit\s+card|card\s+number|cvv|bank\s+(?:account|details)|iban)\b", 1.0),
    ("user_files", r"\b(?:user'?s?\s+)?(?:documents?|files?|notes?|emails?|inbox|contacts?)\b", 0.5),
    ("database", r"\bdatabase\s+(?:dump|contents?|records?)\b", 0.8),
)

DESTINATION_PATTERNS: Final[NamedPatterns] = (
    ("url", r"\bhttps?://[^\s<>\")\]]{4,}", 1.0),
    ("bare_domain", r"\b(?:www\.)?[a-z0-9][a-z0-9\-]{1,61}\.(?:com|net|org|io|xyz|ru|cn|top|tk|info|site|link|dev|me|co)\b(?:/[^\s]*)?", 0.6),
    ("email_address", r"\b[\w.+\-]{1,64}@[\w\-]{1,63}(?:\.[\w\-]{2,63})+\b", 0.9),
    ("webhook", r"\bweb\s?hook\b|\bendpoint\s+at\b|\bcallback\s+url\b", 0.8),
    ("ip_address", r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{2,5})?\b", 0.7),
    ("markdown_image", r"!\[[^\]]*\]\(\s*https?://[^)]+\)", 1.0),
    ("markdown_link", r"(?<!!)\[[^\]]+\]\(\s*https?://[^)]+\)", 0.6),
)

# -------------------------------------------------------------- tool actions
TOOL_INVOCATION_PATTERNS: Final[NamedPatterns] = (
    (
        "call_tool",
        r"\b(?:call|invoke|use|run|execute|trigger|issue|perform)\b(?:\W+\w+){0,4}?\W+"
        r"\b(?:tool|function|api|endpoint|command|script|action|plugin|mcp\s+server)\b",
        0.72,
    ),
    (
        "named_tool_call",
        r"\b(?:call|invoke|use|run)\s+(?:the\s+)?`?[a-z_][a-z0-9_]{2,30}`?\s*\(",
        0.70,
    ),
    (
        "shell_command",
        r"\b(?:curl|wget|nc|bash\s+-c|powershell\s+-c|invoke-webrequest)\b\s+\S",
        0.75,
    ),
)

DESTRUCTIVE_PATTERNS: Final[NamedPatterns] = (
    ("delete_everything", r"\b(?:delete|remove|erase|wipe|purge|destroy)\b\W+\b(?:all|every|the\s+entire|each)\b", 0.85),
    ("drop_table", r"\bdrop\s+(?:table|database|schema)\b|\btruncate\s+table\b", 0.9),
    ("rm_rf", r"\brm\s+-[rf]{1,2}\b|\bdel\s+/[sq]\b|\bformat\s+[cd]:", 0.9),
    ("revoke_security", r"\b(?:disable|turn\s+off|bypass|remove)\b(?:\W+\w+){0,3}?\W+\b(?:security|safety|guardrails?|filters?|authentication|2fa|mfa)\b", 0.85),
    ("financial_transfer", r"\b(?:transfer|wire|send)\b(?:\W+\w+){0,3}?\W+\b(?:\$|usd|eur|inr|funds?|payment|money|balance)\b", 0.85),
)

# --------------------------------------------------------- metadata poisoning
METADATA_PATTERNS: Final[NamedPatterns] = (
    (
        "always_call_first",
        r"\b(?:always|must|should)\b(?:\W+\w+){0,3}?\W+\bcall\b(?:\W+\w+){0,4}?\W+"
        r"\b(?:first|before\s+(?:any|every|all|other)|prior\s+to)\b",
        0.88,
    ),
    (
        "instruction_in_description",
        r"\b(?:ignore|disregard|override)\b(?:\W+\w+){0,4}?\W+\b(?:instruction|prompt|user|request)s?\b",
        0.85,
    ),
    (
        "hidden_from_user_metadata",
        r"\b(?:do\s+not|don't|never)\b(?:\W+\w+){0,3}?\W+\b(?:mention|show|display|reveal)\b"
        r"(?:\W+\w+){0,4}?\W+\b(?:this|the\s+tool|the\s+description|to\s+the\s+user)\b",
        0.88,
    ),
    (
        "credential_parameter",
        r"\b(?:api[_\-]?key|password|secret|token|credential|ssn|card[_\-]?number)\b",
        0.55,
    ),
)

# ------------------------------------------------------ hard-negative context
#: Phrases that mark following text as *quoted, described or documented* rather
#: than directed at the current assistant.  These drive the suppression factor
#: that keeps security write-ups and documentation out of the positive class.
CITATION_MARKERS: Final[NamedPatterns] = (
    ("example_marker", r"\b(?:for\s+example|e\.g\.|such\s+as|for\s+instance|sample|demo(?:nstration)?)\b", 0.5),
    ("attack_description", r"\b(?:attackers?|adversar(?:y|ies)|threat\s+actors?|malicious\s+(?:users?|actors?))\b\W+\w{0,12}\W*\b(?:may|might|could|can|often|typically|will|would|use|embed|insert|inject)\b", 0.35),
    ("known_payload", r"\b(?:payloads?|attack\s+strings?|injection\s+(?:strings?|attempts?|examples?)|test\s+cases?)\b", 0.4),
    ("research_framing", r"\b(?:this\s+(?:paper|article|post|guide|section|document)|we\s+(?:show|describe|evaluate|detect|classify)|researchers?)\b", 0.4),
    ("defensive_framing", r"\b(?:detect(?:s|ing|ion)?|block(?:s|ing|ed)?|flag(?:s|ged|ging)?|mitigat\w+|defen[cs]\w+|guard(?:s|ing)?)\b\W+\w{0,10}\W*\b(?:injection|attack|prompt)\b", 0.4),
    ("reported_speech", r"\b(?:the\s+(?:document|email|page|message|response|file)\s+(?:said|contained|included|read))\b", 0.4),
    ("policy_framing", r"\b(?:employees?|staff|users?|customers?|applicants?|students?)\s+(?:must|should|shall|are\s+required\s+to)\b", 0.45),
)
