# 🎠 Carousel Generator

An AI-powered tool that turns any lesson link or topic into a ready-to-post educational image carousel — in seconds.

Built on the OpenAI Agents SDK with a two-agent pipeline: one agent plans the slides, another generates the visuals. Outputs polished PNG slides with a composited background and optional slide-number stamps.

---

## ✨ Features

- **Prompt → Carousel**: Paste a URL or free-text topic; get a multi-slide carousel
- **Batch mode**: Generate several carousels at once, either sequentially or all at once
- **Style system**: Swap the entire look-and-feel by switching style folders
- **Custom accent color**: Live color picker synced to every slide
- **Custom background**: Upload your own background image or reset to default
- **Slide count control**: 1–10 slides per carousel
- **Slide numbers**: Toggle on/off; color-matched to your accent
- **Run history**: Browser sidebar with thumbnail previews and a lightbox viewer
- **CLI mode**: Generate carousels headlessly from the terminal

---

## 🏗️ How It Works

```
User input (URL or topic)
        │
        ▼
┌──────────────────────┐
│  Carousel Planner    │  GPT-5.5 (reasoning)
│  Agent               │  → structured JSON:
│                      │    title, description,
│                      │    image_description
└──────────┬───────────┘
           │  for each slide
           ▼
┌──────────────────────┐
│  Drawing Agent       │  GPT-5.5 + gpt-image-1
│                      │  → 1024×1024 PNG (RGBA,
│                      │    transparent bg)
└──────────┬───────────┘
           │
           ▼
  apply_background.py   ← composites Background.png behind each slide
           │
           ▼
  add_slide_numbers.py  ← stamps "1/5", "2/5" … in accent color
           │
           ▼
  output/<timestamp>/composited/slide_01.png … slide_N.png
```

Each slide's instructions are loaded from a **style folder** (`styles/<Style Name>/`), making it easy to create completely different carousel aesthetics without touching any Python.

---


## 🚀 Getting Started

### 1. Prerequisites

- Python 3.11+
- An [OpenAI API key](https://platform.openai.com/api-keys) with access to `gpt-image-1`

### 2. Install dependencies

```bash
pip install flask pillow python-dotenv openai openai-agents pydantic
```

### 3. Configure your API key

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
```

### 4. Run the web app

```bash
python app.py
```

Open **http://localhost:5000** in your browser.

### 5. (Optional) Run from the CLI

```bash
python run.py "What is RSI and how to use it in trading"
# or pass a URL:
python run.py https://example.com/lesson/rsi
```

## 🎨 Adding a New Style

1. Create a new subfolder under `styles/`:
   ```
   styles/
   └── My New Style/
       ├── carousel_planner_instructions.txt
       └── drawing_agent_instructions.txt
   ```

2. Write your agent instructions. Use these placeholders — they're replaced at runtime:

   **`carousel_planner_instructions.txt`**
   | Placeholder | Replaced with |
   |---|---|
   | `__LESSON_LINK__` | The user's input topic or URL |
   | `__MAX_SLIDES__` | The requested slide count |
   | `#6DFF2F` | The user's chosen accent color |

   **`drawing_agent_instructions.txt`**
   | Placeholder | Replaced with |
   |---|---|
   | `__SLIDE_NUMBER__` | Current slide index (0-based) |
   | `__POST_TITLE__` | Slide title from the planner |
   | `__POST_DESCRIPTION__` | Slide body text from the planner |
   | `__POST_IMAGE_DESCRIPTION__` | Visual brief from the planner |
   | `#6DFF2F` | The user's chosen accent color |
