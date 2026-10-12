"""The plan builder's tools (sub-plan 13.5): the plan is built step by step, each checked when
it's added, in the order the builder chooses, to a time budget at his pace.

Same pattern as the memory agent (memory_tools.py): every tool validates its arguments and
applies them to an in-request PlanDraft; nothing is saved until the whole plan is done. Each
step type's tool is generated from its class (app/steps.py): the parameters from its content
fields, the description from its GUIDE.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from app.agent.runner import Tool
from app.schemas import ClassPlan, GameHomework, GamesAppFeedback, GoalType, PrimaryGoal
from app.steps import (ActivityStep, GamesActivityStep, NamesGameStep, OpeningStep, PracticeStep, ThreadStep,
                       tool_parameters)

BUDGET_MINUTES = 9.0  # the wrap-up note comes at ~9 minutes
MIN_ACCEPT = 0.7  # an unfinished draft (round limit) is still used if it reaches this share of the budget


def _norm(text: str) -> str:
    return " ".join((text or "").split())


@dataclass
class PlanDraft:
    # Minutes per step kind, measured from his real sessions (step_minutes in next_class.py); a kind
    # without data uses the class's default. A guessed pace factor got it backwards (12.10): a "slow"
    # talker with long answers finished each step SOONER.
    measured: dict[str, float] = field(default_factory=dict)
    goal: PrimaryGoal | None = None
    steps: list = field(default_factory=list)
    homework: str = ""
    fatigue_fallback: str = ""
    avoid: list[str] = field(default_factory=list)
    games_note: str = ""
    game_homework: list[GameHomework] = field(default_factory=list)
    games_feedback: list[GamesAppFeedback] = field(default_factory=list)
    notes_applied: str = ""
    finished: bool = False

    def step_minutes(self, step) -> float:
        return self.measured.get(step.kind, step.MINUTES)

    def minutes(self) -> float:
        return round(sum(self.step_minutes(s) for s in self.steps), 1)

    def progress(self) -> dict:
        return {"ok": True, "plan_minutes": self.minutes(), "budget_minutes": BUDGET_MINUTES,
                "steps_so_far": [f"{s.kind}{f' ({s.label()})' if s.label() else ''}" for s in self.steps]}

    def usable(self) -> str | None:
        """Why the draft can't be a plan (None = it can)."""
        if self.goal is None:
            return "no goal yet: call set_goal"
        if len([s for s in self.steps if not isinstance(s, OpeningStep)]) < 2:
            return "too few steps: add at least two steps after the opening"
        return None

    def to_plan(self) -> ClassPlan:
        problem = self.usable()
        if problem:
            raise ValueError(f"unusable plan: {problem}")
        steps = list(self.steps)
        if not isinstance(steps[0], OpeningStep):
            steps = [OpeningStep(), *steps]
        return ClassPlan(plan_type="regular", primary_goal=self.goal, steps=steps, homework=self.homework,
                         fatigue_fallback=self.fatigue_fallback, avoid=self.avoid, games_note=self.games_note,
                         game_homework=self.game_homework, notes_applied=self.notes_applied,
                         estimated_minutes=self.minutes())


