"""
app.py — Flask web frontend for the Carousel Generator
"""
from dotenv import load_dotenv
load_dotenv()

import asyncio
import json
import threading
import uuid
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string
from run import run_workflow, WorkflowInput, list_styles, ACTIVE_STYLE

app = Flask(__name__)
BASE_DIR = Path(__file__).parent

# In-memory job store  {job_id: {"status": ..., "log": [...], "run_folder": ..., "slides": [...]}}
jobs: dict[str, dict] = {}

# Batch store  {batch_id: {"mode": ..., "status": ..., "job_ids": [...], "topics": [...]}}
batches: dict[str, dict] = {}

# Serialises builtins.print patching so single-job verbose capture stays correct
_print_lock = threading.Lock()


# ── HTML Template ─────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Carousel Generator</title>
<style>
  :root {
    --bg: #0f0f13;
    --surface: #1a1a24;
    --surface2: #22222f;
    --border: #2e2e3e;
    --accent: #6c63ff;
    --accent-dim: #6c63ff22;
    --accent2: #ff6b6b;
    --text: #e8e8f0;
    --muted: #888899;
    --green: #22c55e;
    --slide-accent: #6DFF2F;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body {
    background: var(--bg); color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    display: flex; flex-direction: column; height: 100vh; overflow: hidden;
  }

  /* ── Header ── */
  header {
    flex-shrink: 0;
    padding: 1rem 2rem;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 1rem;
  }
  header h1 { font-size: 1.3rem; font-weight: 700; letter-spacing: -0.3px; white-space: nowrap; }
  header h1 span { color: var(--accent); }
  header p { color: var(--muted); font-size: .85rem; }

  /* ── Two-column layout ── */
  .layout {
    display: grid;
    grid-template-columns: 420px 1fr;
    flex: 1;
    min-height: 0;
  }

  /* ── LEFT PANEL ── */
  .left-panel {
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 1.75rem;
    display: flex; flex-direction: column; gap: 1.25rem;
  }

  .form-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 1.5rem;
  }
  label {
    display: block; font-size: .78rem; color: var(--muted);
    margin-bottom: .45rem; letter-spacing: .06em; text-transform: uppercase;
  }
  textarea {
    width: 100%; min-height: 90px; resize: vertical;
    background: var(--bg); border: 1px solid var(--border); border-radius: 9px;
    color: var(--text); font-size: .95rem; padding: .75rem .9rem;
    outline: none; transition: border-color .2s; font-family: inherit;
  }
  textarea:focus { border-color: var(--accent); }
  button[type=submit] {
    margin-top: 1rem; width: 100%; padding: .8rem;
    background: var(--accent); border: none; border-radius: 9px;
    color: #fff; font-size: .95rem; font-weight: 600; cursor: pointer;
    transition: opacity .2s, transform .1s;
  }
  button[type=submit]:hover { opacity: .88; }
  button[type=submit]:active { transform: scale(.98); }
  button[type=submit]:disabled { opacity: .45; cursor: not-allowed; }

  /* Progress */
  .progress-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 1.25rem; display: none;
  }
  .status-row { display: flex; align-items: center; gap: .7rem; margin-bottom: .85rem; }
  .spinner {
    width: 18px; height: 18px; border: 2px solid var(--border);
    border-top-color: var(--accent); border-radius: 50%;
    animation: spin .75s linear infinite; flex-shrink: 0;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #status-text { font-weight: 600; font-size: .9rem; }
  .log-box {
    background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
    padding: .65rem .85rem; font-family: monospace; font-size: .78rem;
    color: var(--muted); max-height: 140px; overflow-y: auto;
    white-space: pre-wrap; word-break: break-all;
  }

  .error-msg { color: var(--accent2); font-size: .85rem; margin-top: .6rem; }

  #new-run-btn {
    width: 100%; padding: .7rem;
    background: transparent; border: 1px solid var(--border); border-radius: 9px;
    color: var(--text); font-size: .9rem; cursor: pointer; transition: border-color .2s;
    display: none;
  }
  #new-run-btn:hover { border-color: var(--accent); color: var(--accent); }

  /* ── Style Options Card ── */
  .style-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    overflow: hidden;
  }
  .style-card-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: .85rem 1.5rem;
    cursor: pointer; user-select: none;
    transition: background .15s;
  }
  .style-card-header:hover { background: var(--surface2); }
  .style-card-title {
    font-size: .72rem; color: var(--muted);
    letter-spacing: .08em; text-transform: uppercase;
  }
  .style-card-chevron {
    color: var(--muted); font-size: .8rem;
    transition: transform .25s;
  }
  .style-card.open .style-card-chevron { transform: rotate(180deg); }
  .style-card-body {
    display: none;
    padding: 0 1.5rem 1.25rem;
    display: flex; flex-direction: column; gap: 1.1rem;
  }
  .style-card:not(.open) .style-card-body { display: none; }
  .style-card.open      .style-card-body { display: flex; }

  /* Color picker */
  .color-row {
    display: flex; align-items: center; gap: .7rem;
  }
  .color-swatch-wrap {
    position: relative; width: 34px; height: 34px;
    border-radius: 8px; border: 2px solid var(--border);
    overflow: hidden; flex-shrink: 0; cursor: pointer;
    background: var(--slide-accent);
  }
  .color-swatch-wrap input[type=color] {
    position: absolute; inset: -6px;
    width: calc(100% + 12px); height: calc(100% + 12px);
    cursor: pointer; opacity: 0;
  }
  .color-hex {
    font-family: monospace; font-size: .85rem;
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: .3rem .65rem;
    color: var(--text); min-width: 96px; text-align: center;
    letter-spacing: .04em;
  }
  .btn-text {
    font-size: .74rem; color: var(--muted);
    background: none; border: none; cursor: pointer;
    text-decoration: underline; padding: 0;
  }
  .btn-text:hover { color: var(--accent); }

  /* Style picker */
  .style-select {
    width: 100%;
    background: var(--bg); border: 1px solid var(--border); border-radius: 9px;
    color: var(--text); font-size: .9rem; padding: .55rem .8rem;
    outline: none; cursor: pointer; appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23888899' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right .75rem center;
    padding-right: 2rem;
    transition: border-color .2s;
  }
  .style-select:focus { border-color: var(--accent); }
  .style-select option { background: var(--surface); }

  /* Background picker */
  .bg-row {
    display: flex; align-items: center; gap: .75rem;
  }
  .bg-thumb {
    width: 52px; height: 52px; border-radius: 8px;
    object-fit: cover; border: 1px solid var(--border);
    flex-shrink: 0; background: #111;
  }
  .bg-info { flex: 1; min-width: 0; }
  .bg-name {
    font-size: .8rem; color: var(--text);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .bg-actions { display: flex; gap: .4rem; margin-top: .35rem; flex-wrap: wrap; }
  .btn-sm {
    font-size: .72rem; padding: .22rem .6rem;
    border-radius: 5px; border: 1px solid var(--border);
    background: transparent; color: var(--muted);
    cursor: pointer; white-space: nowrap;
  }
  .btn-sm:hover { border-color: var(--accent); color: var(--accent); }
  #bg-upload-input { display: none; }

  /* ── Slide Options Card (shares style-card skeleton) ── */
  .stepper-row {
    display: flex; align-items: center; gap: .6rem;
  }
  .stepper-btn {
    width: 30px; height: 30px;
    border: 1px solid var(--border); border-radius: 7px;
    background: transparent; color: var(--text);
    font-size: 1.1rem; line-height: 1; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: border-color .15s, color .15s; flex-shrink: 0;
  }
  .stepper-btn:hover { border-color: var(--accent); color: var(--accent); }
  .stepper-btn:disabled { opacity: .35; cursor: not-allowed; }
  .stepper-val {
    font-size: 1rem; font-weight: 700; min-width: 24px;
    text-align: center; color: var(--text);
  }
  .stepper-hint { font-size: .73rem; color: var(--muted); margin-left: .25rem; }

  /* Toggle switch */
  .toggle-row {
    display: flex; align-items: center; justify-content: space-between;
  }
  .toggle-label { font-size: .88rem; color: var(--text); }
  .toggle-switch {
    position: relative; width: 38px; height: 22px; flex-shrink: 0;
  }
  .toggle-switch input { opacity: 0; width: 0; height: 0; position: absolute; }
  .toggle-track {
    position: absolute; inset: 0; border-radius: 11px;
    background: var(--border); cursor: pointer;
    transition: background .2s;
  }
  .toggle-track::after {
    content: ''; position: absolute;
    width: 16px; height: 16px; border-radius: 50%;
    background: #fff; top: 3px; left: 3px;
    transition: transform .2s;
  }
  .toggle-switch input:checked + .toggle-track { background: var(--accent); }
  .toggle-switch input:checked + .toggle-track::after { transform: translateX(16px); }

  /* ── Batch mode toggle ── */
  .label-muted { color: var(--muted); font-weight: 400; letter-spacing: 0; text-transform: none; font-size: .72rem; }
  .batch-mode-row { margin-top: .9rem; }
  .mode-toggle { display: flex; gap: .4rem; margin-top: .35rem; }
  .mode-btn {
    flex: 1; padding: .48rem .6rem;
    border: 1px solid var(--border); border-radius: 8px;
    background: transparent; color: var(--muted);
    font-size: .82rem; cursor: pointer; transition: all .15s;
    white-space: nowrap;
  }
  .mode-btn:hover:not(.active) { color: var(--text); }
  .mode-btn.active {
    border-color: var(--accent);
    background: var(--accent-dim);
    color: var(--text); font-weight: 600;
  }

  /* ── Batch job progress list ── */
  .batch-jobs-list {
    display: flex; flex-direction: column; gap: .35rem;
    margin-top: .5rem;
  }
  .batch-job-row {
    display: flex; align-items: center; gap: .55rem;
    padding: .42rem .75rem;
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 7px; font-size: .79rem;
  }
  .batch-job-row.job-done { cursor: pointer; }
  .batch-job-row.job-done:hover { border-color: var(--accent); }
  .batch-job-row.job-error .batch-job-status { color: var(--accent2); }
  .batch-job-icon { flex-shrink: 0; font-size: .82rem; width: 16px; text-align: center; }
  .batch-job-topic {
    flex: 1; min-width: 0; color: var(--text);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .batch-job-status { color: var(--muted); font-size: .74rem; white-space: nowrap; }
  .mini-spinner {
    display: inline-block;
    width: 11px; height: 11px;
    border: 1.5px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin .75s linear infinite;
    vertical-align: middle;
  }

  /* ── RIGHT PANEL ── */
  .right-panel {
    overflow-y: auto;
    padding: 1.75rem;
    display: flex; flex-direction: column; gap: 0;
  }

  .right-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 1.25rem;
  }
  .right-header h2 { font-size: 1rem; font-weight: 600; }
  .right-header .run-count { color: var(--muted); font-size: .82rem; }

  /* Run accordion */
  .run-item {
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: .75rem;
    overflow: hidden;
    transition: border-color .2s;
  }
  .run-item.active { border-color: var(--accent); }

  .run-header {
    display: flex; align-items: center; gap: .85rem;
    padding: .9rem 1.1rem;
    cursor: pointer;
    background: var(--surface);
    user-select: none;
    transition: background .15s;
  }
  .run-header:hover { background: var(--surface2); }

  .run-thumb-strip {
    display: flex; gap: 3px; flex-shrink: 0;
  }
  .run-thumb-strip img {
    width: 28px; height: 28px; border-radius: 4px; object-fit: cover;
  }

  .run-meta { flex: 1; min-width: 0; }
  .run-title {
    font-size: .88rem; font-weight: 600;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .run-ts { font-size: .74rem; color: var(--muted); margin-top: .15rem; }

  .run-chevron {
    color: var(--muted); font-size: .85rem; transition: transform .2s; flex-shrink: 0;
  }
  .run-item.active .run-chevron { transform: rotate(180deg); }

  /* Slides list inside a run */
  .run-slides { display: none; border-top: 1px solid var(--border); }
  .run-item.active .run-slides { display: block; }

  .slide-row {
    display: grid;
    grid-template-columns: 120px 1fr;
    gap: 1rem;
    padding: 1rem 1.1rem;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background .15s;
  }
  .slide-row:last-child { border-bottom: none; }
  .slide-row:hover { background: var(--surface2); }

  .slide-img-wrap {
    position: relative; flex-shrink: 0;
  }
  .slide-img-wrap img {
    width: 120px; height: 120px; object-fit: cover;
    border-radius: 8px; display: block;
  }
  .slide-num-badge {
    position: absolute; top: 5px; left: 5px;
    background: rgba(0,0,0,.65); color: #fff;
    font-size: .68rem; font-weight: 700;
    padding: 2px 6px; border-radius: 4px;
  }

  .slide-meta { display: flex; flex-direction: column; justify-content: flex-start; gap: .45rem; min-width: 0; }
  .slide-meta-title { font-size: .88rem; font-weight: 700; line-height: 1.3; }
  .slide-meta-desc { font-size: .8rem; color: var(--muted); line-height: 1.5; }
  .slide-meta-img-label {
    font-size: .7rem; color: var(--accent); text-transform: uppercase;
    letter-spacing: .05em; font-weight: 600; margin-top: .25rem;
  }
  .slide-meta-img-desc {
    font-size: .75rem; color: #7070aa; line-height: 1.5;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .empty-runs {
    text-align: center; color: var(--muted); padding: 3rem 1rem; font-size: .9rem;
  }

  /* ── Lightbox ── */
  #lightbox {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,.88); z-index: 999;
    align-items: center; justify-content: center; flex-direction: column; gap: 1rem;
  }
  #lightbox.open { display: flex; }
  #lightbox img { max-width: 88vw; max-height: 78vh; border-radius: 12px; }
  #lightbox-close {
    position: absolute; top: 1rem; right: 1.5rem;
    background: none; border: none; color: #fff; font-size: 2rem; cursor: pointer; line-height: 1;
  }
  #lightbox-meta {
    background: rgba(26,26,36,.95);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: .75rem 1.25rem;
    max-width: 600px; text-align: center;
  }
  #lightbox-meta-title { font-size: .95rem; font-weight: 700; }
  #lightbox-meta-desc { font-size: .82rem; color: var(--muted); margin-top: .3rem; }
  #lightbox-nav { display: flex; gap: 1rem; }
  #lightbox-nav button {
    background: var(--surface); border: 1px solid var(--border);
    color: var(--text); padding: .45rem 1.1rem; border-radius: 8px; cursor: pointer; font-size: .88rem;
  }
  #lightbox-nav button:hover { background: var(--accent); border-color: var(--accent); }
