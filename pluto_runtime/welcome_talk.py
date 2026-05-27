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
        }

    def _match(self, normalized: str, words: list[str]) -> tuple[str | None, str, float, str]:
        input_tokens = set(words)
        best: tuple[str | None, str, float, str] = (None, self.config.unknown_response, 0.0, "fallback")

        for rule in INTENT_RULES:
            for trigger in rule.triggers:
                trigger_norm = normalize_text(trigger)
                trigger_tokens = set(trigger_norm.split())
                if not trigger_tokens:
                    continue
                if len(trigger_tokens) == 1:
                    if next(iter(trigger_tokens)) in input_tokens:
                        return rule.intent, rule.response, 1.0, "keyword"
                    continue

                if trigger_norm in normalized or trigger_tokens.issubset(input_tokens):
                    return rule.intent, rule.response, 1.0, "keyword"

                ratio = SequenceMatcher(None, normalized, trigger_norm).ratio()
                overlap = len(input_tokens & trigger_tokens) / max(len(trigger_tokens), 1)
                score = max(ratio, overlap * 0.85)
                if score > best[2]:
                    best = (rule.intent, rule.response, score, "fuzzy")

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


def count_words(text: str) -> int:
    normalized = normalize_text(text)
    return len(normalized.split()) if normalized else 0


def enforce_word_limit(text: str, max_words: int) -> str:
    words = WORD_RE.findall(text)
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()
