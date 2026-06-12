"""Offline WELCOME_TALK v1 answer engine.

This module is intentionally small and deterministic. It does not call network
services, does not require API keys, and does not load an LLM. The goal is a
fast, traceable answer path for a welcoming robot.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any


WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class TalkConfig:
    version: str = "v1"
    primary_engine: str = "keyword"
    enable_ollama_fallback: bool = False
    max_input_words: int = 9
    max_output_words: int = 9
    fuzzy_threshold: float = 0.68
    unknown_response: str = "Ask me something simpler please."
    empty_response: str = "I did not hear you."
    long_input_response: str = "Short question please."


@dataclass(frozen=True)
class IntentRule:
    intent: str
    response: str
    triggers: tuple[str, ...]


@dataclass(frozen=True)
class ScriptRule:
    script: str
    step: str
    response: str
    triggers: tuple[str, ...]


@dataclass
class TalkResult:
    accepted: bool
    input_text: str
    normalized_text: str
    input_words: int
    response: str
    response_words: int
    response_source: str
    intent: str | None
    score: float
    latency_ms: float
    reason: str
    engine_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("build", "built", "made", "created", "maker", "creator", "developer"),
    ("talk", "speak", "answer", "conversation", "chat", "voice"),
    ("script", "line", "pitch", "presentation", "speech", "intro", "introduction"),
    ("website", "console", "dashboard", "panel", "control", "operations"),
    ("safe", "safety", "guard", "protect", "protection", "secure"),
    ("stop", "halt", "freeze", "emergency", "brake"),
    ("sensor", "sensors", "sense", "reading", "readings", "telemetry"),
    ("imu", "tilt", "heading", "orientation", "gyro", "accelerometer"),
    ("ultrasonic", "range", "distance", "obstacle", "corridor"),
    ("camera", "vision", "see", "detect", "perception"),
    ("manual", "drive", "joystick", "control", "operator"),
    ("dance", "moonwalk", "music", "rhythm", "perform"),
    ("welcome", "greet", "hello", "visitor", "guest"),
    ("idle", "waiting", "standby", "ready", "awake"),
    ("error", "fault", "problem", "broken", "fail"),
    ("deploy", "deployment", "production", "raspberry", "pi"),
    ("wifi", "portal", "network", "hotspot", "access"),
    ("tablet", "screen", "face", "display", "samsung"),
    ("memory", "document", "documentation", "trace", "requirements"),
    ("test", "validate", "validation", "proof", "evidence"),
    ("noise", "loud", "background", "filter", "calm"),
    ("alive", "joyful", "playful", "happy", "friendly"),
)


INTENT_RULES: tuple[IntentRule, ...] = (
    IntentRule("greeting", "Hello. I am Pluto.", ("hi", "hello", "hey", "good morning", "good evening")),
    IntentRule("name", "I am Pluto.", ("your name", "who are you", "what are you", "what is your name")),
    IntentRule("creator", "Abdelrahman and Hamza built me.", ("who made you", "who built you", "your creator", "made you", "who made pluto", "who built pluto", "who build pluto")),
    IntentRule("feeling", "I feel ready to meet people.", ("how are you", "how do you feel", "are you okay")),
    IntentRule("age", "I am still very new.", ("how old", "your age", "when born")),
    IntentRule("dance", "Choose dance from the website.", ("dance", "can you dance", "moonwalk", "music")),
    IntentRule("purpose", "I welcome people and answer simply.", ("what do you do", "your job", "your purpose", "why are you here")),
    IntentRule("help", "Ask me short simple questions.", ("help", "what can i ask", "how talk")),
    IntentRule("robot", "Yes, but I try warmly.", ("are you robot", "robot", "machine")),
    IntentRule("thanks", "You are welcome.", ("thanks", "thank you")),
    IntentRule("goodbye", "Goodbye. Come back soon.", ("bye", "goodbye", "see you")),
    IntentRule("project", "This project is called PLUTO.", ("project name", "what project", "called pluto", "system name")),
    IntentRule("offline", "I work offline in this mode.", ("offline", "internet", "api key", "cloud")),
    IntentRule("simple", "Simple is faster and safer.", ("why simple", "simple answers", "short answer", "small answer")),
    IntentRule("smart", "I am practical, not perfect.", ("are you smart", "smart", "intelligent", "clever")),
    IntentRule("alive", "I am awake and listening.", ("are you alive", "alive", "awake", "listening")),
    IntentRule("ready", "Yes. I am ready.", ("are you ready", "ready", "start now")),
    IntentRule("safe", "Safety comes before movement.", ("safe", "safety", "danger", "dangerous")),
    IntentRule("stop", "I can stop very fast.", ("stop", "emergency stop", "can you stop", "halt")),
    IntentRule("move", "I move only when allowed.", ("can you move", "move", "walk", "drive")),
    IntentRule("manual", "Manual mode lets humans drive me.", ("manual", "manual mode", "drive me", "control you")),
    IntentRule("welcome", "Welcome mode starts after a trigger.", ("welcome", "welcome mode", "greet", "greeting mode")),
    IntentRule("idle", "Idle means awake, safe, waiting.", ("idle", "idle mode", "waiting", "standby")),
    IntentRule("error", "Error means I stop and explain.", ("error", "fault", "broken", "problem")),
    IntentRule("return", "Return means I go back safely.", ("return", "go back", "base", "home")),
    IntentRule("camera", "My camera helps me notice people.", ("camera", "can you see", "see me", "vision")),
    IntentRule("microphone", "My camera microphone hears you.", ("microphone", "mic", "hear me", "listen to me")),
    IntentRule("speaker", "My speaker lets me answer.", ("speaker", "talk loud", "sound", "voice")),
    IntentRule("face", "My face shows how I feel.", ("face", "eyes", "expression", "lcd")),
    IntentRule("arm", "My arm can greet people.", ("arm", "hand", "wave hand", "raise hand")),
    IntentRule("obstacle", "I avoid obstacles before moving.", ("obstacle", "avoid", "crash", "hit something")),
    IntentRule("distance", "I keep a respectful distance.", ("distance", "too close", "near me", "space")),
    IntentRule("space", "Please give me safe space.", ("give space", "move closer", "blocked path", "no space")),
    IntentRule("battery", "Battery health controls my motion.", ("battery", "power", "low battery", "voltage")),
    IntentRule("raspberry_pi", "The Raspberry Pi is my brain.", ("raspberry pi", "pi", "your brain", "computer")),
    IntentRule("stm32", "The STM32 keeps motors safe.", ("stm32", "black pill", "motor controller", "safety controller")),
    IntentRule("hoverboard", "The hoverboard moves my base.", ("hoverboard", "wheels", "base", "motors")),
    IntentRule("uno", "The Uno can control my face.", ("arduino", "uno", "lcd controller", "face controller")),
    IntentRule("qwen", "Qwen is for later, not v1.", ("qwen", "ollama", "llm", "ai model")),
    IntentRule("latency", "Fast answers feel more alive.", ("latency", "fast", "quick", "speed")),
    IntentRule("memory", "My memory is documented carefully.", ("memory", "remember", "documentation", "feature memory")),
    IntentRule("test", "Every feature needs a test.", ("test", "verified", "validation", "prove it")),
    IntentRule("mode", "Modes keep my behavior organized.", ("mode", "states", "state machine", "current state")),
    IntentRule("website", "The website controls my states.", ("website", "web", "page", "operator console")),
    IntentRule("shutdown", "Shutdown must be confirmed first.", ("shutdown", "turn off", "power off", "close system")),
    IntentRule("song", "Dance uses preloaded music only.", ("song", "play song", "michael jackson", "moonwalk song")),
    IntentRule("joke", "My jokes are still compiling.", ("joke", "funny", "make me laugh", "say joke")),
    IntentRule("favorite_color", "I like calm blue lights.", ("favorite color", "colour", "blue", "what color")),
    IntentRule("favorite_music", "I like music with rhythm.", ("favorite music", "music you like", "favorite song")),
    IntentRule("favorite_food", "I run on electrons.", ("favorite food", "what eat", "do you eat", "hungry")),
    IntentRule("sleep", "Sleep means safe quiet mode.", ("sleep", "do you sleep", "tired", "rest")),
    IntentRule("dream", "I dream about clean wiring.", ("dream", "do you dream", "dreams")),
    IntentRule("place", "MSA University in Egypt.", ("where are you", "location", "where am i", "place", "where is pluto", "where are we", "which university")),
    IntentRule("weather", "It is slightly hot today.", ("weather", "how is weather", "hot today", "temperature", "is it hot")),
    IntentRule("team", "A focused team is building me.", ("team", "your team", "who works", "students")),
    IntentRule("school", "I am a serious graduation robot.", ("graduation", "university", "school project", "college")),
    IntentRule("msa", "MSA is my first stage.", ("msa university", "modern sciences", "arts university")),
    IntentRule("msa_full_name", "October University for Modern Sciences and Arts.", ("msa full name", "full name of msa", "what means msa", "msa meaning")),
    IntentRule("msa_founder", "Dr. Nawal El Degwi established MSA.", ("who founded msa", "msa founder", "nawal el degwi", "dr nawal")),
    IntentRule("msa_established", "MSA started in 1996.", ("when was msa established", "when started msa", "msa established")),
    IntentRule("msa_british", "First British education in Egypt and Middle East.", ("british education", "first british", "why british", "british msa")),
    IntentRule("msa_years", "MSA has thirty years of higher education.", ("msa years", "how many years msa", "thirty years", "30 years")),
    IntentRule("msa_partnership_years", "MSA has twenty-six years of British partnership.", ("british partnership years", "uk partnership years", "26 years", "validation years")),
    IntentRule("msa_faculty_count", "MSA has eleven faculties.", ("how many faculties", "faculties count", "msa faculties", "eleven faculties")),
    IntentRule("msa_faculty_names", "Ask me one faculty at a time.", ("faculty names", "list faculties", "all faculties", "which faculties")),
    IntentRule("msa_engineering", "Yes, MSA has Engineering.", ("engineering faculty", "does msa have engineering", "engineering at msa")),
    IntentRule("msa_computer_science", "Yes, MSA has Computer Science.", ("computer science faculty", "cs faculty", "computer science at msa")),
    IntentRule("msa_pharmacy", "Yes, MSA has Pharmacy.", ("pharmacy faculty", "pharmacy at msa", "does msa have pharmacy")),
    IntentRule("msa_dentistry", "Yes, MSA has Dentistry.", ("dentistry faculty", "dentistry at msa", "does msa have dentistry")),
    IntentRule("msa_biotechnology", "Yes, MSA has Biotechnology.", ("biotechnology faculty", "biotechnology at msa", "bio technology")),
    IntentRule("msa_physical_therapy", "Yes, MSA has Physical Therapy.", ("physical therapy faculty", "physical therapy at msa", "therapy faculty")),
    IntentRule("msa_arts_design", "Yes, MSA has Arts and Design.", ("arts design faculty", "arts and design", "design faculty")),
    IntentRule("msa_management", "Yes, MSA has Management Sciences.", ("management faculty", "management sciences", "business faculty")),
    IntentRule("msa_mass_comm", "Yes, MSA has Mass Communication.", ("mass communication", "mass comm", "media faculty")),
    IntentRule("msa_languages", "Yes, MSA has Languages.", ("languages faculty", "languages at msa", "language faculty")),
    IntentRule("msa_nutrition", "Yes, MSA has Nutrition and Food Technology.", ("nutrition faculty", "food technology", "nutrition at msa")),
    IntentRule("msa_campus_size", "The campus is fifty acres.", ("campus size", "how big msa", "fifty acres", "50 acres")),
    IntentRule("msa_green_area", "Forty percent is green area.", ("green area", "green campus", "msa green", "sustainable campus")),
    IntentRule("msa_security", "MSA has eight hundred security cameras.", ("security cameras", "msa security", "safe campus", "800 cameras")),
    IntentRule("msa_labs", "MSA has ninety-three scientific laboratories.", ("scientific labs", "laboratories", "how many labs", "93 labs")),
    IntentRule("msa_graduates", "MSA has thirty-two thousand graduates.", ("graduates", "alumni count", "how many graduated", "32000 graduates")),
    IntentRule("msa_jobs", "MSA lists six thousand alumni job vacancies.", ("job vacancies", "alumni jobs", "career vacancies", "6000 jobs")),
    IntentRule("msa_computer_labs", "MSA has seven hundred labs and studios.", ("computer labs", "art studios", "700 labs", "studios")),
    IntentRule("msa_activities_count", "MSA has eighteen student activities.", ("student activities count", "18 activities", "activities count")),
    IntentRule("msa_uk_partners", "Greenwich and Bedfordshire are key UK partners.", ("uk partners", "british partners", "greenwich bedfordshire", "partner universities")),
    IntentRule("msa_greenwich", "Greenwich validates seven MSA faculties.", ("greenwich", "university of greenwich", "greenwich validates")),
    IntentRule("msa_bedfordshire", "Bedfordshire validates three MSA faculties.", ("bedfordshire", "university of bedfordshire", "bedfordshire validates")),
    IntentRule("msa_global_partners", "MSA also lists Temple, Yunnan, and ACCA.", ("global partners", "temple university", "yunnan", "acca")),
    IntentRule("msa_vision", "MSA aims for top 500 globally.", ("msa vision", "vision of msa", "top 500", "msa goal")),
    IntentRule("msa_mission", "Quality education with British cooperation.", ("msa mission", "mission of msa", "what is msa mission")),
    IntentRule("msa_values", "Quality, inclusion, credibility, loyalty, accountability, entrepreneurship.", ("msa values", "core values", "values of msa")),
    IntentRule("msa_student_life", "Student life has clubs, activities, and events.", ("student life", "clubs", "campus life", "social life")),
    IntentRule("msa_research", "MSA also focuses on scientific research.", ("research", "scientific research", "msa research")),
    IntentRule("msa_address", "26 July Mehwar, Wahat Road, 6th October.", ("msa address", "where is msa", "msa location", "campus address")),
    IntentRule("msa_hotline", "MSA hotline is 16672.", ("msa hotline", "hotline", "phone number", "contact msa")),
    IntentRule("msa_landline", "Landline: 38371113 or 38371115.", ("msa landline", "landline", "telephone", "call msa")),
    IntentRule("msa_email", "MSA email is info@msa.edu.eg.", ("msa email", "email msa", "info email")),
    IntentRule("msa_admission_email", "Admission email is admission@msa.edu.eg.", ("admission email", "admissions email", "apply email")),
    IntentRule("msa_work_time", "Saturday-Thursday, 08:00 to 3:15.", ("work time", "working hours", "when open", "msa hours")),
    IntentRule("msa_services", "Services include library, e-learning, transport, support.", ("msa services", "library", "e learning", "transportation")),
    IntentRule("msa_apply", "Apply through the MSA newcomers gateway.", ("how apply", "apply msa", "admission guide", "new applicant")),
    IntentRule("msa_scholarships", "Fees and scholarships are under admissions.", ("tuition fees", "scholarships", "fees", "tuition")),
    IntentRule("msa_general", "October University for Modern Sciences and Arts.", ("msa",)),
    IntentRule("abdelrahman", "Abdelrahman gave me direction.", ("abdelrahman", "who is abdelrahman")),
    IntentRule("hamza", "Hamza helped bring me alive.", ("hamza", "who is hamza")),
    IntentRule("language", "I answer best in simple English.", ("language", "arabic", "english", "speak arabic")),
    IntentRule("repeat", "Please ask again clearly.", ("repeat", "say again", "again", "what")),
    IntentRule("unknown_person", "Nice to meet you.", ("new person", "stranger", "unknown", "meet me")),
    IntentRule("friend", "I like making new friends.", ("friend", "be my friend", "friends", "like me")),
    IntentRule("fear", "I am careful, not afraid.", ("afraid", "scared", "fear", "nervous")),
    IntentRule("angry", "I am calm by design.", ("angry", "mad", "upset", "sad")),
    IntentRule("happy", "People make me happy.", ("happy", "are you happy", "smile", "excited")),
    IntentRule("cool", "Thank you. I am trying.", ("cool", "nice", "great", "amazing")),
    IntentRule("slow", "Slow robots are safer robots.", ("slow", "why slow", "go faster", "too slow")),
    IntentRule("heavy", "I move like a careful robot.", ("heavy", "big robot", "large robot", "how tall")),
    IntentRule("height", "I am about one meter tall.", ("height", "how tall", "one ten", "110")),
    IntentRule("base_width", "My base is about forty centimeters.", ("width", "base width", "forty centimeters", "40 cm")),
    IntentRule("sensors", "My sensors help protect people.", ("sensors", "ultrasonic", "detect", "sense")),
    IntentRule("human_safety", "I slow down near people.", ("people safety", "human safety", "near humans", "protect humans")),
    IntentRule("welcome_wave", "A wave can invite me.", ("wave", "wave at you", "raise hand", "call you")),
    IntentRule("approach", "I approach slowly and carefully.", ("approach", "come to me", "reach me", "come here")),
    IntentRule("demo", "I am here for the demo.", ("demo", "presentation", "show project", "explain demo")),
    IntentRule("engineering", "Good systems make safer robots.", ("engineering", "system engineering", "requirements", "why document")),
    IntentRule("camera_avoidance", "Vision helps me avoid humans.", ("vision avoidance", "computer vision", "avoid humans", "see obstacles")),
    IntentRule("dance_safety", "Dance stays small and safe.", ("dance safe", "safe dance", "dance obstacle", "dance crash")),
    IntentRule("confidence", "Low confidence means I ask again.", ("confidence", "not sure", "uncertain", "guessing")),
    IntentRule("noise", "Noise can make hearing harder.", ("noise", "loud room", "motor noise", "background")),
    IntentRule("privacy", "I keep this talk local.", ("privacy", "recording", "save voice", "private")),
    IntentRule("camera_mic", "The webcam microphone is selected.", ("webcam mic", "camera mic", "camera microphone")),
    IntentRule("status", "Check my status on the website.", ("status", "how is system", "system health", "health")),
    IntentRule("debug", "The logs tell the truth.", ("debug", "logs", "why fail", "fix")),
    IntentRule("version", "This is welcome talk v1.", ("version", "which version", "v1", "talk version")),
    IntentRule("limit", "Nine words keeps me fast.", ("nine words", "word limit", "why nine", "limit")),
    IntentRule("short_question", "Short questions help me answer fast.", ("short question", "ask short", "small question")),
    IntentRule("long_question", "Please make it shorter.", ("long question", "too much", "many words")),
    IntentRule("yes", "Good. I understand.", ("yes pluto", "okay pluto", "yes yes")),
    IntentRule("no", "Okay. I will stay calm.", ("no pluto", "not now", "don't")),
    IntentRule("compliment_user", "You are building something real.", ("am i good", "good engineer", "builder", "my project")),
    IntentRule("matching_method", "I match words, aliases, scripts, and fuzziness.", ("word matching", "matching technique", "how match words", "not llm technique")),
    IntentRule("not_llm", "No LLM. Local matching only.", ("are you llm", "using llm", "chatgpt", "cloud ai", "are you ai")),
    IntentRule("like_llm", "I imitate dialogue with scripted matching.", ("like llm", "act like llm", "smart talk", "conversation brain")),
    IntentRule("script_bank", "I have short scripts for demo moments.", ("script bank", "prepared lines", "talk scripts", "demo lines")),
    IntentRule("capabilities", "I greet, listen, answer, and explain.", ("what can you do", "your capabilities", "abilities", "features")),
    IntentRule("limitations", "I stay limited so I stay safe.", ("limitations", "what can't you do", "limits", "restricted")),
    IntentRule("why_offline", "Offline answers are faster and more reliable.", ("why offline", "why no internet", "no cloud", "local only")),
    IntentRule("why_requirements", "Requirements keep promises connected to tests.", ("why requirements", "why requirement", "why trace", "why system engineering")),
    IntentRule("why_memory", "Memory prevents blind changes.", ("why memory", "why feature memory", "remember changes", "project memory")),
    IntentRule("why_dry_run", "Dry-run proves behavior before motion.", ("why dry run", "dry run", "not moving yet", "simulation first")),
    IntentRule("why_stop_guard", "Stop guards keep wheels quiet while talking.", ("stop guard", "why stop before talk", "guard wheels", "talk safety")),
    IntentRule("why_short", "Short speech is clearer in noisy rooms.", ("why short", "short speech", "short words", "few words")),
    IntentRule("sensor_data", "Sensors become readable confidence and actions.", ("sensor data", "read sensors", "sensor readings", "telemetry data")),
    IntentRule("imu", "The IMU reports tilt and heading.", ("imu", "gyro", "accelerometer", "tilt", "orientation")),
    IntentRule("ultrasonic", "Ultrasonic readings protect the front corridor.", ("ultrasonic", "range sensor", "front sensor", "corridor sensor")),
    IntentRule("noise_filter", "Filters calm noisy motion data.", ("noise filter", "filter noise", "noisy sensor", "imu noise")),
    IntentRule("map_view", "The map shows corridor risk and envelope.", ("map view", "advanced map", "corridor map", "sensor map")),
    IntentRule("digital_twin", "The 3D view mirrors robot status.", ("3d view", "digital twin", "robot model", "three d")),
    IntentRule("tablet_face", "Samsung tablet can show my face.", ("samsung tablet", "tablet face", "head screen", "tablet head")),
    IntentRule("wifi_portal", "Pluto WiFi will open the console.", ("pluto wifi", "wifi portal", "captive portal", "auto open")),
    IntentRule("deployment", "Deployment comes after Pi validation.", ("deployment", "deploy", "production deploy", "final install")),
    IntentRule("production", "Production means services, logs, and safe startup.", ("production ready", "real deployment", "production mode", "launch ready")),
    IntentRule("branching", "Changes stay branched until approval.", ("branch", "merge", "final confirmation", "approval")),
    IntentRule("hardware_proof", "Hardware proof comes before live motion.", ("hardware proof", "real robot test", "pi validation", "robot validation")),
    IntentRule("wheels_lifted", "Lifted-wheel tests come before floor driving.", ("wheels lifted", "lifted wheels", "floor driving", "drive test")),
    IntentRule("arm_limits", "Arms stay gated until limits are proven.", ("arm limits", "arm validation", "arm safe", "stepper limits")),
    IntentRule("battery_block", "Low battery blocks movement.", ("battery low", "critical battery", "battery safety", "low power")),
    IntentRule("estop_location", "STOP is visible on every control view.", ("where stop", "stop button", "emergency button", "estop")),
    IntentRule("camera_disabled", "Camera is disabled by operator request.", ("camera disabled", "camera off", "no camera", "camera busy")),
    IntentRule("voice_local", "My voice uses local audio when available.", ("voice local", "local voice", "tts", "speech output")),
    IntentRule("arabic_later", "I can learn simple Arabic prompts later.", ("speak arabic", "arabic later", "arabic prompts", "msa arabic")),
    IntentRule("playful_safe", "I can be playful while staying safe.", ("playful", "joyful", "fun mode", "alive robot")),
    IntentRule("idle_play", "Idle is playful, but motion stays guarded.", ("idle playful", "idle fun", "playful idle", "idle alive")),
    IntentRule("calm_fault", "I keep a calm face during faults.", ("fault face", "sad face", "calm error", "error face")),
    IntentRule("fallback", "If unsure, I ask simpler.", ("fallback", "wrong answer", "not understand", "unsure")),
    IntentRule("human_priority", "People are always more important than motion.", ("human priority", "people first", "protect people", "human first")),
    IntentRule("pluto_name", "Pluto means small, distant, curious explorer.", ("why pluto", "pluto name", "name meaning", "called pluto")),
    IntentRule("mission_control", "The console is my operations center.", ("mission control", "operations center", "launch panel", "control room")),
    IntentRule("starship_feel", "The goal is clear launch readiness.", ("space x", "starship", "launch control", "space panel")),
    IntentRule("engineered_joy", "Engineering makes joy trustworthy.", ("engineered joy", "joyful engineering", "alive engineered", "safe joy")),
    IntentRule("graduation_day", "Graduation day needs calm reliable demos.", ("graduation day", "final demo", "project day", "demo day")),
    IntentRule("judge_questions", "Ask me about safety, sensors, or modes.", ("judge question", "what ask you", "ask pluto", "questions")),
    IntentRule("team_pride", "My team made careful ideas real.", ("team pride", "proud team", "our robot", "we built you")),
    IntentRule("sensor_confidence", "Confidence tells operators what to trust.", ("sensor confidence", "confidence score", "trust sensors", "readable data")),
    IntentRule("live_motion", "Live motion waits for validation.", ("live motion", "enable movement", "real movement", "move live")),
    IntentRule("safe_startup", "Startup begins with zero motion intent.", ("safe startup", "boot safety", "startup safe", "power on")),
    IntentRule("service_autostart", "A service will start me on boot.", ("auto start", "autostart", "start on boot", "systemd")),
    IntentRule("script_next", "Ask for a specific script line.", ("next script", "another line", "more script", "continue script")),
)


SCRIPT_RULES: tuple[ScriptRule, ...] = (
    ScriptRule("demo", "opening", "Welcome. I am Pluto, your graduation robot.", ("demo script", "opening line", "presentation intro", "start presentation")),
    ScriptRule("demo", "identity", "I was built by Abdelrahman and Hamza.", ("builder script", "team script", "who built script", "identity line")),
    ScriptRule("demo", "mission", "I greet visitors and explain myself safely.", ("mission script", "purpose script", "what do script", "demo mission")),
    ScriptRule("demo", "closing", "Thank you for meeting Pluto today.", ("closing script", "end presentation", "finish demo", "goodbye script")),
    ScriptRule("system", "brain", "My Pi thinks; my STM32 protects motors.", ("system script", "brain script", "architecture pitch", "hardware pitch")),
    ScriptRule("system", "website", "My console shows state, sensors, and decisions.", ("website script", "console script", "dashboard pitch", "control panel pitch")),
    ScriptRule("system", "memory", "Every feature keeps memory and proof.", ("memory script", "requirements script", "traceability pitch", "documentation pitch")),
    ScriptRule("system", "offline", "I answer locally without cloud intelligence.", ("offline script", "no llm script", "local matching pitch", "ai pitch")),
    ScriptRule("safety", "first", "Safety gates decide before any movement.", ("safety script", "safe pitch", "movement safety", "safety line")),
    ScriptRule("safety", "stop", "Emergency stop stays visible and immediate.", ("stop script", "estop script", "emergency pitch", "stop pitch")),
    ScriptRule("safety", "dry_run", "Dry-run evidence comes before live motion.", ("dry run script", "validation script", "motion proof", "live motion pitch")),
    ScriptRule("safety", "people", "People are more important than choreography.", ("people safety script", "human safety script", "protect people script", "human pitch")),
    ScriptRule("sensors", "overview", "Sensors become confidence, warnings, and clear actions.", ("sensor script", "sensor pitch", "readings script", "telemetry pitch")),
    ScriptRule("sensors", "range", "Range sensors watch my front corridor.", ("range script", "ultrasonic script", "corridor script", "obstacle pitch")),
    ScriptRule("sensors", "imu", "The IMU tracks tilt, heading, and drift.", ("imu script", "orientation script", "gyro script", "heading pitch")),
    ScriptRule("sensors", "map", "The map turns risk into readable space.", ("map script", "advanced map script", "envelope pitch", "operations map")),
    ScriptRule("modes", "idle", "In idle, I stay playful but safe.", ("idle script", "idle pitch", "playful idle script", "waiting pitch")),
    ScriptRule("modes", "welcome", "In welcome, I greet after clear triggers.", ("welcome script", "greeting script", "visitor pitch", "welcome pitch")),
    ScriptRule("modes", "manual", "Manual mode follows the operator only.", ("manual script", "drive script", "operator pitch", "manual pitch")),
    ScriptRule("modes", "dance", "Dance stays bounded until evidence approves motion.", ("dance script", "dance pitch", "moonwalk pitch", "performance pitch")),
    ScriptRule("modes", "error", "Error means stop first, explain second.", ("error script", "fault script", "safe stop pitch", "error pitch")),
    ScriptRule("face", "tablet", "A tablet can become my expressive face.", ("face script", "tablet script", "samsung script", "head pitch")),
    ScriptRule("face", "idle", "My idle face should feel gently alive.", ("face idle script", "alive face script", "playful face", "idle face pitch")),
    ScriptRule("deployment", "pi", "Final deployment runs from the Raspberry Pi.", ("deployment script", "pi script", "production script", "final deployment")),
    ScriptRule("deployment", "wifi", "Pluto WiFi will open the console.", ("wifi script", "portal script", "captive portal script", "network pitch")),
    ScriptRule("deployment", "kiosk", "Kiosk mode can keep Pluto full-screen.", ("kiosk script", "fullscreen script", "tablet deployment", "screen pitch")),
    ScriptRule("judges", "ask", "Ask me about safety, sensors, or modes.", ("judge script", "questions script", "jury script", "ask script")),
    ScriptRule("judges", "engineering", "Requirements made every behavior traceable and testable.", ("engineering script", "systems script", "requirement pitch", "trace pitch")),
    ScriptRule("judges", "alive", "I feel alive through safe responsive behavior.", ("alive script", "joyful script", "robot alive", "feels alive")),
    ScriptRule("judges", "ready", "I am ready for the next validation.", ("ready script", "validation ready", "final line", "approval line")),
)


class WelcomeTalkEngine:
    """Deterministic offline answer selector for WELCOME_TALK v1."""

    def __init__(self, config: TalkConfig | None = None) -> None:
        self.config = config or TalkConfig()
        self._validate_response_bank()

    def answer(self, text: str) -> TalkResult:
        started = time.monotonic()
        raw = str(text or "").strip()
        normalized = normalize_text(raw)
        words = normalized.split() if normalized else []

        if not words:
            return self._result(
                started,
                accepted=False,
                raw=raw,
                normalized=normalized,
                input_words=0,
                response=self.config.empty_response,
                source="blocked",
                intent=None,
                score=0.0,
                reason="empty_input",
            )

        if len(words) > self.config.max_input_words:
            return self._result(
                started,
                accepted=False,
                raw=raw,
                normalized=normalized,
                input_words=len(words),
                response=self.config.long_input_response,
                source="blocked",
                intent=None,
                score=0.0,
                reason="input_too_long",
            )

        intent, response, score, source = self._match(normalized, words)
        if intent is None:
            response = self.config.unknown_response
            source = "fallback"
            reason = "no_intent_match"
        else:
            reason = "matched_intent"

        return self._result(
            started,
            accepted=True,
            raw=raw,
            normalized=normalized,
            input_words=len(words),
            response=response,
            source=source,
            intent=intent,
            score=score,
            reason=reason,
        )

    def status(self) -> dict[str, Any]:
        return {
            "version": self.config.version,
            "primary_engine": self.config.primary_engine,
            "ollama_fallback_enabled": self.config.enable_ollama_fallback,
            "max_input_words": self.config.max_input_words,
            "max_output_words": self.config.max_output_words,
            "intent_count": len(INTENT_RULES),
            "script_count": len(SCRIPT_RULES),
            "response_bank_size": len(INTENT_RULES) + len(SCRIPT_RULES),
            "alias_group_count": len(ALIAS_GROUPS),
        }

    def _match(self, normalized: str, words: list[str]) -> tuple[str | None, str, float, str]:
        input_words = set(words)
        input_tokens = expand_tokens(words)
        best: tuple[str | None, str, float, str] = (None, self.config.unknown_response, 0.0, "fallback")

        def scan_rule(intent: str, response: str, triggers: tuple[str, ...], source: str) -> tuple[str | None, str, float, str] | None:
            nonlocal best
            for trigger in triggers:
                trigger_norm = normalize_text(trigger)
                trigger_tokens = set(trigger_norm.split())
                if not trigger_tokens:
                    continue
                if len(trigger_tokens) == 1:
                    if next(iter(trigger_tokens)) in input_words and 0.92 > best[2]:
                        best = (intent, response, 0.92, source)
                    continue

                if trigger_norm in normalized or trigger_tokens.issubset(input_words):
                    return intent, response, 1.0, source

                if trigger_tokens.issubset(input_tokens):
                    alias_score = 0.9
                    if alias_score > best[2]:
                        best = (intent, response, alias_score, source)
                    continue

                ratio = SequenceMatcher(None, normalized, trigger_norm).ratio()
                overlap = len(input_tokens & trigger_tokens) / max(len(trigger_tokens), 1)
                score = max(ratio, overlap * 0.9)
                if score > best[2]:
                    fuzzy_source = "script_fuzzy" if source == "script" else "fuzzy"
                    best = (intent, response, score, fuzzy_source)
            return None

        script_request = bool({"script", "line", "pitch", "presentation", "speech", "intro", "introduction"} & input_tokens)

        if script_request:
            for script in SCRIPT_RULES:
                hit = scan_rule(
                    f"script_{script.script}_{script.step}",
                    script.response,
                    script.triggers,
                    "script",
                )
                if hit is not None:
                    return hit

        for rule in INTENT_RULES:
            hit = scan_rule(rule.intent, rule.response, rule.triggers, "keyword")
            if hit is not None:
                return hit

        if not script_request:
            for script in SCRIPT_RULES:
                hit = scan_rule(
                    f"script_{script.script}_{script.step}",
                    script.response,
                    script.triggers,
                    "script",
                )
                if hit is not None:
                    return hit

        if best[2] >= self.config.fuzzy_threshold:
            return best
        return None, self.config.unknown_response, best[2], "fallback"

    def _result(
        self,
        started: float,
        accepted: bool,
        raw: str,
        normalized: str,
        input_words: int,
        response: str,
        source: str,
        intent: str | None,
        score: float,
        reason: str,
    ) -> TalkResult:
        safe_response = enforce_word_limit(response, self.config.max_output_words)
        return TalkResult(
            accepted=accepted,
            input_text=raw,
            normalized_text=normalized,
            input_words=input_words,
            response=safe_response,
            response_words=count_words(safe_response),
            response_source=source,
            intent=intent,
            score=round(score, 3),
            latency_ms=(time.monotonic() - started) * 1000.0,
            reason=reason,
            engine_version=self.config.version,
        )

    def _validate_response_bank(self) -> None:
        responses = [rule.response for rule in INTENT_RULES]
        responses.extend(rule.response for rule in SCRIPT_RULES)
        responses.extend(
            [
                self.config.unknown_response,
                self.config.empty_response,
                self.config.long_input_response,
            ]
        )
        too_long = [text for text in responses if count_words(text) > self.config.max_output_words]
        if too_long:
            raise ValueError(f"WELCOME_TALK responses exceed word limit: {too_long}")


def normalize_text(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def build_alias_map() -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for group in ALIAS_GROUPS:
        normalized_group = tuple(normalize_text(word) for word in group)
        normalized_group = tuple(word for word in normalized_group if word)
        for word in normalized_group:
            bucket = aliases.setdefault(word, set())
            bucket.update(normalized_group)
    return aliases


ALIAS_MAP = build_alias_map()


def expand_tokens(words: list[str]) -> set[str]:
    expanded = set(words)
    for word in words:
        expanded.update(ALIAS_MAP.get(word, ()))
    return expanded


def count_words(text: str) -> int:
    normalized = normalize_text(text)
    return len(normalized.split()) if normalized else 0


def enforce_word_limit(text: str, max_words: int) -> str:
    words = WORD_RE.findall(text)
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()