</style>
</head>
<body>

<header>
  <h1>🎠 Carousel <span>Generator</span></h1>
  <p>Paste a lesson link or topic — get a ready-to-post educational carousel.</p>
</header>

<div class="layout">

  <!-- ── LEFT: Generator ── -->
  <div class="left-panel">
    <div class="form-card">
      <form id="gen-form">
        <label for="topic">Lesson links or topics <span class="label-muted">· one per line for batch</span></label>
        <textarea id="topic" name="topic"
          placeholder="https://example.com/lesson/rsi&#10;What is RSI and how to use it&#10;Candlestick patterns for beginners"
          required></textarea>

        <!-- Shown only when >1 topic is entered -->
        <div id="batch-mode-row" class="batch-mode-row" style="display:none">
          <label>Processing mode</label>
          <div class="mode-toggle">
            <button type="button" class="mode-btn active" id="mode-sequential">⏭ One by one</button>
            <button type="button" class="mode-btn"        id="mode-concurrent">⚡ All at once</button>
          </div>
        </div>

        <div id="form-error" class="error-msg"></div>
        <button type="submit" id="submit-btn">✨ Generate Carousel</button>
      </form>
    </div>

    <!-- Style Options (collapsed by default) -->
    <div class="style-card" id="style-card">
      <div class="style-card-header" id="style-card-header">
        <span class="style-card-title">⚙ Style Options</span>
        <span class="style-card-chevron">▾</span>
      </div>

      <div class="style-card-body">
        <!-- Style picker -->
        <div>
          <label>Carousel style</label>
          <select class="style-select" id="style-select">
            <option value="" disabled>Loading styles…</option>
          </select>
        </div>

        <!-- Accent color -->
        <div>
          <label>Slide accent color</label>
          <div class="color-row">
            <div class="color-swatch-wrap" id="color-swatch">
              <input type="color" id="accent-color-input" value="#6dff2f" title="Pick accent color"/>
            </div>
            <span class="color-hex" id="accent-color-hex">#6DFF2F</span>
            <button type="button" class="btn-text" id="reset-color-btn">reset</button>
          </div>
        </div>

        <!-- Background image -->
        <div>
          <div class="toggle-row" style="margin-bottom:.6rem">
            <label style="margin:0">Background image</label>
            <label class="toggle-switch">
              <input type="checkbox" id="use-bg-toggle" checked/>
              <span class="toggle-track"></span>
            </label>
          </div>
          <div id="bg-picker-wrap">
            <div class="bg-row">
              <img class="bg-thumb" id="bg-thumb" src="/background-image/Background.png" alt="Background"/>
              <div class="bg-info">
                <div class="bg-name" id="bg-name">Background.png (default)</div>
                <div class="bg-actions">
                  <button type="button" class="btn-sm" id="bg-upload-btn">↑ Upload new</button>
                  <button type="button" class="btn-sm" id="bg-reset-btn">↩ Use default</button>
                </div>
              </div>
            </div>
          </div>
          <input type="file" id="bg-upload-input" accept=".png,.jpg,.jpeg,.webp"/>
        </div>

        <!-- Image quality -->
        <div>
          <label>Image quality</label>
          <select class="style-select" id="quality-select">
            <option value="auto">Auto</option>
            <option value="low">Low &mdash; fastest</option>
            <option value="medium">Medium</option>
            <option value="high">High &mdash; best quality</option>
          </select>
        </div>

        <!-- Slide dimensions -->
        <div>
          <label>Slide dimensions</label>
          <div class="mode-toggle">
            <button type="button" class="mode-btn active" id="size-square"    data-size="1024x1024">&#9632; Square</button>
            <button type="button" class="mode-btn"        id="size-portrait"  data-size="1024x1536">&#9650; Portrait</button>
            <button type="button" class="mode-btn"        id="size-landscape" data-size="1536x1024">&#9654; Landscape</button>
          </div>
        </div>

        <!-- Reasoning effort -->
        <div>
          <label>Reasoning effort</label>
          <div class="mode-toggle">
            <button type="button" class="mode-btn active" id="effort-low">    &#9889; Low</button>
            <button type="button" class="mode-btn"        id="effort-medium"> &#9898; Medium</button>
            <button type="button" class="mode-btn"        id="effort-high">   &#128269; High</button>
          </div>
        </div>

      </div>
    </div>

    <!-- Slide Options (collapsed by default) -->
    <div class="style-card" id="slide-options-card">
      <div class="style-card-header" id="slide-options-header">
        <span class="style-card-title">🎞 Slide Options</span>
        <span class="style-card-chevron">▾</span>
      </div>
      <div class="style-card-body">
        <div>
          <label>Max slides per carousel</label>
          <div class="stepper-row">
            <button type="button" class="stepper-btn" id="slides-dec">−</button>
            <span class="stepper-val" id="slides-val">5</span>
            <button type="button" class="stepper-btn" id="slides-inc">+</button>
            <span class="stepper-hint">1 – 10</span>
          </div>
        </div>
        <div class="toggle-row">
          <span class="toggle-label">Slide numbers</span>
          <label class="toggle-switch">
            <input type="checkbox" id="slide-numbers-toggle" checked/>
            <span class="toggle-track"></span>
          </label>
        </div>
      </div>
    </div>

    <div class="progress-card" id="progress-card">
      <div class="status-row">
        <div class="spinner"></div>
        <span id="status-text">Starting…</span>
      </div>
      <!-- Single-job verbose log -->
      <div class="log-box" id="log-box"></div>
      <!-- Batch: one row per job -->
      <div class="batch-jobs-list" id="batch-jobs-list" style="display:none"></div>
    </div>

    <button id="new-run-btn">↩ Generate another carousel</button>
  </div>

  <!-- ── RIGHT: Run history ── -->
  <div class="right-panel" id="right-panel">
    <div class="right-header">
      <h2>Previous Runs</h2>
      <span class="run-count" id="run-count"></span>
    </div>
    <div id="runs-list"></div>
  </div>