def build_plan_tools(draft: PlanDraft, *, check_practice: Callable[[PracticeStep], str | None],
                     his_games: set[str], set_names: set[str]) -> list[Tool]:
    """`check_practice` returns why a practice step is rejected (None = fine): his data (8.5),
    untreated names-game names (12). `his_games`: the game ids he has (06)."""

    def all_names() -> set[str]:
        return {_norm(n) for s in draft.steps for n in s.names()}

    def set_goal(args: dict) -> dict:
        kind = args.get("type")
        if kind not in {g.value for g in GoalType} - {"intro"}:
            raise ValueError(f"type must be one of {sorted({g.value for g in GoalType} - {'intro'})}")
        draft.goal = PrimaryGoal(type=kind, description=str(args.get("description", ""))[:600])
        return draft.progress()

    def set_opening(args: dict) -> dict:
        draft.steps = [s for s in draft.steps if not isinstance(s, OpeningStep)]
        draft.steps.insert(0, OpeningStep(**{k: str(v)[:400] for k, v in args.items() if k in ("recall", "opener")}))
        return draft.progress()

    def place_names_game(args: dict) -> dict:
        if not set_names:
            raise ValueError("there is no names-game set yet: skip the names game today")
        if any(isinstance(s, NamesGameStep) for s in draft.steps):
            raise ValueError("the names game is already placed (once per session)")
        draft.steps.append(NamesGameStep())
        return draft.progress()

    def add_practice(args: dict) -> dict:
        step = PracticeStep(**args)
        if _norm(step.name) in all_names():
            raise ValueError(f"rejected: {step.name} is already in the plan -- choose another name")
        problem = check_practice(step)
        if problem:
            raise ValueError(problem)
        draft.steps.append(step)
        return draft.progress()

    def add_activity(args: dict) -> dict:
        draft.steps.append(ActivityStep(**args))
        return draft.progress()

    def add_games_activity(args: dict) -> dict:
        if not his_games:
            raise ValueError("no games app data: skip the game-linked activity")
        draft.steps.append(GamesActivityStep(**args))
        return draft.progress()

    def add_thread(args: dict) -> dict:
        draft.steps.append(ThreadStep(**args))
        return draft.progress()

    def set_closing(args: dict) -> dict:
        draft.homework = str(args.get("homework", ""))[:400]
        draft.fatigue_fallback = str(args.get("fatigue_fallback", ""))[:400]
        draft.avoid = [str(a)[:150] for a in (args.get("avoid") or [])][:8]
        draft.games_note = str(args.get("games_note", ""))[:300]
        return draft.progress()

    def add_game_homework(args: dict) -> dict:
        game_id = args.get("game_id")
        if game_id not in his_games:
            raise ValueError(f"unknown game id {game_id!r}: only ids listed in GAMES")
        if len(draft.game_homework) >= 2:
            raise ValueError("at most 2 game homework items")
        draft.game_homework.append(GameHomework(game_id=game_id, why=str(args.get("why", ""))[:200]))
        return draft.progress()

    def suggest_games_app_change(args: dict) -> dict:
        if args.get("game_id") not in his_games:
            raise ValueError("only for games listed in GAMES")
        if len(draft.games_feedback) >= 2:
            raise ValueError("at most 2 suggestions")
        draft.games_feedback.append(GamesAppFeedback(**args))
        return {"ok": True}

    def finish(args: dict) -> dict:
        problem = draft.usable()
        if problem:
            raise ValueError(problem)
        if draft.minutes() < BUDGET_MINUTES:
            raise ValueError(f"the plan is ~{draft.minutes()} of {BUDGET_MINUTES} minutes at his pace: add more "
                             f"steps (practice in a topic, a thread, an activity) before finishing")
        draft.notes_applied = str(args.get("notes_applied", ""))[:300]
        draft.finished = True
        return {"ok": True, "plan_minutes": draft.minutes(), "done": True}

    def step_tool(cls, handler) -> Tool:
        return Tool(cls.TOOL, cls.GUIDE, tool_parameters(cls), handler)

    str_list = {"type": "array", "items": {"type": "string"}}
    tools = [
        Tool("set_goal", "Set the session's ONE primary goal type (see the rotation rule) and why, in English.",
             {"type": "object", "properties": {
                 "type": {"type": "string", "enum": sorted({g.value for g in GoalType} - {"intro"})},
                 "description": {"type": "string", "description": "ENGLISH: what this session works on, and why."}},
              "required": ["type", "description"]}, set_goal),
        step_tool(OpeningStep, set_opening),
        Tool(NamesGameStep.TOOL, NamesGameStep.GUIDE, {"type": "object", "properties": {}}, place_names_game),
        step_tool(PracticeStep, add_practice),
        step_tool(ActivityStep, add_activity),
        step_tool(ThreadStep, add_thread),
        Tool("set_closing", "The session-level parts: homework for next time (she gives it in the closing), an easy "
             "fatigue fallback, what to avoid, and one fact about his recent games she may mention. ENGLISH.",
             {"type": "object", "properties": {
                 "homework": {"type": "string"}, "fatigue_fallback": {"type": "string"}, "avoid": str_list,
                 "games_note": {"type": "string"}}, "required": ["homework", "fatigue_fallback"]}, set_closing),
        Tool("finish", "Call LAST, when the plan fills the time budget. notes_applied: ENGLISH, one sentence on how "
             "the plan applies the NOTES FROM THE FAMILY / THERAPIST (empty if none).",
             {"type": "object", "properties": {"notes_applied": {"type": "string"}}}, finish),
    ]
    if his_games:
        tools += [
            step_tool(GamesActivityStep, add_games_activity),
            Tool("add_game_homework", "0-2 games from GAMES that fit TODAY'S goal, each with a one-line why (English).",
                 {"type": "object", "properties": {"game_id": {"type": "string", "enum": sorted(his_games)},
                                                   "why": {"type": "string"}}, "required": ["game_id", "why"]},
                 add_game_homework),
            Tool("suggest_games_app_change", "0-2 suggestions for improving the games app, ONLY when the GAMES data "
                 "shows a reason, each with evidence from the data (never from the conversation alone).",
                 {"type": "object", "properties": {
                     "game_id": {"type": "string", "enum": sorted(his_games)},
                     "kind": {"type": "string", "enum": ["tune_difficulty", "bug", "ux", "new_game", "platform"]},
                     "title": {"type": "string"}, "rationale": {"type": "string"}, "evidence": {"type": "string"}},
                  "required": ["game_id", "kind", "title", "rationale", "evidence"]}, suggest_games_app_change),
        ]
    return tools
