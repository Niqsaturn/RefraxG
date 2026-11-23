# Refrax G
Global radio-wave and ionospheric observatory framework.

## Explore
The static web interface visualizes published international HF reference sites and schedules, coarse public receiver density, NOAA GloTEC model cells, map building geometry, and manually placed conditional free-space wave surfaces. Select 3D perspective and zoom into a city to view available building heights. The globe view is the default. The geometry of wave rings is to scale; their vertical extrusion is illustrative.

## Data API
The gateway runs separately on a loopback-bound server. It reads fixed data feeds, projects them into a minimal public schema, and caches snapshots. It does not forward arbitrary requests or execute models.
- GET /v1/health
- GET /v1/snapshot — global published reference catalog and quality-qualified model cells
- POST /v1/location — JSON {"latitude": 0, "longitude": 0}; explicit caller coordinates only, no IP geolocation or automatic default. Coordinate request bodies are not retained or recorded by the application. Map-tile providers receive viewport requests; network infrastructure may retain connection metadata.

Run `python api.py --port 8875` with compatible data feeds available at the configured loopback upstream. The three JSON feed contracts are in api.py: international radio catalog, global ionospheric model, and receiver directory; source adapters can be substituted to match these contracts. Configure an HTTPS reverse proxy to this gateway only. Set REFRAX_WEB_ORIGIN to the exact web origin; do not expose upstream administration endpoints. Local tests: `python -m unittest discover -s tests -v`.

## Your own agent
Ollama and llama.cpp provide OpenAI-compatible chat completion endpoints. Run your model locally, then:
```sh
python agent.py --model llama3.2 "Summarize global propagation context"
python agent.py --model-url http://127.0.0.1:8080/v1 --model local-model "Describe the limitations of the ionospheric model"
```
Optional --lat and --lon request location context, with your explicit consent. The adapter passes bounded scientific context to your own local model, not to the public data server for execution. Other local OpenAI-compatible model runtimes can use the same adapter. Agents can also consume the read-only API directly. See [Ollama compatibility](https://docs.ollama.com/api/openai-compatibility) and [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server).

## Scientific provenance
HFCC schedule membership is not a measured radio transmission. NOAA GloTEC is an assimilated model, not measured local reception. The free-space reference assumes 1 W isotropic EIRP and does not solve local multipath, terrain blockage, antenna directivity or measured carrier phase. Map data availability and building height completeness vary by region.

MapLibre GL JS · OpenFreeMap / OpenStreetMap · HFCC · NOAA SWPC.