</div>

<!-- Lightbox -->
<div id="lightbox">
  <button id="lightbox-close">×</button>
  <img id="lightbox-img" src="" alt="Slide"/>
  <div id="lightbox-meta">
    <div id="lightbox-meta-title"></div>
    <div id="lightbox-meta-desc"></div>
  </div>
  <div id="lightbox-nav">
    <button id="lb-prev">← Prev</button>
    <button id="lb-next">Next →</button>
  </div>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let currentJobId   = null;   // single-job mode
let currentBatchId = null;   // batch mode
let pollInterval   = null;
let currentMode    = 'sequential';  // 'sequential' | 'concurrent'
let lbSlides = [];
let lbIndex  = 0;

// Style options state
const DEFAULT_ACCENT = '#6DFF2F';
let currentAccentColor    = DEFAULT_ACCENT;
let currentBgFile         = null;
let currentUseBackground  = localStorage.getItem('carousel_use_background') !== 'false';
let currentStyle          = null;   // null = server default
let currentImageQuality   = localStorage.getItem('carousel_image_quality')    || 'auto';
let currentImageSize      = localStorage.getItem('carousel_image_size')       || '1024x1024';
let currentReasoningEffort= localStorage.getItem('carousel_reasoning_effort') || 'low';

// ── DOM refs ───────────────────────────────────────────────────────────────
const form          = document.getElementById('gen-form');
const submitBtn     = document.getElementById('submit-btn');
const progressCard  = document.getElementById('progress-card');
const statusText    = document.getElementById('status-text');
const logBox        = document.getElementById('log-box');
const batchJobsList = document.getElementById('batch-jobs-list');
const newRunBtn     = document.getElementById('new-run-btn');
const formError     = document.getElementById('form-error');
const runsList      = document.getElementById('runs-list');
const runCount      = document.getElementById('run-count');
const topicTextarea = document.getElementById('topic');
const batchModeRow  = document.getElementById('batch-mode-row');

