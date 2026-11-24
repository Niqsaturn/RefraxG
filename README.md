<div align="center">

# Refrax G

**Explore Earth's radio and ionospheric environment through an interactive scientific map.**

Global data · 3D geography · RF reference simulations · Local AI integration

[Quick start](#quick-start) · [Features](#features) · [API](#api-reference) · [Agent integration](#connect-your-own-agent) · [Contributing](#contributing)

</div>

---

## Overview

Refrax G is a geographic visualization framework for radio propagation research, education, and exploration. It combines international broadcast-site catalogs, public receiver-density information, and assimilated ionospheric models with an interactive map and configurable electromagnetic reference scenarios.

Explore the world from a global view down to individual city blocks, inspect model context for a selected location, and visualize the geometry of idealized wave propagation. The project uses deterministic calculations for scientific quantities and lets optional local AI assistants explain the resulting context.

> **Scientific scope:** Refrax G visualizes reference catalogs, published model products, and explicit simulations. It is not a global live RF receiver, a spectrum surveillance system, or a measurement of actual transmissions.

## Features

| Feature | What it does |
| --- | --- |
| Global map | Explore geographic data worldwide using MapLibre GL JS and OpenFreeMap. |
| 3D cities | Tilt the map to reveal available building geometry and height data. |
| HF reference catalog | Display international HF sites and season-schedule membership. |
| Receiver density | View volunteer receiver listings aggregated into one-degree geographic cells. |
| Ionospheric layer | Visualize quality-qualified NOAA GloTEC total electron content (TEC) model cells. |
| Reference waves | Place a hypothetical isotropic 1 W emitter and visualize geographic range rings in 3D. |
| Location context | Retrieve nearby public HF reference sites and the nearest available ionospheric model cell. |
| Data API | Read a bounded, cached global snapshot through a fixed-schema HTTP interface. |
| Local AI | Connect an Ollama, llama.cpp, or compatible local model without remote model execution. |

No account is required by the application. Model data and map coverage depend on upstream availability.

## Quick start

### 1. Explore the interface

When the website is deployed, open it in a current WebGL-capable browser. Alternatively, clone the release branch and serve its static files locally:

~~~bash
git clone --branch refrax-release https://github.com/Niqsaturn/AntennaMAP.git
cd AntennaMAP
python -m http.server 8000 --bind 127.0.0.1
~~~

Open http://127.0.0.1:8000/ in your browser.

**Local development:** the website currently points at the hosted API in the API constant at the top of app.js. To use a local gateway, change that constant to http://127.0.0.1:8875/v1 and configure the gateway origin as http://127.0.0.1:8000. The map renderer and basemap require network access to their asset providers. Browser geolocation requires a secure context and permission (localhost is normally treated as trustworthy).

### 2. Navigate the observatory

| Control | Use |
| --- | --- |
| Global view | Return to the world-scale map. |
| 3D perspective | Toggle between top-down and tilted map views; zoom into a city to see available extrusions. |
| HF reference / schedule sites | Toggle international radio site markers. |
| Public receiver density | Toggle aggregated receiver listing counts. |
| Ionospheric TEC model | Toggle model grid points colored by vertical TEC. |
| Place reference wave | Set the scenario frequency in MHz, then select a map point to place a reference source. |
| Clear wave | Remove the reference wave geometry. |
| Use my location | Request browser permission and center the map on your position locally. |
| Look up selected location | Explicitly submit the selected coordinates to the API for public geographic context. |

### 3. Start the data gateway

Requirements: Python 3.10 or later (standard library only for the gateway and agent), compatible upstream JSON feeds, and a WebGL-capable browser for the map.

~~~bash
python api.py --port 8875
~~~

The gateway listens on 127.0.0.1 by default. Configure the exact allowed web origin before launching it.

Linux/macOS:

~~~bash
REFRAX_WEB_ORIGIN=http://127.0.0.1:8000 python api.py --port 8875
~~~

Windows PowerShell:

~~~powershell
$env:REFRAX_WEB_ORIGIN = "http://127.0.0.1:8000"
python api.py --port 8875
~~~

Run only one gateway process on the selected port. Allow time for the first snapshot to load.

The gateway is a data interface, not an autonomous data downloader. For a self-hosted deployment, supply compatible feeds on the loopback upstream configured in api.py (UPSTREAM, default http://127.0.0.1:8874). Implement your own source adapters or configure an equivalent service using the following input contracts:

| Upstream path | Required input structure |
| --- | --- |
| /api/global-rf/catalog | features array containing GeoJSON Point coordinates and properties.frequencies_hz, properties.scheduled_this_season; downloaded_utc |
| /api/ionosphere/snapshot | cells arrays of [longitude, latitude, TEC, anomaly, hmF2, foF2, quality_flag]; timestamp_utc and stale |
| /api/public-sources/catalog | layers.public_sdr_receivers array of GeoJSON Points; generated_at_utc |

The gateway validates coordinates, frequency ranges, model-quality flags, and response sizes. Missing or failed feeds remain unavailable or retain an explicitly stale cached snapshot. No credentials are required by the gateway itself.

## Architecture

~~~mermaid
flowchart LR
    A[Published radio catalogs] --> D[Compatible data adapters]
    B[Ionospheric model products] --> D
    C[Public receiver directory] --> D
    D --> E[Validated read-only gateway]
    E --> F[Web observatory]
    E --> G[Local agent adapter]
    G --> H[User-controlled local model]
    I[Explicit viewer coordinates] --> E
~~~

| File | Responsibility |
| --- | --- |
| index.html | Observatory layout and map controls |
| style.css | Responsive presentation |
| app.js | Map rendering, reference geometry, location and snapshot interaction |
| api.py | Fixed-route gateway, validation, cache and location calculations |
| agent.py | Local chat-completion adapter |
| tests/test_gateway.py | Gateway and agent-context regression tests |

Scientific calculations are independent of AI output. The data service has no arbitrary execution or model-hosting interface.

## API reference

Hosted API base:

https://en-route.ringtail-anoles.ts.net/refrax-api/v1

For local development, use http://127.0.0.1:8875/v1 instead.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | /health | Gateway process health; does not guarantee upstream availability |
| GET | /snapshot | Global radio, ionospheric and aggregated receiver information |
| POST | /location | Public geographic context for explicitly supplied coordinates |

### Health and snapshot

~~~bash
curl https://en-route.ringtail-anoles.ts.net/refrax-api/v1/health
curl https://en-route.ringtail-anoles.ts.net/refrax-api/v1/snapshot
~~~

Illustrative snapshot structure (example values, not live readings):

~~~json
{
  "scope": "global",
  "status": "ok",
  "radio": {
    "classification": "scheduled_reference_not_measured_emission",
    "sites": [
      {
        "lon": 0.0,
        "lat": 0.0,
        "frequencies_hz": [10000000],
        "scheduled_this_season": true
      }
    ]
  },
  "ionosphere": {
    "classification": "assimilated_model_not_measured_local_signal",
    "fields": [
      "longitude_deg", "latitude_deg", "vertical_tec_tecu",
      "hmF2_km", "foF2_MHz"
    ],
    "cells": [[0.0, 0.0, 15.0, 300.0, 5.0]]
  },
  "receivers": {
    "classification": "catalog_counts_not_live_reception",
    "cell_size_degrees": 1,
    "cells": [[0.5, 0.5, 2]]
  }
}
~~~

Inspect source timestamps, cache_stale, upstream_stale and status before drawing conclusions. The service refreshes its cache on a nominal 180-second interval after each retrieval cycle; source products may update at different rates.

### Location context

The following example uses an intentionally chosen coordinate, not an automatically detected position.

~~~bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"latitude": 51.5, "longitude": 0.0}' \
  https://en-route.ringtail-anoles.ts.net/refrax-api/v1/location
~~~

Supply latitude and longitude together in decimal degrees. Valid ranges are -90 to 90 and -180 to 180 respectively. The response returns up to eight nearby public HF reference sites, their great-circle distances, and the nearest quality-qualified ionospheric cell if available. It does not predict actual signal reception.

There is no automatic server-location or IP-geolocation fallback.

## Connect your own agent

Run your preferred model on your computer. The adapter retrieves bounded radio and ionospheric summaries and optional location context, then passes them to a local OpenAI-compatible chat completion endpoint.

### Ollama

Install [Ollama](https://ollama.com/), download an appropriate model and make sure the local server is running.

~~~bash
ollama pull llama3.2
python agent.py --model llama3.2 "Summarize the global radio propagation context."
~~~

### llama.cpp

Run [llama.cpp](https://github.com/ggml-org/llama.cpp) with a compatible GGUF model:

~~~bash
llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 8080
python agent.py --model-url http://127.0.0.1:8080/v1 --model local-model "Explain the limitations of the current ionospheric model."
~~~

Use the model name accepted by your running server. Other compatible loopback model servers may use the same adapter.

### Location-aware agent and self-hosted API

~~~bash
python agent.py --model llama3.2 --lat 51.5 --lon 0.0 "Describe the available geographic context."
python agent.py --api http://127.0.0.1:8875/v1 --model llama3.2 "Summarize the available data."
~~~

Coordinates are optional; both must be supplied for a location query. Your model runs locally and is responsible for its own outputs. The gateway does not execute prompts, tools, scripts or shell commands. Agents may also consume the HTTP API directly.

See [Ollama API compatibility](https://docs.ollama.com/api/openai-compatibility) and [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/tree/master/tools/server).

## Scientific methods and limitations

The reference wave calculation uses SI units:

- Wavelength: lambda = c / f, where c = 299,792,458 m/s.
- Isotropic far-field power flux density: S = P / (4 pi r^2), in W/m^2.
- RMS electric field: E = sqrt(Z0 S), in V/m, with Z0 approximately 376.73 ohms.
- The illustrative source has P = 1 W EIRP. Ring radii use spherical Earth geographic geometry.
- The minimum range guard max(20 m, 3 wavelengths) excludes some invalid near-source scenarios; it does not establish the actual far field of an unknown antenna.
- Ring extrusion heights are visualization aids, not measured wave heights or a full Maxwell solution.

HFCC records describe reference sites and schedules, not confirmed active transmitters. Receiver density is an inventory, not measured coverage or listening activity. NOAA GloTEC is an assimilated ionospheric model. Map building heights may be missing or approximate. The model does not calculate full terrain diffraction, urban multipath, antenna patterns, or real carrier phase. Missing data are not zero-valued observations.

## Privacy and deployment

- Viewer location permission is optional; coordinate lookup is initiated explicitly.
- The application does not persist submitted coordinate bodies or use them to alter the shared snapshot. Map providers receive viewport requests, and network infrastructure may retain connection metadata.
- Receiver data are aggregated before publication.
- Expose only the gateway through an HTTPS reverse proxy, not the upstream service.
- Set the exact frontend CORS origin, enforce request and concurrency budgets at the reverse proxy, and review security and provider terms before public deployment. CORS is not authentication.
- Do not commit credentials, private sensor records, access tokens or user locations. Review source licenses and provider attribution before redistributing data.

GitHub Pages serves static frontend assets only; deploy the Python gateway on a separate server and configure app.js with its HTTPS API address.

## Development and testing

~~~bash
python -m unittest discover -s tests -v
~~~

The included tests exercise schema minimization, unknown-route rejection, coordinate validation and isolation, origin restrictions, stale-cache behavior, and local agent context. Model-specific completion and browser compatibility should be tested against your environment.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Map is blank | WebGL support and access to MapLibre assets and the map style provider. |
| API unavailable | HTTPS endpoint, gateway health, browser console and exact CORS origin. |
| Partial or delayed feed | Upstream availability, data format and source timestamps. |
| No 3D buildings | Zoom in and check whether the local map source includes building heights. |
| No wave rings | Choose a valid scenario frequency and nonpolar location away from the antimeridian. |
| Location unavailable | Grant browser permission or select a point manually. |
| Agent cannot connect | Confirm the local model server, port and model identifier. |

## Roadmap

Potential contributions include standalone source adapters, additional regional catalogs, better layer inspection, richer RF propagation models, time-history visualization, and calibrated measurement input. New models should be tested against analytical limiting cases and clearly labeled with their assumptions.

## Contributing

Open an issue describing the proposed change, its rationale, and reproducible steps. Keep pull requests focused, include regression tests, and document new equations, units, sources and validity limits. For a data adapter, include a small synthetic test fixture instead of publishing personal information.

Report security issues privately to the repository maintainer rather than posting sensitive details or credentials in an issue.

## Credits and references

- [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/) — GPU-accelerated mapping.
- [OpenFreeMap](https://openfreemap.org/) and [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) — geographic data and cartography.
- [HFCC](https://www.hfcc.org/) — international HF broadcast coordination information.
- [NOAA Space Weather Prediction Center](https://www.swpc.noaa.gov/) — ionospheric context.
- [Ollama](https://ollama.com/) and [llama.cpp](https://github.com/ggml-org/llama.cpp) — optional local model runtimes.

## License

A project license has not yet been selected. Review the applicable source and data-provider terms before redistribution. Third-party components retain their respective licenses.
