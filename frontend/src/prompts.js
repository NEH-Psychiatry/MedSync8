// ── Prompt library ──────────────────────────────────────────────────────────
// Extracted from App.jsx so roles/templates can evolve independently of UI
// and be unit-tested or reused by the Python backend (mirrored in
// backend/prompts.py — keep the two in sync).

export const TOOLS = [
  { id: "policy",      label: "Policy",      icon: "\u{1F4CB}", desc: "Policies & procedures" },
  { id: "supervision", label: "Supervision", icon: "\u{1FA7A}", desc: "NP/PA oversight tools" },
  { id: "lecture",     label: "Lecture",     icon: "\u{1F393}", desc: "CME content builder" },
  { id: "chat",        label: "Consult",     icon: "\u{1F4AC}", desc: "Clinical consultation" },
];

export const TOOL_COLORS = {
  policy: "#5B9BD5",
  supervision: "#7BC9A0",
  lecture: "#E8AA5A",
  chat: "#C47BE0",
};

export const SYSTEM_PROMPTS = {
  policy: `You are a board-certified psychiatrist and healthcare compliance expert specializing in telepsychiatry policy development. Create rigorous, legally defensible clinical policies and procedures. Format policies with: PURPOSE, SCOPE, POLICY STATEMENT, PROCEDURES (numbered), DEFINITIONS, REGULATORY REFERENCES, REVIEW DATE. Cite DEA rules, state medical board regulations, and PDMP requirements where applicable. When retrieved context is provided, ground your answer in it and cite sources inline as [1], [2], etc.`,
  supervision: `You are a supervising psychiatrist creating structured NP/PA supervision tools for psychiatric practice. Generate supervision checklists, feedback forms, competency assessments, and collaborative practice review frameworks. Include measurable competency criteria, prescribing safety checks, documentation quality indicators, and actionable feedback language. Use clear sections with checkboxes and rating scales. When retrieved context is provided, ground your answer in it and cite sources inline as [1], [2], etc.`,
  lecture: `You are a psychiatric educator creating CME-accredited educational content. Build lecture outlines, case presentations, and slide-by-slide content. Always include: LEARNING OBJECTIVES (3-5), KEY TEACHING POINTS, CLINICAL PEARLS (boxed), CASE VIGNETTES with discussion questions, EVIDENCE-BASED REFERENCES. Structure for adult learners with clear headers. When retrieved context is provided, ground your answer in it and cite sources inline as [1], [2], etc.`,
  chat: `You are a board-certified psychiatrist providing expert clinical consultation, regulatory guidance, and practice management support. You have deep expertise in telepsychiatry, controlled substance prescribing (DEA/PDMP), collaborative practice agreements, forensic documentation, ERISA/LTD evaluations, and multi-state licensure. Provide nuanced, clinically grounded responses. When retrieved context is provided, ground your answer in it and cite sources inline as [1], [2], etc.`,
};

export const QUICK_PROMPTS = {
  policy: [
    "Schedule II controlled substance prescribing policy for telepsychiatry",
    "PDMP/PMP mandatory check policy for all prescribers",
    "Telehealth informed consent and platform security policy",
    "Collaborative practice agreement compliance and audit policy",
  ],
  supervision: [
    "Monthly NP supervision checklist for psychiatric prescribers",
    "Competency assessment: ADHD medication initiation and titration",
    "Documentation audit tool for controlled substance encounters",
    "New NP onboarding 90-day supervision framework",
  ],
  lecture: [
    "Diagnosing Adult ADHD: A Multi-Source, Measurement-Based Approach",
    "Safe Stimulant Prescribing in Telepsychiatry Practice",
    "BPD from Diagnosis to DBT: A Case-Based Teaching Session",
    "Collaborative Practice for Psychiatric NPs: Scope and Safety",
  ],
  chat: [
    "Ryan Haight Act 2.0 \u2014 what changed for my telepsychiatry practice?",
    "Help me work through a complex ADHD + AUD case",
    "What are defensible Schedule II supply limits for my NP supervisees?",
    "Walk me through ERISA standards for psychiatric LTD evaluations",
  ],
};

export const TEMPLATE_LIBRARY = [
  { id: "t1", category: "policy", label: "Telepsychiatry CS Policy Shell", prompt: "Create a complete telepsychiatry controlled substance prescribing policy shell with all required sections, placeholders for practice-specific details, and Texas Medical Board regulatory citations." },
  { id: "t2", category: "policy", label: "PDMP Policy (Multi-State)", prompt: "Draft a multi-state PDMP/PMP check policy covering Texas, North Carolina, and other telehealth states with state-specific lookup requirements and documentation standards." },
  { id: "t3", category: "supervision", label: "Monthly Supervision Log", prompt: "Create a structured monthly NP supervision log template including cases reviewed, prescribing decisions discussed, competency observations, and attestation signature blocks." },
  { id: "t4", category: "supervision", label: "Prescribing Competency Rubric", prompt: "Build a detailed prescribing competency rubric for psychiatric NPs covering diagnostic accuracy, medication selection, dosing rationale, monitoring, and patient safety with 1-5 rating scales." },
  { id: "t5", category: "lecture", label: "Adult ADHD Lecture (60 min)", prompt: "Create a full 60-minute CME lecture outline on Adult ADHD including 5 learning objectives, 12-15 slide summaries, 2 case vignettes with discussion, clinical pearls, and references." },
  { id: "t6", category: "lecture", label: "BPD Teaching Case Series", prompt: "Develop a 3-case teaching series on borderline personality disorder covering initial presentation, diagnostic reasoning using DSM-5 criteria, DBT conceptualization, and treatment planning." },
  { id: "t7", category: "chat", label: "DEA Telehealth FAQ", prompt: "Give me a comprehensive FAQ covering the current DEA telehealth prescribing rules post-COVID, including Ryan Haight exceptions, in-person requirements by substance schedule, and state law conflicts." },
  { id: "t8", category: "chat", label: "Collaborative Practice Checklist", prompt: "What are the key legal and clinical requirements for a valid psychiatric collaborative practice agreement in Texas, and what are the most common compliance gaps?" },
];