// Style option DOM refs
const styleSelect   = document.getElementById('style-select');
const accentInput   = document.getElementById('accent-color-input');
const accentHex     = document.getElementById('accent-color-hex');
const colorSwatch   = document.getElementById('color-swatch');
const resetColorBtn = document.getElementById('reset-color-btn');
const bgThumb       = document.getElementById('bg-thumb');
const bgName        = document.getElementById('bg-name');
const bgUploadBtn   = document.getElementById('bg-upload-btn');
const bgResetBtn    = document.getElementById('bg-reset-btn');
const bgUploadInput = document.getElementById('bg-upload-input');

// ── Style options ──────────────────────────────────────────────────────────
function loadStyleOptions() {
  const savedColor  = localStorage.getItem('carousel_accent_color');
  const savedBg     = localStorage.getItem('carousel_bg_file');
  if (savedColor) applyAccentColor(savedColor, false);
  if (savedBg)    applyBgFile(savedBg, false);
  // max_slides is initialised inline at declaration; just sync the DOM
  applyMaxSlides(currentMaxSlides, false);
  // Restore use-background toggle
  const useBgToggle = document.getElementById('use-bg-toggle');
  useBgToggle.checked = currentUseBackground;
  document.getElementById('bg-picker-wrap').style.display = currentUseBackground ? '' : 'none';
  // Restore image quality
  document.getElementById('quality-select').value = currentImageQuality;
  // Restore slide dimensions
  document.querySelectorAll('#size-square, #size-portrait, #size-landscape').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.size === currentImageSize);
  });
  // Restore reasoning effort
  const effortMap = { low: 'effort-low', medium: 'effort-medium', high: 'effort-high' };
  document.querySelectorAll('#effort-low, #effort-medium, #effort-high').forEach(btn => {
    btn.classList.toggle('active', btn.id === effortMap[currentReasoningEffort]);
  });
}

async function loadStyles() {
  try {
    const res    = await fetch('/styles');
    const data   = await res.json();
    const styles = data.styles || [];
    const saved  = localStorage.getItem('carousel_style') || data.default || '';

    styleSelect.innerHTML = '';
    for (const name of styles) {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      if (name === saved) opt.selected = true;
      styleSelect.appendChild(opt);
    }
    currentStyle = styleSelect.value || null;
  } catch (_) {
    styleSelect.innerHTML = '<option value="">Default</option>';
  }
}

styleSelect.addEventListener('change', () => {
  currentStyle = styleSelect.value || null;
  if (currentStyle) localStorage.setItem('carousel_style', currentStyle);
});

function applyAccentColor(hex, save = true) {
  currentAccentColor = hex.toUpperCase();
  accentInput.value  = hex;
  accentHex.textContent = hex.toUpperCase();
  colorSwatch.style.background = hex;
  document.documentElement.style.setProperty('--slide-accent', hex);
  if (save) localStorage.setItem('carousel_accent_color', hex);
}

function applyBgFile(filename, save = true) {
  currentBgFile = filename;
  const url = filename ? `/background-image/${filename}` : '/background-image/Background.png';
  bgThumb.src = url;
  bgName.textContent = filename ? filename : 'Background.png (default)';
  if (save) {
    if (filename) localStorage.setItem('carousel_bg_file', filename);
    else          localStorage.removeItem('carousel_bg_file');
  }
}

accentInput.addEventListener('input',  () => applyAccentColor(accentInput.value));
accentInput.addEventListener('change', () => applyAccentColor(accentInput.value));
resetColorBtn.addEventListener('click', () => applyAccentColor(DEFAULT_ACCENT));

document.getElementById('use-bg-toggle').addEventListener('change', function() {
  currentUseBackground = this.checked;
  localStorage.setItem('carousel_use_background', currentUseBackground);
  document.getElementById('bg-picker-wrap').style.display = currentUseBackground ? '' : 'none';
});

