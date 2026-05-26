from dotenv import load_dotenv
load_dotenv()

import asyncio
import base64
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from agents import ImageGenerationTool, RunContextWrapper, Agent, ModelSettings, TResponseInputItem, Runner, RunConfig, trace
from pydantic import BaseModel, Field
from openai.types.shared.reasoning import Reasoning

# ── Style configuration ────────────────────────────────────────────────────────
# Change ACTIVE_STYLE to switch between styles in the styles/ folder.
ACTIVE_STYLE = "Educational Candlesticks"
STYLES_DIR = Path(__file__).parent / "styles"

def _load_style_file(filename: str, style: str = ACTIVE_STYLE) -> str:
    """Read a raw instruction template from the given style folder."""
    path = STYLES_DIR / style / filename
    return path.read_text(encoding="utf-8")


def list_styles() -> list[str]:
    """Return the names of all available styles (subfolders of styles/)."""
    if not STYLES_DIR.exists():
        return []
    return sorted(
        d.name for d in STYLES_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )

# Tool definitions
image_generation = ImageGenerationTool(tool_config={
  "type": "image_generation",
  "model": "gpt-image-1",
  "size": "1024x1024",
  "quality": "auto",
  "output_format": "png",
  "background": "transparent",
  "moderation": "auto",
})

# FIX 1: "image description" had a space — invalid Python identifier; renamed to image_description
class CarouselPlannerSchema__PostsItem(BaseModel):
  title: str
  description: str
  image_description: str


class CarouselPlannerSchema(BaseModel):
  posts: list[CarouselPlannerSchema__PostsItem] = Field(max_length=10)


class CarouselPlannerContext:
  def __init__(self, state_lesson_link: str, accent_color: str = "#6DFF2F", max_slides: int = 5, style: str = ACTIVE_STYLE):
    self.state_lesson_link = state_lesson_link
    self.accent_color = accent_color
    self.max_slides = max_slides
    self.style = style

def carousel_planner_instructions(run_context: RunContextWrapper[CarouselPlannerContext], _agent: Agent[CarouselPlannerContext]):
  ctx = run_context.context

  raw = _load_style_file("carousel_planner_instructions.txt", ctx.style)
  raw = raw.replace("__LESSON_LINK__", ctx.state_lesson_link)
  raw = raw.replace("__MAX_SLIDES__", str(ctx.max_slides))
  return raw.replace("#6DFF2F", ctx.accent_color)

carousel_planner = Agent(
  name="Carousel Planner",
  instructions=carousel_planner_instructions,
  model="gpt-5.5",
  output_type=CarouselPlannerSchema,
  model_settings=ModelSettings(
    store=True,
    reasoning=Reasoning(
      effort="low",
      summary="auto"
    )
  )
)


# FIX 3 & 4: DrawingAgentContext now carries the actual slide data, not just a number
class DrawingAgentContext:
  def __init__(self, state_current_post: int, post_title: str, post_description: str, post_image_description: str, accent_color: str = "#6DFF2F", style: str = ACTIVE_STYLE):
    self.state_current_post = state_current_post
    self.post_title = post_title
    self.post_description = post_description
    self.post_image_description = post_image_description
    self.accent_color = accent_color
    self.style = style

def drawing_agent_instructions(run_context: RunContextWrapper[DrawingAgentContext], _agent: Agent[DrawingAgentContext]):
  ctx = run_context.context

  raw = _load_style_file("drawing_agent_instructions.txt", ctx.style)
  raw = raw.replace("__SLIDE_NUMBER__", str(ctx.state_current_post))
  raw = raw.replace("__POST_TITLE__", ctx.post_title)
  raw = raw.replace("__POST_DESCRIPTION__", ctx.post_description)
  raw = raw.replace("__POST_IMAGE_DESCRIPTION__", ctx.post_image_description)
  return raw.replace("#6DFF2F", ctx.accent_color)

drawing_agent = Agent(
  name="Drawing Agent",
  instructions=drawing_agent_instructions,
  model="gpt-5.5",
  tools=[
    image_generation
  ],
  model_settings=ModelSettings(
    store=True,
    reasoning=Reasoning(
      effort="low",
      summary="auto"
    )
  )
)


class WorkflowInput(BaseModel):
  input_as_text: str
  accent_color: str = "#6DFF2F"
  background_file: str | None = None
  max_slides: int = 5
  style: str = ACTIVE_STYLE
  slide_numbers: bool = True


BASE_DIR = Path(__file__).parent

def create_run_folder() -> Path:
  """Create a unique, timestamped output folder.

  Uses microsecond precision (%f) and retries on the rare collision,
  so concurrent batch jobs never share the same directory.
  """
  while True:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
    folder = BASE_DIR / "output" / timestamp
    try:
      folder.mkdir(parents=True)   # exist_ok=False → raises FileExistsError on collision
      return folder
    except FileExistsError:
      continue  # sub-microsecond collision; spin and try the next tick


