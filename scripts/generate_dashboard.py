#!/usr/bin/env python3
"""
Generates an interactive Leaflet heatmap dashboard for Alagoas CBMAL fire incident reports.
"""

import csv
import json
import os
import sys
import unicodedata
from pathlib import Path

# Paths
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = WORKSPACE_DIR / "data" / "cbmal_fire_incidents.csv"
DOCS_DIR = WORKSPACE_DIR / "docs"
INDEX_HTML_PATH = DOCS_DIR / "index.html"


def normalize_category(detalhe: str, tipo: str) -> str:
    raw = f"{detalhe or ''} {tipo or ''}"
    norm = unicodedata.normalize("NFD", raw).encode("ascii", "ignore").decode("utf-8", "ignore").lower() if isinstance(raw, bytes) else unicodedata.normalize("NFD", raw).encode("ascii", "ignore").decode("utf-8").lower()

    if "edifica" in norm:
        return "Edificação"
    elif "vegeta" in norm:
        return "Vegetação"
    elif "transporte" in norm or "veiculo" in norm:
        return "Veículo"
    else:
        return "Diversos"


def load_incidents(csv_path: Path):
    incidents = []
    if not csv_path.exists():
        print(f"Warning: {csv_path} does not exist.")
        return incidents

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lat_str = row.get("latitude", "").strip()
            lng_str = row.get("longitude", "").strip()
            if not lat_str or not lng_str:
                continue

            try:
                lat = float(lat_str)
                lng = float(lng_str)
            except ValueError:
                continue

            # Format item
            date_str = row.get("data", "").strip()
            time_str = row.get("hora", "").strip()
            datetime_iso = f"{date_str}T{time_str}" if date_str and time_str else date_str
            detalhe_str = row.get("detalhe", "").strip()
            tipo_str = row.get("tipo", "").strip()

            category = normalize_category(detalhe_str, tipo_str)

            incidents.append({
                "id": row.get("incident_id", ""),
                "date": date_str,
                "time": time_str,
                "datetime": datetime_iso,
                "city": row.get("cidade", "").strip(),
                "type": tipo_str,
                "detalhe": detalhe_str,
                "category": category,
                "location": row.get("local", "").strip(),
                "vehicles": row.get("viaturas", "").strip(),
                "personnel": row.get("militares", "").strip(),
                "lat": lat,
                "lng": lng
            })

    # Sort by date and time
    incidents.sort(key=lambda x: x["datetime"])
    return incidents