bgUploadBtn.addEventListener('click', () => bgUploadInput.click());
bgUploadInput.addEventListener('change', async () => {
  const file = bgUploadInput.files[0];
  if (!file) return;
  bgName.textContent = 'Uploading…';
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res  = await fetch('/upload-background', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Upload failed');
    applyBgFile(data.filename);
  } catch (err) {
    bgName.textContent = currentBgFile ? currentBgFile : 'Background.png (default)';
    alert('Upload failed: ' + err.message);
  }
  bgUploadInput.value = '';
});
bgResetBtn.addEventListener('click', () => applyBgFile(null));

// ── Image quality ──────────────────────────────────────────────────────────
document.getElementById('quality-select').addEventListener('change', function() {
  currentImageQuality = this.value;
  localStorage.setItem('carousel_image_quality', currentImageQuality);
});

// ── Slide dimensions ───────────────────────────────────────────────────────
document.querySelectorAll('#size-square, #size-portrait, #size-landscape').forEach(btn => {
  btn.addEventListener('click', function() {
    document.querySelectorAll('#size-square, #size-portrait, #size-landscape')
      .forEach(b => b.classList.remove('active'));
    this.classList.add('active');
    currentImageSize = this.dataset.size;
    localStorage.setItem('carousel_image_size', currentImageSize);
  });
});

// ── Reasoning effort ───────────────────────────────────────────────────────
const effortBtns = { 'effort-low': 'low', 'effort-medium': 'medium', 'effort-high': 'high' };
Object.keys(effortBtns).forEach(id => {
  document.getElementById(id).addEventListener('click', function() {
    Object.keys(effortBtns).forEach(bid => document.getElementById(bid).classList.remove('active'));
    this.classList.add('active');
    currentReasoningEffort = effortBtns[id];
    localStorage.setItem('carousel_reasoning_effort', currentReasoningEffort);
  });
});

// ── Style Options collapse / expand ───────────────────────────────────────
document.getElementById('style-card-header').addEventListener('click', () => {
  document.getElementById('style-card').classList.toggle('open');
});

// ── Slide Options ─────────────────────────────────────────────────────────
const MIN_SLIDES = 1, MAX_SLIDES = 10;
let currentMaxSlides = parseInt(localStorage.getItem('carousel_max_slides') || '5', 10);

const slidesVal  = document.getElementById('slides-val');
const slidesDec  = document.getElementById('slides-dec');
const slidesInc  = document.getElementById('slides-inc');

function applyMaxSlides(n, save = true) {
  currentMaxSlides = Math.min(MAX_SLIDES, Math.max(MIN_SLIDES, n));
  slidesVal.textContent   = currentMaxSlides;
  slidesDec.disabled      = currentMaxSlides <= MIN_SLIDES;
  slidesInc.disabled      = currentMaxSlides >= MAX_SLIDES;
  if (save) localStorage.setItem('carousel_max_slides', currentMaxSlides);
}

slidesDec.addEventListener('click', () => applyMaxSlides(currentMaxSlides - 1));
slidesInc.addEventListener('click', () => applyMaxSlides(currentMaxSlides + 1));

// ── Slide numbers toggle ───────────────────────────────────────────────────
const slideNumbersToggle = document.getElementById('slide-numbers-toggle');
let currentSlideNumbers = localStorage.getItem('carousel_slide_numbers') !== 'false';
slideNumbersToggle.checked = currentSlideNumbers;

slideNumbersToggle.addEventListener('change', () => {
  currentSlideNumbers = slideNumbersToggle.checked;
  localStorage.setItem('carousel_slide_numbers', currentSlideNumbers);
});

document.getElementById('slide-options-header').addEventListener('click', () => {
  document.getElementById('slide-options-card').classList.toggle('open');
});

// ── Batch mode toggle ──────────────────────────────────────────────────────
function getTopics() {
  return topicTextarea.value.split('\n').map(l => l.trim()).filter(Boolean);
}

function updateBatchModeVisibility() {
  const topics = getTopics();
  const multi  = topics.length > 1;
  batchModeRow.style.display = multi ? 'block' : 'none';
  const label = multi ? `✨ Generate ${topics.length} Carousels` : '✨ Generate Carousel';
  if (!submitBtn.disabled) submitBtn.textContent = label;
}

topicTextarea.addEventListener('input', updateBatchModeVisibility);

document.getElementById('mode-sequential').addEventListener('click', function() {
  currentMode = 'sequential';
  this.classList.add('active');
  document.getElementById('mode-concurrent').classList.remove('active');
});
document.getElementById('mode-concurrent').addEventListener('click', function() {
  currentMode = 'concurrent';
  this.classList.add('active');
  document.getElementById('mode-sequential').classList.remove('active');
});

// ── Generate form submit ───────────────────────────────────────────────────
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const topics = getTopics();
  if (!topics.length) return;

  formError.textContent = '';
  submitBtn.disabled = true;
  submitBtn.textContent = '⏳ Generating…';
  progressCard.style.display = 'block';
  newRunBtn.style.display    = 'none';
  statusText.textContent     = 'Starting…';

  // Reset progress areas
  logBox.textContent         = '';
  batchJobsList.innerHTML    = '';
  logBox.style.display       = topics.length === 1 ? 'block' : 'none';
  batchJobsList.style.display= topics.length > 1  ? 'block' : 'none';

  try {
    const res  = await fetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topics,
        mode:             currentMode,
        accent_color:     currentAccentColor,
        background_file:  currentBgFile || null,
        use_background:   currentUseBackground,
        max_slides:       currentMaxSlides,
        style:            currentStyle || null,
        slide_numbers:    currentSlideNumbers,
        image_quality:    currentImageQuality,
        image_size:       currentImageSize,
        reasoning_effort: currentReasoningEffort,
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Server error');

    if (data.batch_id) {
      currentBatchId = data.batch_id;
      currentJobId   = null;
      pollInterval   = setInterval(pollBatchStatus, 2000);
    } else {
      currentJobId   = data.job_id;
      currentBatchId = null;
      pollInterval   = setInterval(pollStatus, 2000);
    }
  } catch (err) {
    formError.textContent = '❌ ' + err.message;
    resetForm();
  }
});

// ── Single-job polling ─────────────────────────────────────────────────────
async function pollStatus() {
  if (!currentJobId) return;
  try {
    const res  = await fetch('/status/' + currentJobId);
    const data = await res.json();
    logBox.textContent = data.log.join('\n');
    logBox.scrollTop   = logBox.scrollHeight;
    statusText.textContent = data.status_label || data.status;

    if (data.status === 'done') {
      clearInterval(pollInterval);
      resetForm();
      newRunBtn.style.display = 'block';
      progressCard.style.display = 'none';
      loadRuns();
    } else if (data.status === 'error') {
      clearInterval(pollInterval);
      formError.textContent = '❌ ' + (data.error || 'An error occurred.');
      resetForm();
    }
  } catch (_) {}
}

