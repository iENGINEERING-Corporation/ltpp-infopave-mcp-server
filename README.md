# LTPP InfoPave MCP Server

An MCP server that lets an AI assistant answer questions about pavement performance using FHWA's Long-Term Pavement Performance (LTPP) program data, as published on [InfoPave](https://infopave.fhwa.dot.gov). It serves the InfoPave Analysis Ready Datasets from LTPP Standard Data Release 40: 2,581 test sections in the US and Canada, with layer structure and materials, construction features, roughness, rutting, cracking and load transfer, climate, traffic, and maintenance and rehabilitation history.

Built for the GSA MCP Server and SI Agent Government Hackathon (November 2026).

**Who it is for.** Pavement engineers, researchers and agency staff who today download LTPP tables, join them by hand and look up codes in the data dictionary. With this server they can ask a question in plain English, for example *"How did roughness change after AC overlays on wet-freeze sections with at least 6 inches of asphalt?"*, and get an answer with units, the data release and the datasets it came from.

## What it does

- **42 read-only tools** over 64 tables (7.4 million rows), grouped by dataset (see [Tools](#tools)).
- Every answer carries the same envelope: `data`, `data_release`, `sources`, `caveats`, `total_count` and `next_offset` for paging, and `fields` with each column's unit and the meaning of each code.
- Sections are named the way engineers name them: a state (name, postal code or number) plus a SHRP ID.
- Units are converted on request (`units="us"` or `"si"`) and never mixed silently.
- LTPP's own quality markers are passed on rather than dropped: outlier flags, imputed or default values, and source codes.
- 4 prompts and 4 resources plus 3 resource templates (`infopave://codes/{code_type}`, `infopave://topic/{topic}`, `infopave://section/{state}/{shrp_id}`).

**What it does not do.** Daily and hourly climate are not included (monthly and annual MERRA-2 only, 1980 to 2025). Before/after treatment results are observational, so the server reports the number of treatments compared and never claims a treatment caused a change. The data is a read-only snapshot; nothing is written back.

## Layout

```
src/infopave_mcp/
  server.py       MCP app, transport selection (stdio or HTTP)
  tools/          one module per domain (sections, materials, construction, performance, climate,
                  traffic, maintenance, cross_dataset)
  resources/      infopave:// URI handlers
  prompts/        the 4 prompt templates
  models/         Pydantic inputs and the response Envelope
  services/       units, field metadata, section resolution, caveats, treatment pairing ...
  repository/     base.py (interface), duckdb_repo.py (Parquet), sqlserver_repo.py (placeholder)
  kb/             system prompt, tool catalogue
  eval/local/        gold questions, server tests, agent eval runner, sample pack for CI
```

Every tool returns the same `Envelope`: `data`, data release stamp, `sources`, `caveats`, `total_count`, `next_offset`.

## How to connect the MCP
The live server is hosted on AWS and speaks MCP over streamable HTTP:

```
MCP URL: https://ltpp-mcp.iengineering.com/mcp
```

### Access key (bearer token)

The endpoint is protected. Every request must carry a **bearer token** in the `Authorization` header, otherwise the MCP server answers `401 Unauthorized`:

```
Authorization: Bearer <YOUR_ACCESS_KEY>
```

- The bearer token is shared in the `LTPP InfoPave MCP Server - Evaluation Document`. It is not stored in this repository.

### Claude Desktop

Add the server as a **custom connector** from the Claude Desktop interface. No config file editing is needed.

1. Open Claude Desktop and go to **Settings > Connectors**.
2. Click **Add custom connector**.
3. Fill in the form:
   - **Name:** `LTPP InfoPave`
   - **Remote MCP server URL:** `https://ltpp-mcp.iengineering.com/mcp`
   - **Advanced settings** (optional): enter the bearer token from the submission PDF if the form asks for credentials.
4. Click **Add**.
5. In a new chat, open the **tools / connectors menu** (the `+` or sliders icon in the message box) and make sure **LTPP InfoPave** is switched on. Its 42 tools should be listed.
6. Try: *"Tell me about LTPP section 53-1007."*

Custom connectors may require a Pro, Max, Team or Enterprise plan. On Team and Enterprise plans an organization owner may need to add the connector first (**Organization settings > Connectors**), after which members enable it for themselves.

## Dataset

The server answers from a read-only **dataset**: a folder of Parquet files built from the FHWA InfoPave Analysis Ready Datasets.

| | |
|---|---|
| Source | FHWA LTPP, published on [InfoPave](https://infopave.fhwa.dot.gov) |
| Release | LTPP Standard Data Release 40 |
| Format | Parquet, queried in-process with DuckDB |
| Size | 64 files (tables), about 7.4 million rows |
| Coverage | 2,581 test sections in the US and Canada |
| Integrity | `manifest.json` records each file's size, SHA-256, row and column counts; `scripts/data_manifest.py verify` checks it |

The dataset is not in this repository. The deployment pipeline syncs it from S3 and verifies it against the manifest before building the image.

### What data we have

| Area | What it contains |
|---|---|
| **Test sections** | Inventory of all 2,581 sections: state/province, SHRP ID, pavement type, experiment (GPS/SPS), climate zone. |
| **Performance** | Roughness (IRI/MRI), rut depth, cracking and distress for asphalt, jointed concrete and CRCP pavements, joint/crack load transfer efficiency, dowel bar scan (MIT) results. |
| **Construction features** | Layer structure, subsurface drainage design, concrete joint design, shoulder structure and condition. |
| **Materials** | Asphalt, asphalt-treated, concrete, concrete-treated and unbound layer properties; asphalt dynamic modulus (E*) and creep compliance; interlayers and engineering fabrics; warm-mix asphalt binder and mix (SPS-10); supporting statistics for each, used for variability. |
| **Maintenance and rehabilitation** | Treatment event summary plus detail tables for asphalt spot and surface treatments, concrete spot and surface treatments, and subdrainage work. |
| **Climate** | MERRA-2 modelled data for the grid cell serving each section: air temperature, precipitation, humidity, wind and solar radiation, yearly and monthly, 1980 to 2025, plus yearly binder-grade temperature extremes. No daily or hourly data. |
| **Traffic** | Representative traffic parameters, annual AADTT and ESAL trend, monthly adjustment factors, hourly distribution, axle load distribution, axles per truck, truck volume and class parameters. |
| **Reference tables** | Code lists, code types, LTPP and InfoPave data and table dictionaries, and the data release list. Used to explain every code and unit in an answer. |

Things to know when reading results:

- A section is identified by **state + SHRP ID**; the SHRP ID alone repeats across states.
- A **construction number** is a construction event on a section. An overlay or reconstruction starts a new one, and properties and performance belong to a construction event.
- Pavement families: `ACUB`, `ACATB`, `ACCTB`, `ACTB` are asphalt over base (flexible); `ACPCC` is composite; `JPC*`, `JRC*`, `CRC*` and `PCPCC` are concrete (rigid).
- Values may be imputed, defaulted or flagged as possible outliers by LTPP. The server passes these markers on in `caveats` and `fields` rather than dropping them.
- Before/after treatment comparisons are observational and are not evidence of cause.

## Example questions

| Question | Tools it uses |
|---|---|
| Tell me about LTPP section 53-1007. | `get_section_report` |
| Which Ohio SPS sections are in a wet-freeze climate? | `search_sections` |
| How has roughness changed on Washington 1007 since it was built? | `get_roughness_history` |
| Did crack sealing slow the growth of cracking, and on how many sections? | `compare_treatment_effect_across_groups` |
| How does freeze index differ between SPS-8 sections in Ohio and Arizona? | `compare_climate_between_groups` |
| What is the hourly temperature at section 04-1001? | none: declined, daily and hourly climate are out of scope |