def generate_html(incidents):
    incidents_json = json.dumps(incidents, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Alagoas Fire Incidents - Interactive Heatmap & Temporal Dashboard</title>

  <!-- Google Fonts & Font Awesome -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">

  <!-- Leaflet CSS -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>

  <style>
    :root {{
      --bg-dark: #0B0F19;
      --bg-card: rgba(18, 24, 38, 0.88);
      --bg-card-hover: rgba(28, 36, 56, 0.95);
      --border-color: rgba(255, 255, 255, 0.12);
      --text-main: #F3F4F6;
      --text-muted: #9CA3AF;
      
      /* Alagoas Flag Color Theme */
      --alagoas-red: #DA251E;
      --alagoas-red-glow: rgba(218, 37, 30, 0.4);
      --alagoas-blue: #0077B9;
      --alagoas-blue-glow: rgba(0, 119, 185, 0.4);
      --alagoas-gold: #F8C300;
      --alagoas-green: #00923F;
      
      --radius-lg: 16px;
      --radius-md: 12px;
      --shadow-premium: 0 20px 40px -15px rgba(0, 0, 0, 0.5), 0 0 20px rgba(218, 37, 30, 0.15);
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background-color: var(--bg-dark);
      color: var(--text-main);
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}

    #map {{
      width: 100%;
      height: 100vh;
      z-index: 1;
    }}

    /* Overlay Controls Container */
    .dashboard-overlay {{
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      pointer-events: none;
      z-index: 1000;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      padding: 20px;
    }}

    .pointer-events-auto {{
      pointer-events: auto;
    }}

    /* Header Panel */
    .header-panel {{
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-lg);
      padding: 16px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      max-width: 1200px;
      margin: 0 auto;
      width: 100%;
      box-shadow: var(--shadow-premium);
      gap: 12px;
    }}

    .brand-title {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}

    .brand-icon {{
      width: 44px;
      height: 44px;
      border-radius: 12px;
      background: linear-gradient(135deg, var(--alagoas-red), var(--alagoas-blue));
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      font-size: 20px;
      box-shadow: 0 4px 15px var(--alagoas-red-glow);
    }}

    .brand-text h1 {{
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .brand-text p {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 2px;
    }}

    .header-right-group {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    /* GitHub & CSV Buttons */
    .github-btn {{
      display: flex;
      align-items: center;
      gap: 8px;
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 20px;
      padding: 6px 14px;
      color: #FFF;
      font-size: 0.8rem;
      font-weight: 600;
      text-decoration: none;
      transition: all 0.2s ease;
    }}

    .github-btn:hover {{
      background: rgba(255, 255, 255, 0.16);
      border-color: rgba(255, 255, 255, 0.3);
      transform: translateY(-1px);
    }}

    .csv-btn {{
      display: flex;
      align-items: center;
      gap: 6px;
      background: rgba(0, 119, 185, 0.18);
      border: 1px solid rgba(56, 189, 248, 0.4);
      border-radius: 20px;
      padding: 6px 14px;
      color: #38BDF8;
      font-size: 0.8rem;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .csv-btn:hover {{
      background: rgba(0, 119, 185, 0.35);
      border-color: rgba(56, 189, 248, 0.7);
      color: #FFF;
      transform: translateY(-1px);
    }}

    /* Language Switcher */
    .lang-switcher {{
      display: flex;
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 8px;
      padding: 3px;
      gap: 2px;
    }}

    .lang-btn {{
      padding: 5px 10px;
      font-size: 0.75rem;
      font-weight: 700;
      border: none;
      background: transparent;
      color: var(--text-muted);
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .lang-btn.active {{
      background: var(--alagoas-red);
      color: white;
    }}

    .disclaimer-badge {{
      display: flex;
      align-items: center;
      gap: 6px;
      background: rgba(248, 195, 0, 0.15);
      border: 1px solid rgba(248, 195, 0, 0.35);
      padding: 6px 12px;
      border-radius: 20px;
      color: var(--alagoas-gold);
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .disclaimer-badge:hover {{
      background: rgba(248, 195, 0, 0.25);
      transform: scale(1.03);
    }}

    .stats-pills {{
      display: flex;
      gap: 12px;
    }}

    .stat-pill {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: var(--radius-md);
      padding: 8px 14px;
      text-align: right;
    }}

    .stat-pill .label {{
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
    }}

    .stat-pill .value {{
      font-size: 1rem;
      font-weight: 700;
      color: var(--alagoas-gold);
      font-family: 'JetBrains Mono', monospace;
    }}

    /* Bottom Timeline Controls */
    .timeline-panel {{
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--border-color);
      border-radius: var(--radius-lg);
      padding: 20px 24px;
      max-width: 1050px;
      margin: 0 auto;
      width: 100%;
      box-shadow: var(--shadow-premium);
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}

    .timeline-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}

    .current-date-badge {{
      display: flex;
      align-items: center;
      gap: 8px;
      background: rgba(218, 37, 30, 0.15);
      border: 1px solid rgba(218, 37, 30, 0.35);
      padding: 6px 14px;
      border-radius: 20px;
      color: #FF6B66;
      font-weight: 600;
      font-size: 0.85rem;
      font-family: 'JetBrains Mono', monospace;
      position: relative;
    }}

    .date-display-btn {{
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 6px;
      color: #FFF;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.82rem;
      padding: 3px 10px;
      outline: none;
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .date-display-btn:hover {{
      background: rgba(218, 37, 30, 0.25);
      border-color: rgba(218, 37, 30, 0.6);
      color: #FF6B66;
    }}

    .hidden-date-picker {{
      position: absolute;
      opacity: 0;
      width: 0;
      height: 0;
      pointer-events: none;
    }}

    .timeline-controls {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}

    .play-btn {{
      width: 46px;
      height: 46px;
      border-radius: 50%;
      border: none;
      background: linear-gradient(135deg, var(--alagoas-red), var(--alagoas-blue));
      color: white;
      font-size: 16px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.2s ease;
      box-shadow: 0 4px 14px var(--alagoas-red-glow);
    }}

    .play-btn:hover {{
      transform: scale(1.06);
      box-shadow: 0 6px 20px rgba(218, 37, 30, 0.6);
    }}

    /* Dual Range Slider Container */
    .dual-slider-container {{
      position: relative;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}

    .sliders-track-wrapper {{
      position: relative;
      width: 100%;
      height: 24px;
      display: flex;
      align-items: center;
    }}

    .slider-track-bg {{
      position: absolute;
      width: 100%;
      height: 8px;
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.12);
      z-index: 1;
    }}

    .slider-track-highlight {{
      position: absolute;
      height: 8px;
      border-radius: 4px;
      background: linear-gradient(90deg, var(--alagoas-red), var(--alagoas-blue));
      z-index: 2;
    }}

    .range-slider-input {{
      position: absolute;
      width: 100%;
      -webkit-appearance: none;
      appearance: none;
      background: transparent;
      pointer-events: none;
      outline: none;
      z-index: 3;
      margin: 0;
    }}

    .range-slider-input::-webkit-slider-thumb {{
      -webkit-appearance: none;
      appearance: none;
      pointer-events: auto;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: var(--alagoas-red);
      border: 3px solid #FFF;
      box-shadow: 0 0 10px rgba(218, 37, 30, 0.8);
      cursor: pointer;
      transition: transform 0.15s ease;
    }}

    .range-slider-input::-webkit-slider-thumb:hover {{
      transform: scale(1.2);
    }}

    .slider-labels {{
      display: flex;
      justify-content: space-between;
      font-size: 0.75rem;
      color: var(--text-muted);
      font-family: 'JetBrains Mono', monospace;
    }}

    .filter-pills {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}

    .filter-pill {{
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.1);
      padding: 6px 12px;
      border-radius: 20px;
      font-size: 0.78rem;
      color: var(--text-muted);
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .filter-pill.active {{
      background: rgba(0, 119, 185, 0.25);
      border-color: rgba(0, 119, 185, 0.6);
      color: #FFF;
      font-weight: 600;
    }}

    .mode-toggle {{
      display: flex;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 8px;
      padding: 3px;
      gap: 2px;
    }}

    .mode-btn {{
      padding: 5px 10px;
      font-size: 0.75rem;
      border: none;
      background: transparent;
      color: var(--text-muted);
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .mode-btn.active {{
      background: var(--alagoas-red);
      color: white;
      font-weight: 600;
    }}

    /* Custom Leaflet Dark Popup */
    .leaflet-popup-content-wrapper {{
      background: rgba(15, 21, 35, 0.95) !important;
      backdrop-filter: blur(12px) !important;
      border: 1px solid rgba(255, 255, 255, 0.15) !important;
      color: #F3F4F6 !important;
      border-radius: 12px !important;
      padding: 4px !important;
      box-shadow: 0 15px 30px rgba(0, 0, 0, 0.6) !important;
    }}

    .leaflet-popup-tip {{
      background: rgba(15, 21, 35, 0.95) !important;
    }}

    .popup-card {{
      padding: 10px 12px;
      min-width: 260px;
    }}

    .popup-badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      background: rgba(218, 37, 30, 0.2);
      color: #FF6B66;
    }}

    .popup-title {{
      font-size: 0.95rem;
      font-weight: 700;
      margin-bottom: 6px;
      color: #FFF;
    }}

    .popup-meta {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-bottom: 4px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .popup-meta i {{
      color: var(--alagoas-gold);
      width: 14px;
    }}

    .popup-disclaimer-note {{
      font-size: 0.72rem;
      color: var(--text-muted);
      margin-top: 8px;
      border-top: 1px solid rgba(255, 255, 255, 0.1);
      padding-top: 6px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 5px;
      flex-wrap: wrap;
    }}

    .popup-report-btn {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 8px;
      border-radius: 6px;
      background: rgba(218, 37, 30, 0.15);
      border: 1px solid rgba(218, 37, 30, 0.35);
      color: #FF7D47;
      font-size: 0.7rem;
      font-weight: 600;
      text-decoration: none;
      transition: all 0.2s ease;
    }}

    .popup-report-btn:hover {{
      background: rgba(218, 37, 30, 0.3);
      border-color: rgba(218, 37, 30, 0.6);
      color: #FFF;
      transform: translateY(-1px);
    }}

    /* Modal Overlay */
    .modal-overlay {{
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      z-index: 2000;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }}

    .modal-overlay.active {{
      display: flex;
    }}

    .modal-card {{
      background: #121826;
      border: 1px solid var(--border-color);
      border-radius: 16px;
      max-width: 560px;
      width: 100%;
      padding: 24px;
      box-shadow: var(--shadow-premium);
      animation: modalFadeIn 0.2s ease-out;
    }}

    @keyframes modalFadeIn {{
      from {{ opacity: 0; transform: scale(0.95); }}
      to {{ opacity: 1; transform: scale(1); }}
    }}

    .modal-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }}

    .modal-header h3 {{
      font-size: 1.1rem;
      color: #FFF;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .modal-close-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 1.2rem;
      cursor: pointer;
      transition: color 0.15s ease;
    }}

    .modal-close-btn:hover {{
      color: #FFF;
    }}

    .modal-body p {{
      font-size: 0.88rem;
      color: var(--text-muted);
      line-height: 1.55;
      margin-bottom: 12px;
    }}

    @media (max-width: 768px) {{
      .dashboard-overlay {{
        padding: 10px;
      }}
      .header-panel {{
        flex-direction: column;
        align-items: flex-start;
        gap: 12px;
        padding: 12px 16px;
      }}
      .header-right-group {{
        width: 100%;
        justify-content: space-between;
        flex-wrap: wrap;
      }}
      .stats-pills {{
        width: 100%;
        justify-content: space-between;
      }}
      .timeline-panel {{
        padding: 14px 16px;
      }}
    }}
  </style>
</head>
<body>

  <div id="map"></div>

  <div class="dashboard-overlay">
    <!-- Top Header -->
    <div class="header-panel pointer-events-auto">
      <div class="brand-title">
        <div class="brand-icon">
          <i class="fa-solid fa-fire-flame-curved"></i>
        </div>
        <div class="brand-text">
          <h1><span data-i18n="title">Incêndios em Alagoas</span> <span style="font-size: 0.7rem; background: rgba(0,119,185,0.25); color: #38BDF8; border: 1px solid rgba(0,119,185,0.4); padding: 2px 8px; border-radius: 10px; font-family: monospace;" data-i18n="cbmalData">DADOS CBMAL</span></h1>
          <p><span data-i18n="subtitle">Painel interativo de ocorrências do CBMAL</span> • <span data-i18n="byAuthor">Criado por</span> <a href="https://github.com/ajtga" target="_blank" rel="noopener" style="color: var(--alagoas-gold); text-decoration: none; font-weight: 600;">ajtga</a></p>
        </div>
      </div>

      <div class="header-right-group">
        <!-- CSV Download Button -->
        <button type="button" id="csv-btn" class="csv-btn pointer-events-auto" title="Baixar dados em CSV">
          <i class="fa-solid fa-file-csv"></i>
          <span data-i18n="downloadCsv">Baixar CSV</span>
        </button>

        <!-- GitHub Repo & Author Link -->
        <a href="https://github.com/ajtga/fire-incidents" target="_blank" rel="noopener" class="github-btn pointer-events-auto" title="Ver código no GitHub">
          <i class="fa-brands fa-github"></i>
          <span>GitHub</span>
        </a>

        <!-- Language Switcher -->
        <div class="lang-switcher">
          <button class="lang-btn active" data-lang="pt">PT</button>
          <button class="lang-btn" data-lang="en">EN</button>
          <button class="lang-btn" data-lang="es">ES</button>
        </div>

        <!-- Disclaimer Button -->
        <div class="disclaimer-badge" id="disclaimer-btn" title="Aviso de precisão das coordenadas">
          <i class="fa-solid fa-triangle-exclamation"></i>
          <span data-i18n="approxCoordinates">Coordenadas Aproximadas</span>
        </div>

        <!-- Stats Pills -->
        <div class="stats-pills">
          <div class="stat-pill">
            <div class="label" data-i18n="filteredIncidents">Ocorrências Filtradas</div>
            <div class="value" id="stat-visible-count">0</div>
          </div>
          <div class="stat-pill">
            <div class="label" data-i18n="totalGeocoded">Total Geocodificado</div>
            <div class="value" id="stat-total-count" style="color: #38BDF8;">{len(incidents)}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom Controls -->
    <div class="timeline-panel pointer-events-auto">
      <div class="timeline-header">
        <div class="current-date-badge">
          <i class="fa-regular fa-calendar-days"></i>
          <span data-i18n="from">De</span>
          <button type="button" id="start-date-btn" class="date-display-btn">--</button>
          <input type="date" id="start-date-picker" class="hidden-date-picker">
          <span data-i18n="to">Até</span>
          <button type="button" id="end-date-btn" class="date-display-btn">--</button>
          <input type="date" id="end-date-picker" class="hidden-date-picker">
        </div>

        <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
          <!-- Filter pills -->
          <div class="filter-pills" id="category-filters">
            <span class="filter-pill active" data-type="ALL" data-i18n="allTypes">Todos os Tipos</span>
            <span class="filter-pill" data-type="Edificação" data-i18n="edificacao">Edificação</span>
            <span class="filter-pill" data-type="Vegetação" data-i18n="vegetacao">Vegetação</span>
            <span class="filter-pill" data-type="Veículo" data-i18n="veiculo">Veículo</span>
            <span class="filter-pill" data-type="Diversos" data-i18n="diversos">Diversos</span>
          </div>

          <!-- Visualization toggle -->
          <div class="mode-toggle">
            <button class="mode-btn active" id="mode-heat"><i class="fa-solid fa-fire"></i> <span data-i18n="heatmap">Mapa de Calor</span></button>
            <button class="mode-btn" id="mode-markers"><i class="fa-solid fa-location-dot"></i> <span data-i18n="markers">Marcadores</span></button>
          </div>
        </div>
      </div>

      <div class="timeline-controls">
        <button class="play-btn" id="play-btn" title="Iniciar animação temporal">
          <i class="fa-solid fa-play" id="play-icon"></i>
        </button>

        <div class="dual-slider-container">
          <div class="sliders-track-wrapper">
            <div class="slider-track-bg"></div>
            <div class="slider-track-highlight" id="slider-highlight"></div>
            <input type="range" class="range-slider-input" id="start-slider" min="0" max="0" value="0">
            <input type="range" class="range-slider-input" id="end-slider" min="0" max="0" value="0">
          </div>
          <div class="slider-labels">
            <span id="slider-start-label">Data Inicial</span>
            <span id="slider-range-span" style="color: var(--alagoas-gold); font-weight: 600;">Janela Ativa</span>
            <span id="slider-end-label">Data Final</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Disclaimer Modal -->
  <div class="modal-overlay pointer-events-auto" id="disclaimer-modal">
    <div class="modal-card">
      <div class="modal-header">
        <h3><i class="fa-solid fa-triangle-exclamation" style="color: var(--alagoas-gold);"></i> <span data-i18n="disclaimerTitle">Aviso: Precisão das Coordenadas</span></h3>
        <button class="modal-close-btn" id="modal-close"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="modal-body">
        <p data-i18n="disclaimerText1">As coordenadas de latitude e longitude exibidas neste mapa de calor e marcadores são aproximações geográficas genéricas e não devem ser consideradas localizações exatas.</p>
        <p data-i18n="disclaimerText2">Em muitos casos, os relatórios oficiais do CBMAL não fornecem números de endereço ou coordenadas exatas. A geocodificação automatizada (via OpenStreetMap Nominatim) e inserções manuais utilizam o contexto disponível—frequentemente recorrendo a centroides de municípios, bairros ou ruas.</p>
        <p data-i18n="disclaimerText3">Trate sempre as coordenadas como estimativas espaciais para análise regional, e não como localizações exatas de atendimento de emergência.</p>
      </div>
    </div>
  </div>

  <!-- Data Download & ODbL License Modal -->
  <div class="modal-overlay pointer-events-auto" id="download-modal">
    <div class="modal-card">
      <div class="modal-header">
        <h3><i class="fa-solid fa-file-csv" style="color: #38BDF8;"></i> <span data-i18n="downloadModalTitle">Download dos Dados & Licença ODbL</span></h3>
        <button class="modal-close-btn" id="download-modal-close"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="modal-body">
        <p><strong style="color: #FFF;"><i class="fa-solid fa-building-shield" style="color: var(--alagoas-blue); margin-right: 6px;"></i><span data-i18n="downloadModalSourceTitle">Fonte dos Dados:</span></strong> <span data-i18n="downloadModalSourceBody">Corpo de Bombeiros Militar de Alagoas (CBMAL). Os relatórios públicos de ocorrências de incêndio são coletados e estruturados automaticamente.</span></p>
        
        <p><strong style="color: #FFF;"><i class="fa-solid fa-scale-balanced" style="color: var(--alagoas-gold); margin-right: 6px;"></i><span data-i18n="downloadModalLicenseTitle">Licença dos Dados (ODbL v1.0):</span></strong> <span data-i18n="downloadModalLicenseBody">Esta base de dados e dados geográficos derivados do OpenStreetMap são disponibilizados sob a Open Database License (ODbL v1.0). Você é livre para copiar, distribuir, adaptar e produzir trabalhos derivados dos dados, desde que mantenha os créditos de atribuição e disponibilize derivados sob a mesma licença.</span></p>
        
        <p><strong style="color: #FFF;"><i class="fa-solid fa-triangle-exclamation" style="color: var(--alagoas-red); margin-right: 6px;"></i><span data-i18n="downloadModalDisclaimerTitle">Aviso de Precisão:</span></strong> <span data-i18n="downloadModalDisclaimerBody">As coordenadas geográficas são aproximações automatizadas (Nominatim) ou centroides de bairros/municípios, não constituindo dados oficiais de localização exata de emergência.</span></p>

        <div style="margin-top: 20px; display: flex; gap: 10px; justify-content: flex-end;">
          <button type="button" id="download-cancel-btn" style="background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; padding: 8px 16px; color: var(--text-muted); cursor: pointer; font-size: 0.85rem; font-weight: 600;" data-i18n="cancel">Cancelar</button>
          <a href="https://raw.githubusercontent.com/ajtga/fire-incidents/main/data/cbmal_fire_incidents.csv" download target="_blank" rel="noopener" id="confirm-download-btn" style="background: var(--alagoas-blue); border: none; border-radius: 8px; padding: 8px 18px; color: #FFF; text-decoration: none; font-size: 0.85rem; font-weight: 700; display: inline-flex; align-items: center; gap: 8px; box-shadow: 0 4px 12px var(--alagoas-blue-glow);">
            <i class="fa-solid fa-download"></i>
            <span data-i18n="confirmDownload">Baixar cbmal_fire_incidents.csv</span>
          </a>
        </div>
      </div>
    </div>
  </div>

  <!-- Leaflet & Heatmap Scripts -->
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>

  <script>
    // Embedded incidents data
    const RAW_INCIDENTS = {incidents_json};

    // I18N Translation Dictionary
    const I18N = {{
      pt: {{
        title: "Incêndios em Alagoas",
        cbmalData: "DADOS CBMAL",
        subtitle: "Painel interativo de ocorrências do CBMAL",
        byAuthor: "Criado por",
        filteredIncidents: "Ocorrências Filtradas",
        totalGeocoded: "Total Geocodificado",
        approxCoordinates: "Coordenadas Aproximadas",
        downloadCsv: "Baixar CSV",
        from: "De",
        to: "Até",
        allTypes: "Todos os Tipos",
        edificacao: "Edificação",
        vegetacao: "Vegetação",
        veiculo: "Veículo",
        diversos: "Diversos",
        heatmap: "Mapa de Calor",
        markers: "Marcadores",
        daySpanSingle: "1 dia selecionado",
        daySpanPlural: "dias selecionados",
        disclaimerTitle: "Aviso: Precisão das Coordenadas",
        disclaimerText1: "As coordenadas de latitude e longitude exibidas neste mapa de calor e marcadores são aproximações geográficas genéricas e não devem ser consideradas localizações exatas.",
        disclaimerText2: "Em muitos casos, os relatórios oficiais do CBMAL não fornecem números de endereço ou coordenadas exatas. A geocodificação automatizada (via OpenStreetMap Nominatim) e inserções manuais utilizam o contexto disponível—frequentemente recorrendo a centroides de municípios, bairros ou ruas.",
        disclaimerText3: "Trate sempre as coordenadas como estimativas espaciais para análise regional, e não como localizações exatas de atendimento de emergência.",
        downloadModalTitle: "Download dos Dados & Licença ODbL",
        downloadModalSourceTitle: "Fonte dos Dados:",
        downloadModalSourceBody: "Corpo de Bombeiros Militar de Alagoas (CBMAL). Os relatórios públicos de ocorrências de incêndio são coletados e estruturados automaticamente.",
        downloadModalLicenseTitle: "Licença dos Dados (ODbL v1.0):",
        downloadModalLicenseBody: "Esta base de dados e dados geográficos derivados do OpenStreetMap são disponibilizados sob a Open Database License (ODbL v1.0). Você é livre para copiar, distribuir, adaptar e produzir trabalhos derivados dos dados, desde que mantenha os créditos de atribuição e disponibilize derivados sob a mesma licença.",
        downloadModalDisclaimerTitle: "Aviso de Precisão:",
        downloadModalDisclaimerBody: "As coordenadas geográficas são aproximações automatizadas (Nominatim) ou centroides de bairros/municípios, não constituindo dados oficiais de localização exata de emergência.",
        cancel: "Cancelar",
        confirmDownload: "Baixar cbmal_fire_incidents.csv",
        popupApprox: "Aproximação",
        reportInaccuracy: "Reportar Inexatidão"
      }},
      en: {{
        title: "Alagoas Fire Incidents",
        cbmalData: "CBMAL DATA",
        subtitle: "Interactive temporal heatmap & incident dashboard",
        byAuthor: "Created by",
        filteredIncidents: "Filtered Incidents",
        totalGeocoded: "Total Geocoded",
        approxCoordinates: "Approximate Coordinates",
        downloadCsv: "Download CSV",
        from: "From",
        to: "To",
        allTypes: "All Types",
        edificacao: "Building",
        vegetacao: "Vegetation",
        veiculo: "Vehicle",
        diversos: "Miscellaneous",
        heatmap: "Heatmap",
        markers: "Markers",
        daySpanSingle: "1 day selected",
        daySpanPlural: "days selected",
        disclaimerTitle: "Disclaimer: Coordinate Accuracy",
        disclaimerText1: "The latitude and longitude coordinates displayed in this heatmap and map markers are rough geographic approximations and must not be relied upon as exact pinpoint locations.",
        disclaimerText2: "In many cases, official incident reports published by CBMAL do not provide precise street numbers or building coordinates. Automated geocoding (via OpenStreetMap's Nominatim API) and manual coordinate backfills rely on available context—often falling back to city centroids, street centroids, or neighborhood boundaries.",
        disclaimerText3: "Always treat map coordinates as estimated spatial indicators for regional analysis rather than exact emergency dispatch locations.",
        downloadModalTitle: "Data Download & Terms of Use",
        downloadModalSourceTitle: "Data Source:",
        downloadModalSourceBody: "Corpo de Bombeiros Militar de Alagoas (CBMAL). Public fire incident reports are automatically scraped and structured.",
        downloadModalLicenseTitle: "Data License (ODbL v1.0):",
        downloadModalLicenseBody: "This database and derived OpenStreetMap spatial data are made available under the Open Database License (ODbL v1.0). You are free to copy, distribute, adapt, and build upon the data, provided that you attribute the source and license any derived database under ODbL.",
        downloadModalDisclaimerTitle: "Accuracy Disclaimer:",
        downloadModalDisclaimerBody: "Geographic coordinates are automated approximations (via Nominatim) or city/neighborhood centroids, and must not be used as exact emergency dispatch locations.",
        cancel: "Cancel",
        confirmDownload: "Download cbmal_fire_incidents.csv",
        popupApprox: "Approximation",
        reportInaccuracy: "Report Inaccuracy"
      }},
      es: {{
        title: "Incendios en Alagoas",
        cbmalData: "DATOS CBMAL",
        subtitle: "Panel interactivo de mapa de calor temporal de incidentes",
        byAuthor: "Creado por",
        filteredIncidents: "Incidentes Filtrados",
        totalGeocoded: "Total Geocodificado",
        approxCoordinates: "Coordenadas Aproximadas",
        downloadCsv: "Descargar CSV",
        from: "Desde",
        to: "Hasta",
        allTypes: "Todos los Tipos",
        edificacao: "Edificación",
        vegetacao: "Vegetación",
        veiculo: "Vehículo",
        diversos: "Diversos",
        heatmap: "Mapa de Calor",
        markers: "Marcadores",
        daySpanSingle: "1 día seleccionado",
        daySpanPlural: "días seleccionados",
        disclaimerTitle: "Aviso: Precisión de Coordenadas",
        disclaimerText1: "Las coordenadas de latitud y longitud mostradas en este mapa de calor y marcadores son aproximaciones geográficas y no deben considerarse ubicaciones exactas.",
        disclaimerText2: "En muchos casos, los informes oficiales publicados por CBMAL no proporcionan números exactos de calles o coordenadas precisas. La geocodificación automatizada (OpenStreetMap Nominatim) y las entradas manuales dependen del contexto disponible, recurriendo a centroides de ciudades o barrios.",
        disclaimerText3: "Trate siempre las coordenadas como estimaciones espaciales para análisis regional en lugar de ubicaciones exactas de emergencia.",
        downloadModalTitle: "Descarga de Datos y Términos de Uso",
        downloadModalSourceTitle: "Fuente de Datos:",
        downloadModalSourceBody: "Corpo de Bombeiros Militar de Alagoas (CBMAL). Los informes públicos de incidentes se recopilan y estructuran automáticamente.",
        downloadModalLicenseTitle: "Licencia de Datos (ODbL v1.0):",
        downloadModalLicenseBody: "Esta base de datos y los datos derivados de OpenStreetMap están disponibles bajo la licencia Open Database License (ODbL v1.0). Es libre de copiar, distribuir, adaptar y crear obras derivadas, manteniendo el crédito de atribución.",
        downloadModalDisclaimerTitle: "Aviso de Precisión:",
        downloadModalDisclaimerBody: "Las coordenadas geográficas son aproximaciones automatizadas (Nominatim) o centroides de ciudades/barrios, y no constituyen datos de ubicación exacta de emergencia.",
        cancel: "Cancelar",
        confirmDownload: "Descargar cbmal_fire_incidents.csv",
        popupApprox: "Aproximación",
        reportInaccuracy: "Reportar Inexactitud"
      }}
    }};

    // Global state
    let currentLang = 'pt'; // Default PT-BR
    let map;
    let heatLayer;
    let markerGroup;
    let isPlaying = false;
    let playInterval = null;
    let currentMode = 'heat';
    let selectedCategory = 'ALL';
    let datesList = [];

    let startIndex = 0;
    let endIndex = 0;
    
    // Grouped markers state for cycling through stacked incidents
    window.POPUP_GROUPS = {{}};

    // Helper: Format date into locale-aware month name
    function formatDateLocale(dateStr, lang) {{
      if (!dateStr) return '';
      const parts = dateStr.split('-');
      if (parts.length !== 3) return dateStr;
      const year = parseInt(parts[0]);
      const month = parseInt(parts[1]);
      const day = parseInt(parts[2]);

      const dateObj = new Date(Date.UTC(year, month - 1, day, 12, 0, 0));
      const localeMap = {{ pt: 'pt-BR', en: 'en-US', es: 'es-ES' }};
      const locale = localeMap[lang] || 'pt-BR';

      let formatted = new Intl.DateTimeFormat(locale, {{
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        timeZone: 'UTC'
      }}).format(dateObj);

      // Clean up PT / ES connectors
      formatted = formatted.replace(/\\bde\\b/gi, '').replace(/\\./g, '').replace(/\\s+/g, ' ').trim();
      
      // Capitalize first letter of month
      formatted = formatted.replace(/([a-zA-Z]{{3,}})/g, match => match.charAt(0).toUpperCase() + match.slice(1));

      return formatted;
    }}

    // Helper: Normalize strings for accent & case insensitive comparison
    function normalizeStr(str) {{
      if (!str) return '';
      return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    }}

    // Global function to cycle through stacked incidents at the same coordinate
    window.cyclePopupGroup = function(groupKey, delta, event) {{
      if (event) {{
        event.preventDefault();
        event.stopPropagation();
      }}
      const groupData = window.POPUP_GROUPS[groupKey];
      if (!groupData || !groupData.items || groupData.items.length === 0) return;

      groupData.currentIndex = (groupData.currentIndex + delta + groupData.items.length) % groupData.items.length;
      
      const container = document.getElementById(`popup-card-${{groupKey}}`);
      if (container) {{
        container.innerHTML = renderPopupInner(groupKey);
      }}
    }};

    function renderPopupInner(groupKey) {{
      const groupData = window.POPUP_GROUPS[groupKey];
      if (!groupData) return '';

      const dict = I18N[currentLang] || I18N.pt;
      const inc = groupData.items[groupData.currentIndex];
      const formattedDate = formatDateLocale(inc.date, currentLang);
      const total = groupData.items.length;

      const paginationHeader = total > 1 ? `
        <div class="popup-pagination" style="display: flex; align-items: center; gap: 6px; font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;">
          <button type="button" onclick="window.cyclePopupGroup('${{groupKey}}', -1, event)" style="background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.25); border-radius: 4px; color: #FFF; width: 22px; height: 22px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; outline: none;"><i class="fa-solid fa-chevron-left"></i></button>
          <span style="color: var(--alagoas-gold); font-weight: 700;">${{groupData.currentIndex + 1}} / ${{total}}</span>
          <button type="button" onclick="window.cyclePopupGroup('${{groupKey}}', 1, event)" style="background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.25); border-radius: 4px; color: #FFF; width: 22px; height: 22px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; outline: none;"><i class="fa-solid fa-chevron-right"></i></button>
        </div>
      ` : '';

      const issueTitle = encodeURIComponent(`[Coordenadas Inexatas] Ocorrência ${{inc.id}}`);
      const issueBody = encodeURIComponent(
        `### Reportar Inexatidão de Coordenadas / Report Coordinate Inaccuracy\\n\\n` +
        `- **ID da Ocorrência / Incident ID**: ${{inc.id}}\\n` +
        `- **Data e Hora / Date & Time**: ${{inc.date}} ${{inc.time}}\\n` +
        `- **Município / City**: ${{inc.city}}\\n` +
        `- **Endereço Relatado / Location**: ${{inc.location}}\\n` +
        `- **Coordenadas Atuais / Current Coords**: ${{inc.lat}}, ${{inc.lng}}\\n\\n` +
        `---\\n` +
        `**Coordenadas Corretas ou Sugestão / Correct Coordinates or Suggestion**:\\n` +
        `(Por favor insira o endereço correto ou latitude, longitude aqui)`
      );
      const reportIssueUrl = `https://github.com/ajtga/fire-incidents/issues/new?title=${{issueTitle}}&body=${{issueBody}}`;

      return `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
          <span class="popup-badge">${{inc.category || inc.type}}</span>
          ${{paginationHeader}}
        </div>
        <div class="popup-title">${{inc.detalhe || inc.type}}</div>
        <div class="popup-meta"><i class="fa-solid fa-city"></i> ${{inc.city}}</div>
        <div class="popup-meta"><i class="fa-regular fa-clock"></i> ${{formattedDate}} ${{inc.time}}</div>
        <div class="popup-meta"><i class="fa-solid fa-location-dot"></i> ${{inc.location}}</div>
        <div class="popup-meta"><i class="fa-solid fa-truck-medical"></i> ${{inc.vehicles}} | ${{inc.personnel}}</div>
        <div class="popup-disclaimer-note">
          <span><i class="fa-solid fa-triangle-exclamation"></i> ${{dict.popupApprox}}</span>
          <a href="${{reportIssueUrl}}" target="_blank" rel="noopener" class="popup-report-btn" title="Abrir Issue no GitHub para reportar localização incorreta">
            <i class="fa-solid fa-flag"></i> ${{dict.reportInaccuracy}}
          </a>
        </div>
      `;
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      initMap();
      processData();
      setupEventListeners();
      applyLanguage(currentLang);
    }});

    function initMap() {{
      map = L.map('map', {{
        center: [-9.57, -36.00],
        zoom: 9,
        zoomControl: false
      }});

      L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a> | Data: CBMAL | Created by <a href="https://github.com/ajtga" target="_blank">ajtga</a> (<a href="https://github.com/ajtga/fire-incidents" target="_blank">GitHub</a>)',
        subdomains: 'abcd',
        maxZoom: 19
      }}).addTo(map);

      L.control.zoom({{ position: 'topright' }}).addTo(map);
      markerGroup = L.layerGroup().addTo(map);
    }}

    function processData() {{
      if (!RAW_INCIDENTS || RAW_INCIDENTS.length === 0) return;

      const dateSet = new Set();
      RAW_INCIDENTS.forEach(inc => {{
        if (inc.date) dateSet.add(inc.date);
      }});

      datesList = Array.from(dateSet).sort();
      if (datesList.length === 0) return;

      const minDate = datesList[0];
      const maxDate = datesList[datesList.length - 1];

      // Configure Date Pickers
      const startPicker = document.getElementById('start-date-picker');
      const endPicker = document.getElementById('end-date-picker');

      startPicker.min = minDate;
      startPicker.max = maxDate;
      startPicker.value = minDate;

      endPicker.min = minDate;
      endPicker.max = maxDate;
      endPicker.value = maxDate;

      // Configure Dual Range Sliders
      const startSlider = document.getElementById('start-slider');
      const endSlider = document.getElementById('end-slider');

      startSlider.min = 0;
      startSlider.max = datesList.length - 1;
      startSlider.value = 0;

      endSlider.min = 0;
      endSlider.max = datesList.length - 1;
      endSlider.value = datesList.length - 1;

      startIndex = 0;
      endIndex = datesList.length - 1;

      updateUI();
      renderState();
    }}

    function applyLanguage(lang) {{
      currentLang = lang;
      const dict = I18N[lang] || I18N.pt;

      // Translate data-i18n elements
      document.querySelectorAll('[data-i18n]').forEach(el => {{
        const key = el.dataset.i18n;
        if (dict[key]) {{
          el.textContent = dict[key];
        }}
      }});

      // Update lang buttons
      document.querySelectorAll('.lang-btn').forEach(btn => {{
        if (btn.dataset.lang === lang) btn.classList.add('active');
        else btn.classList.remove('active');
      }});

      updateUI();
      renderState();
    }}

    function updateUI() {{
      const startSlider = document.getElementById('start-slider');
      const endSlider = document.getElementById('end-slider');
      const startPicker = document.getElementById('start-date-picker');
      const endPicker = document.getElementById('end-date-picker');
      const highlight = document.getElementById('slider-highlight');
      const dict = I18N[currentLang] || I18N.pt;

      const totalSteps = datesList.length - 1 || 1;
      const startPct = (startIndex / totalSteps) * 100;
      const endPct = (endIndex / totalSteps) * 100;

      highlight.style.left = startPct + '%';
      highlight.style.width = (endPct - startPct) + '%';

      startSlider.value = startIndex;
      endSlider.value = endIndex;

      if (datesList[startIndex]) startPicker.value = datesList[startIndex];
      if (datesList[endIndex]) endPicker.value = datesList[endIndex];

      const startFormatted = formatDateLocale(datesList[startIndex], currentLang);
      const endFormatted = formatDateLocale(datesList[endIndex], currentLang);

      document.getElementById('start-date-btn').textContent = startFormatted;
      document.getElementById('end-date-btn').textContent = endFormatted;

      document.getElementById('slider-start-label').textContent = startFormatted;
      document.getElementById('slider-end-label').textContent = endFormatted;

      const daySpan = endIndex - startIndex + 1;
      const spanText = daySpan === 1 ? dict.daySpanSingle : `${{daySpan}} ${{dict.daySpanPlural}}`;
      document.getElementById('slider-range-span').textContent = spanText;
    }}

    function getFilteredIncidents() {{
      const startDateStr = datesList[startIndex];
      const endDateStr = datesList[endIndex];

      let filtered = RAW_INCIDENTS.filter(inc => inc.date >= startDateStr && inc.date <= endDateStr);

      if (selectedCategory !== 'ALL') {{
        const normSelected = normalizeStr(selectedCategory);
        filtered = filtered.filter(inc => {{
          const normCat = normalizeStr(inc.category);
          const normDet = normalizeStr(inc.detalhe);
          const normTyp = normalizeStr(inc.type);
          return normCat.includes(normSelected) || normDet.includes(normSelected) || normTyp.includes(normSelected);
        }});
      }}

      return filtered;
    }}

    function renderState() {{
      const activeIncidents = getFilteredIncidents();
      const dict = I18N[currentLang] || I18N.pt;

      document.getElementById('stat-visible-count').textContent = activeIncidents.length;

      markerGroup.clearLayers();
      if (heatLayer) map.removeLayer(heatLayer);
      window.POPUP_GROUPS = {{}};

      if (activeIncidents.length === 0) return;

      if (currentMode === 'heat') {{
        const heatPoints = activeIncidents.map(inc => [inc.lat, inc.lng, 0.8]);
        heatLayer = L.heatLayer(heatPoints, {{
          radius: 25,
          blur: 15,
          maxZoom: 15,
          gradient: {{
            0.2: '#0077B9',  // Alagoas Blue
            0.5: '#F8C300',  // Alagoas Gold
            0.8: '#DA251E',  // Alagoas Red
            1.0: '#900C3F'   // Peak Crimson
          }}
        }}).addTo(map);
      }} else {{
        // Group incidents by spatial coordinate key (5 decimal precision ~1 meter)
        const groupedMap = new Map();
        activeIncidents.forEach(inc => {{
          const key = `${{inc.lat.toFixed(5)}}_${{inc.lng.toFixed(5)}}`;
          if (!groupedMap.has(key)) {{
            groupedMap.set(key, []);
          }}
          groupedMap.get(key).push(inc);
        }});

        groupedMap.forEach((items, groupKey) => {{
          const first = items[0];
          window.POPUP_GROUPS[groupKey] = {{
            items: items,
            currentIndex: 0
          }};

          // If stacked multiple incidents, give marker a gold highlight ring & slightly larger radius
          const isStacked = items.length > 1;
          const marker = L.circleMarker([first.lat, first.lng], {{
            radius: isStacked ? 9 : 7,
            fillColor: '#DA251E',
            color: isStacked ? '#F8C300' : '#FFFFFF',
            weight: isStacked ? 3 : 2,
            opacity: 1,
            fillOpacity: 0.9
          }});

          const popupWrapper = `<div class="popup-card" id="popup-card-${{groupKey}}">${{renderPopupInner(groupKey)}}</div>`;
          marker.bindPopup(popupWrapper);
          markerGroup.addLayer(marker);
        }});
      }}
    }}

    function setupEventListeners() {{
      const startSlider = document.getElementById('start-slider');
      const endSlider = document.getElementById('end-slider');
      const startPicker = document.getElementById('start-date-picker');
      const endPicker = document.getElementById('end-date-picker');
      const startBtn = document.getElementById('start-date-btn');
      const endBtn = document.getElementById('end-date-btn');

      // Date button triggers native picker
      startBtn.addEventListener('click', () => {{
        if (typeof startPicker.showPicker === 'function') {{
          startPicker.showPicker();
        }} else {{
          startPicker.click();
        }}
      }});

      endBtn.addEventListener('click', () => {{
        if (typeof endPicker.showPicker === 'function') {{
          endPicker.showPicker();
        }} else {{
          endPicker.click();
        }}
      }});

      startSlider.addEventListener('input', (e) => {{
        if (isPlaying) stopAnimation();
        let val = parseInt(e.target.value);
        if (val > endIndex) val = endIndex;
        startIndex = val;
        updateUI();
        renderState();
      }});

      endSlider.addEventListener('input', (e) => {{
        if (isPlaying) stopAnimation();
        let val = parseInt(e.target.value);
        if (val < startIndex) val = startIndex;
        endIndex = val;
        updateUI();
        renderState();
      }});

      startPicker.addEventListener('change', (e) => {{
        if (isPlaying) stopAnimation();
        const dateVal = e.target.value;
        const idx = datesList.indexOf(dateVal);
        if (idx !== -1) {{
          startIndex = Math.min(idx, endIndex);
          updateUI();
          renderState();
        }}
      }});

      endPicker.addEventListener('change', (e) => {{
        if (isPlaying) stopAnimation();
        const dateVal = e.target.value;
        const idx = datesList.indexOf(dateVal);
        if (idx !== -1) {{
          endIndex = Math.max(idx, startIndex);
          updateUI();
          renderState();
        }}
      }});

      const playBtn = document.getElementById('play-btn');
      playBtn.addEventListener('click', () => {{
        if (isPlaying) stopAnimation();
        else startAnimation();
      }});

      const filterPills = document.querySelectorAll('#category-filters .filter-pill');
      filterPills.forEach(pill => {{
        pill.addEventListener('click', () => {{
          filterPills.forEach(p => p.classList.remove('active'));
          pill.classList.add('active');
          selectedCategory = pill.dataset.type;
          renderState();
        }});
      }});

      const heatBtn = document.getElementById('mode-heat');
      const markerBtn = document.getElementById('mode-markers');

      heatBtn.addEventListener('click', () => {{
        currentMode = 'heat';
        heatBtn.classList.add('active');
        markerBtn.classList.remove('active');
        renderState();
      }});

      markerBtn.addEventListener('click', () => {{
        currentMode = 'markers';
        markerBtn.classList.add('active');
        heatBtn.classList.remove('active');
        renderState();
      }});

      // Language Switcher buttons
      const langBtns = document.querySelectorAll('.lang-btn');
      langBtns.forEach(btn => {{
        btn.addEventListener('click', () => {{
          applyLanguage(btn.dataset.lang);
        }});
      }});

      // Disclaimer Modal listeners
      const disclaimerBtn = document.getElementById('disclaimer-btn');
      const disclaimerModal = document.getElementById('disclaimer-modal');
      const modalClose = document.getElementById('modal-close');

      disclaimerBtn.addEventListener('click', () => {{
        disclaimerModal.classList.add('active');
      }});

      modalClose.addEventListener('click', () => {{
        disclaimerModal.classList.remove('active');
      }});

      disclaimerModal.addEventListener('click', (e) => {{
        if (e.target === disclaimerModal) {{
          disclaimerModal.classList.remove('active');
        }}
      }});

      // Data Download & ODbL License Modal listeners
      const csvBtn = document.getElementById('csv-btn');
      const downloadModal = document.getElementById('download-modal');
      const downloadModalClose = document.getElementById('download-modal-close');
      const downloadCancelBtn = document.getElementById('download-cancel-btn');
      const confirmDownloadBtn = document.getElementById('confirm-download-btn');

      if (csvBtn) {{
        csvBtn.addEventListener('click', (e) => {{
          e.preventDefault();
          downloadModal.classList.add('active');
        }});
      }}

      const closeDownloadModal = () => downloadModal.classList.remove('active');

      if (downloadModalClose) downloadModalClose.addEventListener('click', closeDownloadModal);
      if (downloadCancelBtn) downloadCancelBtn.addEventListener('click', closeDownloadModal);
      if (confirmDownloadBtn) confirmDownloadBtn.addEventListener('click', closeDownloadModal);

      if (downloadModal) {{
        downloadModal.addEventListener('click', (e) => {{
          if (e.target === downloadModal) closeDownloadModal();
        }});
      }}
    }}

    function startAnimation() {{
      if (endIndex >= datesList.length - 1 && startIndex === 0) {{
        startIndex = 0;
        endIndex = 0;
      }}

      isPlaying = true;
      document.getElementById('play-icon').className = 'fa-solid fa-pause';

      playInterval = setInterval(() => {{
        if (endIndex < datesList.length - 1) {{
          startIndex++;
          endIndex++;
          updateUI();
          renderState();
        }} else {{
          stopAnimation();
        }}
      }}, 1200);
    }}

    function stopAnimation() {{
      isPlaying = false;
      document.getElementById('play-icon').className = 'fa-solid fa-play';
      if (playInterval) clearInterval(playInterval);
    }}
  </script>
</body>
</html>
"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Successfully generated dashboard at: {INDEX_HTML_PATH}")


def main():
    incidents = load_incidents(CSV_PATH)
    print(f"Loaded {len(incidents)} valid geocoded incidents.")
    generate_html(incidents)


if __name__ == "__main__":
    main()