// ── Batch polling ──────────────────────────────────────────────────────────
async function pollBatchStatus() {
  if (!currentBatchId) return;
  try {
    const res  = await fetch('/batch-status/' + currentBatchId);
    const data = await res.json();

    renderBatchProgress(data);

    if (data.status === 'done' || data.status === 'error') {
      clearInterval(pollInterval);
      resetForm();
      newRunBtn.style.display = 'block';
      progressCard.style.display = 'none';
      loadRuns();
    }
  } catch (_) {}
}

function renderBatchProgress(data) {
  // Header status text
  const modeLabel = data.mode === 'concurrent' ? 'All at once' : 'One by one';
  statusText.textContent =
    data.status === 'done'  ? `Done! ${data.completed}/${data.total} carousels` :
    data.status === 'error' ? `Finished with errors — ${data.completed}/${data.total}` :
    `${modeLabel} · ${data.completed}/${data.total} complete`;

  // Per-job rows
  batchJobsList.innerHTML = '';
  for (const job of data.jobs) {
    const row = document.createElement('div');
    row.className = 'batch-job-row job-' + job.status;
    if (job.run_ts) row.dataset.runTs = job.run_ts;

    let icon;
    if      (job.status === 'running') icon = '<span class="mini-spinner"></span>';
    else if (job.status === 'done')    icon = '✅';
    else if (job.status === 'error')   icon = '❌';
    else                               icon = '⌛';

    const label =
      job.status === 'queued' ? 'Queued' :
      job.status === 'error'  ? (job.error || 'Error') :
      (job.status_label || '');

    row.innerHTML =
      `<span class="batch-job-icon">${icon}</span>` +
      `<span class="batch-job-topic">${esc(job.topic.slice(0, 70))}</span>` +
      `<span class="batch-job-status">${esc(label.slice(0, 50))}</span>`;

    if (job.status === 'done' && job.run_ts) {
      row.addEventListener('click', () => {
        const el = document.querySelector(`.run-item[data-ts="${job.run_ts}"]`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          if (!el.classList.contains('active')) toggleRun(el, job.run_ts);
        }
      });
    }

    batchJobsList.appendChild(row);
  }
}

function resetForm() {
  const topics = getTopics();
  submitBtn.disabled = false;
  submitBtn.textContent = topics.length > 1
    ? `✨ Generate ${topics.length} Carousels`
    : '✨ Generate Carousel';
}

newRunBtn.addEventListener('click', () => {
  progressCard.style.display = 'none';
  newRunBtn.style.display    = 'none';
  topicTextarea.value        = '';
  formError.textContent      = '';
  currentJobId               = null;
  currentBatchId             = null;
  updateBatchModeVisibility();
});

// ── Run history sidebar ────────────────────────────────────────────────────
async function loadRuns() {
  const res  = await fetch('/runs');
  const runs = await res.json();

  runCount.textContent = runs.length + ' run' + (runs.length !== 1 ? 's' : '');

  if (runs.length === 0) {
    runsList.innerHTML = '<div class="empty-runs">No runs yet — generate your first carousel!</div>';
    return;
  }

  // Preserve open accordion panel
  const openTs = document.querySelector('.run-item.active')?.dataset.ts || runs[0].ts;

  runsList.innerHTML = '';
  for (const run of runs) {
    const item = buildRunItem(run);
    runsList.appendChild(item);
    if (run.ts === openTs) item.classList.add('active');
  }
}

function buildRunItem(run) {
  const item = document.createElement('div');
  item.className = 'run-item';
  item.dataset.ts = run.ts;

  const thumbs = run.thumbnails.slice(0, 4).map(u =>
    `<img src="${u}" alt="" loading="lazy"/>`
  ).join('');

  item.innerHTML = `
    <div class="run-header">
      <div class="run-thumb-strip">${thumbs}</div>
      <div class="run-meta">
        <div class="run-title">${esc(run.title)}</div>
        <div class="run-ts">${formatTs(run.ts)} &middot; ${run.slide_count} slides</div>
      </div>
      <span class="run-chevron">▾</span>
    </div>
    <div class="run-slides" id="slides-${run.ts}">
      <div style="padding:1rem 1.1rem;color:var(--muted);font-size:.82rem;">Loading…</div>
    </div>
  `;

  item.querySelector('.run-header').addEventListener('click', () => toggleRun(item, run.ts));
  return item;
}

async function toggleRun(item, ts) {
  const wasActive = item.classList.contains('active');
  document.querySelectorAll('.run-item').forEach(el => el.classList.remove('active'));
  if (wasActive) return;

  item.classList.add('active');
  const container = document.getElementById('slides-' + ts);

  if (container.dataset.loaded) return;
  container.dataset.loaded = '1';

  const res  = await fetch('/runs/' + ts);
  const data = await res.json();
  renderSlides(container, data.slides, ts);
}

function renderSlides(container, slides, ts) {
  container.innerHTML = '';
  slides.forEach((slide, i) => {
    const row = document.createElement('div');
    row.className = 'slide-row';
    row.innerHTML = `
      <div class="slide-img-wrap">
        <img src="${slide.url}" alt="Slide ${i+1}" loading="lazy"/>
        <span class="slide-num-badge">#${i+1}</span>
      </div>
      <div class="slide-meta">
        <div class="slide-meta-title">${esc(slide.title)}</div>
        <div class="slide-meta-desc">${esc(slide.description)}</div>
        <div class="slide-meta-img-label">Visual</div>
        <div class="slide-meta-img-desc">${esc(slide.image_description)}</div>
      </div>
    `;
    row.addEventListener('click', () => openLightbox(slides, i));
    container.appendChild(row);
  });
}

// ── Lightbox ───────────────────────────────────────────────────────────────
function openLightbox(slides, idx) {
  lbSlides = slides;
  lbIndex  = idx;
  updateLightbox();
  document.getElementById('lightbox').classList.add('open');
}

function updateLightbox() {
  const s = lbSlides[lbIndex];
  document.getElementById('lightbox-img').src                      = s.url;
  document.getElementById('lightbox-meta-title').textContent = s.title;
  document.getElementById('lightbox-meta-desc').textContent  = s.description;
}

document.getElementById('lightbox-close').addEventListener('click', () =>
  document.getElementById('lightbox').classList.remove('open'));
document.getElementById('lb-prev').addEventListener('click', () => {
  lbIndex = (lbIndex - 1 + lbSlides.length) % lbSlides.length; updateLightbox(); });
document.getElementById('lb-next').addEventListener('click', () => {
  lbIndex = (lbIndex + 1) % lbSlides.length; updateLightbox(); });
document.getElementById('lightbox').addEventListener('click', e => {
  if (e.target === document.getElementById('lightbox'))
    document.getElementById('lightbox').classList.remove('open'); });