def save_image_from_result(result_temp, slide_index: int, run_folder: Path):
  """Extract base64 image data from the agent result and save it as a PNG."""
  for item in result_temp.raw_responses:
    for output in getattr(item, "output", []):
      if getattr(output, "type", None) == "image_generation_call":
        img_data = getattr(output, "result", None)
        if img_data:
          file_path = run_folder / f"slide_{slide_index + 1:02d}.png"
          file_path.write_bytes(base64.b64decode(img_data))
          print(f"  Saved: {file_path}")
          return
  print(f"  Warning: no image found in result for slide {slide_index + 1}")


# Main code entrypoint
async def run_workflow(workflow_input: WorkflowInput):
  run_folder = create_run_folder()
  print(f"Saving output to: {run_folder}\n")

  with trace("Post Creator"):
    state = {
      "lesson_link": None,
      "current_post": 0,
      "post_amount": None,
      "amount_of_posts": None,
      "current_post_title": None,
      "current_post_description": None,
      "posts": [],
      "post": {
        "title": None,
        "description": None,
        "image_description": None
      }
    }
    workflow = workflow_input.model_dump()
    conversation_history: list[TResponseInputItem] = [
      {
        "role": "user",
        "content": [
          {
            "type": "input_text",
            "text": workflow["input_as_text"]
          }
        ]
      }
    ]
    # FIX 5: state["lesson_link"] was None; pass the actual user input as the lesson link
    carousel_planner_result_temp = await Runner.run(
      carousel_planner,
      input=[
        *conversation_history
      ],
      run_config=RunConfig(trace_metadata={
        "__trace_source__": "agent-builder",
        "workflow_id": "wf_6a1187f45dfc8190933a638ccd08744308b151026d90b549"
      }),
      context=CarouselPlannerContext(
          state_lesson_link=workflow["input_as_text"],
          accent_color=workflow_input.accent_color,
          max_slides=workflow_input.max_slides,
          style=workflow_input.style,
      )
    )
    carousel_planner_result = {
      "output_text": carousel_planner_result_temp.final_output.model_dump_json(),
      "output_parsed": carousel_planner_result_temp.final_output.model_dump()
    }
    state["current_post"] = 0
    state["amount_of_posts"] = len(carousel_planner_result["output_parsed"]["posts"])
    state["posts"] = carousel_planner_result["output_parsed"]["posts"]

    # FIX 6: was `>=` which caused one extra iteration and an IndexError; corrected to `<`
    # FIX 7: removed the unconditional post-increment index update that crashed on the last slide
    while state["current_post"] < state["amount_of_posts"]:
      state["post"] = state["posts"][state["current_post"]]
      drawing_agent_result_temp = await Runner.run(
        drawing_agent,
        input=[
          *conversation_history
        ],
        run_config=RunConfig(trace_metadata={
          "__trace_source__": "agent-builder",
          "workflow_id": "wf_6a1187f45dfc8190933a638ccd08744308b151026d90b549"
        }),
        context=DrawingAgentContext(
          state_current_post=state["current_post"],
          post_title=state["post"]["title"],
          post_description=state["post"]["description"],
          post_image_description=state["post"]["image_description"],
          accent_color=workflow_input.accent_color,
          style=workflow_input.style,
        )
      )
      save_image_from_result(drawing_agent_result_temp, state["current_post"], run_folder)
      state["current_post"] = state["current_post"] + 1

    json_path = run_folder / "carousel.json"
    json_path.write_text(carousel_planner_result["output_text"], encoding="utf-8")
    print(f"  Saved: {json_path}")

    # Resolve background image path
    if workflow_input.background_file:
        bg_path = BASE_DIR / "assets" / "uploads" / workflow_input.background_file
        if not bg_path.exists():
            bg_path = BASE_DIR / "assets" / workflow_input.background_file
    else:
        bg_path = None  # apply_background.py will use its built-in default

    # Composite background onto all generated slides
    print("\nApplying background...")
    bg_cmd = [sys.executable, str(BASE_DIR / "apply_background.py"), str(run_folder)]
    if bg_path:
        bg_cmd.append(str(bg_path))
    subprocess.run(bg_cmd, check=True)

    # Stamp slide numbers onto composited images (optional)
    if workflow_input.slide_numbers:
        print("\nAdding slide numbers...")
        subprocess.run(
          [sys.executable, str(BASE_DIR / "add_slide_numbers.py"), str(run_folder),
           "--color", workflow_input.accent_color],
          check=True
        )
    else:
        print("\nSlide numbers disabled — skipping.")

    return carousel_planner_result, run_folder


if __name__ == "__main__":
    import sys

    # Accept lesson link as a CLI argument, or fall back to a prompt
    if len(sys.argv) > 1:
        lesson_link = " ".join(sys.argv[1:])
    else:
        lesson_link = input("Enter the lesson link or topic: ").strip()

    print(f"Starting carousel generation for: {lesson_link}\n")
    result, run_folder = asyncio.run(run_workflow(WorkflowInput(input_as_text=lesson_link)))
    print(f"\nDone! Images saved to: {run_folder}")
    print("\nCarousel planner output:")
    print(result["output_text"])