document.addEventListener('keydown', e => {
  if (!document.getElementById('lightbox').classList.contains('open')) return;
  if (e.key === 'Escape')      document.getElementById('lightbox').classList.remove('open');
  if (e.key === 'ArrowLeft')  { lbIndex = (lbIndex - 1 + lbSlides.length) % lbSlides.length; updateLightbox(); }
  if (e.key === 'ArrowRight') { lbIndex = (lbIndex + 1) % lbSlides.length; updateLightbox(); }
});

// ── Helpers ────────────────────────────────────────────────────────────────
function esc(str) {
  return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function formatTs(ts) {
  // "2026-05-24_13-36-29-847392" → "May 24, 2026 · 13:36"
  // Microsecond segment and seconds are discarded by destructuring.
  const [date, time] = ts.split('_');
  const [y, m, d]   = date.split('-');
  const [hh, mm]    = time.split('-');   // hh, mm; ss + µs ignored
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${months[parseInt(m)-1]} ${parseInt(d)}, ${y} · ${hh}:${mm}`;
}

// ── Boot ───────────────────────────────────────────────────────────────────
loadStyleOptions();
loadStyles();
loadRuns();
</script>
</body>
</html>
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run_ts_list():
    """Return all run timestamp dirs, newest first."""
    output_dir = BASE_DIR / "output"
    if not output_dir.exists():
        return []
    return sorted(
        [d for d in output_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True
    )

def _load_carousel_json(run_dir: Path):
    p = run_dir / "carousel.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def _composited_slides(run_dir: Path):
    comp = run_dir / "composited"
    if comp.exists():
        return sorted(comp.glob("slide_*.png"))
    return sorted(run_dir.glob("slide_*.png"))


# ── API Routes ─────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template_string(HTML)


@app.get("/styles")
def get_styles():
    """Return available style names from the styles/ folder."""
    from run import list_styles
    styles = list_styles()
    return jsonify(styles=styles, default=ACTIVE_STYLE)


@app.get("/runs")
def list_runs():
    """Return summary of all run folders for the sidebar."""
    result = []
    for run_dir in _run_ts_list():
        slides = _composited_slides(run_dir)
        carousel = _load_carousel_json(run_dir)
        title = "Untitled Run"
        if carousel and carousel.get("posts"):
            title = carousel["posts"][0].get("title", title)

        thumbnails = [f"/slide/{run_dir.name}/{s.name}" for s in slides[:4]]
        result.append({
            "ts": run_dir.name,
            "title": title,
            "slide_count": len(slides),
            "thumbnails": thumbnails,
        })
    return jsonify(result)


@app.get("/runs/<run_ts>")
def get_run(run_ts: str):
    """Return full slide list with metadata for one run."""
    run_dir = BASE_DIR / "output" / run_ts
    if not run_dir.is_dir():
        return jsonify(error="Run not found"), 404

    slides  = _composited_slides(run_dir)
    carousel = _load_carousel_json(run_dir)
    posts   = (carousel or {}).get("posts", [])

    result = []
    for i, slide_path in enumerate(slides):
        post = posts[i] if i < len(posts) else {}
        result.append({
            "url":               f"/slide/{run_ts}/{slide_path.name}",
            "title":             post.get("title", f"Slide {i+1}"),
            "description":       post.get("description", ""),
            "image_description": post.get("image_description", ""),
        })
    return jsonify(slides=result)


@app.get("/background-image/<filename>")
def serve_background_image(filename: str):
    """Serve background images from assets/ or assets/uploads/."""
    # Prevent directory traversal
    filename = Path(filename).name
    path = BASE_DIR / "assets" / filename
    if not path.exists():
        path = BASE_DIR / "assets" / "uploads" / filename
    if not path.exists():
        return "Not found", 404
    return send_file(path.resolve())


@app.post("/upload-background")
def upload_background():
    """Accept a background image upload, save it, return the filename."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="No file provided"), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        return jsonify(error="Only PNG/JPG/WEBP files are accepted"), 400
    uploads_dir = BASE_DIR / "assets" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}{ext}"
    f.save(str(uploads_dir / filename))
    return jsonify(filename=filename)


@app.post("/generate")
def generate():
    body = request.get_json(silent=True) or {}

    # Accept either topics[] (batch) or legacy topic (single)
    raw_topics: list = body.get("topics") or []
    if not raw_topics:
        single = (body.get("topic") or "").strip()
        if single:
            raw_topics = [single]
    topics = [t.strip() for t in raw_topics if isinstance(t, str) and t.strip()]

    if not topics:
        return jsonify(error="Please provide at least one lesson link or topic."), 400

    mode             = body.get("mode", "sequential")
    accent_color     = (body.get("accent_color") or "#6DFF2F").strip()
    background_file  = body.get("background_file") or None
    use_background   = bool(body.get("use_background", True))
    max_slides       = max(1, min(10, int(body.get("max_slides") or 5)))
    style            = (body.get("style") or ACTIVE_STYLE).strip()
    slide_numbers    = bool(body.get("slide_numbers", True))
    image_quality    = (body.get("image_quality") or "auto").strip()
    image_size       = (body.get("image_size") or "1024x1024").strip()
    reasoning_effort = (body.get("reasoning_effort") or "low").strip()

    # Build job records for every topic
    job_specs = []
    for topic in topics:
        job_id = str(uuid.uuid4())
        initial_label = "Queued" if (mode == "sequential" and len(topics) > 1) else "Planning carousel…"
        initial_status = "queued" if (mode == "sequential" and len(topics) > 1) else "running"
        jobs[job_id] = {
            "status": initial_status, "status_label": initial_label,
            "topic": topic, "log": [], "slides": [], "error": None, "run_ts": None,
        }
        job_specs.append({"job_id": job_id, "topic": topic})

    if len(topics) == 1:
        # Single job: backward-compatible response
        jobs[job_specs[0]["job_id"]]["status"] = "running"
        threading.Thread(
            target=_run_job,
            args=(job_specs[0]["job_id"], topics[0], accent_color, background_file, use_background, True, max_slides, style, slide_numbers),
            kwargs=dict(image_quality=image_quality, image_size=image_size, reasoning_effort=reasoning_effort),
            daemon=True,
        ).start()
        return jsonify(job_id=job_specs[0]["job_id"])

    # Batch
    batch_id = str(uuid.uuid4())
    batches[batch_id] = {
        "mode":    mode,
        "status":  "running",
        "job_ids": [s["job_id"] for s in job_specs],
        "topics":  topics,
    }

    if mode == "concurrent":
        for spec in job_specs:
            jobs[spec["job_id"]]["status"]       = "running"
            jobs[spec["job_id"]]["status_label"] = "Planning carousel…"
        threading.Thread(
            target=_run_concurrent_batch,
            args=(batch_id, job_specs, accent_color, background_file, use_background, max_slides, style, slide_numbers),
            kwargs=dict(image_quality=image_quality, image_size=image_size, reasoning_effort=reasoning_effort),
            daemon=True,
        ).start()
    else:
        threading.Thread(
            target=_run_sequential_batch,
            args=(batch_id, job_specs, accent_color, background_file, use_background, max_slides, style, slide_numbers),
            kwargs=dict(image_quality=image_quality, image_size=image_size, reasoning_effort=reasoning_effort),
            daemon=True,
        ).start()

    return jsonify(
        batch_id=batch_id,
        job_ids=[s["job_id"] for s in job_specs],
        topics=topics,
    )


def _run_sequential_batch(batch_id: str, job_specs: list, accent_color: str, background_file, use_background: bool = True, max_slides: int = 5, style: str = ACTIVE_STYLE, slide_numbers: bool = True, image_quality: str = "auto", image_size: str = "1024x1024", reasoning_effort: str = "low"):
    """Run each job in order, waiting for one to finish before starting the next."""
    for spec in job_specs:
        jobs[spec["job_id"]]["status"]       = "running"
        jobs[spec["job_id"]]["status_label"] = "Planning carousel…"
        _run_job(spec["job_id"], spec["topic"], accent_color, background_file, use_background,
                 capture_print=True, max_slides=max_slides, style=style, slide_numbers=slide_numbers,
                 image_quality=image_quality, image_size=image_size, reasoning_effort=reasoning_effort)

    batch = batches[batch_id]
    batch["status"] = (
        "done" if all(jobs[jid]["status"] == "done" for jid in batch["job_ids"])
        else "error"
    )


def _run_concurrent_batch(batch_id: str, job_specs: list, accent_color: str, background_file, use_background: bool = True, max_slides: int = 5, style: str = ACTIVE_STYLE, slide_numbers: bool = True, image_quality: str = "auto", image_size: str = "1024x1024", reasoning_effort: str = "low"):
    """Start all jobs simultaneously in separate threads and wait for all to finish."""
    threads = [
        threading.Thread(
            target=_run_job,
            args=(spec["job_id"], spec["topic"], accent_color, background_file, use_background, False, max_slides, style, slide_numbers),
            kwargs=dict(image_quality=image_quality, image_size=image_size, reasoning_effort=reasoning_effort),
            daemon=True,
        )
        for spec in job_specs
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    batch = batches[batch_id]
    batch["status"] = (
        "done" if all(jobs[jid]["status"] == "done" for jid in batch["job_ids"])
        else "error"
    )


@app.get("/batch-status/<batch_id>")
def batch_status(batch_id: str):
    batch = batches.get(batch_id)
    if not batch:
        return jsonify(error="Unknown batch"), 404

    job_list = []
    for i, jid in enumerate(batch["job_ids"]):
        job = jobs.get(jid, {})
        job_list.append({
            "job_id":       jid,
            "topic":        batch["topics"][i],
            "status":       job.get("status", "unknown"),
            "status_label": job.get("status_label", ""),
            "error":        job.get("error"),
            "run_ts":       job.get("run_ts"),          # for sidebar linking
            "log_tail":     job.get("log", [])[-3:],    # last 3 lines only
        })

    completed = sum(1 for j in job_list if j["status"] in ("done", "error"))
    return jsonify(
        batch_id=batch_id,
        status=batch["status"],
        mode=batch["mode"],
        total=len(batch["job_ids"]),
        completed=completed,
        jobs=job_list,
    )


def _run_job(job_id: str, topic: str, accent_color: str = "#6DFF2F",
             background_file=None, use_background: bool = True, capture_print: bool = True,
             max_slides: int = 5, style: str = ACTIVE_STYLE, slide_numbers: bool = True,
             image_quality: str = "auto", image_size: str = "1024x1024", reasoning_effort: str = "low"):
    job = jobs[job_id]
    def log(msg): job["log"].append(msg)

    try:
        log(f"Starting generation for: {topic[:80]}…")
        job["status_label"] = "Planning slides with AI…"

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        if capture_print:
            # Serialise builtins.print patching – safe for single-job or sequential batch
            import builtins
            with _print_lock:
                _orig = builtins.print
                def _cap(*args, **kw):
                    log(" ".join(str(a) for a in args))
                    _orig(*args, **kw)
                builtins.print = _cap
                try:
                    result, run_folder = loop.run_until_complete(
                        run_workflow(WorkflowInput(
                            input_as_text=topic,
                            accent_color=accent_color,
                            background_file=background_file,
                            use_background=use_background,
                            max_slides=max_slides,
                            style=style,
                            slide_numbers=slide_numbers,
                            image_quality=image_quality,
                            image_size=image_size,
                            reasoning_effort=reasoning_effort,
                        ))
                    )
                finally:
                    builtins.print = _orig
        else:
            # Concurrent batch: skip print patching to avoid race conditions
            try:
                result, run_folder = loop.run_until_complete(
                    run_workflow(WorkflowInput(
                        input_as_text=topic,
                        accent_color=accent_color,
                        background_file=background_file,
                        use_background=use_background,
                        max_slides=max_slides,
                        style=style,
                        slide_numbers=slide_numbers,
                        image_quality=image_quality,
                        image_size=image_size,
                        reasoning_effort=reasoning_effort,
                    ))
                )
            finally:
                pass

        loop.close()

        slide_files = _composited_slides(run_folder)
        job["slides"]       = [f"/slide/{run_folder.name}/{f.name}" for f in slide_files]
        job["run_folder"]   = str(run_folder)
        job["run_ts"]       = run_folder.name   # used by batch sidebar linking
        job["status"]       = "done"
        job["status_label"] = f"Done! {len(slide_files)} slides generated."
        log(f"\n✅ Done — {len(slide_files)} slides saved to {run_folder}")

    except Exception as exc:
        job["status"]       = "error"
        job["status_label"] = "Error"
        job["error"]        = str(exc)
        log(f"\n❌ Error: {exc}")


@app.get("/status/<job_id>")
def status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify(error="Unknown job"), 404
    return jsonify(
        status=job["status"],
        status_label=job.get("status_label", ""),
        log=job["log"],
        slides=job.get("slides", []),
        error=job.get("error"),
    )


@app.get("/slide/<run_ts>/<filename>")
def serve_slide(run_ts: str, filename: str):
    path = BASE_DIR / "output" / run_ts / "composited" / filename
    if not path.exists():
        path = BASE_DIR / "output" / run_ts / filename
    if not path.exists():
        return "Not found", 404
    return send_file(path.resolve(), mimetype="image/png")


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
